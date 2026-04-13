/**
 * panel.js – CEP panel JavaScript.
 *
 * Runs inside Premiere Pro's embedded Chromium.
 * Communicates with:
 *   - Premiere Pro host via CSInterface (JSX bridge)
 *   - AI Video Agent server via fetch/WebSocket (http://localhost:8000)
 */

const cs          = new CSInterface();
const AGENT_URL   = "http://localhost:8000";
const AGENT_WS    = "ws://localhost:8000";

/* ── Premiere bridge WebSocket ───────────────────────────────────────────────
 * Maintains a persistent connection to the server so the agent can send JSX
 * commands directly into Premiere Pro.
 */
let _bridgeWs = null;
let _bridgeReconnectTimer = null;
let _bridgePingTimer = null;

function connectPremierebridge() {
    if (_bridgeWs && (_bridgeWs.readyState === WebSocket.CONNECTING ||
                       _bridgeWs.readyState === WebSocket.OPEN)) return;

    clearTimeout(_bridgePingTimer);

    try {
        _bridgeWs = new WebSocket(AGENT_WS + "/ws/premiere");
    } catch(e) {
        _bridgeReconnectTimer = setTimeout(connectPremierebridge, 3000);
        return;
    }

    _bridgeWs.onopen = () => {
        setServer(true);
        clearTimeout(_bridgeReconnectTimer);
        // Send a keepalive ping every 20s to prevent Premiere dropping the connection
        _bridgePingTimer = setInterval(() => {
            if (_bridgeWs && _bridgeWs.readyState === WebSocket.OPEN) {
                try { _bridgeWs.send(JSON.stringify({ ping: true })); } catch(_) {}
            }
        }, 20000);
    };

    _bridgeWs.onmessage = ({ data }) => {
        let msg;
        try { msg = JSON.parse(data); } catch (_) { return; }
        // Ignore pong responses
        if (msg.pong) return;
        if (!msg.id || !msg.jsx) return;

        // Execute the JSX inside Premiere Pro and send back the result
        cs.evalScript(msg.jsx, (result) => {
            try {
                _bridgeWs.send(JSON.stringify({ id: msg.id, result: result || "" }));
            } catch(e) {}
        });
    };

    _bridgeWs.onerror = () => {
        setServer(false);
    };

    _bridgeWs.onclose = () => {
        setServer(false);
        clearInterval(_bridgePingTimer);
        // Reconnect after 3s (handles server restarts)
        _bridgeReconnectTimer = setTimeout(connectPremierebridge, 3000);
    };
}

connectPremierebridge();

/* ── DOM refs ────────────────────────────────────────────────────────────── */
const serverDot       = document.getElementById("serverDot");
const serverLabel     = document.getElementById("serverLabel");
const projectInfo     = document.getElementById("projectInfo");
const refreshProject  = document.getElementById("refreshProject");
const runAutoEdit     = document.getElementById("runAutoEdit");
const autoLog         = document.getElementById("autoLog");
const progressBar     = document.getElementById("progressBar");
const progressFill    = document.getElementById("progressFill");
const statusText      = document.getElementById("statusText");
const chatMessages    = document.getElementById("chatMessages");
const chatInput       = document.getElementById("chatInput");
const chatSend        = document.getElementById("chatSend");
const exportBtn       = document.getElementById("exportAndAnalyse");
const viralResults    = document.getElementById("viralResults");
const viralList       = document.getElementById("viralList");

/* ── Tabs ────────────────────────────────────────────────────────────────── */
document.querySelectorAll(".tab").forEach(btn => {
    btn.addEventListener("click", () => {
        document.querySelectorAll(".tab").forEach(b => b.classList.remove("active"));
        document.querySelectorAll(".tab-content").forEach(c => c.classList.remove("active"));
        btn.classList.add("active");
        document.getElementById("tab-" + btn.dataset.tab).classList.add("active");
    });
});

/* ── Server status ───────────────────────────────────────────────────────── */
function setServer(ok) {
    serverDot.className     = "server-dot" + (ok ? " ok" : " error");
    serverLabel.textContent = ok ? "Connected" : "Server offline";
}

// Initial state until bridge connects
setServer(false);

/* ── Load project info from Premiere ────────────────────────────────────── */
function loadProjectInfo() {
    cs.evalScript("getProjectInfo()", (result) => {
        try {
            const data = JSON.parse(result);
            if (data.error) {
                projectInfo.innerHTML = `<span style="color:var(--red)">${data.error}</span>`;
                return;
            }
            projectInfo.innerHTML =
                `<strong>${data.name}</strong><br>` +
                `Sequences: ${data.sequences.length}<br>` +
                (data.sequences.length ? `Active: <strong>${data.sequences[0].name}</strong>` : "");
        } catch (e) {
            projectInfo.textContent = "Could not load project info";
        }
    });
}

refreshProject.addEventListener("click", loadProjectInfo);
loadProjectInfo();

/* ── Auto Edit ───────────────────────────────────────────────────────────── */
runAutoEdit.addEventListener("click", async () => {
    const style        = document.getElementById("editStyle").value;
    const numClips     = parseInt(document.getElementById("numClips").value) || 5;
    const captionStyle = document.getElementById("captionStyle").value;
    const addVO        = document.getElementById("addVoiceover").checked;
    const importBack   = document.getElementById("exportToProject").checked;

    setRunning(true);
    autoLog.style.display = "block";
    autoLog.innerHTML = "";

    // Step 1: get active sequence info from Premiere
    setStatus("Getting sequence info…");
    const seqResult = await new Promise(resolve => {
        cs.evalScript("getActiveSequenceInfo()", resolve);
    });

    let seqInfo;
    try { seqInfo = JSON.parse(seqResult); } catch (_) { seqInfo = {}; }

    if (seqInfo.error) {
        logLine(`No active sequence: ${seqInfo.error}`, "error");
        setRunning(false);
        return;
    }

    logLine(`Sequence: "${seqInfo.name}" (${seqInfo.duration.toFixed(1)}s)`);

    // Step 2: export the sequence to a temp mp4
    // Pass no path — host.jsx uses Folder.temp.fsName (cross-platform)
    setStatus("Exporting sequence for analysis…");
    const exportResult = await new Promise(resolve => {
        cs.evalScript(`exportActiveSequence()`, resolve);
    });

    let exportData;
    try { exportData = JSON.parse(exportResult); } catch (_) { exportData = {}; }

    if (exportData.error) {
        logLine(`Export error: ${exportData.error}`, "error");
        logLine("Tip: Make sure Adobe Media Encoder is open.", "error");
        setRunning(false);
        return;
    }

    logLine(`Exported to: ${exportData.output_path}`);

    // Step 3: send to agent
    setStatus("Agent analysing…");
    const message = buildAgentPrompt(style, numClips, captionStyle, addVO, exportData.output_path);
    await runAgentSession(message, async (event) => {

        if (event.type === "text")   logLine(event.content);
        if (event.type === "tool_call") logLine(`→ ${event.tool_name}`, "tool");
        if (event.type === "tool_result") {
            logLine(`  ✓ ${event.content.slice(0, 100)}`, "result");

            // If a final clip was produced and user wants to import it back
            if (importBack && event.is_file && event.file_path &&
                event.file_path.match(/\.(mp4|mov|mxf)$/i)) {
                cs.evalScript(`importFileToProject("${event.file_path}")`, () => {
                    logLine(`Imported into project: ${event.file_path.split("/").pop()}`, "result");
                });
            }
        }
        if (event.type === "done") {
            setStatus("Done!");
            setRunning(false);
        }
        if (event.type === "error") {
            logLine(event.content, "error");
            setRunning(false);
        }
    });
});

function buildAgentPrompt(style, numClips, captionStyle, addVO, videoPath) {
    const styleMap = {
        viral_horizontal: "dramatic and viral, portrait 9:16 for Instagram Reels",
        fast_cuts:        "fast-paced with quick cuts, high energy",
        cinematic:        "slow and cinematic with dramatic pauses",
        documentary:      "clean documentary style with smooth transitions",
    };

    let prompt = `Auto-edit this video for ${styleMap[style] || style} style.
Video path: ${videoPath}
Number of clips: ${numClips}
Captions: ${captionStyle !== "none" ? captionStyle : "none"}

Workflow:
1. Transcribe the video
2. Find the ${numClips} most viral moments
3. Extract each clip
4. ${captionStyle !== "none" ? "Add captions to each clip" : "Skip captions"}
5. ${addVO ? "Generate a voiceover narration for each clip using the cloned voice" : "Keep original audio"}
6. Compose final portrait clips ready for Instagram Reels`;

    return prompt;
}

/* ── Chat tab ────────────────────────────────────────────────────────────── */
chatSend.addEventListener("click", sendChat);
chatInput.addEventListener("keydown", e => {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendChat(); }
});

async function sendChat() {
    const text = chatInput.value.trim();
    if (!text) return;
    chatInput.value = "";
    appendChat(text, "user");
    setStatus("Agent thinking…");
    setRunning(true);

    let agentBubble = null;
    await runAgentSession(text, (event) => {
        if (event.type === "text") {
            if (!agentBubble) agentBubble = appendChat("", "agent");
            agentBubble.textContent += event.content;
            chatMessages.scrollTop = chatMessages.scrollHeight;
        }
        if (event.type === "done") { setRunning(false); setStatus("Ready"); }
        if (event.type === "error") { appendChat("Error: " + event.content, "agent"); setRunning(false); }
    });
}

function appendChat(text, role) {
    const div = document.createElement("div");
    div.className = "chat-msg " + role;
    div.textContent = text;
    chatMessages.appendChild(div);
    chatMessages.scrollTop = chatMessages.scrollHeight;
    return div;
}

/* ── Viral Clips tab ─────────────────────────────────────────────────────── */
exportBtn.addEventListener("click", async () => {
    setStatus("Exporting for analysis…");
    setRunning(true);

    const exportResult = await new Promise(resolve => {
        cs.evalScript(`exportActiveSequence()`, resolve);
    });

    let exportData;
    try { exportData = JSON.parse(exportResult); } catch (_) { exportData = {}; }

    if (exportData.error) {
        setStatus("Export failed: " + exportData.error);
        setRunning(false);
        return;
    }

    setStatus("Finding viral moments…");
    const prompt = `Transcribe the video at "${exportData.output_path}", then find the 5 most viral moments. Return the results.`;

    await runAgentSession(prompt, (event) => {
        if (event.type === "tool_result" && event.tool_name === "find_viral_moments") {
            try {
                const moments = JSON.parse(event.content);
                renderViralClips(moments, exportData.output_path);
            } catch (_) {}
        }
        if (event.type === "done" || event.type === "error") setRunning(false);
    });
});

function renderViralClips(moments, sourcePath) {
    viralResults.classList.remove("hidden");
    viralList.innerHTML = "";
    moments.forEach((m, i) => {
        const card = document.createElement("div");
        card.className = "clip-card";
        card.innerHTML = `
            <div class="clip-title">${i + 1}. ${escHtml(m.suggested_title || "Clip " + (i+1))}</div>
            <div class="clip-time">${fmtTime(m.start)} → ${fmtTime(m.end)} (${(m.end - m.start).toFixed(1)}s)</div>
            <div class="clip-hook">${escHtml(m.hook || "")}</div>
            <div class="clip-actions">
                <button class="clip-action" data-start="${m.start}" data-end="${m.end}" data-source="${sourcePath}" data-title="${escHtml(m.suggested_title || "")}">✂️ Extract</button>
                <button class="clip-action" data-action="caption" data-start="${m.start}" data-end="${m.end}" data-source="${sourcePath}">💬 +Captions</button>
            </div>`;

        card.querySelectorAll(".clip-action").forEach(btn => {
            btn.addEventListener("click", () => handleClipAction(btn, m, sourcePath));
        });

        viralList.appendChild(card);
    });
}

async function handleClipAction(btn, moment, sourcePath) {
    const action = btn.dataset.action || "extract";
    const prompt = action === "caption"
        ? `Extract the clip from "${sourcePath}" between ${moment.start} and ${moment.end} seconds, then add captions and compose a final portrait clip.`
        : `Extract the clip from "${sourcePath}" between ${moment.start} and ${moment.end} seconds and save it.`;

    setStatus("Processing clip…");
    setRunning(true);

    await runAgentSession(prompt, (event) => {
        if (event.type === "tool_result" && event.is_file) {
            cs.evalScript(`importFileToProject("${event.file_path}")`, () => {});
        }
        if (event.type === "done" || event.type === "error") {
            setRunning(false);
            setStatus(event.type === "done" ? "Clip ready" : "Error");
        }
    });
}

/* ── WebSocket agent runner ──────────────────────────────────────────────── */
async function runAgentSession(message, onEvent) {
    let sessionId;
    try {
        const res = await fetch(AGENT_URL + "/api/chat", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ message }),
        });
        const data = await res.json();
        sessionId = data.session_id;
    } catch (err) {
        onEvent({ type: "error", content: "Cannot reach agent server at " + AGENT_URL });
        return;
    }

    return new Promise(resolve => {
        const ws = new WebSocket(AGENT_WS + "/ws/" + sessionId);
        ws.onmessage = ({ data }) => {
            const event = JSON.parse(data);
            onEvent(event);
            if (event.type === "done" || event.type === "error") {
                ws.close();
                resolve();
            }
        };
        ws.onerror = () => {
            onEvent({ type: "error", content: "WebSocket error" });
            resolve();
        };
    });
}

/* ── Helpers ─────────────────────────────────────────────────────────────── */
function logLine(text, cls) {
    const line = document.createElement("div");
    if (cls) line.className = "log-" + cls;
    line.textContent = text;
    autoLog.appendChild(line);
    autoLog.scrollTop = autoLog.scrollHeight;
}

function setStatus(text) { statusText.textContent = text; }

function setRunning(running) {
    runAutoEdit.disabled  = running;
    chatSend.disabled     = running;
    exportBtn.disabled    = running;
    progressBar.classList.toggle("hidden", !running);
    if (running) progressBar.classList.add("indeterminate");
    else         progressBar.classList.remove("indeterminate");
}

function fmtTime(s) {
    const m = Math.floor(s / 60);
    const sec = (s % 60).toFixed(1).padStart(4, "0");
    return `${m}:${sec}`;
}

function escHtml(str) {
    return String(str || "")
        .replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;")
        .replace(/"/g,"&quot;");
}
