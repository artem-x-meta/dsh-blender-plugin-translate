/** Real TCP probe: a successful connection means "listening". Lighter than an HTTP liveness check and unaffected by host fetch timeouts. */
export declare function probeTcp(host: string, port: number, timeoutMs?: number): Promise<boolean>;
/** HTTP liveness check: only a 2xx counts as "the backend is really serving" (port open but backend not up => false). */
export declare function probeHttp(url: string, timeoutMs?: number): Promise<boolean>;
/**
 * Start decision table (pure function, easy to unit test):
 *   portUp                -> "already-running" (one started by another session also counts as running; never start a second one)
 *   !portUp && childAlive -> "stale-handle" (stale handle: the port is not listening => it must be cleared before starting)
 *   !portUp && !childAlive-> "spawn"
 */
export type StartDecision = 'already-running' | 'stale-handle' | 'spawn';
export declare function decideStart({ portUp, childAlive, }: {
    portUp: boolean;
    childAlive: boolean;
}): StartDecision;
/** Poll until it can serve (op=start uses it to give a real verdict instead of "sleep a fixed time and probe once"). */
export declare function waitHttp(url: string, timeoutMs?: number, intervalMs?: number): Promise<boolean>;
