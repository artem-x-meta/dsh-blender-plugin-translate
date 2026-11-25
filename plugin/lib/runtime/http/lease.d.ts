/**
 * Write-permission lease: when several agents / sessions drive one Blender at once, this keeps them from stepping on each other.
 * Semantics: holding no lease blocks nothing (a single agent on one machine never notices); once someone explicitly takes the lease, other sessions' writes are rejected with 409.
 * It expires on its own (TTL, 10 min by default; every write operation renews it).
 */
export interface ScopeEntry {
    kind: 'collection' | 'prefix';
    value: string;
}
export interface LeaseRec {
    holder: string | null;
    token: string | null;
    acquiredAt: number | null;
    expiresAt: number | null;
    ttlMs: number;
    renewals: number;
    scope: ScopeEntry[] | null;
}
export interface LeaseView {
    active: boolean;
    holder: string | null;
    expiresInMs: number;
    ttlMs: number;
    since: number | null;
    renewals: number;
    holderAlive: boolean | null;
    scope: ScopeEntry[] | null;
    staleReclaimed: number;
}
declare const LEASE: LeaseRec;
/**
 * v0.9.4: whether the lease holder **is still alive** (seen in practice: after a DSH session crashed / was closed, its lease kept
 * applying in memory until the TTL (1 h by default) and blocked other sessions' whole write channel — while that session was long gone).
 * The holder convention is `plugin-pid-<pid>` (the plugin-side HOLDER, see src/index.ts); the backend runs on the same machine → it can probe liveness directly.
 * Returns true/false; **returns null when it cannot tell** (treat that as "alive", never steal someone else's lease by mistake).
 */
/**
 * v2.6 (feedback #7 this round): normalize write-scope declarations into [{kind:'collection'|'prefix', value}].
 *
 * Field case: a subagent had write permission for a single collection only, so lights (LGT-*) were forced into the asset collection and then moved
 * one by one by hand at assembly time — "write scope" was cut along collections only, out of sync with "object-name prefix", the real ownership signal.
 * Both dimensions may be declared at the same time here:
 *   collection:COL_Lights   or bare COL_Lights        → collection dimension
 *   prefix:LGT-             or bare LGT-* / LGT-      → object-name prefix dimension
 * Semantics are **declarative** (advisory): they do not block writes, but they appear in /who, /lease and 409 receipts,
 * making "who should write where" visible at the protocol level; ownership is enforced once by the assembly layer's K.route_collections().
 */
declare function normalizeScope(scope: unknown): ScopeEntry[] | null;
declare function holderAlive(holder: unknown): boolean | null;
declare function leaseView(): LeaseView;
/** Lease of a dead session → reclaim at once (returns the reclaimed holder; null when there is nothing to reclaim). Lease semantics unchanged; it only adds an exit for "the holder does not exist". */
declare function releaseStaleLease(why: unknown): string | null;
declare function leaseAcquire(holder: unknown, ttlMs: unknown, force?: unknown, scope?: unknown): {
    denied: true;
    granted?: false;
    holder: string | null;
    expiresInMs: number;
} | {
    granted: true;
    lease: LeaseView;
};
/** Read-only ops: allowed even when someone else holds the lease (otherwise even "look at the current state" would be blocked) */
declare const READ_ONLY_OPS: Record<string, string[]>;
declare function isReadOnly(path: string, op: unknown): boolean;
/** Gate applied when the request carries holder/force; null = allowed */
declare function leaseGate(payload?: Record<string, unknown> | null): Record<string, unknown> | null;
export { LEASE, normalizeScope, holderAlive, leaseView, releaseStaleLease, leaseAcquire, READ_ONLY_OPS, isReadOnly, leaseGate, };
