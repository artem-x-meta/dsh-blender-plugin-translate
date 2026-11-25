import type { EngineApiDeps } from './index.js';
export declare function createLoopApi(E: EngineApiDeps): {
    loopStart(spec: unknown): Promise<unknown>;
    loopStatus(history?: number): Promise<unknown>;
    loopStop(): Promise<unknown>;
    loopBench(iterations?: number): Promise<unknown>;
    /** Candidate table: top_k / grouped (cross-object batch) results */
    loopBoard(limit?: number, groups?: boolean): Promise<unknown>;
    /** Export a reusable script (embedded setup source + best parameters) */
    loopExport(opts?: Record<string, unknown>): Promise<unknown>;
    /** Inner-loop contract cheat sheet (spec fields + ns presets + helper functions) */
    loopHelp(): Promise<unknown>;
};
