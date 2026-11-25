import { workerAlive, workerCall, workerState } from './api.js';
import { workerStart } from './worker-start.js';
export async function workerStop(ctx, nameArg) {
    const w = workerState(ctx, nameArg);
    if (!workerAlive(w)) {
        w.ready = false;
        return { name: w.name, stopped: false, wasAlive: false };
    }
    let bye = null;
    try {
        bye = await workerCall(w, { op: 'shutdown' }, 8000);
    }
    catch (e) {
        /* kill it directly */
    }
    await new Promise((r) => setTimeout(r, 300));
    try {
        if (workerAlive(w) && w.child)
            w.child.kill('SIGKILL');
    }
    catch (e) { }
    w.ready = false;
    return { name: w.name, stopped: true, wasAlive: true, bye: bye };
}
/** Restart: swap in a clean session (reuse = giving up process isolation; use it when a script made the session dirty) */
export async function workerRestart(ctx, nameArg, opts) {
    await workerStop(ctx, nameArg);
    return workerStart(ctx, opts || {}, nameArg);
}
// Session pool: idle reaping (default 15 min; tunable via DSH_WORKER_TTL_MS; 0=off). Only hot processes that are ready with no request in flight are reaped.
export function createWorkerReaper(ctx) {
    const WORKER_TTL_MS = (() => {
        const n = Number(process.env.DSH_WORKER_TTL_MS);
        return Number.isFinite(n) && n >= 0 ? n : 900000;
    })();
    let workerReaper = null;
    if (WORKER_TTL_MS > 0) {
        workerReaper = setInterval(() => {
            const now = Date.now();
            for (const w of ctx.WORKERS.values()) {
                if (!workerAlive(w) || !w.ready)
                    continue;
                if (w.lastUsed && now - w.lastUsed > WORKER_TTL_MS) {
                    try {
                        workerStop(ctx, w.name).catch(() => { });
                    }
                    catch (e) {
                        /* try again next round */
                    }
                }
            }
        }, 30000);
        try {
            if (workerReaper.unref)
                workerReaper.unref();
        }
        catch (e) { }
    }
    function clearWorkerReaper() {
        if (workerReaper) {
            try {
                clearInterval(workerReaper);
            }
            catch (e) { }
            workerReaper = null;
        }
    }
    function killWorkers() {
        try {
            for (const w of ctx.WORKERS.values()) {
                if (workerAlive(w) && w.child)
                    w.child.kill('SIGKILL');
            }
        }
        catch (e) { }
    }
    return { clearWorkerReaper, killWorkers };
}
//# sourceMappingURL=lifecycle.js.map