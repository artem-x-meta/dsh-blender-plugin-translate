import { spawn } from 'node:child_process';
import { BLENDER_EXE } from '../../../paths.js';
import { assertBlenderExe, blenderExeSource } from '../../exe-guard.js';
import { makeStageScanner, startHeartbeat } from '../../../core/progress.js';
import { baseChildEnv, withWslEnv } from '../../../proc_env.js';
import { wslToWin } from '../../../config.js';
export function spawnJobChild(d, j, p, so, se, opts) {
    const jobs = d.jobs;
    // job and worker share the precheck; when empty it throws blender_exe_missing at once,
    // instead of letting spawn(null) throw Node's raw TypeError (route/tool layer gets no actionable guidance).
    assertBlenderExe(BLENDER_EXE, blenderExeSource(), 'blender_rt_job op=start');
    const spawnOpts = {
        env: withWslEnv(baseChildEnv(Object.assign({}, p.envPairs)), opts.env),
        stdio: ['ignore', 'pipe', 'pipe'],
        detached: false,
        windowsHide: true,
    };
    const child = spawn(BLENDER_EXE, p.args, spawnOpts);
    j.child = child;
    j.pid = child.pid;
    // v0.9.3: stage scanning + line/byte counting (stdout is still piped to the log file)
    const scanOut = makeStageScanner(j), scanErr = makeStageScanner(j);
    if (child.stdout)
        child.stdout.on('data', (d) => {
            try {
                j.logBytes = (j.logBytes || 0) + d.length;
                scanOut(d.toString('utf8'));
            }
            catch (e) {
                /* ignore */
            }
        });
    if (child.stderr)
        child.stderr.on('data', (d) => {
            try {
                scanErr(d.toString('utf8'));
            }
            catch (e) {
                /* ignore */
            }
        });
    if (child.stdout)
        child.stdout.pipe(so);
    if (child.stderr)
        child.stderr.pipe(se);
    jobs.set(p.id, j);
    if (jobs.size > 20) {
        const k = jobs.keys().next().value;
        if (k !== undefined && k !== p.id)
            jobs.delete(k);
    }
    d.ledgerAppend({
        id: p.id,
        kind: 'job',
        status: 'running',
        startedAt: j.startedAt,
        pid: j.pid,
        script: p.sp.win,
        runId: p.runId,
        outdir: p.outdirWin,
        engine: p.engineMode,
        timeoutMs: p.timeoutMs,
        stage: null,
        file: p.fileOpt === undefined ? null : String(p.fileOpt), // F-09: the ledger records file, so afterwards we can tell "no file given" from "given but not opened"
        dir: wslToWin(p.dir),
        stdoutLog: wslToWin(p.outPath),
        stderrLog: wslToWin(p.errPath),
    });
    j.timer = setTimeout(() => {
        j.status = 'killed';
        try {
            child.kill('SIGKILL');
        }
        catch (e) { }
    }, p.timeoutMs);
    const stopHb = startHeartbeat(j, p.dir);
    return { child, stopHb };
}
//# sourceMappingURL=spawn.js.map