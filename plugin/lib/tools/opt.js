import { vTool } from '../contracts/tool.js';
import { ANY_SCHEMA } from './schema-diagnostic.js';
import { T, BACKEND_HINT } from '../constants.js';
import { ensureBackend } from '../host/backend/index.js';
import { backendPost, jsonPayload, leasedText } from '../host/http.js';
import { renderOne } from '../ui/cards.js';
import { toolError } from './errors.js';
import { text } from '../contracts/dynamic.js';
export function registerOpt(ctx, port) {
    ctx.effect(() => ctx.tools.register(vTool({
        name: 'blender_rt_opt',
        description: '[Object slimming] Cuts Cycles per-round scene sync cost (measured ≈1.4 ms/object). op=analyze lists groups that can be merged safely plus the expected savings; op=join performs the merge (**default dry_run=true reports only**; only dry_run=false really merges — strongly recommended to also pass save_before=<absolute .blend path> to store a rollback point first). Merge rules: same collection / same material / same parent / no modifiers / no animation / no shape keys / no custom properties / no instances / not library-linked. After merging there is **zero geometry loss** (face and vertex counts unchanged); merged objects are named `<prefix>_MERGED_<material>`.',
        parameters: {
            op: { type: 'string', required: true, description: 'analyze | join | help' },
            args: {
                type: 'json',
                description: 'join{dry_run=true, save_before="D:/.../xxx_before_join.blend"}',
            },
        },
        output: { schema: ANY_SCHEMA, render: renderOne },
        isConcurrencySafe: () => false,
        timeoutMs: T.opt,
        async execute(args) {
            if (!(await ensureBackend(port)))
                return toolError('backend_unreachable', 'backend unavailable (127.0.0.1:' + String(port) + ')', BACKEND_HINT);
            const op = text(args.op) || 'analyze';
            const oargs = jsonPayload(args.args);
            const r = await backendPost(port, '/opt', {
                op: op === 'join' ? 'opt_join' : 'opt_analyze',
                args: Object.keys(oargs).length ? oargs : undefined,
            }, 600000);
            const lt = leasedText(r);
            if (lt)
                return { text: lt };
            if (!r || r.ok !== true)
                return toolError('backend_error', 'OPT ' + op + ' failed · ' + text(r.error || r.raw || 'unknown'), 'Check the op name; blender_rt_opt op=list');
            return { text: 'OPT ' + op + ' ' + JSON.stringify(r.result) };
        },
    })), 'dsh-blender-plugin: rt-opt');
}
//# sourceMappingURL=opt.js.map