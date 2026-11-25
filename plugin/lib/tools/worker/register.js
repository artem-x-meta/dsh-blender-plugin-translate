/** blender_rt_worker tool declaration and registration (the schema/parameter descriptions are the model contract, keep them verbatim). */
import { vTool } from '../../contracts/tool.js';
import { ANY_SCHEMA } from '../schema-diagnostic.js';
import { T } from '../../constants.js';
import { renderOne } from '../../ui/cards.js';
import { executeWorker } from './execute.js';
function buildWorkerTool(ctx, port) {
    return vTool({
        name: 'blender_rt_worker',
        description: '[Interactive headless hot session] A resident blender -b process: start launches it / exec runs code / see renders one offscreen frame (Workbench) / watch samples frame by frame / reset clears the scene / status / stop / restart / list.' +
            'start can take preload (inject modules such as imgtools/assembly/blockout/visualreport/shapesolve into K) and warmup; with no GUI, see is the AI\'s viewport, 50–100 ms per step.' +
            'The scene and K of one session persist across calls; the idle TTL defaults to 15 min (tunable via DSH_WORKER_TTL_MS).' +
            'Serial, windowless: bpy.ops calls that need the GUI may fail; for parameter details see blender_rt_plan(op="catalog", args={tool:"rt_worker"}).',
        parameters: {
            op: {
                type: 'string',
                required: true,
                description: 'start | exec | see | reset | status | stop | restart | list',
            },
            name: {
                type: 'string',
                description: 'instance name (default default); start several hot sessions for small batch work — when one gets dirty, use restart to swap in a new session',
            },
            code: {
                type: 'string',
                description: 'Python source for op=exec (K/bpy/math/mathutils/Vector are preloaded)',
            },
            timeout_ms: {
                type: 'integer',
                description: 'response timeout for op=exec, default 120000; raise it for long code',
            },
            preload: {
                type: 'string',
                description: 'modules to preload on op=start (comma-separated, e.g. "audit,qc,runner"); a preload failure makes start fail outright',
            },
            warmup: { type: 'boolean', description: 'op=start warms up the renderer (default true)' },
            from: { type: 'string', description: 'op=see camera position "x,y,z"' },
            look_at: { type: 'string', description: 'op=see look-at point "x,y,z"' },
            lens: { type: 'number', description: 'op=see focal length in mm' },
            ortho: { type: 'boolean', description: 'op=see orthographic projection' },
            view_size: { type: 'string', description: 'op=see resolution "WxH"' },
            gpu: {
                type: 'string',
                description: 'GPU semantics for op=start (cycles only): auto / true / false',
            },
            engine: {
                type: 'string',
                description: 'render engine for op=start: eevee (default) / cycles / workbench / keep',
            },
            purge_prefix: {
                type: 'string',
                description: 'module prefixes cleared before op=exec (comma-separated) — after changing a user module you must clear them or import hits the old code',
            },
        },
        output: { schema: ANY_SCHEMA, render: renderOne },
        isConcurrencySafe: () => false,
        timeoutMs: T.worker,
        async execute(args) {
            return executeWorker(args, ctx, port);
        },
    });
}
export function registerWorker(ctx, port) {
    ctx.effect(() => ctx.tools.register(buildWorkerTool(ctx, port)), 'dsh-blender-plugin: rt-worker');
}
//# sourceMappingURL=register.js.map