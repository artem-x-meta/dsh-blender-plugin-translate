/**
 * F-09 · file= parameter guard (shared by the engine and the tool side) —
 * "file= missing / empty string / misspelled parameter name" is no longer silently wrapped into a successful run
 * (old symptom: ok=true / exitCode=0 / inputFile=null / zero warnings / the script got a factory-empty scene).
 *
 * Pure-function module; three consumers share one judgement:
 *  - runtime/execution/headless.ts + runtime/execution/jobs.ts (fallback guard for a direct /headless call + receipt semantics)
 *  - src/index.ts (tool-side ALIAS / empty-string interception — the tool side strips falsy values to
 *    undefined before the body is assembled, so the engine-side guard **never fires** for the tool path; ALIAS therefore has to live on this side)
 *  - tests/unit/js/headless-file-guard.test.ts (offline unit test, needs neither Blender nor the backend)
 */
import fs from 'node:fs';
/** The common misspelled parameter names for file=. The tool side must error explicitly when these keys are present (≠undefined),
 *  instead of silently treating them as "not passed" — silently dropping a parameter is one of the F-09 signatures (blend=<good path> → empty scene ok=true). */
export const FILE_ALIAS_KEYS = ['blend', 'blendFile', 'path', 'filepath', 'blend_file', 'input'];
/** Returns the file= alias keys present in args (so the error text can point out that the proper name is file). */
export function detectFileAlias(args) {
    if (!args || typeof args !== 'object')
        return [];
    const rec = args;
    return FILE_ALIAS_KEYS.filter((k) => rec[k] !== undefined && rec[k] !== null);
}
/**
 * Engine-side guard: returns a normalized file= (non-empty string) or undefined (= not passed).
 *  - '' / whitespace only → throw code='file-empty': explicitly reject "passed but empty" rather than silently treating it as absent
 *  - null / undefined → undefined (not-passed semantics; the receipt side adds words via describeMissingInput + the no_input_file warning)
 *  - single-element string array → take the only element (keeps the existing String([p])===p convenience behaviour, no semantic change under the guise of a fix)
 *  - any other non-string → throw code='file-type' (the old behaviour for objects/arrays joined them into "[object Object]" and hit ENOENT,
 *    now a readable error is given one step earlier; the error-path invariant holds: ok=false)
 */
export function validateFileOpt(raw) {
    if (raw === undefined || raw === null)
        return undefined;
    let v = raw;
    if (Array.isArray(v) && v.length === 1 && typeof v[0] === 'string')
        v = v[0];
    if (typeof v !== 'string') {
        throw Object.assign(new Error('file= must be a string path, got ' + (Array.isArray(v) ? 'array' : typeof v)), {
            code: 'file-type',
            hint: 'e.g. file="D:\\x\\y.blend"; to run a .py script use script_file= (file= is .blend)',
        });
    }
    if (!v.trim()) {
        throw Object.assign(new Error('file= was passed an empty string — this call will not open any .blend (the script gets a factory-empty scene)'), {
            code: 'file-empty',
            hint: 'Either give a real .blend path or do not pass file= at all; if you meant a .blend but passed a .py, ' +
                'it will run inline as a script and no file will be opened (see fileLooksPython).',
        });
    }
    try {
        if (fs.lstatSync(v).isSymbolicLink()) {
            throw Object.assign(new Error('file= points at a symbolic link, refusing to follow it: ' + v), {
                code: 'file-symlink',
                hint: 'Pass the real .blend path; a symbolic link can bypass the workspace boundary.',
            });
        }
    }
    catch (e) {
        const code = e && typeof e === 'object' && 'code' in e ? String(e.code) : '';
        if (code === 'file-symlink')
            throw e;
        if (code && !['ENOENT', 'ENOTDIR', 'EACCES', 'EPERM', 'EINVAL'].includes(code))
            throw e;
    }
    return v;
}
/**
 * Receipt semantics for "nothing opened": no bare null any more — given/opened/reason make
 * "no file given" and "a .py was given" distinguishable in the receipt.
 * Shape frozen (issue compatibility clause): on the normal path the fileFingerprint return value is **untouched, character for character**;
 * only the old null branch is replaced with an object carrying meaning. The in-repo truthiness consumers (src/index.ts's
 * `if (r.inputFile && r.inputFile.md5)`) are gated by the existence of .md5 and are unaffected.
 */
export function describeMissingInput(fileOpt, fileLooksPython) {
    if (fileLooksPython) {
        return {
            given: true,
            opened: false,
            reason: 'file= is a .py — executed inline as a script, no .blend was opened',
        };
    }
    if (fileOpt !== undefined && fileOpt !== null && !String(fileOpt).trim()) {
        return { given: true, opened: false, reason: 'file= is empty — no .blend was opened' };
    }
    return { given: false, opened: false, reason: 'file= was not passed, so Blender starts with a factory-empty scene' };
}
/** "Succeeded but opened nothing" must no longer be silent: it is promoted to an explicit entry in the receipt warnings (no need to dig through the scriptFile relay data to find out). */
export function noInputFileWarning(fileLooksPython) {
    return {
        code: 'no_input_file',
        hint: 'This run opened no .blend (' +
            (fileLooksPython ? 'file= is a .py, run as a script' : 'file= not passed') +
            '). If you thought a file was opened, check whether the parameter name is file (not blend/path).',
    };
}
/**
 * stdout/stderr log file names de-collide within the same millisecond (same root as the staging script collision, issue):
 * the old names were precise only to the millisecond, so two runs in the same millisecond had createWriteStream append to the same file and their stdout polluted each other.
 * runId is unique per run (client-generated or engine-generated); appended to the name, so the same millisecond no longer collides.
 */
export function headlessLogNames(stamp, runId) {
    const tag = runId ? '_' + String(runId).replace(/[^A-Za-z0-9_-]/g, '_') : '';
    return {
        stdout: 'dsh_headless_' + stamp + tag + '.stdout.log',
        stderr: 'dsh_headless_' + stamp + tag + '.stderr.log',
    };
}
//# sourceMappingURL=file_guard.js.map