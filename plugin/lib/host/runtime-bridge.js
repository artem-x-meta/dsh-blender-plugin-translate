/**
 * runtime-bridge: the single src-side entry point into the compiled artifacts lib/runtime/*.js.
 * Why a bridge is needed: src is the TypeScript plugin layer, runtime is the separately compiled Blender-side host layer;
 * the two layers differ in module format/publish layout (src builds to lib, runtime builds to lib/runtime).
 * Previously 4 src files each imported '../../lib/runtime/*.js' directly — a directory move/publish layout change
 * scattered the edits. Now that it is centralized in this file, src code may only touch the runtime layer via host/runtime-bridge.ts.
 */
export { probeHttp, waitHttp, decideStart } from '../../lib/runtime/backend_probe.js';
export { winKillPids, winSamePortHolders } from '../../lib/runtime/win_proc.js';
export { detectFileAlias } from '../../lib/runtime/file_guard.js';
export { serverPidsFromProcRows } from '../../lib/runtime/ports.js';
//# sourceMappingURL=runtime-bridge.js.map