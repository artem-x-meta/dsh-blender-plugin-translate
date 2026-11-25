/**
 * v0.9.4 (return channel): **uniform sanitization of tool return values** so they pass the host's lossless-JSON gate.
 *
 * Background (external feedback 2026-09-25 "M1A1 part modeling"): the host validates every tool's return value with
 * dsh-util-values' walkJsonValue, whose rules are **much stricter than JSON.stringify**; any of the following is judged
 * tool returned invalid output: value is not lossless JSON and kills the whole tool channel:
 *   - own enumerable key whose value is undefined (stringify drops the key → invisible to the eye)
 *   - NaN / ±Infinity (stringify yields null) · -0 (stringify yields 0, the sign is lost)
 *   - Date / Map / Set / class instances / functions / Symbol / circular references / objects with symbol or non-enumerable keys
 * Measured consequence: one promoted: undefined in the v0.9.3 envelope made
 * blender_rt_headless **fail every time** (the task actually finished and the result was on disk, only the receipt was rejected),
 * and rt_job's status/collect/wait had the same disease — i.e. "the task can be handed out but not collected back".
 *
 * Sanitization policy (**not silent**: every change is recorded in fixes and named in the receipt text):
 *   undefined → drop the key (array element → null, length does not collapse) · non-finite number → null · -0 → 0
 *   bigint → number (string if beyond the safe integer range) · Date → ISO string · Map/Set → array
 *   class instance → its own enumerable properties · binary view → {bytes:N} · circular → '[Circular]'
 */
import { isRecord } from './dynamic.js';
export function losslessSanitize(root) {
    const fixes = [];
    const seen = new Set();
    const walk = (v, at) => {
        if (v === null)
            return null;
        if (typeof v === 'string' || typeof v === 'boolean')
            return v;
        if (typeof v === 'number') {
            if (!Number.isFinite(v)) {
                fixes.push(at + '=' + String(v) + '→null');
                return null;
            }
            if (Object.is(v, -0)) {
                fixes.push(at + '=-0→0');
                return 0;
            }
            return v;
        }
        if (typeof v === 'undefined') {
            fixes.push(at + '=undefined→dropped');
            return undefined;
        }
        if (typeof v === 'bigint') {
            const n = Number(v);
            fixes.push(at + '=bigint→' + (Number.isSafeInteger(n) ? 'number' : 'string'));
            return Number.isSafeInteger(n) ? n : String(v);
        }
        if (typeof v === 'function' || typeof v === 'symbol') {
            fixes.push(at + '=' + typeof v + '→dropped');
            return undefined;
        }
        if (seen.has(v)) {
            fixes.push(at + '=circular reference→[Circular]');
            return '[Circular]';
        }
        seen.add(v);
        let out;
        if (Array.isArray(v)) {
            out = [];
            for (let i = 0; i < v.length; i++) {
                const w = walk(v[i], at + '[' + String(i) + ']');
                out.push(w === undefined ? null : w);
            }
        }
        else if (v instanceof Date) {
            const ms = v.getTime();
            fixes.push(at + '=Date→ISO');
            out = Number.isFinite(ms) ? v.toISOString() : null;
        }
        else if (v instanceof Map) {
            fixes.push(at + '=Map→array');
            out = Array.from(v.entries()).map((e, i) => walk(e, at + '<map' + String(i) + '>'));
        }
        else if (v instanceof Set) {
            fixes.push(at + '=Set→array');
            out = Array.from(v.values()).map((e, i) => walk(e, at + '<set' + String(i) + '>'));
        }
        else if (ArrayBuffer.isView(v) || v instanceof ArrayBuffer) {
            const n = v.byteLength;
            fixes.push(at + '=binary(' + String(n) + 'B)→{bytes} (to return it to the model go through attachments/saveImage)');
            out = { bytes: n, why: 'binary-not-json' };
        }
        else if (typeof v.toJSON === 'function' && !isPlainObjectLike(v)) {
            // The host does not define toJSON semantics, but it is at least more likely than a class instance to give a JSON shape; fall back to own keys on failure
            try {
                return walk(v.toJSON(), at + '<toJSON>');
            }
            catch {
                /* fall back to own enumerable keys */
            }
            out = {};
            for (const k of Object.keys(v)) {
                const w = walk(v[k], at + '.' + k);
                if (w !== undefined)
                    out[k] = w;
            }
        }
        else {
            out = {};
            for (const k of Object.keys(v)) {
                const w = walk(v[k], at + '.' + k);
                if (w !== undefined)
                    out[k] = w; // drop the key (the host rejects undefined values)
            }
        }
        seen.delete(v); // DAG sharing (non-circular) may appear repeatedly
        return out;
    };
    const value = walk(root, 'value');
    return { value: value === undefined ? null : value, fixes: fixes };
}
/** Plain object/array test (used to decide whether to take the toJSON branch) */
export function isPlainObjectLike(v) {
    if (Array.isArray(v))
        return true;
    if (!isRecord(v))
        return false;
    const proto = Object.getPrototypeOf(v);
    return proto === Object.prototype || proto === null;
}
//# sourceMappingURL=lossless.js.map
