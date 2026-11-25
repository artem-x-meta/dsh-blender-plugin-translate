export declare const IS_WIN: boolean;
/**
 * v0.8.10 (self-identifying version): tool descriptions all carry a version prefix.
 * The description is generated from **the lib that is actually loaded** -> a session can tell at a glance which generation it is running,
 * and accidents like "reading new source but running an old lib" no longer happen (meta-lesson from external j20-build feedback).
 */
export declare const PLUGIN_VERSION = "3.0.6";
export declare const HERE: string;
/**
 * The runtime source is TypeScript; the runtime entry is the build output lib/runtime/server.js.
 * - Production/packaged layout: HERE = <pkg>/lib -> <pkg>/lib/runtime/server.js
 * - Development/test layout: HERE = <pkg>/src -> <pkg>/lib/runtime/server.js (build first)
 * The DSH_BLENDER_SERVER override still has the highest priority (for troubleshooting/custom install locations).
 */
export declare function resolveServerPath(here?: string, env?: NodeJS.ProcessEnv, exists?: (p: string) => boolean): string;
export declare const SERVER_PATH: string;
export declare const HOSTNAME = "127.0.0.1";
/** Shared hint for when the backend is not ready (assumes no local paths) */
export declare const BACKEND_HINT: string;
/**
 * v0.9.2 (R3): **static** deadlines handed to the host - defineTool only takes constants, they cannot vary per argument.
 * Rule: always = the tool's longest internal timeout + margin -> the internal timeout always fires first and the model gets
 * this plugin's readable error; the host's TOOL_TIMEOUT only catches the last case where even the internal timeout did not hold.
 * Background: since host 0.1.6 @deepseek-ai/dsh-tool-call-timeout-policy is wired in, but **it only sets a deadline when the tool
 * declares timeoutMs itself**; not declaring one = as soon as upstream supplies a default, Blender is still running while the tool is already timed out.
 */
export declare const T: {
    see: number;
    act: number;
    watch: number;
    cmd: number;
    commands: number;
    loop: number;
    perf: number;
    opt: number;
    headless: number;
    plan: number;
    worker: number;
    txn: number;
    preset: number;
    job: number;
    viewport: number;
};
/**
 * (status/doctor telling the truth): bounded host-side probe budgets. The outer timeout must be **greater** than the
 * backend's internal budget, otherwise the model gets the host's aborted first and never sees the addonError diagnosis;
 * it must also be clearly below T.viewport (60s) so the tool itself stays bounded.
 */
/**
 * op=start: after /health succeeds, probe /status to decide whether addon/bpy are usable.
 * After the fix the backend's /status addon budget is 5s; after a transport timeout lifecycle also runs diagnose() once more (~2.5s),
 * so the half-open addon steady state is ~7.5s; startup probing no longer occupies the serial queue, so the first call only pays one cold-start cost.
 * The budget is 12s to cover the first call and is still far below T.viewport's 60s.
 */
export declare const VIEWPORT_START_STATUS_TIMEOUT_MS = 12000;
/** op=doctor catch: probe /health first to tell "backend present" from "backend not started". */
export declare const VIEWPORT_DOCTOR_HEALTH_TIMEOUT_MS = 800;
export declare const HOST_API: string;
/** Shared wording for host cancellation (exec.signal abort): say only that the wait was cancelled, never claim the task failed */
export declare const ABORT_HINT: string;
/** This session's identity on the write channel (lease holder); used to tell sessions apart when they share one backend */
export declare const HOLDER: string;
