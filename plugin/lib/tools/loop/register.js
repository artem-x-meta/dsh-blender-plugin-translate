import { vTool } from '../../contracts/tool.js';
import { ANY_SCHEMA } from '../schema-diagnostic.js';
import { T } from '../../constants.js';
import { executeLoop } from './execute.js';
import { renderOne } from '../../ui/cards.js';
export function registerLoop(ctx, port) {
    ctx.effect(() => ctx.tools.register(vTool({
        name: 'blender_rt_loop',
        description: '[Inner-loop search] Move "dozens to thousands of parameter trials" out of the model turn and into the Blender main thread (bpy.app.timers, 160 tick/s, both iteration and time caps + emergency stop): you write only the objective and the range, the machine searches.' +
            '**Use it when the task shape fits**: alignment / fitting / back-solving dimensions / parameter sweeps — the criterion can be written as a single number (silhouette IoU, bounding-box size error, profile difference, or your own score), with dozens to thousands of candidates. Trying ≤5 sets → just loop in rt_do yourself.' +
            '**GUI uses timers (160 tick/s); for headless pass target="session"** (uses the worker\'s dsh_loop_sync blocking loop, not dependent on timers; needs the worker started with runner in preload, the tool starts it automatically).' +
            'setup runs once, step/measure share ns (preset bpy/K/random/np/i/frac/penalize/anneal/record); measure must set ns["score"] (parameters go in ns["params"]); ready-made objective functions K.dsh_measure = {silhouette_iou, aabb_err, profile_err}.' +
            'Rhythm: op=start → status → board (candidate table) → export (best written to a reproducible script; only replayed automatically if apply(p) is defined in setup).' +
            '**The inner loop only optimizes the objective function you wrote: after convergence you must cross-check through another path + take a look with rt_see** (guard against Goodhart); after the run the scene stays on the last iteration\'s parameters, not on best.' +
            'See blender_rt_plan(op="catalog", args={tool:"rt_loop"}) for the spec fields, the ns contract and copy-paste templates.',
        parameters: {
            op: {
                type: 'string',
                required: true,
                description: 'start | status | stop | board | export | help | bench',
            },
            target: {
                type: 'string',
                description: 'gui (default, timers) | session (headless worker blocking synchronously, the recommended headless main path)',
            },
            session: {
                type: 'string',
                description: 'worker instance name when target=session (default dsh-loop)',
            },
            spec: {
                type: 'json',
                description: 'spec for op=start: {setup, step, measure, iterations, budget_ms, interval, measure_every, minimize, top_k, group_key, redraw_every}',
            },
            history: { type: 'integer', description: 'length of the metric trail returned by op=status, default 8' },
            board: {
                type: 'integer',
                description: 'also return the top N candidates with op=status (default 0 = do not return)',
            },
            limit: { type: 'integer', description: 'number of candidate rows for op=board, default 10' },
            groups: { type: 'boolean', description: 'whether op=board includes grouped candidates (default true)' },
            path: {
                type: 'string',
                description: 'path to write the script to with op=export (a host-visible path, e.g. /tmp/xxx.py or D:\\out\\xxx.py); omit = return text only',
            },
            top: { type: 'integer', description: 'number of variants for op=export (together with include_variants)' },
            include_variants: { type: 'boolean', description: 'whether op=export also exports the candidate table together' },
            note: { type: 'string', description: 'note for op=export (written into the script header)' },
            iterations: { type: 'integer', description: 'number of iterations for op=bench' },
        },
        output: { schema: ANY_SCHEMA, render: renderOne },
        isConcurrencySafe: () => false,
        timeoutMs: T.loop,
        async execute(args) {
            return executeLoop(port, args);
        },
    })), 'dsh-blender-plugin: rt-loop');
}
//# sourceMappingURL=register.js.map