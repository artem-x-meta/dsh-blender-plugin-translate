// /host status view + @ mention data source (split out of http/host.ts)
import { stats } from '../config.js';
import { leaseView } from '../lease.js';
import { clampItemsLimit } from '../response.js';
/**
 * v2.6.1: response body of GET /host/state (pure memory, zero Blender round-trips; any part that cannot be read gets a conservative default, nothing throws).
 * "AI paused" can only be known after the addon rejects a command (the backend does not poll Blender for it), and one success clears it.
 */
export function hostStateView(E) {
    const { engine } = E;
    const now = Date.now();
    const age = (t) => (typeof t === 'number' && t ? now - t : null);
    let m;
    try {
        m = (engine.metrics() || {});
    }
    catch (e) {
        m = {};
    }
    let render = {
        busy: false,
        ageMs: null,
        scene: null,
    };
    try {
        const g = engine.renderFlag();
        if (g && g.present)
            render = {
                busy: !g.stale,
                ageMs: g.ageMs,
                scene: g.info?.['scene'] || null,
            };
    }
    catch (e) {
        /* cannot read the flag = not rendering */
    }
    let running;
    try {
        running = (engine.job.list() || []).filter((j) => j && j.status === 'running').length;
    }
    catch (e) {
        running = 0;
    }
    return {
        ok: true,
        channel: {
            lastOkAgeMs: age(m.lastOkAt),
            lastCmd: m.lastCmd || null,
            lastCmdAgeMs: age(m.lastCmdAt),
            inflight: Number(m.inflight) || 0,
            lastError: m.lastError ? String(m.lastError).slice(0, 200) : null,
            lastErrorAgeMs: age(m.lastErrorAt),
            diagnosis: m.lastDiagnosis && m.lastDiagnosis.kind
                ? String(m.lastDiagnosis.kind)
                : null,
            aiPaused: !!m.aiPausedAt,
        },
        lease: leaseView(),
        render: render,
        jobs: { running: running },
        backend: { pid: process.pid, uptimeMs: now - stats.startedAt },
    };
}
/** contract §1.6 @ mention data source (GET /host/scene-items) */
export async function handleSceneItems(E, url, res, origin) {
    const { engine, hostJson, hostErrText } = E;
    let out;
    try {
        out = (await engine.hostSceneItems({
            q: url.searchParams.get('q') || '',
            limit: clampItemsLimit(url.searchParams.get('limit')),
        }));
    }
    catch (e) {
        stats.lastError = hostErrText(e);
        hostJson(res, 502, { ok: false, error: hostErrText(e) }, origin);
        return;
    }
    hostJson(res, 200, {
        ok: true,
        objects: out.objects || [],
        materials: out.materials || [],
        collections: out.collections || [],
    }, origin);
}
//# sourceMappingURL=scene-items.js.map
