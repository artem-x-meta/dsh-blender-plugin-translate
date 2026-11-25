// engine lifecycle: metrics / addon.send wrapper (split out of engine.ts, behaviour frozen)
import { diagnose } from '../../transport/probes.js';
import { errorMessage } from '../json.js';
export const MAIN_THREAD_CMDS = new Set([
    'execute_code',
    'get_scene_info',
    'get_object_info',
    'get_viewport_screenshot',
    'export_scene',
    'describe_node_type',
    'bpy_api_lookup',
    'drain_human_activity',
    'get_activity_state',
    'get_selection',
    'send_selection_to_dsh',
]);
export function createEngineMetrics() {
    const metrics = {
        calls: 0,
        errors: 0,
        timeouts: 0,
        inflight: 0,
        lastCmd: null,
        lastCmdAt: null,
        lastOkAt: null,
        lastError: null,
        lastDiagnosis: null,
        views: 0,
        headlessRuns: 0,
        lastHeadlessMs: null,
        workerStarts: 0,
        workerExecs: 0,
        lastErrorAt: null,
        aiPausedAt: null,
    };
    return metrics;
}
function renderBusyError(g, metrics) {
    metrics.errors++;
    const msg = 'BUSY_RENDER: Blender is rendering (' +
        String(Math.round((g.ageMs || 0) / 1000)) +
        ' s, scene=' +
        String((g.info && g.info.scene) || '?') +
        ') — main-thread commands will queue until timeout; ' +
        'wait for it with blender_rt_plan(op="render_wait"), or send once the render finishes (for long renders start with blender_rt_job)';
    metrics.lastError = msg;
    const e = new Error(msg);
    e.renderBusy = true;
    e.renderGuard = g;
    return e;
}
export function installAddonSend(addon, metrics, readRenderFlag) {
    const rawSend = addon.send.bind(addon);
    addon.send = async (type, params = {}, timeoutMs) => {
        if (MAIN_THREAD_CMDS.has(String(type))) {
            const g = readRenderFlag();
            if (g.present && !g.stale)
                throw renderBusyError(g, metrics);
        }
        metrics.calls++;
        metrics.inflight++;
        metrics.lastCmd = type;
        metrics.lastCmdAt = Date.now();
        try {
            const r = await rawSend(type, params, timeoutMs);
            metrics.lastOkAt = Date.now();
            metrics.lastDiagnosis = null;
            metrics.aiPausedAt = null;
            return r;
        }
        catch (e) {
            const msg = errorMessage(e);
            metrics.errors++;
            metrics.lastError = msg;
            metrics.lastErrorAt = Date.now();
            if (/AI_PAUSED|paused/i.test(msg))
                metrics.aiPausedAt = metrics.lastErrorAt;
            const transport = /timeout|closed|ECONN|ECONNRESET|socket/i.test(msg);
            if (transport)
                metrics.timeouts++;
            const err = e;
            if (transport) {
                try {
                    err.diagnosis = await diagnose();
                    metrics.lastDiagnosis = err.diagnosis;
                }
                catch (x) {
                    /* a failing diagnosis must not mask the original error */
                }
            }
            else {
                err.kind = 'execution';
            }
            throw err;
        }
        finally {
            metrics.inflight--;
        }
    };
}
//# sourceMappingURL=lifecycle.js.map