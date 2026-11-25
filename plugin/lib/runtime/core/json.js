/**
 * Boundary parsing — JSON / environment variables / subprocess output are all unknown in type terms.
 *
 * Rule: narrow unknown to a concrete type only at the boundary; business code must not swallow
 * boundary data with `as SomeType`, and must not use explicit any. When a new field is needed, add a
 * guard/reader here first, then declare the interface in the module.
 */
export function isRecord(v) {
    return typeof v === 'object' && v !== null && !Array.isArray(v);
}
export function isArray(v) {
    return Array.isArray(v);
}
export function isString(v) {
    return typeof v === 'string';
}
export function isNumber(v) {
    return typeof v === 'number' && Number.isFinite(v);
}
export function isBoolean(v) {
    return typeof v === 'boolean';
}
/** Any value → string; null/undefined returns undefined (does not invent an empty string). */
export function readString(v) {
    if (v === undefined || v === null)
        return undefined;
    return typeof v === 'string' ? v : String(v);
}
/** Any value → finite number; returns fallback when it cannot be converted or is not positive (config-item semantics). */
export function readPositiveNumber(v, fallback) {
    const n = typeof v === 'number' ? v : Number(v);
    return Number.isFinite(n) && n > 0 ? n : fallback;
}
/** Any value → finite number; returns fallback when it cannot be converted. */
export function readNumber(v, fallback) {
    const n = typeof v === 'number' ? v : Number(v);
    return Number.isFinite(n) ? n : fallback;
}
/** Error object/string → readable message (equivalent to the old String((e && e.message) || e)). */
export function errorMessage(e) {
    if (isRecord(e)) {
        const msg = e.message;
        if (msg !== undefined && msg !== null && msg !== '')
            return String(msg);
    }
    return String(e);
}
/** Error object/string → error code (Node system errors carry code). */
export function errorCode(e) {
    return isRecord(e) && typeof e.code === 'string' ? e.code : undefined;
}
/** Custom extension fields on error objects (dynamic boundaries like the old e.diagnosis / e.hint / e.code). */
export function errorField(e, key) {
    return isRecord(e) ? e[key] : undefined;
}
/** Error object/string → detail (stack when present, otherwise the message; /router's 500 receipt semantics). */
export function errorDetail(e) {
    if (isRecord(e) && typeof e.stack === 'string' && e.stack)
        return e.stack;
    return errorMessage(e);
}
/** Any value → plain record (empty object when not an object, used for optional config fragments). */
export function readRecord(v) {
    return isRecord(v) ? v : {};
}
//# sourceMappingURL=json.js.map