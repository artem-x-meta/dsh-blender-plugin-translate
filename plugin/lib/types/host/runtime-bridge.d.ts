/**
 * runtime-bridge: the single entry from the src side into the compiled lib/runtime/*.js artifacts.
 * Why a bridge: src is the TypeScript plugin layer and runtime is the separately compiled Blender-side host layer;
 * the two layers differ in module format / release layout (src builds into lib, runtime builds into lib/runtime).
 * Previously 4 src files each imported '../../lib/runtime/*.js' directly — directory moves / release-layout changes
 * would scatter the edits. After concentrating them in this file, src may touch the runtime layer only through host/runtime-bridge.ts.
 */
export { probeHttp, waitHttp, decideStart } from '../../lib/runtime/backend_probe.js';
export { winKillPids, winSamePortHolders } from '../../lib/runtime/win_proc.js';
export { detectFileAlias } from '../../lib/runtime/file_guard.js';
export { serverPidsFromProcRows } from '../../lib/runtime/ports.js';
