import { type ReceiptContext } from './human-text.js';
/**
 * v0.9.3: the client's per-call wait limit. Past it, **do not just wait**: move to the job layer and return a jobId (matching bash's promoted semantics).
 * Default 100 s: the outer run_code default deadline is 120 s, leaving 20 s of margin for the receipt and status queries.
 */
export declare const HEADLESS_WAIT_MS: number;
/** The run id is generated **client-side**: when the window expires a usable handle is already at hand (the server registers it in its ledger) */
export declare function newRunId(): string;
/** Backgroundize + optional wait: POST /headless with asJob:true to get a jobId, then op=wait for a short while */
export declare function startJobThenMaybeWait(port: number, body: unknown, waitS: number | null): Promise<Record<string, unknown>>;
/** Normalize the shots receipt: the sync path gives {rows:[…]}, job snapshots give qc_render's original {views:[…]} */
export declare function normalizeShots(s: unknown): Record<string, unknown> | null;
/** Structured envelope (block 0): stable fields + bounded size (large results only give a resultPath) */
export declare function receiptEnvelope(res: unknown, ctx: ReceiptContext): Record<string, unknown>;
export interface ToolReceipt {
    text: string;
    envelope: Record<string, unknown>;
    images?: unknown[];
    [key: string]: unknown;
}
/** Headless receipt (sync / job completion): {text, envelope} - the source of the two text blocks */
export declare function headlessReceipt(res: unknown, ctx: ReceiptContext): ToolReceipt;
/**
 * v0.9.3: **promoted receipt** - the task is still running (or has finished but we did not wait for it) and the handle is already valid.
 */
export declare function promotedReceipt(job: unknown, jobId: string, why: string): ToolReceipt;
/**
 * v0.9.3: fallback for client wait-window expiry / host cancellation - ask the server for status first:
 *   finished -> collect the result directly; still running -> return a promoted receipt (the runId was generated client-side, so the handle is always valid).
 */
export declare function promotedFromTimeout(port: number, runId: string, err: unknown): Promise<Record<string, unknown>>;
/** Status snapshot for an id (run-… / job-…); returns null when unavailable and never throws */
export declare function fetchJobStatus(port: number, id: string): Promise<unknown>;
