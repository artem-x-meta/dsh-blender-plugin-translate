import { AsyncLocalStorage } from 'node:async_hooks';
// v0.9.2 (DSH update adaptation R3): put the host's exec (exec.signal = user interrupt / per-tool deadline)
// into AsyncLocalStorage so the transport's withTimeout() merges it automatically — **the 15 tool bodies
// respond to host cancellation without a single change**; each tool also carries a static timeoutMs
// (see T), turning the silent mismatch of "upstream set a default deadline" from "Blender is still
// running but the tool was already timed out" into "this plugin reports a readable error first".
export const EXEC_CTX = new AsyncLocalStorage();
/** Host exec.signal for the current tool call (undefined when absent) */
export function execSignal() {
    const s = EXEC_CTX.getStore();
    return s?.signal instanceof AbortSignal ? s.signal : undefined;
}
//# sourceMappingURL=exec-context.js.map