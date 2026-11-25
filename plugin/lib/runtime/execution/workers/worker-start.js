// worker start and readiness (split out of workers.ts, behavior frozen)
import path from 'node:path';
import fs from 'node:fs';
import { spawn } from 'node:child_process';
import { winToWsl, wslToWin } from '../../config.js';
import { assertBlenderExe, blenderExeSource } from '../exe-guard.js';
import { BLENDER_EXE, USER_CONFIG_WIN, USER_SCRIPTS_WIN, WIN_TMP, WORKER_PATH, } from '../../paths.js';
import { KERNEL_BOOTSTRAP } from '../../core/kernel/index.js';
import { errorMessage } from '../../core/json.js';
import { workerAlive, workerCall, workerSnapshot, workerState, workerKey } from './api.js';
// assertBlenderExe moved to runtime/execution/exe-guard.ts (shared with the job channel); the old export name is kept here for compatibility.
export { assertBlenderExe } from '../exe-guard.js';
function prepareBootFile(ctx, w, opts) {
    // preload — write KERNEL_BOOTSTRAP + module sources into a boot file that the worker execs before becoming ready.
    const preloadRaw = opts.preload === undefined || opts.preload === null ? [] : opts.preload;
    const preloadList = (Array.isArray(preloadRaw) ? preloadRaw : String(preloadRaw).split(','))
        .map((x) => String(x).trim().replace(/\.py$/, ''))
        .filter(Boolean);
    if (!preloadList.length)
        return null;
    try {
        const bootWsl = path.join(winToWsl(WIN_TMP), 'worker_boot_' + workerKey(w.name) + '.py');
        fs.mkdirSync(path.dirname(bootWsl), { recursive: true });
        const bootSrc = [KERNEL_BOOTSTRAP]
            .concat(preloadList.map((m) => ctx.preloadChunk(m)))
            .join(String.fromCharCode(10));
        fs.writeFileSync(bootWsl, bootSrc, 'utf8');
        return wslToWin(bootWsl);
    }
    catch (e) {
        const err = new Error('failed to write the worker preload prelude to disk: ' + errorMessage(e));
        err.hint = 'Check that workDir is writable (DSH_BLENDER_WORKDIR)';
        throw err;
    }
}
function buildWorkerArgs(port, gpuMode, engineMode, bootWin) {
    const args = [
        '-b',
        '--factory-startup',
        '--python',
        wslToWin(WORKER_PATH),
        '--',
        '--port',
        String(port),
        '--gpu',
        gpuMode,
        '--engine',
        engineMode,
        '--frame-dir',
        String(WIN_TMP),
    ];
    if (bootWin)
        args.push('--boot', bootWin);
    return args;
}
function buildWorkerEnv(opts) {
    const childEnv = Object.assign({}, process.env, {
        PYTHONIOENCODING: 'utf-8',
        DSH_WORKER_FRAME_DIR: String(WIN_TMP),
    });
    if (opts.useUserConfig) {
        if (USER_CONFIG_WIN)
            childEnv.BLENDER_USER_CONFIG = USER_CONFIG_WIN;
        if (USER_SCRIPTS_WIN)
            childEnv.BLENDER_USER_SCRIPTS = USER_SCRIPTS_WIN;
    }
    return childEnv;
}
function waitWorkerReady(w, child, opts) {
    return new Promise((resolve) => {
        let so = '', se = '';
        const t = setTimeout(() => resolve({ timedOut: true }), Math.max(20000, Number(opts.startTimeoutMs) || 90000));
        if (child.stdout)
            child.stdout.on('data', (d) => {
                so += d.toString('utf8');
                w.stdoutTail = so.slice(-4000);
                const m = so.match(/DSH_WORKER (\{[\s\S]*?\})\s*(\r?\n|$)/);
                if (m) {
                    try {
                        clearTimeout(t);
                        resolve({ ok: JSON.parse(m[1]) });
                    }
                    catch (e) {
                        /* keep accumulating */
                    }
                }
            });
        if (child.stderr)
            child.stderr.on('data', (d) => {
                se += d.toString('utf8');
                w.stderrTail = se.slice(-4000);
            });
        child.on('close', (code, sig) => {
            clearTimeout(t);
            resolve({ exited: true, code: code, signal: sig });
        });
        child.on('error', (e) => {
            clearTimeout(t);
            resolve({ spawnErr: e });
        });
    });
}
function assertWorkerReady(w, child, info) {
    if (info.spawnErr) {
        const e = new Error('worker would not start (' +
            String(BLENDER_EXE) +
            '): ' +
            String((info.spawnErr && info.spawnErr.message) || info.spawnErr));
        e.hint = 'Check the blenderExe setting and whether runtime/py/core/worker.py exists';
        throw e;
    }
    if (!info.ok) {
        const e = new Error('worker not ready: ' + JSON.stringify(info).slice(0, 200));
        e.hint = 'worker stderr tail: ' + String(w.stderrTail || '').slice(-500);
        try {
            child.kill('SIGKILL');
        }
        catch (x) { }
        throw e;
    }
    const boot = (info.ok.boot || null);
    if (boot && boot.ok === false) {
        const e = new Error('worker boot/preload failed: ' + String(boot.error || 'unknown'));
        e.hint =
            'boot stderr tail: ' +
                String(boot.stderr || '').slice(-500) +
                '; check the preload module name (runtime/py/<domain>/<name>.py)';
        try {
            child.kill('SIGKILL');
        }
        catch (x) { }
        throw e;
    }
    return info.ok;
}
async function warmupWorker(w) {
    try {
        const wr = await workerCall(w, { op: 'see', spec: { width: 64, height: 36, aa: '2' } }, 60000);
        return { ok: !!(wr && wr.ok !== false), ms: (wr && wr.ms) || null };
    }
    catch (err) {
        return {
            ok: false,
            error: String(err.message || err).slice(0, 200),
        };
    }
}
// With an empty BLENDER_EXE, spawn() throws Node's TypeError synchronously and neither child.on('error')
// nor assertWorkerReady's hint is ever reached. So pre-check before starting (implemented in exe-guard.ts) and give actionable config guidance.
export async function workerStart(ctx, opts = {}, nameArg) {
    const w = workerState(ctx, nameArg !== undefined ? nameArg : opts.name);
    if (workerAlive(w) && w.ready)
        return workerSnapshot(w);
    // The pre-check must come before prepareBootFile writes to disk and before spawn: an empty exe no longer triggers Node's raw TypeError.
    assertBlenderExe(BLENDER_EXE, blenderExeSource());
    if (w.child) {
        try {
            w.child.kill('SIGKILL');
        }
        catch (e) { }
        w.child = null;
    }
    const port = Number(opts.port) || w.port;
    const gpuMode = String(opts.gpu === undefined || opts.gpu === null ? 'auto' : opts.gpu);
    const engineMode = String(opts.engine === undefined || opts.engine === null ? 'eevee' : opts.engine);
    const bootWin = prepareBootFile(ctx, w, opts);
    const args = buildWorkerArgs(port, gpuMode, engineMode, bootWin);
    const spawnOpts = {
        env: buildWorkerEnv(opts),
        stdio: ['ignore', 'pipe', 'pipe'],
        windowsHide: true,
    };
    const child = spawn(BLENDER_EXE, args, spawnOpts);
    w.child = child;
    w.port = port;
    w.ready = false;
    w.startedAt = Date.now();
    w.gpu = null;
    w.pid = child.pid ?? null;
    w.lastError = null;
    w.stdoutTail = '';
    w.stderrTail = '';
    const info = await waitWorkerReady(w, child, opts);
    const okRec = assertWorkerReady(w, child, info);
    const okPid = typeof okRec.pid === 'number' ? okRec.pid : null;
    w.ready = true;
    w.gpu = okRec.gpu || null;
    w.pid = okPid || child.pid || null;
    w.boot = (info.ok && info.ok.boot) || null;
    w.lastUsed = Date.now();
    ctx.metrics.workerStarts++;
    // Interactive headless: the first Workbench frame pays ~1 s of renderer initialization (measured on this machine: first 1003ms / second 13ms).
    // So run one tiny warmup (64×36) at start and pay that second up front; only then does each see cost 10–40ms.
    let warm = null;
    if (opts.warmup !== false)
        warm = await warmupWorker(w);
    return Object.assign(workerSnapshot(w), { hello: info.ok, warmup: warm });
}
//# sourceMappingURL=worker-start.js.map