/* ── State ──────────────────────────────────────────────────────────────────── */
let uploadedFilePath = null;
let isRunning = false;
let conversationId = null;   // persists across messages in the same chat session

/* ── DOM refs ───────────────────────────────────────────────────────────────── */
const chatArea       = document.getElementById('chatArea');
const chatInput      = document.getElementById('chatInput');
const sendBtn        = document.getElementById('sendBtn');
const uploadZone     = document.getElementById('uploadZone');
const fileInput      = document.getElementById('fileInput');
const uploadedFile   = document.getElementById('uploadedFile');
const uploadedFileName = document.getElementById('uploadedFileName');
const uploadedFilePath_ = document.getElementById('uploadedFilePath');
const clearUpload    = document.getElementById('clearUpload');
const filesList      = document.getElementById('filesList');
const refreshFiles   = document.getElementById('refreshFiles');
const statusDot      = document.getElementById('statusDot');
const statusText     = document.getElementById('statusText');
const modalOverlay   = document.getElementById('modalOverlay');
const modalClose     = document.getElementById('modalClose');
const modalVideo     = document.getElementById('modalVideo');
const modalInfo      = document.getElementById('modalInfo');

/* ── Upload ─────────────────────────────────────────────────────────────────── */
uploadZone.addEventListener('click', () => fileInput.click());
fileInput.addEventListener('change', () => fileInput.files[0] && handleUpload(fileInput.files[0]));

uploadZone.addEventListener('dragover', e => { e.preventDefault(); uploadZone.classList.add('dragover'); });
uploadZone.addEventListener('dragleave', () => uploadZone.classList.remove('dragover'));
uploadZone.addEventListener('drop', e => {
  e.preventDefault();
  uploadZone.classList.remove('dragover');
  const f = e.dataTransfer.files[0];
  if (f) handleUpload(f);
});

clearUpload.addEventListener('click', () => {
  uploadedFilePath = null;
  uploadedFile.classList.add('hidden');
  uploadZone.classList.remove('hidden');
  fileInput.value = '';
});

async function handleUpload(file) {
  const fd = new FormData();
  fd.append('file', file);
  setStatus('Uploading…', 'running');
  try {
    const res  = await fetch('/api/upload', { method: 'POST', body: fd });
    const data = await res.json();
    uploadedFilePath = data.path;
    uploadedFileName.textContent  = data.name;
    uploadedFilePath_.textContent = data.path;
    uploadZone.classList.add('hidden');
    uploadedFile.classList.remove('hidden');
    setStatus('Ready', '');
    appendSystemMsg(`Uploaded: **${data.name}**  \`${data.path}\``);
  } catch (err) {
    setStatus('Upload failed', 'error');
    console.error(err);
  }
}

/* ── Send message ───────────────────────────────────────────────────────────── */
sendBtn.addEventListener('click', sendMessage);
chatInput.addEventListener('keydown', e => {
  if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage(); }
});

// Auto-resize textarea
chatInput.addEventListener('input', () => {
  chatInput.style.height = 'auto';
  chatInput.style.height = Math.min(chatInput.scrollHeight, 180) + 'px';
});

async function sendMessage() {
  let text = chatInput.value.trim();
  if (!text || isRunning) return;

  // Inject uploaded file path into message
  if (uploadedFilePath && !text.includes(uploadedFilePath)) {
    text += `\n\nFile: ${uploadedFilePath}`;
  }

  chatInput.value = '';
  chatInput.style.height = 'auto';

  appendUserMsg(text);
  setRunning(true);

  try {
    const body = { message: text };
    if (conversationId) body.conversation_id = conversationId;

    const res  = await fetch('/api/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    const data = await res.json();
    conversationId = data.conversation_id;   // remember for next message
    connectWebSocket(data.session_id);
  } catch (err) {
    appendErrorMsg('Failed to connect to agent server.');
    setRunning(false);
  }
}

/* ── WebSocket ──────────────────────────────────────────────────────────────── */
function connectWebSocket(sessionId) {
  const ws = new WebSocket(`ws://${location.host}/ws/${sessionId}`);
  let agentBubble = null;

  ws.onmessage = ({ data }) => {
    const event = JSON.parse(data);

    switch (event.type) {

      case 'thinking':
        appendThinking(event.content);
        break;

      case 'text':
        if (!agentBubble) agentBubble = appendAgentBubble();
        agentBubble.querySelector('.msg-bubble').textContent += event.content;
        scrollToBottom();
        break;

      case 'tool_call':
        agentBubble = null; // next text → new bubble
        appendToolCard(event.tool_name, event.tool_input, null);
        break;

      case 'tool_result':
        updateLastToolCard(event.tool_name, event.content, event.is_file, event.file_path);
        if (event.is_file) loadFiles(); // refresh files panel
        break;

      case 'done':
        setRunning(false);
        loadFiles();
        break;

      case 'error':
        appendErrorMsg(event.content);
        setRunning(false);
        break;
    }
  };

  ws.onerror = () => {
    appendErrorMsg('WebSocket connection error.');
    setRunning(false);
  };
}

/* ── Message renderers ──────────────────────────────────────────────────────── */
function appendUserMsg(text) {
  const msg = el('div', 'msg user');
  msg.innerHTML = `
    <div class="msg-label">You</div>
    <div class="msg-bubble">${escHtml(text)}</div>`;
  chatArea.appendChild(msg);
  scrollToBottom();
}

function appendAgentBubble() {
  const msg = el('div', 'msg agent');
  msg.innerHTML = `
    <div class="msg-label">Agent</div>
    <div class="msg-bubble cursor"></div>`;
  chatArea.appendChild(msg);
  scrollToBottom();
  return msg;
}

function appendThinking(content) {
  const block = el('div', 'thinking-block');
  block.textContent = '💭 Thinking…';
  chatArea.appendChild(block);
  scrollToBottom();
}

// Track last tool card for result injection
let _lastToolCard = null;

function appendToolCard(toolName, toolInput, result) {
  const card = el('div', 'tool-card');
  card.dataset.tool = toolName;
  card.innerHTML = `
    <div class="tool-header">
      <span class="tool-badge">Tool</span>
      <span class="tool-name">${escHtml(toolName)}</span>
      <span class="tool-chevron">▾</span>
    </div>
    <div class="tool-body">
      <div class="tool-section-label" style="font-size:11px;color:var(--text-muted);margin-top:6px">Input</div>
      <pre>${escHtml(JSON.stringify(toolInput, null, 2))}</pre>
    </div>`;

  card.querySelector('.tool-header').addEventListener('click', () => {
    card.classList.toggle('expanded');
  });

  chatArea.appendChild(card);
  scrollToBottom();
  _lastToolCard = card;
  return card;
}

function updateLastToolCard(toolName, content, isFile, filePath) {
  // find the last card matching this tool
  const cards = chatArea.querySelectorAll(`.tool-card[data-tool="${toolName}"]`);
  const card  = cards[cards.length - 1];
  if (!card) return;

  const badge = card.querySelector('.tool-badge');
  badge.textContent = 'Result';
  badge.classList.add('result');

  const body = card.querySelector('.tool-body');

  if (isFile && filePath) {
    const fname = filePath.split('/').pop();
    const url   = `/files/${fname}`;
    const isVid = /\.(mp4|mov|webm)$/i.test(fname);
    const link  = document.createElement('a');
    link.href   = url;
    link.className = 'tool-file-link';
    link.target = '_blank';
    link.innerHTML = `${isVid ? '🎬' : '📄'}  ${escHtml(fname)}`;
    if (isVid) {
      link.addEventListener('click', e => { e.preventDefault(); openVideoModal(url, fname); });
    }
    body.appendChild(link);
  } else {
    const pre = document.createElement('pre');
    pre.textContent = content.slice(0, 800) + (content.length > 800 ? '\n…' : '');
    body.appendChild(pre);
  }

  card.classList.add('expanded');
  scrollToBottom();
}

function appendErrorMsg(text) {
  const msg = el('div', 'msg agent');
  msg.innerHTML = `
    <div class="msg-label">Error</div>
    <div class="msg-bubble" style="background:#450a0a;border-color:#7f1d1d;color:#fca5a5">${escHtml(text)}</div>`;
  chatArea.appendChild(msg);
  scrollToBottom();
}

function appendSystemMsg(text) {
  const msg = el('div', 'msg agent');
  const rendered = text.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>').replace(/`(.+?)`/g, '<code style="background:var(--surface3);padding:1px 5px;border-radius:3px;font-size:11px">$1</code>');
  msg.innerHTML = `<div class="msg-bubble" style="background:var(--surface);font-size:12px;color:var(--text-muted)">${rendered}</div>`;
  chatArea.appendChild(msg);
  scrollToBottom();
}

/* ── Files panel ────────────────────────────────────────────────────────────── */
refreshFiles.addEventListener('click', loadFiles);

async function loadFiles() {
  try {
    const files = await fetch('/api/files').then(r => r.json());
    filesList.innerHTML = '';

    if (!files.length) {
      filesList.innerHTML = '<p class="empty-state">No output files yet</p>';
      return;
    }

    for (const f of files) {
      const isVid  = f.mime && f.mime.startsWith('video');
      const isAud  = f.mime && f.mime.startsWith('audio');
      const icon   = isVid ? '🎬' : isAud ? '🎵' : '📄';

      const item = el('div', 'file-item');
      item.innerHTML = `
        <div class="file-thumb-placeholder">${icon}</div>
        <div class="file-meta">
          <span class="file-meta-name" title="${escHtml(f.name)}">${escHtml(f.name)}</span>
          <span class="file-meta-size">${fmtSize(f.size)}</span>
        </div>
        <div class="file-actions">
          ${isVid ? `<button class="file-action-btn" data-action="preview" data-url="${f.url}" data-name="${escHtml(f.name)}">▶ Preview</button>` : ''}
          <button class="file-action-btn" data-action="download" data-url="${f.url}" data-name="${escHtml(f.name)}">⬇ Download</button>
        </div>`;

      item.querySelectorAll('.file-action-btn').forEach(btn => {
        btn.addEventListener('click', e => {
          e.stopPropagation();
          if (btn.dataset.action === 'preview') openVideoModal(btn.dataset.url, btn.dataset.name);
          if (btn.dataset.action === 'download') downloadFile(btn.dataset.url, btn.dataset.name);
        });
      });

      if (isVid) item.addEventListener('click', () => openVideoModal(f.url, f.name));
      filesList.appendChild(item);
    }
  } catch (err) {
    console.error('Failed to load files:', err);
  }
}

/* ── Quick action buttons ───────────────────────────────────────────────────── */
document.querySelectorAll('.action-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    const prompt = btn.dataset.prompt;
    const selectText = btn.dataset.select;
    chatInput.value = prompt;
    chatInput.dispatchEvent(new Event('input'));
    chatInput.focus();
    // If there's a placeholder to select, highlight it so the user just types to replace it
    if (selectText) {
      const start = prompt.indexOf(selectText);
      if (start !== -1) {
        chatInput.setSelectionRange(start, start + selectText.length);
      }
    }
  });
});

/* ── Video modal ────────────────────────────────────────────────────────────── */
function openVideoModal(url, name) {
  modalVideo.src = url;
  modalInfo.textContent = name;
  modalOverlay.classList.remove('hidden');
  modalVideo.play().catch(() => {});
}

modalClose.addEventListener('click', closeModal);
modalOverlay.addEventListener('click', e => { if (e.target === modalOverlay) closeModal(); });

function closeModal() {
  modalVideo.pause();
  modalVideo.src = '';
  modalOverlay.classList.add('hidden');
}

/* ── Utils ──────────────────────────────────────────────────────────────────── */
function el(tag, cls) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  return e;
}

function escHtml(str) {
  if (!str) return '';
  return String(str)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

function fmtSize(bytes) {
  if (bytes < 1024) return bytes + ' B';
  if (bytes < 1048576) return (bytes / 1024).toFixed(1) + ' KB';
  return (bytes / 1048576).toFixed(1) + ' MB';
}

function scrollToBottom() {
  chatArea.scrollTop = chatArea.scrollHeight;
}

function setRunning(running) {
  isRunning = running;
  sendBtn.disabled = running;
  // Remove cursor from last agent bubble when done
  if (!running) {
    chatArea.querySelectorAll('.msg-bubble.cursor').forEach(b => b.classList.remove('cursor'));
  }
  setStatus(running ? 'Running…' : 'Ready', running ? 'running' : '');
}

function setStatus(text, cls) {
  statusText.textContent = text;
  statusDot.className = 'status-dot' + (cls ? ` ${cls}` : '');
}

function downloadFile(url, name) {
  const a = document.createElement('a');
  a.href = url; a.download = name;
  document.body.appendChild(a); a.click(); document.body.removeChild(a);
}

/* ── Config / Model modal ────────────────────────────────────────────────────── */
const configOpenBtn  = document.getElementById('configOpenBtn');
const configOverlay  = document.getElementById('configOverlay');
const configClose    = document.getElementById('configClose');
const cfgSaveBtn     = document.getElementById('cfgSaveBtn');
const cfgActiveLabel = document.getElementById('cfgActiveLabel');
const pullRow        = document.getElementById('pullRow');
const pullLog        = document.getElementById('pullLog');
const pullBtn        = document.getElementById('pullBtn');
const pullModelName  = document.getElementById('pullModelName');

let _cfgCatalogue = {};
let _cfgProvider  = 'ollama';
let _cfgModel     = '';

configOpenBtn.addEventListener('click', openConfigModal);
configClose.addEventListener('click',   () => configOverlay.classList.add('hidden'));
configOverlay.addEventListener('click', e => { if (e.target === configOverlay) configOverlay.classList.add('hidden'); });

document.querySelectorAll('.cfg-tab').forEach(tab => {
  tab.addEventListener('click', () => {
    document.querySelectorAll('.cfg-tab').forEach(t => t.classList.remove('active'));
    document.querySelectorAll('.cfg-panel').forEach(p => p.classList.remove('active'));
    tab.classList.add('active');
    document.getElementById('cfg-' + tab.dataset.provider).classList.add('active');
    _cfgProvider = tab.dataset.provider;
    // Select first model for this provider if none chosen
    const models = _cfgCatalogue[_cfgProvider] || [];
    if (models.length && !models.find(m => m.id === _cfgModel)) {
      selectModel(_cfgProvider, models[0].id);
    }
    updateActiveLabel();
  });
});

async function openConfigModal() {
  configOverlay.classList.remove('hidden');
  try {
    const res  = await fetch('/api/config');
    const data = await res.json();
    _cfgCatalogue = data.catalogue;
    _cfgProvider  = data.current.provider;
    _cfgModel     = data.current.model;

    // Pre-fill API keys if present
    if (data.current.has_openai_key)    document.getElementById('openaiKey').placeholder    = '••••••••  (saved)';
    if (data.current.has_anthropic_key) document.getElementById('anthropicKey').placeholder = '••••••••  (saved)';

    // Activate the right tab
    document.querySelectorAll('.cfg-tab').forEach(t => {
      t.classList.toggle('active', t.dataset.provider === _cfgProvider);
    });
    document.querySelectorAll('.cfg-panel').forEach(p => p.classList.remove('active'));
    document.getElementById('cfg-' + _cfgProvider).classList.add('active');

    // Render model lists
    renderModelList('ollama',    _cfgCatalogue.ollama    || []);
    renderModelList('openai',    _cfgCatalogue.openai    || []);
    renderModelList('anthropic', _cfgCatalogue.anthropic || []);

    updateActiveLabel();
  } catch(e) {
    cfgActiveLabel.textContent = 'Could not load config';
  }
}

function renderModelList(provider, models) {
  const container = document.getElementById(provider + 'ModelList');
  container.innerHTML = '';
  models.forEach(m => {
    const row = document.createElement('div');
    row.className = 'cfg-model-row' + (m.id === _cfgModel && provider === _cfgProvider ? ' selected' : '');
    row.dataset.id = m.id;
    row.innerHTML = `<span class="cfg-model-name">${m.name}</span><span class="cfg-model-note">${m.note}</span>`;
    row.addEventListener('click', () => selectModel(provider, m.id));
    container.appendChild(row);
  });
}

function selectModel(provider, modelId) {
  _cfgProvider = provider;
  _cfgModel    = modelId;

  // Update selection highlight
  document.querySelectorAll('.cfg-model-row').forEach(r => {
    r.classList.toggle('selected', r.dataset.id === modelId);
  });

  // Show pull button only for Ollama models that may not be installed
  if (provider === 'ollama') {
    pullModelName.textContent = modelId;
    pullRow.classList.remove('hidden');
    pullLog.classList.add('hidden');
    pullLog.innerHTML = '';
  } else {
    pullRow.classList.add('hidden');
  }

  updateActiveLabel();
}

function updateActiveLabel() {
  const providerLabel = { ollama: 'Ollama', openai: 'OpenAI', anthropic: 'Anthropic' };
  cfgActiveLabel.textContent = _cfgModel
    ? `Active: ${providerLabel[_cfgProvider]} / ${_cfgModel}`
    : 'No model selected';
}

pullBtn.addEventListener('click', async () => {
  pullBtn.disabled = true;
  pullLog.classList.remove('hidden');
  pullLog.innerHTML = '';

  const res    = await fetch('/api/config/pull', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ model: _cfgModel }),
  });
  const reader  = res.body.getReader();
  const decoder = new TextDecoder();
  let buf = '';

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });
    const parts = buf.split('\n\n');
    buf = parts.pop();
    for (const part of parts) {
      const line = part.replace(/^data: /, '').trim();
      if (!line) continue;
      try {
        const ev = JSON.parse(line);
        if (ev.msg) {
          const d = document.createElement('div');
          d.textContent = ev.msg;
          pullLog.appendChild(d);
          pullLog.scrollTop = pullLog.scrollHeight;
        }
        if (ev.done) {
          const d = document.createElement('div');
          d.className = ev.status === 'ok' ? 'cfg-pull-ok' : 'cfg-pull-err';
          d.textContent = ev.status === 'ok' ? `✅ ${_cfgModel} installed` : '❌ Pull failed';
          pullLog.appendChild(d);
        }
      } catch(_) {}
    }
  }
  pullBtn.disabled = false;
});

cfgSaveBtn.addEventListener('click', async () => {
  if (!_cfgModel) return;
  cfgSaveBtn.disabled = true;
  cfgSaveBtn.textContent = 'Saving…';

  const body = {
    provider: _cfgProvider,
    model:    _cfgModel,
    openai_key:    document.getElementById('openaiKey').value.trim(),
    anthropic_key: document.getElementById('anthropicKey').value.trim(),
  };

  try {
    const res = await fetch('/api/config', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    const data = await res.json();
    if (data.ok) {
      cfgSaveBtn.textContent = 'Saved ✅';
      setTimeout(() => {
        cfgSaveBtn.textContent = 'Save & Apply';
        cfgSaveBtn.disabled = false;
        configOverlay.classList.add('hidden');
      }, 1200);
    }
  } catch(e) {
    cfgSaveBtn.textContent = 'Error – try again';
    cfgSaveBtn.disabled = false;
  }
});

/* ── Setup modal ─────────────────────────────────────────────────────────────── */
const setupBtn     = document.getElementById('setupBtn');
const setupOverlay = document.getElementById('setupOverlay');
const setupClose   = document.getElementById('setupClose');
const setupRunBtn  = document.getElementById('setupRunBtn');
const setupLog     = document.getElementById('setupLog');

setupBtn.addEventListener('click', () => setupOverlay.classList.remove('hidden'));
setupClose.addEventListener('click', () => setupOverlay.classList.add('hidden'));
setupOverlay.addEventListener('click', e => { if (e.target === setupOverlay) setupOverlay.classList.add('hidden'); });

setupRunBtn.addEventListener('click', async () => {
  setupRunBtn.disabled = true;
  setupLog.classList.remove('hidden');
  setupLog.innerHTML = '';

  const statusIcon = { ok: '✅', running: '⏳', error: '❌' };

  // Track rows by step so we can update them in-place
  const rows = {};

  function upsertRow(step, status, msg) {
    if (!rows[step]) {
      const div = document.createElement('div');
      div.className = 'setup-row';
      setupLog.appendChild(div);
      rows[step] = div;
    }
    const icon = statusIcon[status] || '⏳';
    rows[step].className = `setup-row setup-${status}`;
    rows[step].textContent = `${icon}  ${msg}`;
    setupLog.scrollTop = setupLog.scrollHeight;
  }

  try {
    const res = await fetch('/api/setup');
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buf = '';

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });
      const parts = buf.split('\n\n');
      buf = parts.pop();
      for (const part of parts) {
        const line = part.replace(/^data: /, '').trim();
        if (!line) continue;
        try {
          const ev = JSON.parse(line);
          upsertRow(ev.step, ev.status, ev.msg);
          if (ev.step === 'done') {
            setupRunBtn.textContent = 'Done! ✅';
          }
        } catch (_) {}
      }
    }
  } catch (err) {
    upsertRow('error', 'error', 'Could not reach server: ' + err.message);
  }

  setupRunBtn.disabled = false;
});

/* ── Init ───────────────────────────────────────────────────────────────────── */
loadFiles();

// Welcome message
appendSystemMsg('**AI Video Agent** ready. Upload a video or choose a quick action to get started.');
