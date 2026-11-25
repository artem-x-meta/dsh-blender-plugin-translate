import type { JobRecord } from '../types.js';
import type { PreparedJob } from '../script/index.js';
import type { JobStartDeps } from './index.js';
export declare function buildJobRecord(p: PreparedJob): JobRecord;
/** Final stdout/stderr parsing (HEADLESS / DSH_SHOTS / path audit) */
export declare function collectJobOutputs(j: JobRecord, p: PreparedJob): void;
/** Write the result to disk + terminal-state summary + ledger (still queryable after a backend restart) */
export declare function persistJobResult(d: JobStartDeps, j: JobRecord, p: PreparedJob, opts: Record<string, unknown>): void;
