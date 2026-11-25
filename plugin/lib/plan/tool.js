import { vTool } from '../contracts/tool.js';
import { ANY_SCHEMA } from '../tools/schema-diagnostic.js';
import { BACKEND_HINT, PLUGIN_VERSION, T } from '../constants.js';
import { ensureBackend } from '../host/backend/index.js';
import { backendPost, jsonPayload, leasedText } from '../host/http.js';
import { renderStructured } from '../ui/cards.js';
import { finishPlanResponse, planViaWorker } from './headless-target.js';
import { toolError } from '../tools/errors.js';
import { asRecord, text } from '../contracts/dynamic.js';
export function registerPlan(ctx, port) {
    ctx.effect(() => ctx.tools.register(vTool({
        name: 'blender_rt_plan',
        description: '[v' +
            PLUGIN_VERSION +
            '] [verdict / acceptance / export / sculpting] 34 families · 228 ops; where an op exists you may not hand-write equivalent geometry/acceptance checks.' +
            '**If you are unsure which one to use, ask the catalog first: op="catalog"** (served locally, no Blender round-trip; covers "when to use / when not to / minimal skeleton");' +
            'expand a single family with op="catalog", args={family:"audit"}; for operator details use each family\'s own <family>_help.' +
            'Common ones: audit_* · qc_render_views|qc_compare · sculpt_* · fix_* · uv_* · print_report · sweep_* · ' +
            'deliver_* · motion_* · generator_save|run (save takes **code=**) · material_* · render_lock|render_status · render_state|render_wait · ' +
            'asm_* (assembly scan / manifest / merge / gate) · blockout_* · img_digest|probe|measure|calib · ' +
            'gate_preflight|checkpoint|deliver · ' +
            'visualreport_report · shapesolve_solve · surface_loft|sweep|patch|validate.' +
            'For contract-level criteria see docs/assumption-driven-modeling-cookbook.md; write ops take a lease, read-only ops are exempt.' +
            'Passing session="auto" or a headless worker name starts a worker per family and runs synchronously (does not depend on the GUI); the first takes about 2 s, later ones are reused.' +
            'A misspelled op returns did_you_mean (with a skeleton); a misspelled parameter name returns "unknown parameter".',
        parameters: {
            op: {
                type: 'string',
                required: true,
                description: 'a contract op or plan_<op> (see the tool description; op=help / plan_help prints a quick reference)',
            },
            args: {
                type: 'json',
                description: 'the argument object for the op, e.g. {"cid":"joint","err":184,"tolerance":220,"identifiable":["dy"]}',
            },
            path: {
                type: 'string',
                description: 'output path for op=report (Markdown); when omitted only text is returned',
            },
            attach_images: {
                type: 'boolean',
                description: 'attach result images back to the model (≤2; on by default for img_digest/qc_compare)',
            },
            session: { type: 'string', description: 'headless worker session; "auto"=start automatically' },
        },
        output: { schema: ANY_SCHEMA, render: renderStructured },
        isConcurrencySafe: () => false,
        timeoutMs: T.plan,
        async execute(argsIn) {
            if (!(await ensureBackend(port)))
                return toolError('backend_unreachable', 'backend unavailable (127.0.0.1:' + String(port) + ')', BACKEND_HINT);
            const op = text(argsIn.op) || 'status';
            const payload = jsonPayload(argsIn.args);
            if (!Object.keys(payload).length &&
                typeof argsIn.args === 'string' &&
                argsIn.args.trim() &&
                argsIn.args.trim() !== '{}') {
                return toolError('invalid_params', 'PLAN ' + op + ' failed · args is not a valid JSON object: ' + argsIn.args.slice(0, 200), 'pass args as a JSON object, e.g. {"family":"audit"}');
            }
            if (op === 'report' && argsIn.path)
                payload.path = text(argsIn.path);
            const sessRaw = argsIn.session ? text(argsIn.session) : '';
            if (sessRaw) {
                const pr = await planViaWorker(ctx, port, op, payload, sessRaw === 'auto' ? undefined : sessRaw);
                const prRec = asRecord(pr);
                if (prRec.ok !== true) {
                    return toolError('backend_error', 'PLAN ' +
                        op +
                        ' headless execution failed · ' +
                        text(prRec.error || 'unknown') +
                        (prRec.hint ? String.fromCharCode(10) + text(prRec.hint) : ''), 'first blender_rt_worker(op="start", name="…", preload="…"), or pass session="auto"');
                }
                return await finishPlanResponse(ctx, op, prRec.res, argsIn);
            }
            const r = await backendPost(port, '/plan', { op: op, args: payload }, 300000);
            const lt = leasedText(r);
            if (lt)
                return { text: lt };
            if (!r || r.ok !== true)
                return toolError('backend_error', 'PLAN ' + op + ' failed · ' + text(r.error || r.raw || 'unknown'), 'check the backend /plan route and the op name; when unsure start with op=catalog');
            return await finishPlanResponse(ctx, op, r.result, argsIn);
        },
    })), 'dsh-blender-plugin: rt-plan');
}
//# sourceMappingURL=tool.js.map
