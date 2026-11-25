/**
 * dsh-blender-plugin - host-side entry (entry-only).
 *
 * Re-exports only: implementations live in plugin / contracts / host / tools / plan / headless / utils / ui.
 * 15 model tools: see / do / watch / cmd / commands / loop / perf / opt / headless / plan /
 * worker / txn / preset / job / viewport; plan catalog 34 families / 228 ops (the count source of truth is the catalog, not written by hand here).
 * Works with the persistent kernel variable K (each addon call is a new namespace, K lives in sys.modules -> REPL semantics).
 *
 * Concurrency: writes carry a lease holder automatically; when another session holds it the write routes return 409 (read-only ops are exempt, force can take over).
 */
export { name, inject, Config, apply, __internals } from './plugin.js';
export { frameDedupe, resetFrameCache } from './utils/frame-cache.js';
