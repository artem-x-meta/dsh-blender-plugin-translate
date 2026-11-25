/**
 * v0.9.3 (external feedback 2026-09-24): base environment for child processes — all three spawn sites go through it.
 *
 * The old version only injected PYTHONIOENCODING. Blender's Python stdout is **block-buffered** when redirected (piped),
 * so job's stdout.log / stderr.log stayed **at 0 bytes the whole time** while a task ran, and only hit disk when the process exited
 * (Lead measured it: both logs stayed at 0 bytes through a 20-minute render; engine: "during those 399 s there was no stage information at all, 6 minutes of pure black box").
 * PYTHONUNBUFFERED=1 makes print write out immediately → stage heartbeats and incremental logs become meaningful.
 */
declare function baseChildEnv(extra?: Record<string, string | null | undefined>): Record<string, string | undefined>;
/** WSLENV declarations (a pitfall measured in v0.9.1: when the WSL side spawns a Windows process, env does not cross the boundary automatically) — shared by headless and job
 *  On macOS / Windows the parent and child processes share an OS, so env is inherited naturally and this step is not needed. */
declare function withWslEnv(childEnv: Record<string, string | undefined>, extraEnv?: Record<string, unknown>): Record<string, string | undefined>;
/** Turns "workDir is not shared, so the script lands elsewhere" into a pathWarning **appended at the end** (same shape as pathAudit: carries a hint).
 *  Why append instead of inserting at the front: existing pathAudit assertions (e.g. acceptance_v093) look at pathWarnings[0]; do not take its place. */
declare function workdirStagingWarning(staging?: StagingSummary | null): PathWarning | null;
interface StagingSummary {
    substituted?: boolean;
    requestedWhy?: string;
    note?: string;
    requested?: string;
}
export interface PathWarning {
    code: string;
    value: string;
    evidence: string;
    hint: string;
    [k: string]: unknown;
}
/** Read JSON; a broken file returns null (shared by engine and launch) */
declare function readJsonSafe(p: string): unknown;
export { baseChildEnv, withWslEnv, readJsonSafe, workdirStagingWarning };
