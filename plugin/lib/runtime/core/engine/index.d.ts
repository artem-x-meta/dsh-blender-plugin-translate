import type { AddonClient as AddonClientType } from '../../transport/probes.js';
import type { createJobsApi } from '../../execution/jobs/index.js';
import type { createWorkersApi } from '../../execution/workers/index.js';
/** Channel metrics: who is writing / busy or not / queue depth (used by /status and /who) */
export interface EngineMetrics {
    [k: string]: unknown;
    calls: number;
    errors: number;
    timeouts: number;
    inflight: number;
    lastCmd: string | null;
    lastCmdAt: number | null;
    lastOkAt: number | null;
    lastError: string | null;
    lastDiagnosis: unknown;
    views: number;
    headlessRuns: number;
    lastHeadlessMs: number | null;
    workerStarts: number;
    workerExecs: number;
    lastErrorAt: number | null;
    aiPausedAt: number | null;
}
export type JobApi = ReturnType<typeof createJobsApi>;
export type WorkerApi = ReturnType<typeof createWorkersApi>;
/** Job view on the engine surface (method names match the server.mjs compatibility surface). */
export interface JobView {
    start: JobApi['jobStart'];
    status: JobApi['jobStatus'];
    collect: JobApi['jobCollect'];
    kill: JobApi['jobKill'];
    list: JobApi['jobList'];
    wait: JobApi['jobWait'];
}
/** Worker view on the engine surface. */
export interface WorkerView {
    start: WorkerApi['workerStart'];
    exec: WorkerApi['workerExec'];
    see: WorkerApi['workerSee'];
    watch: WorkerApi['workerWatch'];
    reset: WorkerApi['workerReset'];
    status: WorkerApi['workerStatus'];
    stop: WorkerApi['workerStop'];
    restart: WorkerApi['workerRestart'];
    list: WorkerApi['workerList'];
    snapshot: WorkerApi['workerSnapshot'];
    state: WorkerApi['workerState'];
}
export interface EngineOptions {
    address?: {
        host?: string;
        port?: number;
    } | null;
    [k: string]: unknown;
}
/** Public engine surface: the http layer and scripts take capabilities by name; extra fields are kept via the index signature */
export interface EngineSurface {
    [k: string]: unknown;
    addon: AddonClientType;
    plan: (op: string, payload?: unknown) => Promise<unknown>;
    txn: (op: string, payload?: unknown) => Promise<unknown>;
    preset: (op: string, payload?: unknown) => Promise<unknown>;
    worker: WorkerView;
    job: JobView;
    launchBlender: (o?: unknown) => unknown;
    sceneEpoch: () => Promise<unknown>;
    renderFlag: () => unknown;
    headless: (opts?: Record<string, unknown>) => Promise<Record<string, unknown>>;
    start: () => Promise<unknown>;
    stop: () => unknown;
    metrics: () => unknown;
    protocol: () => Promise<unknown>;
    doctor: () => Promise<unknown>;
    status: () => Promise<unknown>;
    act: (code: unknown, timeoutMs?: number, file?: unknown) => Promise<unknown>;
    cmd: (name: unknown, params?: Record<string, unknown>, timeoutMs?: number) => Promise<unknown>;
    commands: () => Promise<unknown>;
    loopStart: (spec: unknown) => Promise<unknown>;
    loopStatus: (history?: number) => Promise<unknown>;
    loopStop: () => Promise<unknown>;
    loopBench: (iterations?: number) => Promise<unknown>;
    loopBoard: (limit?: number, groups?: boolean) => Promise<unknown>;
    loopExport: (opts?: Record<string, unknown>) => Promise<unknown>;
    loopHelp: () => Promise<unknown>;
    frameArea: (areaIndex?: number) => Promise<unknown>;
    perf: (op: string, payload?: unknown) => Promise<unknown>;
    opt: (op: string, payload?: unknown) => Promise<unknown>;
    frame: (maxSize?: number) => Promise<unknown>;
    view: (spec?: Record<string, unknown>) => Promise<unknown>;
    hostSceneItems: (spec?: Record<string, unknown>) => Promise<unknown>;
}
/**
 * Assemble the engine. The only option is opts.address (addon address override), same as before the split.
 * Note: no business logic lives here; it only wires each factory to the same deps object,
 * so the closures share one addon / metrics / ledger / jobs (same semantics as the single closure before the split).
 */
export declare function createEngine(opts?: EngineOptions): EngineSurface;
