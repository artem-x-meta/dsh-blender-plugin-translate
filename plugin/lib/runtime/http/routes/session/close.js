export function createLeaseHandler(E) {
    const { json, leaseAcquire, leaseView, readBody, releaseStaleLease } = E;
    return async function lease(req, res, _url, _p) {
        const raw = await readBody(req);
        let payload;
        try {
            payload = JSON.parse(raw);
        }
        catch (e) {
            payload = {};
        }
        const holder = String(payload.holder || 'anonymous');
        releaseStaleLease('op=lease: liveness probe found no process for the holder'); // v0.9.4
        if (payload.renewOnly) {
            // Heartbeat: renew only when we already hold the lease — no stealing while idle, so sessions cannot deadlock each other
            const v = leaseView();
            if (v.active && v.holder === holder) {
                const rr = leaseAcquire(holder, payload.ttlMs, false, payload.scope);
                json(res, 200, { ok: true, lease: 'lease' in rr ? rr.lease : null, renewed: true });
            }
            else {
                json(res, 200, { ok: true, lease: v, renewed: false });
            }
            return;
        }
        const r = leaseAcquire(holder, payload.ttlMs, !!payload.force, payload.scope);
        if ('denied' in r) {
            const otherScope = leaseView().scope || null;
            json(res, 409, {
                ok: false,
                error: 'leased',
                holder: r.holder,
                expiresInMs: r.expiresInMs,
                holderScope: otherScope,
                hint: 'Another session holds the write lease; force:true to preempt, or retry in ' +
                    Math.round(r.expiresInMs / 1000) +
                    's',
            });
            return;
        }
        json(res, 200, {
            ok: true,
            lease: 'lease' in r ? r.lease : null,
            renewed: !!payload.renewOnly,
        });
        return;
    };
}
export function createReleaseHandler(E) {
    const { LEASE, json, leaseView, readBody } = E;
    return async function release(req, res, _url, _p) {
        const raw = await readBody(req);
        let payload;
        try {
            payload = JSON.parse(raw);
        }
        catch (e) {
            payload = {};
        }
        const want = String(payload.holder || '');
        let released = null;
        if (LEASE.holder && (!want || LEASE.holder === want)) {
            released = LEASE.holder;
            LEASE.holder = null;
            LEASE.token = null;
            LEASE.expiresAt = null;
            LEASE.acquiredAt = null;
        }
        json(res, 200, { ok: true, released: released, lease: leaseView() });
        return;
    };
}
//# sourceMappingURL=close.js.map