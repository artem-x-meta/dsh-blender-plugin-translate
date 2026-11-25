/** blender_rt_do tool declaration and registration (schema/parameter descriptions are the model contract, kept verbatim). */
import { vTool } from '../../contracts/tool.js';
import { ANY_SCHEMA, HINT_KERNEL } from '../schema-diagnostic.js';
import { T } from '../../constants.js';
import { renderOne } from '../../ui/cards.js';
import { executeDo } from './execute.js';
function buildDoTool(ctx, port) {
    return vTool({
        name: 'blender_rt_do',
        description: 'Drive Blender live: run Python in the persistent kernel K (or run a .py file directly), optionally returning one viewport frame immediately. Only fills the local edits op does not have; if a plan op exists, use the op first.' +
            'When the GUI is available it goes through the addon; when session is passed it uses exec+see in the persistent headless worker (falls back automatically if the GUI is unreachable, not an async job); about 50–150 ms per step.' +
            HINT_KERNEL +
            ' Exceptions also return partial stdout / stderr / traceback (diagnostics are not lost);' +
            ' the file argument can execute a workspace script directly (equivalent to K.run(path), supports WSL / Windows / .blend-relative paths);' +
            ' built-in path helpers K.win_path / K.wsl_path / K.blend_path / K.out_dir;' +
            ' ④ the returned ms is **main-thread occupancy**; >1 s hints to switch to blender_rt_headless / blender_rt_worker.' +
            ' **headless interaction**: when the GUI is offline or session is passed, it falls back automatically to a persistent headless session (exec + Workbench see, the same worker hot path; not a job/async).' +
            'The first call cold-starts the worker, then each step takes ~50–150ms; a fixed session name reuses the same Blender session.',
        parameters: {
            code: {
                type: 'string',
                description: 'Python code (runs on the Blender main thread; bpy/math/mathutils/Vector and the persistent kernel K are preloaded). Mutually exclusive with file',
            },
            file: {
                type: 'string',
                description: 'Path of the .py file to execute (WSL / Windows / relative to the current .blend all work) — use this for long scripts instead of stuffing them into the argument',
            },
            see: { type: 'boolean', description: 'Whether to also return one viewport frame (default true)' },
            max_size: { type: 'integer', description: 'Longest-side pixels of the returned frame, default 560' },
            force: {
                type: 'boolean',
                description: 'When the returned frame has exactly the same hash as the previous one, the image is **not re-attached** by default; pass true to force a resend',
            },
            session: { type: 'string', description: 'Headless interaction session name (reuses the same blender -b)' },
            auto: { type: 'boolean', description: 'Fall back to a headless session when the GUI is unavailable (default true)' },
            preload: { type: 'string', description: 'Modules to preload into the headless session (comma-separated)' },
            from: { type: 'string', description: 'Headless see camera position "x,y,z"' },
            look_at: { type: 'string', description: 'Headless see look-at point "x,y,z"' },
        },
        output: { schema: ANY_SCHEMA, render: renderOne },
        isConcurrencySafe: () => false,
        timeoutMs: T.act,
        async execute(args) {
            return executeDo(args, ctx, port);
        },
    });
}
export function registerDo(ctx, port) {
    ctx.effect(() => ctx.tools.register(buildDoTool(ctx, port)), 'dsh-blender-plugin: rt-do');
}
//# sourceMappingURL=register.js.map
