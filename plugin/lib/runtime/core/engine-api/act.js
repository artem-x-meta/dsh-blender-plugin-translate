// engine API: Python execution / command passthrough (split out of server-compat.ts)
import { ACT_WRAPPER } from '../../paths.js';
import { KERNEL_BOOTSTRAP } from '../kernel/index.js';
import { enrichError } from '../errors.js';
import { planOpCrossChannelHint } from '../../catalog/index.js';
export function createActApi(E) {
    const { addon } = E;
    return {
        async act(code, timeoutMs = 120000, file = null) {
            const src = file
                ? 'K.run(' + JSON.stringify(String(file)) + ')'
                : code === undefined || code === null
                    ? ''
                    : String(code);
            const wrapped = KERNEL_BOOTSTRAP + '\n' + ACT_WRAPPER(src);
            const t0 = Date.now();
            const res = await addon.send('execute_code', { code: wrapped }, timeoutMs);
            const resRec = res !== null && typeof res === 'object' ? res : null;
            const raw = resRec && typeof resRec.result === 'string' ? resRec.result : '';
            const ms = Date.now() - t0;
            const pick = (tag) => {
                const ls = raw.split('\n').filter((x) => x.indexOf(tag + ' ') === 0);
                return ls.length ? ls[ls.length - 1] : null;
            };
            const errLine = pick('DSH_ACT_ERR');
            const okLine = pick('DSH_ACT_OK');
            let p;
            try {
                p = JSON.parse((errLine || okLine || '').slice((errLine ? 'DSH_ACT_ERR ' : 'DSH_ACT_OK ').length).trim());
            }
            catch (e) {
                p = null;
            }
            if (p) {
                return {
                    ok: !errLine,
                    executed: true,
                    ms: ms,
                    mainThreadMs: ms,
                    stdout: p.stdout || '',
                    stderr: p.stderr || '',
                    error: p.error ? enrichError(p.error, p.traceback) : null,
                    traceback: p.traceback || null,
                    sceneEpoch: p.epoch || null,
                    file: file || null,
                };
            }
            return {
                ok: true,
                executed: true,
                ms: ms,
                mainThreadMs: ms,
                stdout: raw,
                stderr: '',
                error: null,
                traceback: null,
                marker_missing: true,
                file: file || null,
            };
        },
        /** Generic command passthrough: any addon command name + parameters (the ones the MCP layer does not expose are callable too) */
        async cmd(name, params = {}, timeoutMs = 120000) {
            if (!name || typeof name !== 'string')
                throw new Error('cmd: name required');
            // v0.9.6: sending a plan op as an addon command is a detour that actually showed up in practice (qc_render_catalog),
            // so it is corrected **locally** here instead of wasting another Blender round-trip.
            const hint = planOpCrossChannelHint(name);
            if (hint)
                return { status: 'error', result: 'CMD_HINT ' + hint, hint_shown: true };
            return addon.send(name, params || {}, timeoutMs);
        },
        /** Command inventory: catalog + current availability (affected by the scene switch and its API key) */
    };
}
//# sourceMappingURL=act.js.map
