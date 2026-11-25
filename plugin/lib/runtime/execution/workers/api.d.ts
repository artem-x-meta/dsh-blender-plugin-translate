import type { ChildProcess } from 'node:child_process';
export interface WorkersDeps {
    metrics: {
        workerStarts: number;
        workerExecs: number;
        [k: string]: unknown;
    };
    preloadChunk: (name: string) => string;
}
export interface WorkerRecord {
    [k: string]: unknown;
    name: string;
    child: ChildProcess | null;
    port: number;
    ready: boolean;
    startedAt: number | null;
    gpu: unknown;
    pid: number | null;
    lastError: string | null;
    stdoutTail: string;
    stderrTail: string;
    boot?: unknown;
    lastUsed?: number;
}
export interface WorkersCtx {
    metrics: WorkersDeps['metrics'];
    preloadChunk: (name: string) => string;
    WORKERS: Map<string, WorkerRecord>;
    WORKER_PORT: number;
}
export declare function workerKey(n: unknown): string;
export declare function workerState(ctx: WorkersCtx, name: unknown): WorkerRecord;
export declare function workerAlive(w: WorkerRecord | null | undefined): boolean;
export declare function workerSnapshot(w: WorkerRecord): Record<string, unknown>;
export declare function workerList(ctx: WorkersCtx): Array<Record<string, unknown>>;
/** A single request-reply with the worker (a new short connection each time, so no state is left behind) */
export declare function workerCall(w: WorkerRecord, req: Record<string, unknown>, timeoutMs?: number): Promise<Record<string, unknown>>;
