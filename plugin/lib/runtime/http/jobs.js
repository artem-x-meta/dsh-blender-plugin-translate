// Job-area helper: receipt trimming and limit clamp for /host/jobs. Pure functions, zero I/O.
// ---------------------------------------------------------------- v2.1 (§8.3) job-area helper
/**
 * §8.3 `<trimmed job>`: keep only the fields the contract names, **trim the big ones** (`script`, over-long path strings, etc.).
 * `resultJson` > 8 KB is truncated and `resultTruncated:true` is set (so one poll does not blow up the panel).
 * **Pure functions, zero I/O** —— this is the precondition that lets `/host/jobs` do "zero Blender round-trips".
 */
function trimJob(j) {
    const src = (j && typeof j === 'object' ? j : {});
    let resultJson = src.resultJson === undefined ? null : src.resultJson;
    let resultTruncated = false;
    if (resultJson !== null) {
        try {
            const s = JSON.stringify(resultJson);
            if (s !== undefined && s.length > 8192) {
                resultJson = { truncated: true, preview: s.slice(0, 8192) };
                resultTruncated = true;
            }
        }
        catch (e) {
            resultJson = null;
            resultTruncated = true;
        }
    }
    return {
        id: String(src.id === undefined ? '' : src.id),
        kind: src.kind === undefined ? null : src.kind,
        status: src.status === undefined ? 'unknown' : src.status,
        runId: src.runId === undefined ? null : src.runId,
        pid: src.pid === undefined ? null : src.pid,
        pidAlive: !!src.pidAlive,
        ms: Number(src.ms) || 0,
        timeoutMs: src.timeoutMs === undefined ? null : src.timeoutMs,
        outdir: src.outdir === undefined ? null : src.outdir,
        logDir: src.logDir === undefined ? null : src.logDir,
        exitCode: src.exitCode === undefined ? null : src.exitCode,
        signal: src.signal === undefined ? null : src.signal,
        stage: src.stage === undefined ? null : src.stage,
        stageName: src.stageName === undefined ? null : src.stageName,
        stageAgoMs: src.stageAgoMs === undefined ? null : src.stageAgoMs,
        lastOutputAt: src.lastOutputAt === undefined ? null : src.lastOutputAt,
        idleMs: src.idleMs === undefined ? null : src.idleMs,
        lines: Number(src.lines) || 0,
        logBytes: Number(src.logBytes) || 0,
        resultJson: resultJson,
        resultTruncated: resultTruncated,
        fromLedger: !!src.fromLedger,
    };
}
/** §8.3 clamp convention: missing/non-numeric → default value; given a number → clamp into [lo,hi] (**no error**, per the existing §1.x convention) */
function clampIntParam(v, dflt, lo, hi) {
    if (v === null || v === undefined || v === '')
        return dflt;
    const n = Number(v);
    if (!Number.isFinite(n))
        return dflt;
    return Math.max(lo, Math.min(hi, Math.round(n)));
}
export { trimJob, clampIntParam };
//# sourceMappingURL=jobs.js.map