export interface StageRecord {
    stage?: unknown;
    stageAt?: number | null;
    stageName?: string | null;
    progress?: unknown;
    progressAt?: number | null;
    progressHistory?: Array<{
        at: number;
        p: unknown;
    }>;
    lastOutputAt?: number | null;
    lines?: number;
    logs?: {
        stdoutWsl?: string;
    } | null;
    dir?: string;
    startedAt: number;
    heartbeat?: Record<string, unknown>;
}
declare const STAGE_TAG = "DSH_STAGE ";
/** v2.6 (feedback #4 of this round): progress channel -- the script side calls dsh_progress(...) / K.progress(...) which prints DSH_PROGRESS {json},
 *  so op=status/collect can read the latest entry directly (per-frame rendering / per-item batching / download percentage).
 *  Difference from stage: stage is a "stage transition" (few), progress is "progress within a stage" (high frequency, overwritable, keeps the last 20). */
declare const PROGRESS_TAG = "DSH_PROGRESS ";
declare function scanProgressLine(line: string, rec: StageRecord, now: number): boolean;
declare function scanStageLine(line: string, rec: StageRecord, now: number): boolean;
/** Feed a chunk line by line to the stage scanner (a partial line spanning chunks is caught by a tail buffer) */
declare function makeStageScanner(rec: StageRecord): (chunk: unknown) => void;
/**
 * v2.6 (feedback #4 of this round): run heartbeat -- update rec.heartbeat every 5s (and optionally append to <dir>/heartbeat.jsonl).
 * Field problem: one EEVEE frame takes 2-3 minutes, and op=status only had the two numbers stage/idleMs, so you could not tell "which frame / how many bytes written".
 * heartbeat provides: elapsedMs / logBytes / lines / stage / lastProgressAt -- enough to judge "is it moving or stuck".
 */
declare function startHeartbeat(rec: StageRecord, dirWsl?: string | null): () => void;
export { STAGE_TAG, PROGRESS_TAG, scanProgressLine, scanStageLine, makeStageScanner, startHeartbeat, };
