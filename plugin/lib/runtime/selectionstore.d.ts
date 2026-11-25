/**
 * selectionstore.ts: event store for "native Blender selection -> DSH" (v2.3).
 *
 * Why it is needed: since v2.3, "selection" moved from clicking a screenshot in the DSH panel to the **Blender N panel**:
 * the user picks objects in the native Blender selection -> clicks "Send selection to DSH" -> addon `POST /host/selection`
 * -> the Web/TUI client half polls `/host/selection/latest` -> inserts the object names into the **current session draft**
 * (without sending automatically) -> `POST /host/selection/consume` marks it consumed.
 *
 * Single source of truth: `docs/host-integration-contract-v2.3-addendum.md`.
 *
 * Discipline:
 *   - Purely in memory, zero I/O, zero Blender round-trips (the addon POSTs on its own; the polling side never touches Blender).
 *   - The payload is **sanitized** at the entry point (length / count limits) so no arbitrary string can blow up the panel or the receipt.
 *   - `consume` only ever increases; the same selection is inserted at most once (the worst case of a multi-tab race is a duplicate insert, the server never lies).
 */
/** Maximum number of names (keeps the payload bounded even when all 4000 objects are selected). */
export declare const MAX_SELECTION_NAMES = 200;
/** Maximum number of object details (the part beyond names). */
export declare const MAX_SELECTION_OBJECTS = 50;
/** Maximum number of "which collections the selection touches" summary entries. */
export declare const MAX_SELECTION_COLLECTIONS = 50;
/** Limit for a single string. */
export declare const MAX_STRING_CHARS = 200;
/** Limit on sub-element (edit mode) indices / bones. */
export declare const MAX_SUB_INDICES = 2000;
export declare const MAX_SUB_BONES = 500;
export declare const MAX_SUB_POINTS = 2000;
/** An unconsumed selection older than this only triggers a hint, it never blocks consumption. */
export declare const STALE_MS: number;
export type SelectionObject = {
    name: string;
    type: string;
    dimensions_mm?: Array<number | null>;
};
export type SelectionCollection = {
    name: string;
    count: number;
};
export type SelectionSub = {
    type: string;
    object: string;
    mode: string | null;
    counts: Record<string, number>;
    truncated: boolean;
    note?: string;
    select_mode?: {
        vertex: boolean;
        edge: boolean;
        face: boolean;
    };
    indices?: Record<string, number[]>;
    bones?: string[];
    points?: Array<[number, number]>;
};
export type SanitizedSelection = {
    kind: 'objects' | 'collection';
    collection: string | null;
    count: number;
    names: string[];
    truncated: boolean;
    active: string | null;
    mode: string | null;
    objects: SelectionObject[];
    collections: SelectionCollection[];
    sub: SelectionSub | null;
};
export type SanitizedActivity = {
    state: string | null;
    human_active: boolean;
    agent_active: boolean;
};
export type SanitizedPayload = {
    v: 1;
    source: string;
    sent_at: number | null;
    selection: SanitizedSelection;
    scene: {
        name: string | null;
        file: string | null;
    };
    activity: SanitizedActivity | null;
};
export type LastConsume = {
    seq: number;
    ok: boolean | null;
    how: string | null;
    reason: string | null;
    at: number;
};
export type PutResult = {
    ok: true;
    seq: number;
    received_at: number;
} | {
    ok: false;
    error: string;
};
export type ConsumeResult = {
    ok: boolean;
    consumed_seq: number;
    error?: string;
};
export type SelectionSnapshot = {
    ok: true;
    seq: number;
    consumed_seq: number;
    unconsumed: boolean;
    received_at: number | null;
    stale_ms: number | null;
    selection: SanitizedSelection | null;
    activity: SanitizedActivity | null;
    scene: SanitizedPayload['scene'] | null;
    last_consume: LastConsume | null;
};
export type SelectionStore = {
    put: (payload: unknown) => PutResult;
    snapshot: () => SelectionSnapshot;
    consume: (value: unknown, meta?: unknown) => ConsumeResult;
    currentSeq: () => number;
    consumedSeq: () => number;
};
/**
 * Sanitize the v2.4 sub-element selection (edit-mode vertices/edges/faces / bones / curve points / lattice points).
 * Arrays are kept but clamped; when the type is not whitelisted only note is kept.
 * @param sub the addon's selection.sub
 * @returns the normalized sub-selection; null when the structure is invalid
 */
export declare function sanitizeSubSelection(sub: unknown): SelectionSub | null;
/**
 * Sanitize the payload pushed by the addon. Field names are preserved (client text generation depends on them); anything beyond the limits is dropped.
 * @param payload the addon's JSON body
 * @returns a normalized, storable payload
 */
export declare function sanitizeSelectionPayload(payload: unknown): SanitizedPayload;
/**
 * Create a selection event store (purely in memory; `now` is injectable for unit tests).
 * @param now clock (milliseconds)
 */
export declare function createSelectionStore(now?: () => number): SelectionStore;
