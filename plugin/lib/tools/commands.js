import { vTool } from '../contracts/tool.js';
import { ANY_SCHEMA } from './schema-diagnostic.js';
import { T, BACKEND_HINT } from '../constants.js';
import { ensureBackend } from '../host/backend/index.js';
import { backendJson } from '../host/http.js';
import { renderOne } from '../ui/cards.js';
import { toolError } from './errors.js';
import { asArray, asRecord, text } from '../contracts/dynamic.js';
export function registerCommands(ctx, port) {
    ctx.effect(() => ctx.tools.register(vTool({
        name: 'blender_rt_commands',
        description: 'Lists the addon commands currently available on the direct channel (19 resident + 15 integration-gated) and the real state of the 5 integrations (whether the switch is on, whether an API key is missing). Use it before blender_rt_cmd.',
        parameters: {},
        output: { schema: ANY_SCHEMA, render: renderOne },
        isConcurrencySafe: () => true,
        timeoutMs: T.commands,
        async execute() {
            if (!(await ensureBackend(port)))
                return toolError('backend_unreachable', 'backend unavailable (127.0.0.1:' + String(port) + ')', BACKEND_HINT);
            // (PR review): the client budget must be < the host's static deadline timeoutMs:T.commands(60s),
            // otherwise the host aborts first when the addon is slow and the model never gets the /commands scene/integration receipt.
            // Worst case on the backend side ≈15 + 5×(3+2.5s diagnostics)≈42.5s < this 45s budget, so the whole receipt comes back within the client budget.
            const r = await backendJson(port, '/commands', 45000);
            if (!r || r.ok !== true) {
                const errText = text(r.error || r.raw || 'unknown');
                // A socket-level failure means the addon bridge is not connected: the status probe itself blocks ~20s before pointing at start,
                // which becomes a dead loop. So give bounded Connect / doctor guidance instead.
                if (/socket closed|ECONNRESET|EPIPE|ECONNREFUSED|connect timeout/i.test(errText))
                    return toolError('addon_unreachable', 'COMMANDS failed · ' + errText, 'Switch back to Blender first and click Connect in the N panel (the addon listens on 127.0.0.1:9876); then run blender_viewport op=doctor for a bounded health check and retry this command once it passes');
                return toolError('backend_error', 'COMMANDS failed · ' + errText, 'Run blender_viewport op=doctor first for a bounded health check (process / port / addon bridge), fix it as advised and retry this command');
            }
            const disabled = asArray(r.disabled);
            const integrations = asRecord(r.integrations);
            const available = asArray(r.available);
            const lines = [];
            lines.push('scene ' + text(r.scene) + (r.file ? ' · file ' + text(r.file) : ' · unsaved file'));
            lines.push('available commands ' +
                text(r.total) +
                '; blocked by integration switches ' +
                String(disabled.length));
            lines.push('integrations: ' +
                Object.keys(integrations)
                    .map((k) => {
                    const it = asRecord(integrations[k]);
                    return k + '=' + (it.enabled ? 'on' : 'off');
                })
                    .join(' · '));
            for (const k of Object.keys(integrations)) {
                const it = asRecord(integrations[k]);
                if (!it.enabled && it.message)
                    lines.push('  [' + k + '] ' + text(it.message));
            }
            if (disabled.length)
                lines.push('blocked: ' + disabled.map(text).join(', '));
            lines.push('available: ' + available.map(text).join(', '));
            return { text: lines.join(String.fromCharCode(10)) };
        },
    })), 'dsh-blender-plugin: rt-commands');
}
//# sourceMappingURL=commands.js.map