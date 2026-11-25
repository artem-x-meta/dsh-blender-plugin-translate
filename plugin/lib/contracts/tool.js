import { createRequire } from 'node:module';
import { defineTool } from '@deepseek-ai/dsh-tools';
import { PLUGIN_VERSION } from '../constants.js';
import { EXEC_CTX } from '../host/exec-context.js';
import { isRecord } from './dynamic.js';
import { losslessSanitize } from './lossless.js';
import { cardPresenters } from '../ui/cards.js';
/**
 * Wrap one tool definition with the plugin's shared behaviour.
 *
 * Tool definitions are authored as object literals (and share schemastery's
 * dynamically resolved schema), so the boundary is typed as a dynamic record
 * and the final options are narrowed once at the defineTool call. The wrapper
 * keeps the public contract of v2.x: card presenters, version prefix and the
 * lossless sanitize gate on every return value.
 */
export const vTool = (spec) => {
    const execute = spec.execute;
    if (typeof execute !== 'function')
        throw new TypeError('tool spec.execute must be a function');
    const presenters = cardPresenters(spec);
    const options = {
        ...spec,
        ...presenters,
        description: '[v' + PLUGIN_VERSION + '] ' + String(spec.description || ''),
        // v0.9.4 (return channel): every tool's **single exit** passes through losslessSanitize —
        // one badly written field (NaN / undefined / -0) must not make the whole tool channel unusable.
        execute: async (args, exec) => {
            const signal = isRecord(exec) && exec.signal instanceof AbortSignal ? exec.signal : undefined;
            const raw = await EXEC_CTX.run({ signal }, () => execute(args, exec));
            const { value, fixes } = losslessSanitize(raw);
            if (fixes.length) {
                const note = '⚠️ Receipt sanitized: ' +
                    String(fixes.length) +
                    ' non-lossless-JSON values (the host gate rejects undefined/NaN/Infinity/-0): ' +
                    fixes.slice(0, 6).join(' · ') +
                    (fixes.length > 6 ? ' …and more' : '');
                try {
                    if (isRecord(value) && typeof value.text === 'string') {
                        value.text += String.fromCharCode(10) + note;
                    }
                    else if (isRecord(value)) {
                        value.__losslessNote = note;
                    }
                    console.warn('[dsh-blender] ' + note);
                }
                catch {
                    /* a failure to notify does not affect the return value */
                }
            }
            return value;
        },
    };
    // The dynamic options record is validated by defineTool at runtime; the broad
    // generic instantiation is only needed to keep the public wrapper ergonomic.
    return defineTool(options);
};
/**
 * The schemastery package name has **two shapes across DSH versions — scoped and unscoped** (schemastery ↔
 * @deepseek-ai/schemastery; same for cordis), so a static import cannot be made conditional and resolution must happen at runtime.
 *
 * v1.0.1 (issue #10 fix) — both the resolution order and the failure semantics changed:
 *   ① **Order**: ESM await import() first, falling back to createRequire on failure.
 *      The old version only used createRequire: in a profile where the host only provides the scoped name that
 *      require failed to resolve under DSH module-resolution interception when several plugins coexist (3/3 reproduced
 *      in the field, see the bundle bisect table in issue #10), whereas the ESM loader is exactly the path the host
 *      itself takes — so try that first.
 *   ② **Failure semantics**: no top-level throw any more. The old version threw during module load ⇒ the host only
 *      reported "failed to import" (the real cause swallowed) and the entry's fiber stayed undefined ⇒ **all 15 tools
 *      disappeared and the backend never started**, with the symptom one layer away from the cause, making it very hard
 *      to track down. Now it is **degraded loading**: register a placeholder tool that only reports the reason
 *      (see the DEGRADED branch below), register no other tools, but keep the error readable and the plugin present.
 *   ③ **Diagnostics**: which channel was used and which names were tried go into __internals.schemaResolve and are
 *      visible in op=status / op=doctor (this kind of "silently vanishes as a whole" must leave a readable trace).
 */
const SM_NAMES = ['@deepseek-ai/schemastery', 'schemastery'];
export const schemaResolve = {
    tried: [],
};
/** Keep only the first line of the error + truncate: diagnostics must fit on one line, don't dump the whole stack into status output */
const smErrLine = (e) => String((isRecord(e) && (e.code || e.message)) || e)
    .split('\n')[0]
    .slice(0, 120);
/** Shape check: only a layer that exposes .object() counts as usable (otherwise it is unrecognized, no gambling) */
const smPick = (m) => {
    const candidate = isRecord(m) ? (m.default ?? m) : m;
    if ((isRecord(candidate) || typeof candidate === 'function') &&
        typeof candidate.object === 'function')
        return candidate;
    return undefined;
};
for (const id of SM_NAMES) {
    try {
        const m = await import(/* webpackIgnore: true */ id);
        const hit = smPick(m);
        if (hit) {
            schemaResolve.z = hit;
            schemaResolve.via = 'esm:' + id;
            break;
        }
        schemaResolve.tried.push(id + '(esm:no-object)');
    }
    catch (e) {
        schemaResolve.tried.push(id + '(esm:' + smErrLine(e) + ')');
    }
}
if (!schemaResolve.z) {
    try {
        const req = createRequire(import.meta.url);
        for (const id of SM_NAMES) {
            try {
                const m = req(id);
                const hit = smPick(m);
                if (hit) {
                    schemaResolve.z = hit;
                    schemaResolve.via = 'cjs:' + id;
                    break;
                }
                schemaResolve.tried.push(id + '(cjs:no-object)');
            }
            catch (e) {
                schemaResolve.tried.push(id + '(cjs:' + smErrLine(e) + ')');
            }
        }
    }
    catch (e) {
        schemaResolve.tried.push('createRequire(' + smErrLine(e) + ')');
    }
}
if (!schemaResolve.z) {
    schemaResolve.error =
        'schemastery resolution failed; tried: ' +
            schemaResolve.tried.join(' / ') +
            '. The host must provide schemastery — either the scoped @deepseek-ai/schemastery or the unscoped schemastery will do.';
    console.error('[dsh-blender] ' +
        schemaResolve.error +
        ' (degraded loading: only a diagnostic placeholder tool is registered, so "all 15 tools vanish and the real cause is swallowed" can no longer happen)');
}
export const z = schemaResolve.z;
//# sourceMappingURL=tool.js.map