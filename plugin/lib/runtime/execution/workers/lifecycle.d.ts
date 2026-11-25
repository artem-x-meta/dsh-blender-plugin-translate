import type { WorkersCtx } from './api.js';
export declare function workerStop(ctx: WorkersCtx, nameArg?: unknown): Promise<Record<string, unknown>>;
/** Restart: switch to a clean session (reusing one means giving up process isolation, so use this when a script has dirtied the session) */
export declare function workerRestart(ctx: WorkersCtx, nameArg?: unknown, opts?: Record<string, unknown>): Promise<Record<string, unknown>>;
export declare function createWorkerReaper(ctx: WorkersCtx): {
    clearWorkerReaper: () => void;
    killWorkers: () => void;
};
