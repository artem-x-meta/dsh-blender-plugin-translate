export { childAlive, getChild, killChildHandle, spawnChild } from './spawn.js';
export { killBackendByCmd } from './process-scan.js';
/**
 * Port resolution (the same source set as runtime/config.ts, so the two configs cannot drift apart):
 *   plugin config port -> DSH_BLENDER_HTTP_PORT -> $DSH_BLENDER_CONFIG -> <package root>/dsh-blender.config.json
 *   -> ~/.dsh/dsh-blender.config.json -> 9877
 */
export declare function resolveHttpPort(): number;
export declare function base(port: number): string;
export declare const sleep: (ms: number) => Promise<unknown>;
export declare function probe(port: number, timeoutMs?: number): Promise<boolean>;
export declare function ensureBackend(port: number): Promise<boolean>;
/**
 * Fix: **probe the port first**, no longer trusting a stale handle/pidfile.
 * Bug seen in the field: the handle is still there (childAlive) but the port is not listening at all, and the old implementation returned 'already-spawned',
 * leaving the user with a backend that cannot be reached; conversely, it really had started but returned 'start failed' because the wait window was too short.
 * Now: the port serves => already-running; the port is dead but the handle exists => judged a stale handle, SIGTERM and respawn.
 */
export declare function startBackend(port: number): Promise<string>;
/**
 * v0.9.2: merge "this plugin's internal timeout" with "the host's exec.signal".
 * Both only affect **waiting**: a Blender-side task the server has already started still runs to completion (existing headless/job semantics
 * = a client disconnect is not a task failure, it is collected by runId).
 */
export declare function withTimeout(path: string, init: RequestInit | undefined, timeoutMs: number): Promise<Response>;
/** The user stopped it explicitly with op=stop -> the watchdog no longer auto-starts it (op=start clears this). Read and written through accessors across modules so only one copy of the live state exists. */
export declare function isPaused(): boolean;
export declare function setPaused(v: boolean): void;
