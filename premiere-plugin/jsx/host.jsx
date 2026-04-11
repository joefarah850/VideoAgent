/**
 * host.jsx – ExtendScript bridge between the CEP panel and Premiere Pro.
 *
 * All functions here run INSIDE Premiere Pro (not in the browser).
 * The panel calls these via CSInterface.evalScript("functionName(args)").
 */

// ── Project info ──────────────────────────────────────────────────────────────

function getProjectInfo() {
    try {
        var proj = app.project;
        return JSON.stringify({
            name:     proj.name,
            path:     proj.path,
            sequences: getSequenceList()
        });
    } catch (e) {
        return JSON.stringify({ error: e.toString() });
    }
}

function getSequenceList() {
    var seqs = [];
    var proj = app.project;
    for (var i = 0; i < proj.sequences.numSequences; i++) {
        var seq = proj.sequences[i];
        seqs.push({
            id:       seq.sequenceID,
            name:     seq.name,
            duration: seq.end / seq.timebase,
            fps:      seq.timebase
        });
    }
    return seqs;
}

// ── Active sequence ────────────────────────────────────────────────────────────

function getActiveSequenceInfo() {
    try {
        var seq = app.project.activeSequence;
        if (!seq) return JSON.stringify({ error: "No active sequence" });
        return JSON.stringify({
            id:       seq.sequenceID,
            name:     seq.name,
            duration: parseFloat(seq.end) / parseFloat(seq.timebase),
            fps:      parseFloat(seq.timebase),
            in_point: seq.getInPoint(),
            out_point: seq.getOutPoint()
        });
    } catch (e) {
        return JSON.stringify({ error: e.toString() });
    }
}

// ── Export active sequence for agent processing ────────────────────────────────

function exportActiveSequence(outputPath) {
    try {
        var seq     = app.project.activeSequence;
        var encoder = app.encoder;
        var preset  = ""; // Use match source preset

        // Build output path
        if (!outputPath) {
            outputPath = Folder.temp.fsName + "/agent_export_" + (new Date().getTime()) + ".mp4";
        }

        // Use AME to export H.264
        var exporter = encoder.encodeSequence(
            seq,
            outputPath,
            "",   // preset path – empty = use H.264 match source
            app.encoder.ENCODE_IN_TO_OUT,
            true  // remove on completion = false means keep in queue
        );

        return JSON.stringify({ success: true, output_path: outputPath });
    } catch (e) {
        return JSON.stringify({ error: e.toString() });
    }
}

// ── Import file into project ───────────────────────────────────────────────────

function importFileToProject(filePath) {
    try {
        var arr = new Array(filePath);
        app.project.importFiles(arr, true, app.project.rootItem, false);
        return JSON.stringify({ success: true });
    } catch (e) {
        return JSON.stringify({ error: e.toString() });
    }
}

// ── Get clip list from active sequence ────────────────────────────────────────

function getClipsFromActiveSequence() {
    try {
        var seq  = app.project.activeSequence;
        var clips = [];
        var track = seq.videoTracks[0];
        for (var i = 0; i < track.clips.numItems; i++) {
            var clip = track.clips[i];
            clips.push({
                name:     clip.name,
                start:    parseFloat(clip.start.seconds),
                end:      parseFloat(clip.end.seconds),
                duration: parseFloat(clip.duration.seconds),
                media:    clip.projectItem ? clip.projectItem.getMediaPath() : ""
            });
        }
        return JSON.stringify({ clips: clips });
    } catch (e) {
        return JSON.stringify({ error: e.toString() });
    }
}

// ── Apply auto-edit: cut + place clips ────────────────────────────────────────

function applyAutoEdit(clipsJson) {
    /**
     * clipsJson: JSON string of [{media_path, start_in, end_in, label}]
     * Creates a new sequence and places the clips in order.
     */
    try {
        var clips    = JSON.parse(clipsJson);
        var seqName  = "AutoEdit_" + (new Date().getTime());
        var newSeq   = app.project.createNewSequence(seqName, "sequence-id-" + (new Date().getTime()));
        var track    = newSeq.videoTracks[0];
        var cursor   = newSeq.getInPoint();

        for (var i = 0; i < clips.length; i++) {
            var c     = clips[i];
            var items = app.project.rootItem.findItemsMatchingMediaPath(c.media_path, true);
            if (!items || items.length === 0) {
                // Import if not already in project
                app.project.importFiles([c.media_path], true, app.project.rootItem, false);
                items = app.project.rootItem.findItemsMatchingMediaPath(c.media_path, true);
            }
            if (items && items.length > 0) {
                var item    = items[0];
                var inPoint = c.start_in;
                var outPoint = c.end_in;
                track.insertClip(item, cursor);
                // TODO: set in/out via clip trim after insert
            }
        }

        app.project.activeSequence = newSeq;
        return JSON.stringify({ success: true, sequence: seqName });
    } catch (e) {
        return JSON.stringify({ error: e.toString() });
    }
}

// ── Add text title to active sequence at timecode ────────────────────────────

function addTitleAtTimecode(text, startSeconds, durationSeconds, position) {
    try {
        // Premiere requires Motion Graphics Templates for modern titles
        // This uses legacy title API available in all versions
        var seq       = app.project.activeSequence;
        var fps       = parseFloat(seq.timebase);
        var startTick = startSeconds * fps;

        // Create a legacy title
        var titleItem = app.project.createNewTitle(text);
        var titleDoc  = titleItem.getTitleDoc();
        var textFrame = titleDoc.createTextFrame(text);
        textFrame.setPosition(960, position === "bottom" ? 1800 : 120); // 1920x1080 coords
        textFrame.setFontSize(72);
        textFrame.setFillColor({ red: 255, green: 255, blue: 255 });

        // Place on a title track
        var titleTrack = seq.videoTracks[1];
        titleTrack.insertClip(titleItem, startTick);

        return JSON.stringify({ success: true });
    } catch (e) {
        return JSON.stringify({ error: e.toString() });
    }
}

// ── Get project path for agent to reference ───────────────────────────────────

function getProjectDirectory() {
    try {
        var path = app.project.path;
        // Strip filename, return directory
        return JSON.stringify({ path: path.substring(0, path.lastIndexOf("/")) });
    } catch (e) {
        return JSON.stringify({ error: e.toString() });
    }
}
