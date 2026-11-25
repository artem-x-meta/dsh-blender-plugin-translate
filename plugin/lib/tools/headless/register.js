/** blender_rt_headless tool declaration and registration (schema/param descriptions are the model contract — keep them verbatim). */
import { vTool } from '../../contracts/tool.js';
import { ANY_SCHEMA } from '../schema-diagnostic.js';
import { IS_WIN, T } from '../../constants.js';
import { renderStructured } from '../../ui/cards.js';
import { executeHeadless } from './execute.js';
function buildHeadlessTool(ctx, port) {
    return vTool({
        name: 'blender_rt_headless',
        description: '[Headless Blender · fallback] Run a script in a separate process (blender -b): for when the GUI is unavailable / batch work / long jobs; takes no GUI and leaves the scene alone.' +
            (IS_WIN ? '⚠ supply a Windows path (D:\\x\\y.py); ' : '⚠ cwd is under UNC, so WSL paths need a leading /; ') +
            'script_file supplies __file__ + sys.path automatically. ' +
            'Batch geometry / validation / rendering / any job that does not need "a human in the loop watching the viewport" goes here first; to "take a look" use rt_do/rt_see. ' +
            'print("HEADLESS " + json.dumps(obj)) reports back (one-line JSON). ' +
            'Defaults to factory-startup + an EEVEE warm-up (override with engine="cycles"|"keep"|"none"). ' +
            '**>100 s or a long render: as_job=true** (collected via rt_job); when the wait window expires it returns a promoted jobId and the result can still be collected. ' +
            'attach_images returns images; shots renders multiple views; after preload you can call K.dsh_*_api directly. ' +
            'See catalog(tool:rt_headless) for parameter details.',
        parameters: {
            script: {
                type: 'string',
                description: 'Python source (K + bpy/math/mathutils/Vector are injected)',
            },
            script_file: {
                type: 'string',
                description: 'Run a .py file directly (Windows or WSL path); less hassle than script=',
            },
            file: {
                type: 'string',
                description: '.blend to open (the receipt carries inputFile{size,mtime,md5}); a .py is treated as a script automatically',
            },
            outdir: {
                type: 'string',
                description: 'Output directory (WSL paths accepted); new files are listed after the run and appended to the script sys.argv',
            },
            as_job: {
                type: 'boolean',
                description: 'true = background it as a job immediately (recommended for work expected to exceed 100 s)',
            },
            wait_s: { type: 'number', description: 'seconds to wait at most after as_job; on expiry it returns the jobId' },
            timeout_ms: {
                type: 'integer',
                description: 'Child-process ceiling, default 180000, max 1800000 (SIGKILL on expiry)',
            },
            engine: {
                type: 'string',
                description: 'eevee (default) | cycles | keep | none (saves 1–1.5 s)',
            },
            preload: {
                type: 'string',
                description: 'Preload runtime modules (comma-separated, e.g. "audit,qc,qc_render") → K.dsh_*_api',
            },
            shots: {
                type: 'json',
                description: 'Multi-view renders [{name,from,look_at,lens,res,samples}]',
            },
            out_json: {
                type: 'string',
                description: 'Path for structured results (anything over 4KB is also written to results/ automatically)',
            },
            env: { type: 'json', description: 'Child-process environment variables {KEY:"VALUE"}' },
            args: {
                type: 'string',
                description: 'Command-line arguments appended after -- (read sys.argv / K.args in the script)',
            },
            workdir: { type: 'string', description: 'chdir inside the script + first entry on sys.path' },
            factory_startup: {
                type: 'boolean',
                description: 'Default true; false = use the user startup file and preferences',
            },
            use_user_config: {
                type: 'boolean',
                description: 'Pass BLENDER_USER_CONFIG/SCRIPTS through to the headless process',
            },
            bootstrap: { type: 'boolean', description: 'Default true = inject the persistent kernel K' },
            gpu: { type: 'string', description: 'cycles only: auto | true (GPU required) | false' },
            include_noise: { type: 'boolean', description: 'Include __pycache__/*.blend1 in the output listing' },
            attach_images: { type: 'json', description: 'Attach shots images: true = 3 of them, "sheet" = contact sheet' },
            hard_exit: {
                type: 'boolean',
                description: 'os._exit(0) after done, skipping exit teardown; default true avoids the 5.2.3 exit AV, false = old behaviour (atexit/handlers run as usual)',
            },
        },
        output: { schema: ANY_SCHEMA, render: renderStructured },
        isConcurrencySafe: () => false,
        timeoutMs: T.headless,
        async execute(args) {
            return executeHeadless(args, ctx, port);
        },
    });
}
export function registerHeadless(ctx, port) {
    ctx.effect(() => ctx.tools.register(buildHeadlessTool(ctx, port)), 'dsh-blender-plugin: rt-headless');
}
//# sourceMappingURL=register.js.map