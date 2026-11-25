/** blender_viewport tool declaration and registration (schema/parameter descriptions are the model contract, kept verbatim in meaning). */
import { vTool } from '../../contracts/tool.js';
import { T } from '../../constants.js';
import { executeViewport } from './execute.js';
import { renderViewportOutput } from './presenter.js';
function buildViewportTool(port) {
    return vTool({
        name: 'blender_viewport',
        description: 'Real-time channel backend (127.0.0.1:' +
            String(port) +
            ') ops entry point: **status** (health / viewport area / counters / version), **doctor** (a real bpy round-trip in a three-tier check: not connected / main thread busy / addon thread stuck, plus how to fix it), ' +
            '**start / stop / restart** (backend process and the 15 s watchdog), **who / lease / release** (write lease; writing routes return 409 while someone else holds it, read-only ops are exempt), ' +
            '**launch** (one-click launch of GUI Blender with an automatic addon Connect: write the boot script → detached spawn → **poll the addon port** (the only trustworthy criterion) → then doctor; idempotent).' +
            'For parameter details see blender_rt_plan(op="catalog", args={tool:"viewport"}).',
        parameters: {
            op: {
                type: 'string',
                required: true,
                description: 'status | doctor | who | lease | release | start | stop | restart | launch',
            },
            holder: {
                type: 'string',
                description: 'holder name for lease/release (defaults to this plugin process\'s pid identity)',
            },
            ttl_ms: {
                type: 'integer',
                description: 'lease lifetime in milliseconds, default 600000; write operations renew it automatically',
            },
            force: {
                type: 'boolean',
                description: 'on lease, take over someone else\'s lease (default false; when it is taken it returns 409)',
            },
            scope: {
                type: 'string',
                description: '[lease]write scope (second dimension): collection:COL_Lights or prefix:LGT- , comma-separated; declarative, it shows up in the who/lease/409 receipt (the assembly layer uses K.route_collections() to actually route things)',
            },
            wait_ms: {
                type: 'integer',
                description: '[launch]upper bound for waiting until the addon port opens, default 90000',
            },
            file: {
                type: 'string',
                description: '[launch]the .blend to open at launch (WSL/Windows paths both accepted)',
            },
            exe: { type: 'string', description: '[launch]explicitly specify blender.exe (overrides config detection)' },
            addon_module: {
                type: 'string',
                description: '[launch]addon module names to enable (comma-separated); by default modules whose names contain mcp / blender_bridge / dshbb are scanned automatically (both old and new names are found)',
            },
            addon_file: {
                type: 'string',
                description: '[launch]absolute path of an addon .py to import by file (fallback for extension layouts)',
            },
            dry_run: {
                type: 'boolean',
                description: '[launch]true = only report the command that would be executed, do not actually launch',
            },
        },
        output: {
            schema: { type: 'string' },
            render: renderViewportOutput,
        },
        timeoutMs: T.viewport,
        async execute(args) {
            return executeViewport(args, port);
        },
    });
}
export function registerViewport(ctx, port) {
    ctx.effect(() => ctx.tools.register(buildViewportTool(port)), 'dsh-blender-plugin: tool');
}
//# sourceMappingURL=register.js.map
