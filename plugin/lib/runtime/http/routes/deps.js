/** Boundary parsing for JSON objects: anything non-object becomes an empty object (equivalent to the old JS `payload.x` reads). */
export function objArg(v) {
    return v !== null && typeof v === 'object' ? v : {};
}
//# sourceMappingURL=deps.js.map