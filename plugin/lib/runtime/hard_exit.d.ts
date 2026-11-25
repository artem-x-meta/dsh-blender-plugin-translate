/**
 * F-14 · hard exit for headless processes (issue: Blender 5.2.3 Steam build AV 0xC0000005 during exit).
 *
 * Field case: after a successful glTF export (`DSH_STAGE {"name":"done"}` had been printed and the artifacts were complete), Blender hit the
 * exporter crash path during **exit teardown**, because the .blend loaded a material with a Value→Material Output.Thickness link — the crash happened after
 * all output had been flushed, so every result had in fact been obtained, yet exitCode≠0 marked the run as "failed".
 *
 * Countermeasure: after the done marker, explicitly flush stdout/stderr and then `os._exit(0)` — skipping Blender's own exit teardown.
 * Enabled by default (opts.hardExit !== false); callers that rely on normal teardown (bpy.app.handlers writing to disk,
 * delayed auto-save) pass hardExit=false explicitly to get the old behavior back.
 *
 * Two assembly paths share this module (the Python line matches the issue's final wording verbatim):
 *  - job path (engine.jobStart, parts.push array form) → hardExitJobParts(opts)
 *  - sync path (engine.headless, body += NL + string-concatenation form) → hardExitSyncTail(opts, NL)
 * Pure functions; tests/unit/js/headless-hard-exit.test.ts asserts the order and switch semantics offline.
 */
/** The hard-exit Python line after done (order is the contract: flush first, then _exit — the reverse loses output). */
export declare function hardExitJobParts(opts?: {
    hardExit?: boolean;
}): string[];
/** The sync path's string-concatenation form: leading NL + three lines; returns an empty string when disabled (body stays byte-for-byte unchanged). */
export declare function hardExitSyncTail(opts: {
    hardExit?: boolean;
} | undefined, NL: string): string;
