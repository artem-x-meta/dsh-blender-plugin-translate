/**
 * F-14 · hard exit for headless processes (issue: access violation 0xC0000005 during teardown in the Blender 5.2.3 Steam build).
 *
 * Symptom: after a successful glTF export (`DSH_STAGE {"name":"done"}` printed, artifacts complete), during the **teardown stage**
 * Blender crashes in the exporter path due to a .blend material with a Value→Material Output.Thickness link — the crash happens
 * after every output has been flushed, so all results were actually obtained, yet exitCode≠0 marks it "failed".
 *
 * Countermeasure: after the done marker, explicitly flush stdout/stderr and then `os._exit(0)` — skipping Blender's own teardown.
 * On by default (opts.hardExit !== false); callers that depend on a normal teardown (bpy.app.handlers writing to disk,
 * deferred auto-save) pass hardExit=false explicitly to return to the old behaviour.
 *
 * Two assembly paths share this module (the Python lines match the final issue text word for word):
 *  - job path (engine.jobStart, parts.push array form) → hardExitJobParts(opts)
 *  - sync path (engine.headless, body += NL + string concatenation form) → hardExitSyncTail(opts, NL)
 * Pure functions; tests/unit/js/headless-hard-exit.test.ts asserts the order and the switch semantics offline.
 */
/** The hard-exit Python lines after done (the order is the contract: flush first, _exit second — the reverse loses output). */
export function hardExitJobParts(opts) {
    if (opts && opts.hardExit === false)
        return [];
    return [
        'import sys as _dsh_sys',
        '_dsh_sys.stdout.flush(); _dsh_sys.stderr.flush()',
        'import os as _dsh_os; _dsh_os._exit(0)',
    ];
}
/** String-concatenation form for the sync path: leading NL + three lines; returns an empty string when disabled (body untouched). */
export function hardExitSyncTail(opts, NL) {
    const parts = hardExitJobParts(opts);
    return parts.length ? NL + parts.join(NL) : '';
}
//# sourceMappingURL=hard_exit.js.map
