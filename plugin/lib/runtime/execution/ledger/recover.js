// Ledger reconciliation (single implementation): disk evidence + pid convergence + run/job receipt shape.
// The former two layers: runtime/recover.ts (pure disk reconciliation, unit-testable without Blender) and
// runtime/execution/ledger/recover.ts (the runSnapshot view + a wrapper injecting win/wsl mapping and pidAlive).
// Now there is only one owner: this file. tests/unit/js/ledger-recover.test.ts imports the pure logic here directly.
//
// v2.6 behavior unchanged: look for disk evidence first, and judge completed (recovered) when it matches; judge stale only when no evidence is found.
// Evidence priority:
//   ① <jobDir>/summary.json        — job terminal summary (written by the engine itself on close)
//   ② rec.resultPath               — structured result dump file (>4KB or explicit out_json)
//   ③ stdout log terminal state    — DSH_STAGE {"name":"done"} / HEADLESS {json} / Traceback
// Design constraint: logs can be hundreds of MB — read only the last 256 KB; called only on the rare path where the pid is already dead.
import fs from 'node:fs';
import path from 'node:path';
import { winToWsl, wslToWin } from '../../config.js';
import { WIN_TMP } from '../../paths.js';
import { PLUGIN_VERSION, pidAlive } from '../../core/evidence.js';
import { errorMessage } from '../../core/json.js';
export const RECOVER_VERSION = '2.6.1';
const NL = String.fromCharCode(10);
const STAGE_TAG = 'DSH_STAGE ';
const PROGRESS_TAG = 'DSH_PROGRESS ';
/** Default mapper (returns the path as-is on the same OS) — embedders inject the real winToWsl/wslToWin */
const IDENTITY_MAP = { winToWsl: (p) => p, wslToWin: (p) => p };
function toWsl(p, map) {
    const s = String(p == null ? '' : p);
    if (!s)
        return null;
    if (/^[A-Za-z]:[\\/]/.test(s) || s.startsWith('\\\\'))
        return map.winToWsl(s);
    return s;
}
/**
 * Read the log tail and extract "terminal-state evidence". Only the tail is read so a huge log cannot drag the process down.
 * Returns { exists, bytes, mtime, lastStage, sawDone, sawScriptEnd, sawHeadless, sawTraceback,
 *        lastProgress, path, tail, error? }
 */
export function logEvidence(pathWsl, maxBytes = 262144) {
    const ev = {
        path: pathWsl,
        exists: false,
        bytes: 0,
        mtime: null,
        lastStage: null,
        sawDone: false,
        sawScriptEnd: false,
        sawHeadless: false,
        sawTraceback: false,
        lastProgress: null,
        tail: null,
    };
    try {
        const st = fs.statSync(pathWsl);
        if (!st.isFile())
            return ev;
        ev.exists = true;
        ev.bytes = st.size;
        ev.mtime = st.mtimeMs;
        const len = Math.min(maxBytes, st.size);
        const buf = Buffer.alloc(len);
        const fd = fs.openSync(pathWsl, 'r');
        try {
            fs.readSync(fd, buf, 0, len, st.size - len);
        }
        finally {
            fs.closeSync(fd);
        }
        const txt = buf.toString('utf8');
        ev.tail = txt.slice(-4000);
        for (const raw of txt.split(NL)) {
            const s = raw.replace(/\r$/, '');
            if (s.indexOf(STAGE_TAG) === 0) {
                try {
                    const o = JSON.parse(s.slice(STAGE_TAG.length).trim());
                    if (o && o.name) {
                        ev.lastStage = String(o.name);
                        if (o.name === 'done')
                            ev.sawDone = true;
                        if (o.name === 'script-end')
                            ev.sawScriptEnd = true;
                    }
                }
                catch (e) {
                    /* ignore partial/broken lines */
                }
            }
            else if (s.indexOf(PROGRESS_TAG) === 0) {
                try {
                    const o = JSON.parse(s.slice(PROGRESS_TAG.length).trim());
                    if (o && typeof o === 'object')
                        ev.lastProgress = o;
                }
                catch (e) {
                    /* ignore broken lines */
                }
            }
            else if (s.indexOf('HEADLESS ') === 0) {
                ev.sawHeadless = true;
            }
            else if (/^Traceback \(most recent call last\)/.test(s)) {
                ev.sawTraceback = true;
            }
        }
    }
    catch (e) {
        ev.error = errorMessage(e).slice(0, 160);
    }
    return ev;
}
/**
 * Find on disk the evidence that "this run/job has finished".
 * rec may contain: dir / jobDir / outdir / resultPath / stdoutLog / stdoutLogWsl / logs
 * map = {winToWsl, wslToWin}
 */
export function recoverFromDisk(rec, map = IDENTITY_MAP) {
    const out = {
        found: false,
        source: null,
        status: null,
        exitCode: undefined,
        finishedAt: null,
        artifacts: [],
        evidence: null,
        stdoutLog: null,
        stderrLog: null,
        lastProgress: null,
    };
    if (!rec || typeof rec !== 'object')
        return out;
    // ① job terminal summary
    const dirWin = (rec.dir || rec.jobDir || null);
    if (dirWin) {
        try {
            const dirWsl = toWsl(dirWin, map);
            const sPath = path.join(dirWsl, 'summary.json');
            const st = fs.statSync(sPath);
            const s = JSON.parse(fs.readFileSync(sPath, 'utf8'));
            out.found = true;
            out.source = 'summary.json';
            out.status = s.status === 'failed' || s.status === 'killed' ? 'failed' : 'done';
            out.exitCode = s.exitCode;
            out.finishedAt = typeof s.finishedAt === 'number' && s.finishedAt ? s.finishedAt : st.mtimeMs;
            out.artifacts = Array.isArray(s.artifacts) ? s.artifacts : [];
            out.evidence = {
                path: map.wslToWin ? map.wslToWin(sPath) : sPath,
                mtime: st.mtimeMs,
                bytes: st.size,
                exitCode: s.exitCode == null ? null : s.exitCode,
                stage: s.stage || null,
                lastException: s.lastException || null,
            };
            out.stdoutLog = path.join(dirWsl, 'stdout.log');
            out.stderrLog = path.join(dirWsl, 'stderr.log');
            return out;
        }
        catch (e) {
            /* no summary → look at the logs */
        }
    }
    // ② structured result dump
    if (rec.resultPath) {
        try {
            const p = toWsl(rec.resultPath, map);
            const st = fs.statSync(p);
            out.found = true;
            out.source = 'resultPath';
            out.status = 'done';
            out.finishedAt = st.mtimeMs;
            out.evidence = { path: rec.resultPath, mtime: st.mtimeMs, bytes: st.size };
            return out;
        }
        catch (e) {
            /* the result file does not exist → look at the logs */
        }
    }
    // ③ stdout log (shared by run and job; candidates ordered by trustworthiness)
    const cands = [];
    if (rec.stdoutLog)
        cands.push(rec.stdoutLog);
    if (rec.stdoutLogWsl)
        cands.push(rec.stdoutLogWsl);
    const logs = rec.logs;
    if (logs && logs.stdout)
        cands.push(logs.stdout);
    if (dirWin) {
        const dw = toWsl(dirWin, map);
        if (dw)
            cands.push(path.join(dw, 'stdout.log'));
    }
    const seen = new Set();
    for (const c of cands) {
        const wsl = toWsl(c, map);
        if (!wsl || seen.has(wsl))
            continue;
        seen.add(wsl);
        const ev = logEvidence(wsl);
        if (!ev.exists)
            continue;
        out.found = true;
        out.source = 'stdout.log';
        out.stdoutLog = wsl;
        out.stderrLog = wsl.replace(/stdout\.log$/, 'stderr.log');
        out.lastProgress = ev.lastProgress || null;
        out.evidence = {
            path: map.wslToWin ? map.wslToWin(wsl) : wsl,
            bytes: ev.bytes,
            mtime: ev.mtime,
            lastStage: ev.lastStage,
            sawDone: ev.sawDone,
            sawHeadless: ev.sawHeadless,
            sawTraceback: ev.sawTraceback,
        };
        if (ev.sawDone || ev.sawHeadless)
            out.status = ev.sawTraceback ? 'failed' : 'done';
        else if (ev.sawTraceback)
            out.status = 'failed';
        else
            out.status = 'incomplete';
        out.finishedAt = ev.mtime;
        return out;
    }
    return out;
}
/**
 * Converge one status=running disk ledger record into a terminal state.
 *  - pid still alive → return as-is (do not take it over)
 *  - pid gone but disk has terminal evidence → status=done/failed + recovered:true
 *  - otherwise → status=stale (old semantics kept), but attach evidence so the caller saves a round of detective work
 */
export function reconcileLedger(rec, map = IDENTITY_MAP, isAlive = () => false) {
    if (!rec || rec.status !== 'running')
        return rec;
    if (rec.pid && isAlive(rec.pid))
        return rec;
    const deadWhy = rec.pid
        ? 'pid ' + String(rec.pid) + ' no longer exists (the process was killed externally, or the handle was lost after a backend restart)'
        : 'the ledger has no pid (only running was recorded before the backend restarted)';
    const ev = recoverFromDisk(rec, map);
    if (ev.found && (ev.status === 'done' || ev.status === 'failed')) {
        return Object.assign({}, rec, {
            status: ev.status,
            recovered: true,
            wasStatus: 'running',
            pidAlive: false,
            recoveredFrom: ev.source,
            recoveredEvidence: ev.evidence,
            recoveredLastProgress: ev.lastProgress || undefined,
            exitCode: ev.exitCode === undefined ? rec.exitCode : ev.exitCode,
            finishedAt: ev.finishedAt || rec.finishedAt || null,
            stage: (ev.evidence && ev.evidence.lastStage) || rec.stage || null,
            artifacts: ev.artifacts && ev.artifacts.length ? ev.artifacts : rec.artifacts,
            staleReason: deadWhy,
            hint: '**The process is gone, but the disk artifacts match → judged completed (recovered, evidence: ' +
                ev.source +
                ')**. ' +
                'Results/logs/artifacts stay readable as usual: op=collect returns stdoutTail, and op=list shows them too. ' +
                'To re-run, start once more with the same command — do not keep waiting on this id.',
        });
    }
    return Object.assign({}, rec, {
        status: 'stale',
        wasStatus: 'running',
        pidAlive: false,
        staleReason: deadWhy,
        evidence: ev.found ? ev.evidence : null,
        evidenceChecked: ['summary.json', 'resultPath', 'stdout.log'],
        hint: 'This is only a historical record in the **disk ledger** (the in-memory handle is gone). ' +
            (ev.found
                ? 'The log exists but no terminal state was reached (lastStage=' +
                    String((ev.evidence && ev.evidence.lastStage) || '?') +
                    ') → judged incomplete.'
                : 'Neither logs nor artifacts were found → judged incomplete.') +
            ' To confirm the process: PowerShell Get-Process blender; to clear orphans: Stop-Process. Collect new jobs with op=kill.',
    });
}
/**
 * v0.9.3: run (the synchronous execution of blender_rt_headless) and job share one structured receipt shape —
 * collect/status take run-… and job-… with the same field set, so the caller need not tell the two apart.
 */
function runSnapshot(r) {
    const now = Date.now();
    const running = r.status === 'running';
    const rLogs = r.logs;
    const rArtifacts = Array.isArray(r.artifacts) ? r.artifacts : [];
    return {
        kind: 'headless',
        id: r.id,
        status: r.status,
        pid: r.pid,
        pidAlive: running ? pidAlive(r.pid) : false,
        ms: (Number(r.finishedAt) || now) - Number(r.startedAt),
        timeoutMs: r.timeoutMs || null,
        outdir: r.outdir || WIN_TMP,
        outdirWsl: r.outdirWsl || null,
        logs: r.logs || null,
        script: r.script || null,
        exitCode: r.exitCode,
        signal: r.signal || null,
        timedOut: r.timedOut || false,
        failureClass: r.failureClass || null,
        stage: r.stage || null,
        stageName: r.stageName || null,
        stageAt: r.stageAt || null,
        stageAgoMs: r.stageAt ? now - Number(r.stageAt) : null,
        lastOutputAt: r.lastOutputAt || null,
        idleMs: r.lastOutputAt ? now - Number(r.lastOutputAt) : now - Number(r.startedAt),
        lines: r.lines || 0,
        logBytes: (() => {
            try {
                const p = rLogs && rLogs.stdoutWsl;
                return p ? fs.statSync(p).size : 0;
            }
            catch (e) {
                return 0;
            }
        })(),
        resultJson: r.result || null,
        result: r.result || null,
        resultParseError: r.parseError || null,
        resultPath: r.resultPath || null,
        resultPathWsl: r.resultPathWsl || null,
        resultBytes: r.resultBytes || 0,
        resultTruncated: !!r.resultTruncated,
        stdoutTail: r.stdoutTail || null,
        stderrTail: r.stderrTail || null,
        pathWarnings: r.pathWarnings || [],
        warnings: r.warnings || r.pathWarnings || [],
        shots: r.shots || null,
        progress: r.progress || null,
        progressAt: r.progressAt || null,
        progressAgeMs: r.progressAt ? now - Number(r.progressAt) : null,
        heartbeat: r.heartbeat || null,
        progressHistory: r.progressHistory || [],
        inputFile: r.inputFile || null,
        artifacts: rArtifacts.map((n) => (typeof n === 'string' ? { name: n } : n)),
        artifactCount: rArtifacts.length,
        expect: r.expect || null,
        pluginVersion: PLUGIN_VERSION,
        hint: 'This is the blender_rt_headless run ledger (run and job share one id space): artifacts live in outdir, logs are under logs; ' +
            'the result is in resultJson / resultPath (while running, watch stage / idleMs for progress)',
    };
}
/**
 * Disk ledger record (history after a backend restart): convergence when it says running but the pid no longer exists.
 *
 * v2.6 (this round's feedback #1): older versions judged everything stale — but twice we measured "the child had actually finished, artifacts/logs were all there",
 * and the caller had to do its own Get-Process + ls detective work, costing at least one extra round trip every time. Now disk reconciliation runs first:
 *   summary.json / resultPath / stdout terminal state (DSH_STAGE done, HEADLESS, Traceback)
 * a match ⇒ status=done|failed + recovered=true (evidence in recoveredFrom/recoveredEvidence);
 * only a mismatch is judged stale, and then evidence (log size/lastStage) is attached.
 * The pure logic lives in recoverFromDisk/reconcileLedger in this same file and is unit-testable without Blender
 * (tests/unit/js/ledger-recover.test.ts).
 */
function reconcileLedgerRecord(rec) {
    if (!rec || rec.status !== 'running')
        return rec;
    return reconcileLedger(rec, { winToWsl: winToWsl, wslToWin: wslToWin }, pidAlive);
}
export function createLedgerRecover() {
    return { runSnapshot, reconcileLedger: reconcileLedgerRecord };
}
//# sourceMappingURL=recover.js.map