// Write-permission lease: when several agents / sessions drive one Blender at the same time, this keeps them from stepping on each other.
// Semantics are identical to before the split: no lease held means no blocking; once a lease is explicitly held, another party's write gets 409; TTL expiry invalidates it automatically.
import { CFG } from '../config.js';
import { PLAN_READ_ONLY_OPS } from '../catalog/index.js';
import { stats } from './config.js';
import { errorCode } from '../core/json.js';
const LEASE = {
    holder: null,
    token: null,
    acquiredAt: null,
    expiresAt: null,
    ttlMs: CFG.leaseTtlMs,
    renewals: 0,
    // v2.6 (this round's feedback #7): the **second dimension** of write scope — not just "who is writing" but also "where they write".
    scope: null,
};
/**
 * v0.9.4: whether the lease holder **is still alive** (hit in practice: after a DSH session crashes or is closed, its lease keeps
 * taking effect in memory until the TTL (1 h by default), blocking other sessions' write channel the whole time — while that session no longer exists).
 * The holder convention is `plugin-pid-<pid>` (plugin frontend HOLDER, see src/index.ts), the backend is on the same machine → it can probe liveness directly.
 * Returns true/false; **returns null when it cannot be determined** (treated as "alive", never stealing someone else's lease by mistake).
 */
/**
 * v2.6 (this round's feedback #7): normalize a write-scope declaration into [{kind:'collection'|'prefix', value}].
 *
 * Field case: a subagent only had write permission for a single collection, so the lights (LGT-*) had to be stuffed into the asset collection and then moved one by one by hand during assembly —
 * "write scope" was applied only along the collection axis, disconnected from "object-name prefix", the actual ownership signal.
 * Here both dimensions can be declared at the same time:
 *   collection:COL_Lights   or bare COL_Lights        → collection dimension
 *   prefix:LGT-             or bare LGT-* / LGT-      → object-name prefix dimension
 * The semantics are **declarative** (advisory): it does not block writes, but it shows up in /who, /lease and the 409 receipt, and makes
 * "who should write where" visible at the protocol layer; enforcing ownership is done in one step by the assembly layer's K.route_collections().
 */
function normalizeScope(scope) {
    const raw = Array.isArray(scope)
        ? scope
        : String(scope == null ? '' : scope).split(',');
    const out = [];
    for (const item of raw) {
        const s0 = String(item || '').trim();
        if (!s0)
            continue;
        if (/^collection:/i.test(s0)) {
            out.push({ kind: 'collection', value: s0.slice(11).trim() });
            continue;
        }
        if (/^prefix:/i.test(s0)) {
            out.push({ kind: 'prefix', value: s0.slice(7).trim() });
            continue;
        }
        if (s0.endsWith('*') || s0.includes('-')) {
            out.push({ kind: 'prefix', value: s0.replace(/\*$/, '') });
            continue;
        }
        out.push({ kind: 'collection', value: s0 });
    }
    return out.length ? out : null;
}
function holderAlive(holder) {
    const m = /^plugin-pid-(\d+)$/.exec(String(holder || ''));
    if (!m)
        return null;
    const pid = Number(m[1]);
    if (!Number.isInteger(pid) || pid < 2 || pid > 4194304)
        return null;
    try {
        process.kill(pid, 0);
        return true;
    }
    catch (e) {
        return errorCode(e) === 'EPERM' ? true : false;
    } // EPERM: exists but no permission → alive
}
function leaseView() {
    const now = Date.now();
    const active = !!(LEASE.holder && LEASE.expiresAt && LEASE.expiresAt > now);
    return {
        active: active,
        holder: active ? LEASE.holder : null,
        expiresInMs: active && LEASE.expiresAt ? LEASE.expiresAt - now : 0,
        ttlMs: LEASE.ttlMs,
        since: LEASE.acquiredAt,
        renewals: LEASE.renewals,
        holderAlive: active ? holderAlive(LEASE.holder) : null, // null = cannot determine / not a local-naming-convention name
        scope: active ? LEASE.scope : null, // v2.6: write scope (collection / prefix dimensions)
        staleReclaimed: Number(stats.staleLeasesReclaimed) || 0,
    };
}
/** A dead session's lease → reclaim immediately (returns the reclaimed holder; null when there is nothing to reclaim). Does not change lease semantics, just adds an exit for "the holder no longer exists". */
function releaseStaleLease(why) {
    const v = leaseView();
    if (!v.active || v.holderAlive !== false)
        return null;
    const dead = v.holder;
    LEASE.holder = null;
    LEASE.token = null;
    LEASE.expiresAt = null;
    LEASE.acquiredAt = null;
    LEASE.renewals = 0;
    stats.staleLeasesReclaimed = (Number(stats.staleLeasesReclaimed) || 0) + 1;
    stats.lastLeaseNote = 'reclaimed the write lease of a dead session (holder=' + dead + ', ' + String(why || '') + ')';
    return dead;
}
function leaseAcquire(holder, ttlMs, force, scope) {
    const now = Date.now();
    const h = String(holder || 'anonymous');
    const v = leaseView();
    if (v.active && v.holder !== h && !force) {
        return { denied: true, holder: v.holder, expiresInMs: v.expiresInMs };
    }
    if (!v.active || v.holder !== h) {
        LEASE.token = 'lk_' + Math.random().toString(16).slice(2, 10);
        LEASE.acquiredAt = now;
        LEASE.renewals = 0;
    }
    else {
        LEASE.renewals++;
    }
    LEASE.holder = h;
    if (ttlMs)
        LEASE.ttlMs = Math.max(5000, Math.min(86400000, Number(ttlMs) || LEASE.ttlMs));
    if (scope !== undefined)
        LEASE.scope = normalizeScope(scope); // v2.6: declarative write scope (kept when omitted)
    LEASE.expiresAt = now + LEASE.ttlMs;
    return { granted: true, lease: leaseView() };
}
/** Read-only ops: allowed even when someone else holds the lease (otherwise even "check the current state" would be blocked) */
const READ_ONLY_OPS = {
    '/perf': ['status', 'help'],
    '/loop': ['status', 'board', 'help'],
    '/opt': ['opt_analyze', 'analyze', 'help'],
    '/plan': PLAN_READ_ONLY_OPS,
    '/worker': ['status', 'list', 'see', 'ping'],
    '/txn': ['list', 'marks', 'help', 'edit_status'],
    '/preset': ['list', 'get', 'help'],
    // v0.9.3: wait is only a "blocking read", and kill only affects the job's own child process (never a live scene) —
    // they should not be blocked by another session's write lease (otherwise "I can't even collect my own job").
    '/job': ['status', 'collect', 'list', 'wait', 'kill'],
};
function isReadOnly(path, op) {
    const list = READ_ONLY_OPS[path];
    return !!(list && list.indexOf(String(op)) >= 0);
}
/** Gate applied when the request carries holder/force; returns null = allowed */
function leaseGate(payload) {
    const payloadRec = (payload || {});
    const h = String(payloadRec.holder || payloadRec.lease || '');
    const force = !!payloadRec.force;
    // v0.9.4: reclaim the lease whose "holder process no longer exists" first (otherwise a crashed session blocks the write channel until the TTL ends)
    releaseStaleLease('liveness probe by plugin-pid-<pid> on write request arrival found the process missing');
    const v = leaseView();
    if (v.active && v.holder !== h && !force) {
        return {
            ok: false,
            error: 'leased',
            holder: v.holder,
            expiresInMs: v.expiresInMs,
            holderAlive: v.holderAlive,
            holderScope: v.scope || null,
            hint: 'another session is driving this Blender. Either wait for it (remaining ' +
                Math.round(v.expiresInMs / 1000) +
                's), or add force:true to the body to take over, or blender_viewport op=lease force=true',
        };
    }
    // Extend the lease on the way through: takes over when the holder matches or nobody holds it
    if (!h)
        return null; // old clients that send no holder: allowed as before when no lease is held
    const r = leaseAcquire(h, null, force);
    if ('denied' in r)
        return {
            ok: false,
            error: 'leased',
            holder: r.holder,
            expiresInMs: r.expiresInMs,
            hint: 'the lease is already held',
        };
    return null;
}
export { LEASE, normalizeScope, holderAlive, leaseView, releaseStaleLease, leaseAcquire, READ_ONLY_OPS, isReadOnly, leaseGate, };
//# sourceMappingURL=lease.js.map