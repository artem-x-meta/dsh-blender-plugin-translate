// engine API: the inner-loop loop_* (split out of server-compat.ts)
import { extractLoop } from '../output/index.js';
import { KERNEL_BOOTSTRAP } from '../kernel/index.js';
export function createLoopApi(E) {
    const { addon, ensureRunner } = E;
    return {
        async loopStart(spec) {
            await ensureRunner();
            const j = JSON.stringify(spec || {});
            const body = 'import json as _json' +
                '\n' +
                'print("LOOP " + K.dsh_loop_api["start"](_json.loads(' +
                JSON.stringify(j) +
                ')))';
            return extractLoop(await addon.send('execute_code', { code: KERNEL_BOOTSTRAP + '\n' + body }, 60000));
        },
        async loopStatus(history = 8) {
            await ensureRunner();
            const body = 'print("LOOP " + K.dsh_loop_api["status"](' + String(Number(history) || 8) + '))';
            return extractLoop(await addon.send('execute_code', { code: KERNEL_BOOTSTRAP + '\n' + body }, 60000));
        },
        async loopStop() {
            await ensureRunner();
            const body = 'print("LOOP " + K.dsh_loop_api["stop"]())';
            return extractLoop(await addon.send('execute_code', { code: KERNEL_BOOTSTRAP + '\n' + body }, 60000));
        },
        async loopBench(iterations = 2000) {
            await ensureRunner();
            const body = 'print("LOOP " + K.dsh_loop_api["bench"](' + String(Number(iterations) || 2000) + '))';
            return extractLoop(await addon.send('execute_code', { code: KERNEL_BOOTSTRAP + '\n' + body }, 60000));
        },
        /** Candidate board: top_k / grouped (cross-object batch) results */
        async loopBoard(limit = 10, groups = true) {
            await ensureRunner();
            const body = 'print("LOOP " + K.dsh_loop_api["board"](' +
                String(Number(limit) || 10) +
                ', ' +
                (groups === false ? 'False' : 'True') +
                '))';
            return extractLoop(await addon.send('execute_code', { code: KERNEL_BOOTSTRAP + '\n' + body }, 60000));
        },
        /** Export a reusable script (embeds the setup source + the best parameters) */
        async loopExport(opts = {}) {
            await ensureRunner();
            const pathLit = opts.path ? JSON.stringify(String(opts.path)) : 'None';
            const top = String(Number(opts.top) || 1);
            const variants = opts.includeVariants ? 'True' : 'False';
            const note = JSON.stringify(String(opts.note || ''));
            const body = 'print("LOOP " + K.dsh_loop_api["export"](path=' +
                pathLit +
                ', top=' +
                top +
                ', include_variants=' +
                variants +
                ', note=' +
                note +
                '))';
            return extractLoop(await addon.send('execute_code', { code: KERNEL_BOOTSTRAP + '\n' + body }, 120000));
        },
        /** Inner-loop contract quick reference (spec fields + ns presets + helper functions) */
        async loopHelp() {
            await ensureRunner();
            const body = 'print("LOOP " + K.dsh_loop_api["help"]())';
            return extractLoop(await addon.send('execute_code', { code: KERNEL_BOOTSTRAP + '\n' + body }, 60000));
        },
        /** Whole-window/region screenshot (the screenshot_area path, preserving the original CLI channel capability) */
    };
}
//# sourceMappingURL=loop.js.map