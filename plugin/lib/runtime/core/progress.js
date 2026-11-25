// Long-task observability: DSH_STAGE / DSH_PROGRESS scanning and the heartbeat file
// @imports
import fs from 'node:fs';
import path from 'node:path';
import { errorMessage } from './json.js';
const STAGE_TAG = 'DSH_STAGE ';
/** v2.6 (feedback round #4): progress channel — scripts call dsh_progress(...) / K.progress(...) to print DSH_PROGRESS {json},
 *  and op=status/collect can read the last record directly (per-frame render / per-item batch / download percentage).
 *  Difference from stage: stage is a "phase transition" (few, low rate), progress is "progress within a phase" (high rate, overwritable, keeps the latest 20). */
const PROGRESS_TAG = 'DSH_PROGRESS ';
function scanProgressLine(line, rec, now) {
    if (line.indexOf(PROGRESS_TAG) !== 0)
        return false;
    try {
        const o = JSON.parse(line.slice(PROGRESS_TAG.length).trim());
        rec.progress = o;
        rec.progressAt = now;
        rec.progressHistory = (rec.progressHistory || []).concat([{ at: now, p: o }]).slice(-20);
        if (o.name) {
            rec.stageName = String(o.name);
            rec.stageAt = now;
        }
    }
    catch (e) {
        rec.progress = { raw: line.slice(0, 200), parse_error: errorMessage(e) };
        rec.progressAt = now;
    }
    return true;
}
function scanStageLine(line, rec, now) {
    if (line.indexOf(STAGE_TAG) !== 0)
        return false;
    try {
        const obj = JSON.parse(line.slice(STAGE_TAG.length).trim());
        rec.stage = obj;
        rec.stageAt = now;
        rec.stageName = obj.name ? String(obj.name) : null;
        return true;
    }
    catch (e) {
        rec.stage = { raw: line.slice(0, 200), parse_error: errorMessage(e) };
        rec.stageAt = now;
        return false;
    }
}
/** Feed one chunk to the stage scanner line by line (a half line split across chunks is held in the tail buffer) */
function makeStageScanner(rec) {
    let tail = '';
    return (chunk) => {
        const now = Date.now();
        rec.lastOutputAt = now;
        const text = tail + String(chunk);
        const lines = text.split('\n');
        tail = lines.pop() || '';
        if (tail.length > 8192)
            tail = tail.slice(-2048);
        rec.lines = (rec.lines || 0) + lines.length;
        for (const l of lines) {
            const s = l.replace(/\r$/, '');
            if (s.indexOf(STAGE_TAG) === 0)
                scanStageLine(s, rec, now);
            else if (s.indexOf(PROGRESS_TAG) === 0)
                scanProgressLine(s, rec, now);
        }
    };
}
/**
 * v2.6 (feedback round #4): run heartbeat — every 5s updates rec.heartbeat (and optionally appends to <dir>/heartbeat.jsonl).
 * Field problem: one EEVEE frame takes 2–3 minutes and op=status only has stage/idleMs, so you cannot tell "which frame / how many bytes written".
 * heartbeat provides: elapsedMs / logBytes / lines / stage / lastProgressAt — enough to judge "is it moving or stuck".
 */
function startHeartbeat(rec, dirWsl) {
    const tick = () => {
        try {
            let bytes = 0;
            if (rec.logs && rec.logs.stdoutWsl) {
                try {
                    bytes = fs.statSync(rec.logs.stdoutWsl).size;
                }
                catch (e) { }
            }
            if (!bytes && rec.dir) {
                try {
                    bytes = fs.statSync(path.join(rec.dir, 'stdout.log')).size;
                }
                catch (e) { }
            }
            const hb = {
                at: Date.now(),
                elapsedMs: Date.now() - rec.startedAt,
                logBytes: bytes,
                lines: rec.lines || 0,
                stage: rec.stageName || null,
                progressAt: rec.progressAt || null,
                progressAgeMs: rec.progressAt ? Date.now() - rec.progressAt : null,
            };
            rec.heartbeat = hb;
            if (dirWsl) {
                try {
                    fs.appendFileSync(path.join(dirWsl, 'heartbeat.jsonl'), JSON.stringify(hb) + String.fromCharCode(10), 'utf8');
                }
                catch (e) { }
            }
        }
        catch (e) {
            /* the heartbeat must never take the job down */
        }
    };
    const t = setInterval(tick, 5000);
    if (t.unref)
        t.unref();
    return () => {
        try {
            clearInterval(t);
        }
        catch (e) { }
    };
}
export { STAGE_TAG, PROGRESS_TAG, scanProgressLine, scanStageLine, makeStageScanner, startHeartbeat, };
//# sourceMappingURL=progress.js.map