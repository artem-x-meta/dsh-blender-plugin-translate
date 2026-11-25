import { existsSync, readFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { asRecord, errorMessage } from './contracts/dynamic.js';
export const IS_WIN = process.platform === 'win32';
/**
 * v0.8.10 (version self-proof): tool descriptions uniformly carry a version prefix.
 * The description is generated from **the lib that actually got loaded** → a session shows at a glance which generation it is running,
 * and the "read the new source, ran the old lib" class of debugging accident cannot happen again (external feedback, the meta-lesson from j20-build).
 */
export const PLUGIN_VERSION = '3.0.6';
// Both the backend and the Blender-side modules live under the plugin package's runtime/ → the whole package can be moved to any directory (WSL or Windows)
export const HERE = path.dirname(fileURLToPath(import.meta.url));
/**
 * The runtime source is TypeScript; the runtime entry point is the build artifact lib/runtime/server.js.
 * - production/packaged layout: HERE = <pkg>/lib → <pkg>/lib/runtime/server.js
 * - dev/test layout: HERE = <pkg>/src → <pkg>/lib/runtime/server.js (build first)
 * The DSH_BLENDER_SERVER override still has the highest precedence (for troubleshooting/custom install locations).
 */
export function resolveServerPath(here = HERE, env = process.env, exists = existsSync) {
    const override = env.DSH_BLENDER_SERVER;
    if (override)
        return override;
    const candidates = [
        path.join(here, 'runtime', 'server.js'),
        path.join(here, '..', 'lib', 'runtime', 'server.js'),
    ];
    for (const candidate of candidates) {
        if (exists(candidate))
            return candidate;
    }
    // When it has not been built, still return the build-layout path: the error then points at the artifact that is genuinely missing, not at a deleted old .mjs.
    return candidates[0];
}
export const SERVER_PATH = resolveServerPath();
export const HOSTNAME = '127.0.0.1';
/** The unified hint when the backend is not ready (assumes no local paths) */
export const BACKEND_HINT = 'First make sure Blender is running and this repo\'s addon (DSH Blender Bridge v1.10+) is Connected; then run blender_viewport op=start to bring the backend up.' +
    'The port/working directory/blender.exe can be configured with DSH_BLENDER_* environment variables or the package-root dsh-blender.config.json (see docs/configuration-reference.md).';
/**
 * v0.9.2 (R3): the **static** deadline handed to the host — defineTool only accepts constants, it cannot be given one dynamically per argument.
 * Guiding rule: always = the tool's longest internal timeout + margin → the internal timeout always fires first, so what the model gets is this plugin's
 * readable error; the host's TOOL_TIMEOUT is only the last line of defence for "not even the internal timeout held".
 * Background: since host 0.1.6 the @deepseek-ai/dsh-tool-call-timeout-policy is assembled, but a deadline is set **only when the tool
 * declares timeoutMs itself**; not declaring it = as soon as upstream supplies a default, the tool is judged timed out while Blender is still running.
 */
export const T = {
    see: 300000, // internal max(/view 180s, /frame.png 60s) + margin
    act: 300000, // /act 180s + frame return 60s + margin
    watch: 600000, // /act 180s + up to 32 frames (each up to 60s)
    cmd: 360000, // /cmd internal 300s
    commands: 60000, // read-only listing
    loop: 360000, // /loop internal 300s (the inner-loop budget is counted separately in spec.budget_ms)
    perf: 660000, // /perf internal 600s
    opt: 660000, // /opt internal 600s
    // v0.9.3: headless no longer "runs along until the timeout" — the client wait window (DSH_HEADLESS_WAIT_MS, default 100 s) returns a
    // promoted receipt (jobId) when it elapses, and the server-side subprocess keeps running. The static deadline just needs a wide margin (users with a large custom window are not judged timed out either).
    headless: 1200000,
    plan: 360000, // /plan internal 300s
    worker: 1920000, // exec timeout_ms is supplied by the caller; the static cap is 32min
    txn: 360000, // /txn internal 300s
    preset: 360000, // /preset internal 300s
    // v0.9.3: job gained op=wait (server-side single-call cap 600 s) → the static deadline has to cover it
    job: 660000,
    viewport: 60000, // retry window for status/doctor/lease + start/restart
    // v1.2: waiting for the user to click — backend TTL defaults to 120 s (clamped to [5,600]); the static deadline leaves a margin covering up to 600 s + wrap-up
};
/**
 * (status/doctor tell the truth): the bounded probe budget on the host side.
 * The outer timeout must be **greater** than the backend's internal budget, otherwise the model gets the host's aborted first and never sees the addonError diagnostics;
 * at the same time it must be clearly less than T.viewport (60s) so the tool itself stays bounded.
 */
/**
 * op=start: after /health passes, probe /status to decide whether addon/bpy are usable.
 * After the fix the backend-side /status addon budget is 5s; after a transport timeout lifecycle also runs diagnose() once (~2.5s),
 * so a half-open addon steady state is ≈7.5s; the start probe no longer occupies the serial queue, so the first call only adds one cold-start cost. The budget takes 12s to cover the first call,
 * and is still far below T.viewport 60s.
 */
export const VIEWPORT_START_STATUS_TIMEOUT_MS = 12000;
/** op=doctor catch: probe /health first to tell "backend present" from "backend not started". */
export const VIEWPORT_DOCTOR_HEALTH_TIMEOUT_MS = 800;
/**
 * v0.9.2 (R2 self-proof): which copy and which version of @deepseek-ai/dsh-tools the plugin actually imports.
 * Local resolution chain: the plugin's node_modules → ~/dsh-harness (fake checkout) → the **global install** under
 * /usr/lib/node_modules. Once DSH upgrades, this is the post-upgrade copy; and when the global install location moves, the plugin gets
 * ERR_MODULE_NOT_FOUND at load time (all 15 tools vanish at once). doctor/status carry it, to tell at a glance
 * "plugin/host API broken" from "Blender not running".
 */
function hostApiInfo() {
    try {
        const meta = import.meta;
        const resolveFn = meta.resolve;
        if (typeof resolveFn !== 'function')
            return 'dsh-tools: import.meta.resolve unavailable (node < 20.6?)';
        const url = String(resolveFn.call(import.meta, '@deepseek-ai/dsh-tools') || '');
        let p = url;
        if (p.startsWith('file://'))
            p = fileURLToPath(p);
        let ver = '?';
        try {
            const parsed = JSON.parse(readFileSync(path.join(path.dirname(path.dirname(p)), 'package.json'), 'utf8'));
            ver = String(asRecord(parsed).version || '?');
        }
        catch {
            /* failing to read the version is not an error */
        }
        return 'dsh-tools@' + String(ver) + ' @ ' + p;
    }
    catch (e) {
        return ('dsh-tools resolution failed: ' +
            errorMessage(e) +
            ' (the plugin will fail at load time: check whether the global install location moved)');
    }
}
export const HOST_API = hostApiInfo();
/** The unified wording when the host cancels (exec.signal abort): only say "the wait was cancelled", never claim the task failed */
export const ABORT_HINT = 'The host cancelled this wait (exec.signal already aborted: the user interrupted, or a per-tool deadline).' +
    'The server-side task may still be running — for long tasks use blender_rt_job and collect by runId;' +
    'this plugin\'s internal timeout normally fires before the host deadline, so what you see in the normal case is a readable error like the one above.';
/** This session's identity on the write channel (the lease holder); used to tell sessions apart when several share one backend */
export const HOLDER = process.env.DSH_BLENDER_HOLDER || 'plugin-pid-' + String(process.pid);
//# sourceMappingURL=constants.js.map
