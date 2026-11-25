import { KERNEL_BOOTSTRAP } from '../kernel/index.js';
import { extractLoop } from '../output/index.js';
import { wslToWin } from '../../config.js';
import { errorMessage } from '../json.js';
/** Local render-guard ops (read/wait/reset flags; install/selftest take one Blender round-trip). */
export function createRenderGuardOp(E) {
    const { RENDER_FLAG_WSL, RENDER_STALE_MS, addon, clearRenderFlag, ensureRenderGuard, readRenderFlag, } = E;
    /** v0.9.6: local ops for the render guard (read/wait/clear the flag; install/selftest take one Blender round-trip) */
    async function renderGuardCall(modOp, payload) {
        await ensureRenderGuard();
        const body = 'print("LOOP " + K.dsh_render_guard["dispatch"](' +
            JSON.stringify(String(modOp)) +
            ', _json.dumps(_json.loads(' +
            JSON.stringify(JSON.stringify(payload || {})) +
            '))))';
        return extractLoop(await addon.send('execute_code', { code: KERNEL_BOOTSTRAP + '\nimport json as _json\n' + body }, 120000));
    }
    async function renderGuardOp(op, payload) {
        const p = payload && typeof payload === 'object' ? payload : {};
        if (op === 'render_state') {
            const g = readRenderFlag();
            const out = {
                ok: true,
                busy: !!(g.present && !g.stale),
                stale: !!g.stale,
                ageMs: g.ageMs,
                flag: g.info,
                flagPath: wslToWin(RENDER_FLAG_WSL),
                staleMs: RENDER_STALE_MS,
                note: 'busy=true ⇒ main-thread commands are rejected immediately; use op="render_wait" to wait for it, or op="render_reset" to clear a stale flag',
            };
            if (p.probe) {
                try {
                    out.blender = await renderGuardCall('state', {});
                }
                catch (e) {
                    out.probe_error = errorMessage(e).slice(0, 200);
                }
            }
            return out;
        }
        if (op === 'render_wait') {
            const cap = Math.max(1000, Math.min(600000, Number(p.timeout_ms) || 120000));
            const t0 = Date.now();
            for (;;) {
                const g = readRenderFlag();
                if (!g.present || g.stale) {
                    return {
                        ok: true,
                        idle: true,
                        waitedMs: Date.now() - t0,
                        stale_cleared: !!g.stale,
                        last: g.info,
                    };
                }
                if (Date.now() - t0 >= cap) {
                    return {
                        ok: false,
                        idle: false,
                        timeout: true,
                        waitedMs: Date.now() - t0,
                        flag: g.info,
                        hint: 'Still rendering: for a long render start with blender_rt_job(op="start") from the outset, so it is a separate process and does not occupy the main thread',
                    };
                }
                await new Promise((r) => setTimeout(r, 400));
            }
        }
        if (op === 'render_reset') {
            const had = readRenderFlag();
            const removed = clearRenderFlag();
            let blender;
            try {
                blender = await renderGuardCall('clear', { why: String(p.why || 'reset') });
            }
            catch (e) {
                blender = { ok: false, error: errorMessage(e).slice(0, 160) };
            }
            return {
                ok: true,
                cleared: removed,
                previous: had.info,
                blender: blender,
                note: 'Only use when "the flag is stale / the render has actually crashed"; clearing it while a render really runs makes write commands queue',
            };
        }
        if (op === 'render_guard_install') {
            const r = await renderGuardCall('install', { force: !!p.force });
            return { ok: true, install: r, flagPath: wslToWin(RENDER_FLAG_WSL) };
        }
        // render_guard_selftest
        return await renderGuardCall('selftest', {});
    }
    return renderGuardOp;
}
//# sourceMappingURL=render-guard.js.map