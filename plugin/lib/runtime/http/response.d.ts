import type { ServerResponse, IncomingMessage } from 'node:http';
declare function json(res: ServerResponse, code: number, obj: unknown): void;
/**
 * Streaming response (ndjson) -- required for long tasks: the client's fetch header timeout defaults to 300 s (observed UND_ERR_HEADERS_TIMEOUT),
 * while the server only replies once the child process has finished -> a long task is bound to hit the timeout. So the response headers are sent immediately plus a periodic heartbeat, and only the last line is the result.
 */
declare function streamJson(res: ServerResponse, producer: () => Promise<unknown>, hbMs?: number): Promise<unknown>;
declare function readBody(req: IncomingMessage, limit?: number): Promise<string>;
declare function hostCorsHeaders(origin: unknown): Record<string, string>;
declare function hostJson(res: ServerResponse, code: number, obj: unknown, origin?: unknown): void;
declare function hostErrText(e: unknown): string;
/** The limit for `@` mentions: clamped to [1,1000], default 200 (the old viewstore convention, still used by the routes). */
declare function clampItemsLimit(v: unknown, dflt?: number): number;
declare function hostNormEmpty(v: unknown): unknown;
export { json, streamJson, readBody, hostCorsHeaders, hostJson, hostErrText, clampItemsLimit, hostNormEmpty, };
