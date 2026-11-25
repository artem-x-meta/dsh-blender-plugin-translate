import { errorCode, errorMessage, errorField } from '../../core/json.js';
// HTTP route /job: job layer
export function createJobRoutes(E) {
    const { engine, isReadOnly, json, leaseGate, pushRtt, readBody, stats, streamJson } = E;
    return {
        async job(req, res, _url, _p) {
            // job layer: start / status / collect / kill / list (long tasks move to the background — a render running all night)
            const raw = await readBody(req);
            let payload = {};
            try {
                payload = JSON.parse(raw);
            }
            catch (e) {
                payload = {};
            }
            const op = String(payload.op || 'list');
            const gate = isReadOnly('/job', op) ? null : leaseGate(payload);
            if (gate) {
                json(res, 409, gate);
                return;
            }
            stats.job = (stats.job || 0) + 1;
            // v0.9.3: op=wait blocks until the terminal state/timeout → stream the receipt (one heartbeat line every 15 s, the client is never judged as timed out)
            if (op === 'wait') {
                await streamJson(res, async () => {
                    try {
                        const j = await engine.job.wait(payload.id, Number(payload.timeoutMs) || Number(payload.timeout_ms) || 120000);
                        return { ok: true, op: op, job: j };
                    }
                    catch (e) {
                        stats.lastError = errorMessage(e);
                        return {
                            ok: false,
                            op: op,
                            error: stats.lastError,
                            code: errorField(e, 'code') || errorCode(e) || null,
                        };
                    }
                });
                return;
            }
            const t0j = Date.now(); // v0.9.4: job route latency feeds the rtt distribution (the "occasionally hangs" kind has to show a trend)
            try {
                if (op === 'start') {
                    json(res, 200, { ok: true, op: op, job: engine.job.start(payload) });
                    return;
                }
                if (op === 'kill') {
                    json(res, 200, { ok: true, op: op, job: engine.job.kill(payload.id) });
                    return;
                }
                if (op === 'collect') {
                    json(res, 200, {
                        ok: true,
                        op: op,
                        job: engine.job.collect(payload.id, Number(payload.tail) || 4000),
                    });
                    return;
                }
                if (op === 'status') {
                    json(res, 200, { ok: true, op: op, job: engine.job.status(payload.id) });
                    return;
                }
                json(res, 200, { ok: true, op: 'list', jobs: engine.job.list() });
            }
            catch (e) {
                stats.lastError = errorMessage(e);
                // expose structured codes such as blender_exe_missing so the tool layer can give configuration guidance instead of a generic backend_error.
                json(res, 200, {
                    ok: false,
                    op: op,
                    error: stats.lastError,
                    code: errorField(e, 'code') || errorCode(e) || null,
                });
            }
            finally {
                pushRtt('job', Date.now() - t0j);
            }
            return;
        },
    };
}
//# sourceMappingURL=job.js.map