import { enrichError } from '../../core/errors.js';
export function extractFailureContext(stderr, script) {
    let traceback = null;
    let lastException = null;
    let hint = null;
    const tbIdx = stderr.lastIndexOf('Traceback (most recent call last)');
    if (tbIdx >= 0)
        traceback = stderr.slice(tbIdx, tbIdx + 3000);
    const em = stderr.match(/^[\w.]*(?:Error|Exception|Warning)\b.*$/gm);
    if (em && em.length)
        lastException = enrichError(em[em.length - 1].slice(0, 300), traceback);
    if (lastException &&
        /line continuation character|invalid syntax/i.test(lastException) &&
        /\\n/.test(script)) {
        hint =
            'a literal \\n (two characters) appears in the script instead of a real newline — in JSON/TS write \\n, or build it with String.fromCharCode(10).';
    }
    return { traceback, lastException, hint };
}
export function classifyFailure(res, gpuFailed, lastException) {
    // ---- v0.9.1 (93-A4): failure semantics are graded — "client timeout" is not the same as "task failed", and must still be recoverable by runId
    return res.spawnErr
        ? 'blender_exe_missing'
        : res.timedOut
            ? 'timeout'
            : gpuFailed
                ? 'gpu_required_missing'
                : res.exitCode !== 0
                    ? 'blender_error'
                    : lastException
                        ? 'script_error'
                        : 'finished';
}
export function failureHint(failureClass) {
    const FAIL_HINT = {
        finished: null,
        script_error: 'the script raised an exception (the exit code may still be 0) — look at the line named by traceback/lastException; the structured result may not exist',
        blender_error: 'the Blender process exited with a non-zero code (crash / bad arguments) — check the tail of stderr and the log path',
        timeout: 'killed by SIGKILL on timeout: the script did not finish. Reduce the batch, or use asJob=true to move to the job layer (which does not hold the client connection)',
        gpu_required_missing: 'GPU required but the device is unavailable (with gpu="true"/engine="cycles") — see the gpu section of the receipt',
        blender_exe_missing: 'cannot start the Blender process: configure blenderExe / DSH_BLENDER_EXE first',
    };
    return FAIL_HINT[failureClass] || null;
}
//# sourceMappingURL=failure.js.map
