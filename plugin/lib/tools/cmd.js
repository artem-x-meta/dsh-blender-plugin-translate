import { vTool } from '../contracts/tool.js';
import { ANY_SCHEMA } from './schema-diagnostic.js';
import { T, BACKEND_HINT } from '../constants.js';
import { ensureBackend } from '../host/backend/index.js';
import { backendPost, leasedText } from '../host/http.js';
import { renderOne } from '../ui/cards.js';
import { toolError } from './errors.js';
import { text } from '../contracts/dynamic.js';
export function registerCmd(ctx, port) {
    ctx.effect(() => ctx.tools.register(vTool({
        name: 'blender_rt_cmd',
        description: 'Call any Blender addon command directly (38 names: 22 resident + 16 integration-gated), including get_world_state_snapshot / drain_human_activity / get_telemetry_consent / set_telemetry_consent / get_addon_info, plus asset commands (PolyHaven / Sketchfab / Poly Pizza / Hyper3D / Hunyuan3D). Only available while the GUI addon is online; for pure headless use rt_worker / rt_headless. Parameters must match the real addon signature: get_scene_info takes no arguments, get_object_info uses name (not object_name). Run blender_rt_commands first to see the list and availability.',
        parameters: {
            name: {
                type: 'string',
                required: true,
                description: 'addon command name, e.g. get_world_state_snapshot, search_polyhaven_assets',
            },
            params: { type: 'json', description: 'parameter object (optional), e.g. {"asset_type":"hdris"}' },
            timeout_ms: {
                type: 'integer',
                description: 'timeout in milliseconds, default 120000 (raise it for downloads/generation)',
            },
        },
        output: { schema: ANY_SCHEMA, render: renderOne },
        isConcurrencySafe: () => false,
        timeoutMs: T.cmd,
        async execute(args) {
            if (!(await ensureBackend(port)))
                return toolError('backend_unreachable', 'backend unavailable (127.0.0.1:' + String(port) + ')', BACKEND_HINT);
            const name = text(args.name);
            if (!name)
                return toolError('invalid_params', 'blender_rt_cmd requires the name parameter', 'pass name=<addon command>; blender_rt_commands lists the 38 commands');
            const r = await backendPost(port, '/cmd', {
                name: name,
                params: args.params || {},
                timeoutMs: Number(args.timeout_ms || 120000),
            }, 300000);
            const lt = leasedText(r);
            if (lt)
                return { text: lt };
            if (!r || r.ok !== true)
                return toolError('backend_error', 'CMD ' + name + ' failed · ' + text(r.error || r.raw || 'unknown'), 'check the command name and parameters with blender_rt_commands');
            const payload = JSON.stringify(r.result);
            const head = 'CMD ' + name + ' ok · ' + text(r.ms) + 'ms · ' + String(payload.length) + ' chars';
            const newline = String.fromCharCode(10);
            return {
                text: head +
                    newline +
                    (payload.length > 3000 ? payload.slice(0, 3000) + newline + '…(truncated)' : payload),
            };
        },
    })), 'dsh-blender-plugin: rt-cmd');
}
//# sourceMappingURL=cmd.js.map