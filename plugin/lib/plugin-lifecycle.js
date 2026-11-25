/** Plugin lifecycle wiring: auto-start, 15s resident watchdog, clear handles on unload (decoupled from the tool surface). */
import { ensureBackend, isPaused, killBackendByCmd, killChildHandle, probe, sleep, startBackend, } from './host/backend/index.js';
import { backendPost } from './host/http.js';
export function registerLifecycle(ctx, port, autoStart) {
    void (async () => {
        if (autoStart && !isPaused())
            await ensureBackend(port);
    })();
    // Resident watchdog: probe liveness every 15s, restart on disconnect (self-heals across host restarts / killed processes / reclaimed ports).
    // An explicit op=stop sets paused; the watchdog respects it and does not fight the user.
    // ★ v1.0.1 (**clear the corpse before respawning** when a probe fails): otherwise, while a "zombie backend holds the port", the respawned
    //   process is bound to hit EADDRINUSE and exit → it spins once every 15 s and never self-heals (field case: the backend event loop was pinned by a long synchronous call,
    //   /health did not answer, and even SIGTERM could not get scheduled). The probe timeout is only 1500ms, so 2 consecutive failures (≈30s)
    //   are required before declaring a hang, to avoid killing a backend that is merely busy.
    let probeMisses = 0;
    ctx.effect(() => {
        const wd = setInterval(() => {
            void (async () => {
                try {
                    if (isPaused())
                        return;
                    if (await probe(port)) {
                        probeMisses = 0;
                        // lease heartbeat: renew only when already held, never seize another session while idle
                        try {
                            await backendPost(port, '/lease', { renewOnly: true }, 5000);
                        }
                        catch {
                            /* the backend may have just died; try again next round */
                        }
                        return;
                    }
                    probeMisses += 1;
                    if (probeMisses >= 2) {
                        probeMisses = 0;
                        // SIGTERM → 1.2s → SIGKILL: a process whose event loop is pinned by synchronous work only answers SIGKILL
                        try {
                            killBackendByCmd(port, 'SIGTERM');
                        }
                        catch {
                            /* ignore */
                        }
                        await sleep(1200);
                        try {
                            killBackendByCmd(port, 'SIGKILL');
                        }
                        catch {
                            /* ignore */
                        }
                    }
                    await startBackend(port);
                }
                catch {
                    /* watchdog failures stay silent; try again next round */
                }
            })();
        }, 15000);
        return () => clearInterval(wd);
    }, 'dsh-blender-plugin: watchdog');
    ctx.effect(() => () => {
        killChildHandle();
    }, 'dsh-blender-plugin: backend');
}
//# sourceMappingURL=plugin-lifecycle.js.map