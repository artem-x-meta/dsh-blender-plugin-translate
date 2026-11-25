import { vTool } from '../contracts/tool.js';
import { ANY_SCHEMA } from './schema-diagnostic.js';
import { T, BACKEND_HINT } from '../constants.js';
import { ensureBackend } from '../host/backend/index.js';
import { backendPost, jsonPayload, leasedText } from '../host/http.js';
import { renderOne } from '../ui/cards.js';
import { toolError } from './errors.js';
import { text } from '../contracts/dynamic.js';
export function registerPerf(ctx, port) {
    ctx.effect(() => ctx.tools.register(vTool({
        name: 'blender_rt_perf',
        description: '[Render performance] Cycles CPU bottleneck diagnosis and optimization presets. op=analyze measures the per-round sync / per-sample GPU cost in practice (takes a dozen-odd seconds of the main thread); op=apply applies presets (persistent_data / OptiX denoising / denoising_use_gpu / auto_tile off / sample cap); op=revert restores the state before apply; op=status shows the current settings and the saved snapshot; op=help shows the contract. Background measured in practice: a 2318-object scene syncs ≈4.2 s per round on the CPU side, one GPU sample ≈0.2 s (1080p), the first kernel JIT ≈15 s; persistent_data takes repeated renders from 14.6 s → 0.79 s.',
        parameters: {
            op: {
                type: 'string',
                required: true,
                description: 'status | analyze | apply | revert | help',
            },
            args: {
                type: 'json',
                description: 'analyze{pct=25,low=1,high=4}; apply{samples=1024,persistent=true,denoiser="OPTIX",denoise_gpu=true,auto_tile=false}',
            },
        },
        output: { schema: ANY_SCHEMA, render: renderOne },
        isConcurrencySafe: () => false,
        timeoutMs: T.perf,
        async execute(args) {
            if (!(await ensureBackend(port)))
                return toolError('backend_unreachable', 'backend unavailable (127.0.0.1:' + String(port) + ')', BACKEND_HINT);
            const op = text(args.op) || 'status';
            // ⚠ With no args you must pass undefined (passing {} makes the python side take one extra positional argument: "_dsh_perf_status_cycles() takes 0 positional arguments" measured in practice)
            const pargs = jsonPayload(args.args);
            const r = await backendPost(port, '/perf', { op: op, args: Object.keys(pargs).length ? pargs : undefined }, 600000);
            const lt = leasedText(r);
            if (lt)
                return { text: lt };
            if (!r || r.ok !== true)
                return toolError('backend_error', 'PERF ' + op + ' failed · ' + text(r.error || r.raw || 'unknown'), 'check the op name; blender_rt_perf op=status');
            return { text: 'PERF ' + op + ' ' + JSON.stringify(r.result) };
        },
    })), 'dsh-blender-plugin: rt-perf');
}
//# sourceMappingURL=perf.js.map