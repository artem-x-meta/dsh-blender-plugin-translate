import { vTool } from '../contracts/tool.js';
import { schemaResolve } from '../contracts/tool.js';
export const ANY_SCHEMA = { type: 'json' };
export const HINT_KERNEL = 'Persistent kernel: K.x = 1 set in this call is still readable in the next one; bpy / math / mathutils / Vector are preloaded.';
/**
 * v1.0.1 (issue #10): the **degraded exit** for when schemastery fails to resolve.
 * The point is not "it can still get work done" but **making the failure readable and locatable**: the placeholder tool still shows up in the tool list,
 * and calling it immediately reports the names that were tried, each channel's real error and the fix — instead of the old behaviour of
 * "throw during module import → all 15 tools vanish at once + the host only says failed to import".
 */
export function registerSchemaDiagnostic(ctx) {
    const text = [
        '⛔ dsh-blender-plugin loaded in **degraded mode**: schemastery could not be parsed, so none of the 15 blender_rt_* tools are registered (this is a **readable failure**, not the plugin disappearing).',
        'Reason: ' + String(schemaResolve.error || '(unknown)'),
        'Names tried and errors: ' + (schemaResolve.tried.length ? schemaResolve.tried.join(' / ') : '(empty)'),
        'Fix: make either @deepseek-ai/schemastery or schemastery resolvable by the host (two published forms of the same package); on a host that only provides the scoped name, upgrade to a version that includes this fix.',
        'Rule: resolution order = ESM `await import()` first → createRequire as fallback; the top level no longer throws.',
    ].join(String.fromCharCode(10));
    ctx.effect(() => ctx.tools.register(vTool({
        name: 'blender_viewport',
        description: 'Diagnostic only: this plugin loaded in degraded mode (schemastery unresolved), so its tools are not registered. Calling it only reports the reason and the fix.',
        parameters: { op: { type: 'string', description: 'Any value; only used to trigger the diagnostic output' } },
        output: {
            schema: { type: 'string' },
            render: (_a, v) => [{ type: 'text', text: String(v) }],
        },
        isConcurrencySafe: () => true,
        timeoutMs: 10000,
        async execute() {
            return text;
        },
    })), 'dsh-blender-plugin: degraded-schema');
}
//# sourceMappingURL=schema-diagnostic.js.map