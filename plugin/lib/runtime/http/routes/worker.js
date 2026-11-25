import { errorMessage, errorField } from '../../core/json.js';
// HTTP route /worker: hot headless session
export function createWorkerRoutes(E) {
    const { engine, isReadOnly, json, leaseGate, readBody, stats, streamJson } = E;
    return {
        async worker(req, res, _url, _p) {
            // hot headless session: start / exec / status / stop / restart (exec streams, so a client timeout cannot cut long code)
            const raw = await readBody(req);
            let payload = {};
            try {
                payload = JSON.parse(raw);
            }
            catch (e) {
                payload = {};
            }
            const op = String(payload.op || 'status');
            // worker is a **separate headless process** and never touches the live GUI scene ⇒ with an explicit isolated:true it does not take the global write lease,
            // otherwise parallel modeling across sessions would 409 each other (a blocker from the C-group research). The same worker is still serialized by itself.
            const gate = payload.isolated || isReadOnly('/worker', op) ? null : leaseGate(payload);
            if (gate) {
                json(res, 409, gate);
                return;
            }
            stats.worker = (stats.worker || 0) + 1;
            await streamJson(res, async () => {
                try {
                    // v0.9.4: everything goes by name (default = 'default', byte-for-byte the same meaning as older calls)
                    if (op === 'start')
                        return {
                            ok: true,
                            op: op,
                            result: await engine.worker.start(payload, payload && payload.name),
                        };
                    if (op === 'stop')
                        return { ok: true, op: op, result: await engine.worker.stop(payload && payload.name) };
                    if (op === 'restart')
                        return {
                            ok: true,
                            op: op,
                            result: await engine.worker.restart(payload && payload.name, payload),
                        };
                    if (op === 'list')
                        return { ok: true, op: op, result: { ok: true, workers: engine.worker.list() } };
                    if (op === 'exec') {
                        const purge = payload.purgePrefix
                            ? String(payload.purgePrefix)
                                .split(',')
                                .map(function (x) {
                                return x.trim();
                            })
                                .filter(Boolean)
                            : null;
                        const r = await engine.worker.exec(String(payload.code || ''), Number(payload.timeoutMs) || 120000, purge, payload && payload.name);
                        // v0.8.4: lift errors/tracebacks to the envelope so the client does not just see unknown
                        return {
                            ok: !!r.ok,
                            op: op,
                            result: r,
                            error: r && r.error ? String(r.error) : null,
                            traceback: r && r.traceback ? String(r.traceback) : null,
                        };
                    }
                    if (op === 'see') {
                        // headless see: temporary camera + offscreen Workbench; returns png_b64 + coverage + ms
                        return {
                            ok: true,
                            op: op,
                            result: await engine.worker.see(payload.spec || payload.see || {}, payload && payload.name),
                        };
                    }
                    if (op === 'watch') {
                        return {
                            ok: true,
                            op: op,
                            result: await engine.worker.watch(payload.spec || payload.watch || {}, payload && payload.name),
                        };
                    }
                    if (op === 'reset') {
                        return { ok: true, op: op, result: await engine.worker.reset(payload && payload.name) };
                    }
                    return {
                        ok: true,
                        op: 'status',
                        result: await engine.worker.status(payload && payload.name),
                    };
                }
                catch (e) {
                    stats.lastError = errorMessage(e);
                    const code = errorField(e, 'code');
                    return {
                        ok: false,
                        op: op,
                        error: stats.lastError,
                        hint: errorField(e, 'hint') || null,
                        // only pass through the code this plugin defines and the tool layer understands: Node internal codes (ERR_INVALID_ARG_TYPE etc.)
                        // must not become model-visible "structured error codes".
                        code: code === 'blender_exe_missing' ? code : null,
                    };
                }
            });
            return;
        },
    };
}
//# sourceMappingURL=worker.js.map
