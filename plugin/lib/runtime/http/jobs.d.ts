/**
 * §8.3 `<trimmed job>`: keep only the fields the contract names and **cut the large ones** (`script`, very long path strings, etc.).
 * `resultJson` over 8 KB is truncated with `resultTruncated:true` (one poll must not blow up the panel).
 * **Pure function, zero I/O** - this is what lets `/host/jobs` achieve "zero Blender round trips".
 */
declare function trimJob(j: unknown): Record<string, unknown>;
/** §8.3 clamp rules: missing/not a number -> default; a number -> clamped into [lo,hi] (**no error**, following the existing §1.x convention) */
declare function clampIntParam(v: unknown, dflt: number, lo: number, hi: number): number;
export { trimJob, clampIntParam };
