import path from 'node:path';
import fs from 'node:fs';
import { winToWsl, wslToWin } from '../../config.js';
import { WIN_TMP } from '../../paths.js';
import { pidAlive } from '../../core/evidence.js';
export function jobDir(id, outdir) {
    const base = outdir ? winToWsl(String(outdir)) : winToWsl(WIN_TMP);
    const d = path.join(base, 'jobs', id);
    fs.mkdirSync(d, { recursive: true });
    return d;
}
export function jobArtifacts(j) {
    const dir = j.outdir ? winToWsl(String(j.outdir)) : null;
    if (!dir)
        return [];
    try {
        const isNoise = (n) => n.indexOf('__pycache__') === 0 ||
            /\.pyc$/.test(n) ||
            /\.blend[12]$/.test(n) ||
            n.indexOf('tmp') === 0;
        const out = [];
        for (const n of fs.readdirSync(dir)) {
            const p = path.join(dir, n);
            let st = null;
            try {
                st = fs.statSync(p);
            }
            catch (e) {
                /* skip */
            }
            if (st && st.isFile() && !isNoise(n))
                out.push({ name: n, bytes: st.size, mtimeMs: st.mtimeMs });
        }
        return out.sort((a, b) => b.mtimeMs - a.mtimeMs).slice(0, 40);
    }
    catch (e) {
        return [];
    }
}
export function jobSnapshot(j) {
    // v0.8.9: ms must freeze once the job is done (the old version used Date.now(), so a finished job left for a while showed minutes-scale durations)
    const now = Date.now();
    const running = j.status === 'running';
    const outWsl = j.outdirWsl || (j.outdir ? winToWsl(String(j.outdir)) : winToWsl(WIN_TMP));
    let logBytes = j.logBytes || 0;
    if (running) {
        try {
            logBytes = fs.statSync(path.join(j.dir, 'stdout.log')).size;
        }
        catch (e) {
            /* not created yet */
        }
    }
    return {
        kind: 'job',
        id: j.id,
        runId: j.runId || null,
        status: j.status,
        pid: j.pid,
        pidAlive: running ? pidAlive(j.pid) : false,
        ms: (j.finishedAt || now) - j.startedAt,
        timeoutMs: j.timeoutMs,
        outdir: j.outdir || WIN_TMP,
        outdirWsl: outWsl,
        logDir: wslToWin(j.dir),
        logDirWsl: j.dir,
        stdoutLog: wslToWin(path.join(j.dir, 'stdout.log')),
        stderrLog: wslToWin(path.join(j.dir, 'stderr.log')),
        stdoutLogWsl: path.join(j.dir, 'stdout.log'),
        stderrLogWsl: path.join(j.dir, 'stderr.log'),
        exitCode: j.exitCode,
        signal: j.signal,
        engine: j.engineMode,
        // ---- v0.9.3: progress is visible while running (no more "6 minutes of pure black box")
        stage: j.stage || null,
        stageName: j.stageName || null,
        stageAt: j.stageAt || null,
        stageAgoMs: j.stageAt ? now - j.stageAt : null,
        lastOutputAt: j.lastOutputAt || null,
        idleMs: j.lastOutputAt ? now - j.lastOutputAt : now - j.startedAt,
        lines: j.lines || 0,
        logBytes: logBytes,
        // ---- v0.9.3: structured result (no more hand-written regexes digging through stdout)
        resultJson: j.parsed || null,
        result: j.parsed || null,
        resultParseError: j.parseError || null,
        resultPath: j.resultPath || null,
        resultPathWsl: j.resultPathWsl || null,
        resultBytes: j.resultBytes || 0,
        resultTruncated: !!j.resultTruncated,
        stdoutTail: j.stdoutTail || null,
        stderrTail: j.stderrTail || null,
        pathWarnings: j.pathWarnings || [],
        warnings: j.warnings || j.pathWarnings || [],
        shots: j.shots || null,
        progress: j.progress || null,
        progressAt: j.progressAt || null,
        progressAgeMs: j.progressAt ? now - j.progressAt : null,
        heartbeat: j.heartbeat || null,
        progressHistory: j.progressHistory || [],
        scriptStaging: j.scriptStaging || null,
        inputFile: j.inputFile || null,
        scriptFile: j.scriptFile || null,
        lastException: j.lastException || null,
        artifacts: running ? [] : jobArtifacts(j),
    };
}
/** Take the tail from a log file (shared by run and job) */
export function tailFile(p, tail) {
    try {
        return fs.readFileSync(p, 'utf8').slice(-tail);
    }
    catch (e) {
        return null;
    }
}
//# sourceMappingURL=snapshot.js.map