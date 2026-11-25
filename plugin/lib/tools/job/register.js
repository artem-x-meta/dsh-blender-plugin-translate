/** blender_rt_job tool declaration and registration (the schema / parameter descriptions are the model contract, kept verbatim). */
import { vTool } from '../../contracts/tool.js';
import { ANY_SCHEMA } from '../schema-diagnostic.js';
import { T } from '../../constants.js';
import { renderStructured } from '../../ui/cards.js';
import { executeJob } from './execute.js';
function buildJobTool(port) {
    return vTool({
        name: 'blender_rt_job',
        description: '[Job layer] long work goes to the background: op=start returns a jobId immediately (it holds no client connection and is not cut off by the tool timeout); status / collect / **wait** / kill / list.' +
            '**wait gets the structured result in one call (default 120 s per call, cap 600 s) — stop firing status repeatedly** (it trips the host\'s duplicate-call detection).' +
            'Division of labour with headless: with an expected <100 s, use headless and take the result directly; longer, or known to be long → as_job=true on headless, or op=start on this tool.' +
            'run and job share **one id space**: a headless runId (run-…) can also be collected with status/collect/wait/kill; logs land in <outdir>/jobs/<id>/.' +
            'Parameter details: blender_rt_plan(op="catalog", args={tool:"rt_job"}).',
        parameters: {
            op: {
                type: 'string',
                required: true,
                description: 'start | status | collect | wait | kill | list',
            },
            id: {
                type: 'string',
                description: 'id for status/collect/wait/kill (job-… or the headless run-…)',
            },
            script: {
                type: 'string',
                description: 'Python source (same prelude and result contract as headless)',
            },
            script_file: { type: 'string', description: 'Run a .py file directly (Windows/WSL paths both accepted)' },
            args: {
                type: 'string',
                description: 'Command-line arguments (space-separated or an array); the script reads sys.argv / K.args',
            },
            env: { type: 'json', description: 'Extra environment variables {KEY:"VALUE"}' },
            file: {
                type: 'string',
                description: '.blend file to open (the receipt carries inputFile{size,mtime,md5})',
            },
            outdir: {
                type: 'string',
                description: 'Output directory (WSL paths accepted too); logs go under its jobs/<id>/',
            },
            timeout_ms: {
                type: 'integer',
                description: 'Job limit, default 3600000, cap 24 h; for wait it is this wait\'s limit (default 120000, cap 600000)',
            },
            engine: { type: 'string', description: 'eevee (default) / cycles / keep' },
            preload: { type: 'string', description: 'Preload runtime modules (comma-separated) → K.dsh_*_api' },
            factory_startup: { type: 'boolean', description: 'default true = --factory-startup' },
            bootstrap: { type: 'boolean', description: 'default true = inject the persistent kernel K' },
            workdir: { type: 'string', description: 'chdir inside the script + first entry on sys.path' },
            include_noise: {
                type: 'boolean',
                description: 'Whether the product listing includes noise files (default false, filtered out)',
            },
            out_json: { type: 'string', description: 'Path to write the structured result (over 4KB is auto-written under results/)' },
            tail: {
                type: 'integer',
                description: 'Trailing stdout/stderr characters for collect/wait (default 4000)',
            },
        },
        output: { schema: ANY_SCHEMA, render: renderStructured },
        isConcurrencySafe: () => true,
        timeoutMs: T.job,
        async execute(args) {
            return executeJob(args, port);
        },
    });
}
export function registerJob(ctx, port) {
    ctx.effect(() => ctx.tools.register(buildJobTool(port)), 'dsh-blender-plugin: rt-job');
}
//# sourceMappingURL=register.js.map