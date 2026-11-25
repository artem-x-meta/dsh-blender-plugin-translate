/**
 * F-09 · file= option guard (shared by engine and tool side) —
 * "file= missing / empty string / misspelled option name" is no longer silently wrapped into a successful run
 * (old symptom: ok=true / exitCode=0 / inputFile=null / zero warnings / the script got a factory-empty scene).
 *
 * Pure-function module; three consumers share one verdict:
 *  - runtime/execution/headless.ts + runtime/execution/jobs.ts (fallback guard for direct /headless + receipt semantics)
 *  - src/index.ts (tool-side ALIAS / empty-string interception — the tool side strips falsy values to
 *    undefined before assembling the body, so the engine-side guard **never fires** on the tool path; hence ALIAS lives here)
 *  - tests/unit/js/headless-file-guard.test.ts (offline unit test, no Blender / backend needed)
 */
/** Common misspelled option names for file=. When the tool side sees these keys present (≠undefined) it must fail loudly,
 *  not silently treat it as "not passed" — silently dropping options is exactly the F-09 signature (blend=<good path> → empty scene, ok=true). */
export declare const FILE_ALIAS_KEYS: string[];
/** Returns the file= alias keys present in args (so error text can point out that the real name is "file"). */
export declare function detectFileAlias(args: unknown): string[];
/**
 * Engine-side guard: returns the normalized file= (non-empty string) or undefined (= not passed).
 *  - '' / whitespace only → throw code='file-empty': explicitly reject "passed but empty" instead of silently ignoring it
 *  - null / undefined → undefined (not-passed semantics; the receipt side adds describeMissingInput + no_input_file warning)
 *  - single-element string array → take the only element (keeps the existing String([p])===p convenience, no semantics change)
 *  - any other non-string → throw code='file-type' (objects/arrays used to stringify to "[object Object]" and hit ENOENT;
 *    now a readable error one step earlier; error-path invariant: ok=false)
 */
export declare function validateFileOpt(raw: unknown): string | undefined;
/**
 * Receipt semantics for "no file opened": no longer a bare null — given/opened/reason let the receipt distinguish
 * "no file given" from "a .py was given".
 * Shape frozen (issue compatibility clause): normal-path fileFingerprint return value is **byte-identical**;
 * only the former null branch becomes a semantic object. In-repo truthiness consumers
 * (`if (r.inputFile && r.inputFile.md5)` in src/index.ts) are guarded by .md5 presence and unaffected.
 */
export declare function describeMissingInput(fileOpt: unknown, fileLooksPython: boolean): {
    given: boolean;
    opened: boolean;
    reason: string;
};
/** "Succeeded but opened no file" may not stay silent: promote it to an explicit receipt-warnings entry (no need to dig scriptFile relay data). */
export declare function noInputFileWarning(fileLooksPython: boolean): {
    code: string;
    hint: string;
};
/**
 * De-duplicate stdout/stderr log names within the same millisecond (same root as staging-script name collisions, issue):
 * the old stamp was only millisecond-precise, so two runs in the same ms appended to one file via createWriteStream and mixed stdout.
 * runId is unique per run (client- or engine-generated), so once it is part of the name, same-ms runs no longer collide.
 */
export declare function headlessLogNames(stamp: string, runId: string | null | undefined): {
    stdout: string;
    stderr: string;
};
