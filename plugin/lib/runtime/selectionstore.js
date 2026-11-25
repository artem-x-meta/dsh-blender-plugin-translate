/**
 * selectionstore.ts —— the "Blender native selection → DSH" event store (v2.3).
 *
 * Why it exists: from v2.3 on, "selection" moved from clicking a DSH panel screenshot to the **Blender N panel**:
 * the user picks objects in Blender's native selection → clicks "send selection to DSH" → the addon `POST /host/selection`
 * → the Web/TUI client half polls `/host/selection/latest` → inserts the object names into the **current session draft**
 * (never sends automatically) → `POST /host/selection/consume` marks it consumed.
 *
 * Single source of truth: `docs/host-integration-contract-v2.3-addendum.md`.
 *
 * Discipline:
 *   · Pure memory, zero I/O, zero Blender round-trips (the addon POSTs to us; the polling side never touches Blender).
 *   · The payload is **sanitized** at the entry (length / entry-count caps), so no arbitrary string can blow up the panel or the receipt.
 *   · `consume` only grows; the same selection is inserted at most once (the worst case under multi-tab races is a duplicate insertion; the server does not lie).
 */
/** Name-count cap (so the payload cannot run away even when all 4000 objects are selected). */
export const MAX_SELECTION_NAMES = 200;
/** Object-detail count cap (the list alongside the names). */
export const MAX_SELECTION_OBJECTS = 50;
/** Cap on the "which collections the selection touches" summary entries. */
export const MAX_SELECTION_COLLECTIONS = 50;
/** Cap for a single string. */
export const MAX_STRING_CHARS = 200;
/** Cap on sub-element (edit mode) indices/bones. */
export const MAX_SUB_INDICES = 2000;
export const MAX_SUB_BONES = 500;
export const MAX_SUB_POINTS = 2000;
/** Sub-element type whitelist (other types keep only the note; their semantics are not guessed). */
const SUB_TYPES = new Set(['MESH', 'ARMATURE', 'CURVE', 'LATTICE', 'OTHER']);
/** An unconsumed selection older than this only raises a hint; it does not block consumption. */
export const STALE_MS = 10 * 60 * 1000;
/** Object boundary parsing: anything that is not a plain object counts as an empty object (equivalent to reading `src.x` in the old JS). */
function asRec(value) {
    return value !== null && typeof value === 'object' && !Array.isArray(value)
        ? value
        : {};
}
function cleanString(value, max = MAX_STRING_CHARS) {
    if (value === null || value === undefined)
        return null;
    const text = String(value);
    return text.length > max ? text.slice(0, max) : text;
}
function cleanNames(list) {
    if (!Array.isArray(list))
        return [];
    const out = [];
    for (const item of list) {
        const name = cleanString(item);
        if (name === null || name.length === 0)
            continue;
        out.push(name);
        if (out.length >= MAX_SELECTION_NAMES)
            break;
    }
    return out;
}
function cleanIntList(list, max) {
    if (!Array.isArray(list))
        return [];
    const out = [];
    for (const item of list) {
        const n = Number(item);
        if (!Number.isFinite(n) || n < 0 || !Number.isInteger(n))
            continue;
        out.push(Math.trunc(n));
        if (out.length >= max)
            break;
    }
    return out;
}
function cleanCounts(value) {
    const src = asRec(value);
    const out = {};
    for (const key of ['vertices', 'edges', 'faces', 'bones', 'points']) {
        const n = Number(src[key]);
        if (Number.isFinite(n) && n >= 0)
            out[key] = Math.trunc(n);
    }
    return out;
}
/**
 * Sanitize a v2.4 sub-element selection (edit-mode vertices/edges/faces / bones / curve points / lattice points).
 * Arrays are kept but capped; a type outside the whitelist keeps only the note.
 * @param sub the addon's selection.sub
 * @returns the normalized sub-selection; null when the structure is invalid
 */
export function sanitizeSubSelection(sub) {
    if (!sub || typeof sub !== 'object' || Array.isArray(sub))
        return null;
    const src = sub;
    const type = typeof src.type === 'string' && SUB_TYPES.has(src.type) ? src.type : 'OTHER';
    const object = cleanString(src.object);
    if (!object)
        return null;
    const out = {
        type: type,
        object: object,
        mode: cleanString(src.mode, 40) || null,
        counts: cleanCounts(src.counts),
        truncated: src.truncated === true,
    };
    const note = cleanString(src.note, 200);
    if (note)
        out.note = note;
    const selectMode = asRec(src.select_mode);
    if (src.select_mode && typeof src.select_mode === 'object' && !Array.isArray(src.select_mode)) {
        out.select_mode = {
            vertex: selectMode.vertex === true,
            edge: selectMode.edge === true,
            face: selectMode.face === true,
        };
    }
    const indices = asRec(src.indices);
    if (src.indices && typeof src.indices === 'object' && !Array.isArray(src.indices)) {
        const idx = {};
        for (const key of ['vertices', 'edges', 'faces']) {
            const raw = indices[key];
            if (!Array.isArray(raw))
                continue;
            idx[key] = cleanIntList(raw, MAX_SUB_INDICES);
            if (raw.length > idx[key].length)
                out.truncated = true;
        }
        out.indices = idx;
    }
    if (Array.isArray(src.bones)) {
        const bones = [];
        for (const item of src.bones) {
            const name = cleanString(item);
            if (!name)
                continue;
            bones.push(name);
            if (bones.length >= MAX_SUB_BONES) {
                out.truncated = true;
                break;
            }
        }
        out.bones = bones;
        if (src.bones.length > bones.length)
            out.truncated = true;
    }
    if (Array.isArray(src.points)) {
        const points = [];
        for (const item of src.points) {
            if (!Array.isArray(item) || item.length < 2)
                continue;
            const a = Number(item[0]);
            const b = Number(item[1]);
            if (!Number.isFinite(a) || !Number.isFinite(b))
                continue;
            points.push([Math.trunc(a), Math.trunc(b)]);
            if (points.length >= MAX_SUB_POINTS) {
                out.truncated = true;
                break;
            }
        }
        out.points = points;
        if (src.points.length > points.length)
            out.truncated = true;
    }
    return out;
}
/**
 * Sanitize the payload pushed by the addon. Field names are preserved (the client text generation depends on them); anything extra is dropped.
 * @param payload the addon's JSON body
 * @returns a normalized, storable payload
 */
export function sanitizeSelectionPayload(payload) {
    const src = asRec(payload);
    const sel = asRec(src.selection);
    const rawNameCount = Array.isArray(sel.names) ? sel.names.length : 0;
    const names = cleanNames(sel.names);
    const rawCount = Number(sel.count);
    const count = Number.isFinite(rawCount) ? Math.max(0, Math.trunc(rawCount)) : rawNameCount;
    const objects = [];
    if (Array.isArray(sel.objects)) {
        for (const item of sel.objects) {
            if (objects.length >= MAX_SELECTION_OBJECTS)
                break;
            if (!item || typeof item !== 'object')
                continue;
            const itemRec = item;
            const name = cleanString(itemRec.name);
            if (name === null || name.length === 0)
                continue;
            const entry = {
                name: name,
                type: cleanString(itemRec.type, 32) || 'UNKNOWN',
            };
            if (Array.isArray(itemRec.dimensions_mm) && itemRec.dimensions_mm.length === 3) {
                const dims = itemRec.dimensions_mm.map((v) => Number.isFinite(Number(v)) ? Math.round(Number(v) * 10) / 10 : null);
                if (dims.every((v) => v !== null))
                    entry.dimensions_mm = dims;
            }
            objects.push(entry);
        }
    }
    const scene = asRec(src.scene);
    const activityRec = src.activity && typeof src.activity === 'object' && !Array.isArray(src.activity)
        ? src.activity
        : null;
    // v2.3: kind=objects (send the selected objects) | collection (send a whole collection, for large assemblies)
    const kind = sel.kind === 'collection' ? 'collection' : 'objects';
    const collections = [];
    if (Array.isArray(sel.collections)) {
        for (const item of sel.collections) {
            if (collections.length >= MAX_SELECTION_COLLECTIONS)
                break;
            if (!item || typeof item !== 'object')
                continue;
            const itemRec = item;
            const name = cleanString(itemRec.name);
            if (name === null || name.length === 0)
                continue;
            const memberCount = Number(itemRec.count);
            collections.push({
                name: name,
                count: Number.isFinite(memberCount) ? Math.max(0, Math.trunc(memberCount)) : 0,
            });
        }
    }
    return {
        v: 1,
        source: cleanString(src.source, 40) || 'unknown',
        sent_at: Number.isFinite(Number(src.sent_at)) ? Math.trunc(Number(src.sent_at)) : null,
        selection: {
            kind: kind,
            collection: cleanString(sel.collection),
            count: count,
            names: names,
            truncated: sel.truncated === true || count > names.length || rawNameCount > names.length,
            active: cleanString(sel.active),
            mode: cleanString(sel.mode, 40),
            objects: objects,
            collections: collections,
            sub: sanitizeSubSelection(sel.sub),
        },
        scene: { name: cleanString(scene.name), file: cleanString(scene.file) },
        activity: activityRec === null
            ? null
            : {
                state: cleanString(activityRec.state, 20),
                human_active: activityRec.human_active === true,
                agent_active: activityRec.agent_active === true,
            },
    };
}
/**
 * Create a selection event store (pure memory; `now` is injectable for unit tests).
 * @param now the clock (milliseconds)
 */
export function createSelectionStore(now = () => Date.now()) {
    let seq = 0;
    let latest = null;
    let consumedSeq = 0;
    let lastConsume = null;
    /**
     * Take one selection pushed by the addon.
     * @param payload the raw JSON body
     */
    function put(payload) {
        if (payload === null || typeof payload !== 'object' || Array.isArray(payload)) {
            return { ok: false, error: 'invalid_payload' };
        }
        const sanitized = sanitizeSelectionPayload(payload);
        // An empty selection is accepted too (the user may clear and then send; the client decides whether to insert text), but it must be "one object".
        seq += 1;
        latest = { seq: seq, received_at: now(), payload: sanitized };
        return { ok: true, seq: latest.seq, received_at: latest.received_at };
    }
    /**
     * Current state: the payload is present only while unconsumed (so a panel reload does not re-insert an old selection).
     */
    function snapshot() {
        const unconsumed = latest !== null && latest.seq > consumedSeq;
        const receivedAt = latest === null ? null : latest.received_at;
        return {
            ok: true,
            seq: previousSeq(),
            consumed_seq: consumedSeq,
            unconsumed: unconsumed,
            received_at: receivedAt,
            stale_ms: receivedAt === null ? null : Math.max(0, now() - receivedAt),
            selection: unconsumed && latest !== null ? latest.payload.selection : null,
            activity: unconsumed && latest !== null ? latest.payload.activity : null,
            scene: unconsumed && latest !== null ? latest.payload.scene : null,
            last_consume: lastConsume,
        };
    }
    /**
     * Mark "already inserted into the draft". Only integers in 1..current seq are accepted; an invalid value returns the current state verbatim (idempotent).
     * `meta` is the client's insertion result (`{ok, how, reason}`), used for diagnostics only ("the button was clicked but the draft stayed empty");
     * omitting it is also legal (older clients / curl).
     * @param value the seq echoed back by the client
     * @param meta the client insertion result
     */
    function consume(value, meta) {
        const target = Number(value);
        if (!Number.isInteger(target) || target < 1 || target > seq) {
            return { ok: false, consumed_seq: consumedSeq, error: 'invalid_seq' };
        }
        if (target > consumedSeq)
            consumedSeq = target;
        const m = meta !== null && typeof meta === 'object' && !Array.isArray(meta)
            ? meta
            : {};
        lastConsume = {
            seq: target,
            ok: typeof m.ok === 'boolean' ? m.ok : null,
            how: cleanString(m.how, 40),
            reason: cleanString(m.reason, 200),
            at: now(),
        };
        return { ok: true, consumed_seq: consumedSeq };
    }
    function previousSeq() {
        return latest === null ? 0 : latest.seq;
    }
    return {
        put: put,
        snapshot: snapshot,
        consume: consume,
        currentSeq: previousSeq,
        consumedSeq: () => consumedSeq,
    };
}
//# sourceMappingURL=selectionstore.js.map
