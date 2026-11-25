export declare const RECOVER_VERSION = "2.6.1";
export interface MapPair {
    winToWsl: (p: string) => string;
    wslToWin: (p: string) => string;
}
export interface LogEvidence {
    path: string | null;
    exists: boolean;
    bytes: number;
    mtime: number | null;
    lastStage: string | null;
    sawDone: boolean;
    sawScriptEnd: boolean;
    sawHeadless: boolean;
    sawTraceback: boolean;
    lastProgress: Record<string, unknown> | null;
    tail: string | null;
    error?: string;
}
/**
 * Read the log tail and extract "terminal-state evidence". Only the tail is read, so a large log cannot stall the process.
 * Returns { exists, bytes, mtime, lastStage, sawDone, sawScriptEnd, sawHeadless, sawTraceback,
 *        lastProgress, path, tail, error? }
 */
export declare function logEvidence(pathWsl: string, maxBytes?: number): LogEvidence;
export interface RecoverOut {
    found: boolean;
    source: string | null;
    status: string | null;
    exitCode: unknown;
    finishedAt: number | null;
    artifacts: unknown[];
    evidence: Record<string, unknown> | null;
    stdoutLog: string | null;
    stderrLog: string | null;
    lastProgress: Record<string, unknown> | null;
}
/**
 * Find on disk the evidence that "this run/job has already finished".
 * rec may contain: dir / jobDir / outdir / resultPath / stdoutLog / stdoutLogWsl / logs
 * map = {winToWsl, wslToWin}
 */
export declare function recoverFromDisk(rec: Record<string, unknown> | null | undefined, map?: MapPair): RecoverOut;
/**
 * Converge a disk ledger record with status=running into a terminal state.
 *  - pid is still alive -> return as-is (no hijack)
 *  - pid is gone but the disk holds terminal-state evidence -> status=done/failed + recovered:true
 *  - otherwise -> status=stale (old semantics kept), but with evidence attached so the caller has one less case to investigate
 */
export declare function reconcileLedger(rec: Record<string, unknown> | null, map?: MapPair, isAlive?: (pid: unknown) => boolean): Record<string, unknown> | null;
/**
 * v0.9.3: run (synchronous execution of blender_rt_headless) and job share the same structured receipt shape --
 * collect/status accept run-… and job-… with the same field set, so callers never have to tell the two apart.
 */
declare function runSnapshot(r: Record<string, unknown>): Record<string, unknown>;
/**
 * Disk ledger record (history after a backend restart): convergence when it says running but the pid no longer exists.
 *
 * v2.6 (feedback #1 of this round): the old version always judged stale -- but twice it was observed that "the child process had in fact finished and both artifacts and logs were there",
 * so the caller had to run Get-Process + ls and investigate, costing at least one extra round-trip every time. Now disk reconciliation runs first:
 *   summary.json / resultPath / stdout terminal state (DSH_STAGE done, HEADLESS, Traceback)
 * match => status=done|failed + recovered=true (evidence in recoveredFrom/recoveredEvidence);
 * only when they do not match is it judged stale, and evidence (log size/lastStage) is attached.
 * The pure logic lives in recoverFromDisk/reconcileLedger in the same file and can be unit tested without Blender
 * (tests/unit/js/ledger-recover.test.ts).
 */
declare function reconcileLedgerRecord(rec: Record<string, unknown> | null): Record<string, unknown> | null;
export declare function createLedgerRecover(): {
    runSnapshot: typeof runSnapshot;
    reconcileLedger: typeof reconcileLedgerRecord;
};
export {};
