import { objArg } from './deps.js';
import { errorMessage, errorField } from '../../core/json.js';
// HTTP route /health: health/status/doctor + removed panel 410
export function createHealthRoutes(E) {
    const { PORT, describeConfig, engine, engineProvenance, json, leaseView, reqCounts, rttView, stats, } = E;
    return {
        async health(req, res, _url, _p) {
            json(res, 200, {
                ok: true,
                stats: stats,
                lease: leaseView(),
                requests: Object.fromEntries(reqCounts),
                // v0.9.4: distribution + the backend's own memory. ⚠ excludes blender.exe RSS —
                // it lives on the Windows side and one sample means launching tasklist (~hundreds of ms), which must not sit on the health probe hot path.
                rtt: rttView(),
                // v0.9.6: loaded-version self-proof (content hash, not mtime) — "should the backend be restarted" is visible at a glance here.
                // local read + hash only (~0.5 ms), no clean-process spawn; a hard cross-check goes through /plan op=catalog args={verify:true}.
                provenance: (() => {
                    try {
                        return engineProvenance({});
                    }
                    catch (e) {
                        return { verdict: 'unknown', error: errorMessage(e) };
                    }
                })(),
                backend: {
                    pid: process.pid,
                    rssMB: Math.round(process.memoryUsage().rss / 1048576),
                    uptimeMs: Date.now() - stats.startedAt,
                },
            });
            return;
        },
        async gone(req, res, _url, _p) {
            json(res, 410, {
                ok: false,
                error: 'gone',
                reason: 'the manual viewport panel (web UI + MJPEG stream + input injection) has been removed',
                hint: 'please close this tab; interact with Blender through the AI channel instead: blender_rt_see / blender_rt_do / blender_rt_watch',
                removedAt: '2026-09-12',
            });
            return;
        },
        async status(req, res, _url, _p) {
            try {
                const s = objArg(await engine.status());
                const m = objArg(engine.metrics());
                json(res, 200, {
                    ok: true,
                    region: s.region,
                    // statusView already folds addon failures into addonError; the route must expose it, otherwise
                    // the presenter's addonError / addon_unresponsive verdict is dead code in production.
                    addonError: s.addonError || null,
                    plugin: s.plugin || null,
                    runs: s.runs || [],
                    jobs: s.jobs || [],
                    ledger: s.ledger || null,
                    stats: stats,
                    metrics: m,
                    diagnosis: m.lastError && m.lastDiagnosis ? m.lastDiagnosis : null,
                });
            }
            catch (e) {
                const m2 = objArg(engine.metrics());
                json(res, 200, {
                    ok: false,
                    error: errorMessage(e),
                    stats: stats,
                    metrics: m2,
                    diagnosis: errorField(e, 'diagnosis') || m2.lastDiagnosis || null,
                });
            }
            return;
        },
        async doctor(req, res, _url, _p) {
            try {
                const d = objArg(await engine.doctor());
                json(res, 200, {
                    ok: true,
                    ...d,
                    config: describeConfig({ httpPort: PORT }),
                    metrics: engine.metrics(),
                    stats: stats,
                });
            }
            catch (e) {
                json(res, 200, { ok: false, error: errorMessage(e), metrics: engine.metrics() });
            }
            return;
        },
    };
}
//# sourceMappingURL=health.js.map