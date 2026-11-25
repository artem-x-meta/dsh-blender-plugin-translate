/**
 * dsh-blender-plugin — host-side entry (entry-only).
 *
 * Re-export only: the implementations live in plugin / contracts / host / tools / plan / headless / utils / ui.
 * 15 model tools: see / do / watch / cmd / commands / loop / perf / opt / headless / plan /
 * worker / txn / preset / job / viewport; the plan catalog has 34 families / 228 ops (the count source of truth is the catalog, not hand-written here).
 * Works with the persistent kernel variable K (the addon gets a fresh namespace on every call; K lives in sys.modules → REPL semantics).
 *
 * Concurrency: write operations automatically carry a lease holder; another session holding it makes the write route 409 (read-only ops are exempt, force can steal).
 */
export { name, inject, Config, apply, __internals } from './plugin.js';
export { frameDedupe, resetFrameCache } from './utils/frame-cache.js';
//# sourceMappingURL=index.js.map
