declare function extractTag(out: unknown, tag: string): unknown;
declare function extractLoop(out: unknown): unknown;
declare function jsonFromStdout(out: unknown): unknown;
/** Path mapping lives in config.mjs: winToWsl / wslToWin (returned as-is on Windows) */
/** Python scripts for headless runs land in a Windows-visible directory; when /mnt is not writable, fall back to tmp inside the package + UNC */
/** v0.8.10: long output as "head + tail + omission marker" - the old version returned only the tail and swallowed the head of long JSON */
declare function clipMiddle(s: unknown, head: number, tail: number): string;
/**
 * v0.9.6 (field feedback: the "double prefix" on WSL absolute paths): a path like `home/.../DSH/test/x.py` that **lost its leading slash**
 * gets appended to cwd as a relative path, yielding `...DSH\home\sixtyseven67\DSH\test\x.py`.
 * Test: if adding a leading "/" makes it actually exist -> correct it and record a note (also written to backend stderr for debugging).
 */
declare function slipFixPath(p: unknown, notes?: string[] | null): string;
export { extractTag, extractLoop, jsonFromStdout, clipMiddle, slipFixPath };
