// engine API: channel diagnostics (split out of server-compat.ts)
import { diagnose, freshPing, protocolInfo, tcpProbe } from '../../transport/probes.js';
import { FLAGS_CODE, REGION_CODE } from '../flags.js';
import { jsonFromStdout } from '../output/index.js';
import { PLUGIN_VERSION, RUNTIME_DIR, engineProvenance, runtimeFingerprint } from '../evidence.js';
import { wslToWin } from '../../config.js';
import { COMMAND_CATALOG } from '../../catalog/index.js';
import { errorMessage } from '../json.js';
import { metricsView } from './metrics.js';
/**
 * Addon-side stage budgets. The host backendJson defaults to 20s and the T.commands static deadline is 60s;
 * the budgets here must land before the host's, otherwise the model only gets aborted and never sees any structured diagnostics.
 */
/**
 * bpy round-trip (REGION_CODE) budget for /status: 5s — the honest value after the fix (the startup probe no longer occupies the head of the serial queue;
 * before the fix only 3.5s could be received). Note that installAddonSend runs diagnose() once more after a transport error
 * (about 2.5s for a half-open addon), so this must not hug the host's 20s — keep enough headroom (half-open steady state ≈5s + 2.5s).
 */
export const ADDON_STATUS_TIMEOUT_MS = 5000;
/** status-stage budget for /doctor: 4s (callback after the fix; in a half-open case ≈4s + reused diagnosis ≈2.5s, still within the <10s target). */
export const ADDON_DOCTOR_STATUS_TIMEOUT_MS = 4000;
/** /commands FLAGS + 5 integrations must fit entirely inside the client budget: 15s + 5×(3s+~2.5s diagnosis)≈42.5s < 45s client < 60s host. */
export const ADDON_FLAGS_TIMEOUT_MS = 15000;
/** Per-integration status budget for /commands (5 in series; a failure also runs one ~2.5s diagnosis each, hence 3s). */
export const ADDON_INTEGRATION_TIMEOUT_MS = 3000;
const TIMEOUT_RE = /timeout|timed out|aborted|abort/i;
/** Whether this is a "no reply from the addon" kind of error (timeout/aborted): blame the addon/bpy rather than the backend process. */
export function isAddonTimeout(e) {
    return TIMEOUT_RE.test(errorMessage(e));
}
export async function statusView(E, opts = {}) {
    const { LEDGER, RESULTS_DIR, SESSION_NAME, TRAJ_DIR, TRAJ_FULL, TRAJ_OFF, addon, jobSnapshot, jobs, ledgerList, ledgerState, runSnapshot, runs, } = E;
    const addonTimeoutMs = opts.addonTimeoutMs || ADDON_STATUS_TIMEOUT_MS;
    let region = null, addonError = null;
    try {
        const out = await addon.send('execute_code', { code: REGION_CODE }, addonTimeoutMs);
        region = jsonFromStdout(out);
    }
    catch (e) {
        addonError = errorMessage(e).slice(0, 300);
    }
    return {
        region: region,
        addonError: addonError,
        plugin: {
            version: PLUGIN_VERSION,
            runtimeDir: wslToWin(RUNTIME_DIR),
            runtime: runtimeFingerprint(),
            provenance: engineProvenance({}),
        },
        session: SESSION_NAME,
        resultsDir: wslToWin(RESULTS_DIR),
        trajectory: {
            dir: wslToWin(TRAJ_DIR),
            off: TRAJ_OFF,
            full: TRAJ_FULL,
            note: 'v0.9.0 (#15): one JSONL line per top-level call (route/op/ms/ok/argument summary); DSH_TRAJ=0 turns it off, DSH_TRAJ_FULL=1 records more arguments',
        },
        runs: Array.from(runs.values())
            .slice(-5)
            .map((r) => runSnapshot(r)),
        jobs: Array.from(jobs.values())
            .slice(-5)
            .map((j) => jobSnapshot(j)),
        ledger: Object.assign({
            path: wslToWin(LEDGER),
            pathWsl: LEDGER,
            recent: ledgerList(5).map((x) => ({
                id: x.id,
                kind: x.kind || 'job',
                status: x.status,
                startedAt: x.startedAt,
                ms: x.ms,
            })),
        }, ledgerState()),
    };
}
/**
 * (PR review): attribution when the addon explicitly returned an error (not a timeout).
 * Such a failure means the channel is up (TCP works, the addon responds); do not attribute it to main-thread-busy / blender-unreachable.
 */
export function addonErrorDiagnosis(error) {
    // While Blender is rendering, a main-thread command hits BUSY_RENDER first: this is "wait for the render", not a broken addon / busy main thread.
    const busy = /BUSY_RENDER/.test(error);
    return {
        kind: 'addon-error',
        tcp: true,
        ping: null,
        error: error,
        stage: 'execute_code',
        summary: busy
            ? 'backend (9877) is up and port 9876 is reachable too; Blender is rendering (BUSY_RENDER): ' +
                error +
                ' — the main thread is taken up by the render; the addon process is not broken and the channel is not down.'
            : 'backend (9877) is up and port 9876 is reachable too; the addon returned an error (not a timeout): ' +
                error +
                ' — the channel itself is still up, handle it as addonError (e.g. the operation is paused / an argument or script error); it is not main-thread-busy.',
        fix: busy
            ? 'Wait for the render to finish, or wait for it with blender_rt_plan(op="render_wait"); for a long render go through blender_rt_job from the start. Do not retry repeatedly on the assumption of a "busy main thread", and op=start is not needed either (it only fixes the 9877 backend process).'
            : 'Fix it according to the specific addonError message (for example resume the paused "AI operation" in DSH; for a script/argument error change the arguments as reported); do not retry on the assumption of a "busy main thread".',
        hint: busy
            ? 'BUSY_RENDER: main-thread commands queue until they time out — wait for the render to finish before sending.'
            : 'TCP 127.0.0.1:9876 works, but the addon explicitly returned an error → attribute it to addonError; the channel is not down and the main thread is not busy.',
    };
}
/**
 * doctor failure branch. When TCP is already up, separate "the addon does not reply" from "the backend is not up" —
 * a timeout no longer collapses into blender-unreachable (that is exactly what made start/doctor contradict each other in field seq 52-56).
 */
async function failedDoctor(E, e, elapsedMs) {
    const { metrics } = E;
    // The addon.send wrapper layer (engine/lifecycle.ts) has already run diagnose() once after a transport error
    // and attached it to err.diagnosis — reuse it so the doctor failure path does not run another ~2.5s probe.
    const timeout = isAddonTimeout(e);
    const err = errorMessage(e);
    // (PR review): a non-timeout error (e.g. "AI operation paused" / a script error) is not main-thread-busy.
    // diagnose() always attributes to main-thread-busy when ping works, so attribute to addonError directly here without running another probe.
    if (!timeout)
        return { ok: false, addon: addonErrorDiagnosis(err), metrics: metricsView(E), error: err };
    const attached = e.diagnosis ||
        (timeout ? metrics.lastDiagnosis : null);
    const d = attached || (await diagnose().catch(() => null));
    if (d)
        metrics.lastDiagnosis = d;
    // Reaching here means the doctor entry's tcpProbe() already succeeded: 9876 is listening, the addon just does not answer the bpy round-trip.
    const addon = {
        ...(d || {}),
        kind: 'addon-unresponsive',
        tcp: true,
        ping: d ? d.ping : null,
        error: err,
        stage: 'execute_code',
        timeout_ms: ADDON_DOCTOR_STATUS_TIMEOUT_MS,
        elapsed_ms: elapsedMs,
        summary: 'backend (9877) is up and port 9876 is reachable too, but the addon did not answer the bpy round-trip within ' +
            String(ADDON_DOCTOR_STATUS_TIMEOUT_MS) +
            'ms (execute_code timed out) — the addon thread is stuck / the Blender main thread is occupied / the other side is not the addon from this repo',
        fix: 'First confirm Blender is running and "DSH Blender Bridge" is Connected; then free Blender from rendering/modal operations and reload the addon if necessary (N panel Disconnect → Connect). op=start only handles the 9877 backend process and does not fix this channel.',
        hint: 'TCP 127.0.0.1:9876 works + backend 9877 is up, but the bpy round-trip times out → the problem is in the addon/bpy, not the backend process.',
    };
    return { ok: false, addon, metrics: metricsView(E), error: err };
}
export function createDoctorApi(E) {
    const { addon, metrics } = E;
    return {
        async protocol() {
            return await protocolInfo();
        },
        /** Field check: actually run one bpy round-trip (status); only a pass counts as ok, and only a failure goes on to the three-tier verdict */
        async doctor() {
            const t0 = Date.now();
            if (!(await tcpProbe())) {
                const d = await diagnose();
                metrics.lastDiagnosis = d;
                return { ok: false, addon: d, metrics: metricsView(E) };
            }
            try {
                const s = await statusView(E, { addonTimeoutMs: ADDON_DOCTOR_STATUS_TIMEOUT_MS });
                // statusView swallows addon errors itself → addonError must count as a failure here, otherwise doctor falsely reports ok:true.
                // Carry over the diagnosis the send wrapper just computed so the failure path does not run another ~2.5s probe.
                if (s.addonError) {
                    const err = new Error(String(s.addonError));
                    if (metrics.lastDiagnosis)
                        err.diagnosis = metrics.lastDiagnosis;
                    throw err;
                }
                const pingMs = await freshPing().catch(() => null);
                const pinfo = await protocolInfo();
                return {
                    ok: true,
                    addon: {
                        kind: 'ok',
                        tcp: true,
                        ping: true,
                        ping_ms: pingMs,
                        roundTripMs: Date.now() - t0,
                        summary: 'channel healthy: TCP + ping + bpy round-trip all work',
                        protocol: pinfo.id,
                        protocol_label: pinfo.label,
                        protocol_from: pinfo.from,
                        fix: 'nothing to do',
                        region: s.region,
                    },
                    metrics: metricsView(E),
                };
            }
            catch (e) {
                return await failedDoctor(E, e, Date.now() - t0);
            }
        },
        /** 3D viewport region rect / window size / shading mode */
        status() {
            return statusView(E);
        },
        async commands() {
            const out = await addon.send('execute_code', { code: FLAGS_CODE }, ADDON_FLAGS_TIMEOUT_MS);
            const meta = (jsonFromStdout(out) || { flags: {}, scene: null, file: null });
            const flags = (meta.flags || {});
            const available = [];
            const disabled = [];
            for (const name of Object.keys(COMMAND_CATALOG)) {
                const gate = COMMAND_CATALOG[name].gate;
                if (!gate || flags[gate])
                    available.push(name);
                else
                    disabled.push(name);
            }
            // the truth about "the toggle is on but it is still unavailable" (missing key etc.) is answered by each status command
            const integrations = {};
            for (const t of [
                'get_polyhaven_status',
                'get_hyper3d_status',
                'get_sketchfab_status',
                'get_polypizza_status',
                'get_hunyuan3d_status',
            ]) {
                try {
                    const r = await addon.send(t, {}, ADDON_INTEGRATION_TIMEOUT_MS);
                    const rr = (r || null);
                    integrations[t.replace('get_', '').replace('_status', '')] = {
                        enabled: !!(rr && rr.enabled),
                        message: String((rr && rr.message) || '')
                            .split('\n')[0]
                            .slice(0, 160),
                    };
                }
                catch (e) {
                    const timeout = isAddonTimeout(e);
                    const msg = errorMessage(e).slice(0, 120);
                    integrations[t.replace('get_', '').replace('_status', '')] = {
                        enabled: false,
                        timeout: timeout,
                        message: timeout
                            ? 'timeout (' + String(ADDON_INTEGRATION_TIMEOUT_MS) + 'ms): ' + msg
                            : msg,
                    };
                }
            }
            return {
                scene: meta.scene,
                file: meta.file,
                total: available.length,
                available: available,
                disabled: disabled,
                gates: flags,
                integrations: integrations,
            };
        },
        /** inner loop: start (see the contract at the top of runner.py for the spec) */
    };
}
//# sourceMappingURL=doctor.js.map