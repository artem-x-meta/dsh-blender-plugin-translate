import { asArray, asRecord, isRecord, text } from '../contracts/dynamic.js';
import { CHIP_KEY, SELECTION_DRAFT_NAME_LIMIT, SUB_DRAFT_INDEX_LIMIT } from './constants.js';
import { getJson, postJson } from './http.js';
import { bridge } from './state.js';
/** v2.4 sub-element selection (mesh vertices/edges/faces, bones, curve/lattice control points) → text. Word-for-word mirror of subSelectionText in lib/client.js. */
export function subSelectionText(sel) {
    const s = asRecord(sel);
    const sub = isRecord(s.sub) ? s.sub : null;
    if (!sub)
        return null;
    const type = text(sub.type);
    const obj = text(sub.object);
    const counts = asRecord(sub.counts);
    const more = sub.truncated === true;
    if (type === 'MESH') {
        const v = Number(counts.vertices || 0), e = Number(counts.edges || 0), f = Number(counts.faces || 0);
        let txt = 'Blender edit mode (mesh) "' + obj + '": selected ' + v + ' vertices / ' + e + ' edges / ' + f + ' faces.';
        const idx = asRecord(sub.indices);
        const labels = {
            vertices: 'vertex indices',
            edges: 'edge indices',
            faces: 'face indices',
        };
        const parts = [];
        for (const k of Object.keys(labels)) {
            const arr = asArray(idx[k]);
            if (!arr.length)
                continue;
            let shown = arr.slice(0, SUB_DRAFT_INDEX_LIMIT).join(',');
            if (arr.length > SUB_DRAFT_INDEX_LIMIT || more)
                shown += '…';
            parts.push(labels[k] + ': ' + shown);
        }
        if (parts.length)
            txt += parts.join('; ') + '.';
        return txt + 'Use bpy / BMesh to modify these elements precisely; when the user says "these vertices/edges/faces" they mean these.';
    }
    if (type === 'ARMATURE') {
        const bones = asArray(sub.bones);
        const boneCount = Number(counts.bones || bones.length);
        let head = 'Blender armature "' +
            obj +
            '" ' +
            (text(sub.mode) === 'POSE' ? 'pose mode' : 'edit mode') +
            ': selected ' +
            boneCount +
            ' bones';
        if (bones.length) {
            head += ': ' + bones.slice(0, SUB_DRAFT_INDEX_LIMIT).map(String).join(', ');
            if (bones.length > SUB_DRAFT_INDEX_LIMIT || more)
                head += '…';
        }
        return (head +
            ". Use bpy.data.objects['" +
            obj +
            '\'].pose.bones[...] to address them precisely; when the user says "these bones" they mean these.');
    }
    if (type === 'CURVE' || type === 'LATTICE') {
        const pts = asArray(sub.points);
        const pcount = Number(counts.points || pts.length);
        const label = type === 'CURVE' ? 'curve/surface control points' : 'lattice control points';
        let txt = 'Blender ' + label + ' "' + obj + '": ' + text(sub.mode) + ', ' + pcount + ' selected';
        if (pts.length) {
            const sample = pts.slice(0, SUB_DRAFT_INDEX_LIMIT).map((p) => {
                const pair = asArray(p);
                return pair.length >= 2 ? String(pair[0]) + ':' + String(pair[1]) : String(p);
            });
            txt += ': ' + sample.join(', ');
            if (pts.length > SUB_DRAFT_INDEX_LIMIT || more)
                txt += '…';
        }
        return txt + '. Address the elements by (spline_index, point_index); when the user says "these points" they mean these.';
    }
    if (type === 'OTHER') {
        return ('Blender ' +
            (text(sub.mode) || 'edit mode') +
            ' (object "' +
            obj +
            '"): ' +
            (text(sub.note) || 'sub-elements are not expanded yet; use Python to read the current selection') +
            '.');
    }
    return null;
}
/** selection payload → the text handed to the model (empty selection returns null). Word-for-word mirror of selectionMessageText in lib/client.js. */
export function selectionMessageText(payload) {
    const sel = asRecord(asRecord(payload).selection);
    if (!isRecord(payload) || !Object.keys(sel).length)
        return null;
    const kind = sel.kind === 'collection' ? 'collection' : 'objects';
    const names = asArray(sel.names).filter((n) => typeof n === 'string' && n.length > 0);
    const count = typeof sel.count === 'number' ? sel.count : names.length;
    if (kind === 'collection') {
        const coll = typeof sel.collection === 'string' && sel.collection.length > 0 ? sel.collection : null;
        if (!coll)
            return null;
        const shown = names.slice(0, SELECTION_DRAFT_NAME_LIMIT);
        let head = 'Blender collection: ' + coll + ' (' + count + ' items';
        if (shown.length) {
            head += '; first ' + shown.length + ': ' + shown.join(', ');
            if (sel.truncated || count > shown.length || names.length > shown.length)
                head += '…';
        }
        return (head +
            "). Get the members with bpy.data.collections['" +
            coll +
            '\'].objects; when the user says "this collection/this batch" they mean it.');
    }
    const subText = subSelectionText(sel);
    if (subText)
        return subText;
    if (!names.length)
        return null;
    const drawn = names.slice(0, SELECTION_DRAFT_NAME_LIMIT);
    let out = 'Blender selection: ' + drawn.join(', ');
    if (sel.truncated || count > drawn.length || names.length > drawn.length)
        out += ' (' + count + ' items total, only the first ' + drawn.length + ' listed)';
    out += '.';
    if (sel.active)
        out += 'Active object: ' + text(sel.active) + '.';
    if (sel.mode)
        out += 'Mode: ' + text(sel.mode) + '.';
    const collections = asArray(sel.collections);
    if (collections.length && count > 1) {
        const summary = collections.slice(0, 4).map((c) => {
            const rec = asRecord(c);
            return text(rec.name) + '(' + Number(rec.count || 0) + ')';
        });
        out += 'Collections involved: ' + summary.join(', ') + '.';
    }
    return out + 'When the user says "this/these" they mean them; the object names can be used directly in bpy.data.objects.';
}
/** chip title (one line, ≤ 80 cells): resending the same key **replaces** the previous entry, so the title only states "what it is and how many" */
export function selectionChipTitle(sel) {
    const s = asRecord(sel);
    const clip = (v, n = 24) => {
        const t = String(v == null ? '' : v);
        return t.length > n ? t.slice(0, n - 1) + '…' : t;
    };
    if (s.kind === 'collection')
        return 'Blender collection · ' + clip(s.collection) + ' (' + String(Number(s.count) || 0) + ' items)';
    const sub = asRecord(s.sub);
    if (sub.type)
        return 'Blender sub-elements · ' + clip(sub.object);
    const names = asArray(s.names);
    const count = typeof s.count === 'number' ? s.count : names.length;
    return count === 1 && names[0]
        ? 'Blender selection · ' + clip(names[0])
        : 'Blender selection · ' + String(count) + ' items';
}
/**
 * One poll (exported for self-checks): take the unconsumed selection → attach a chip → consume.
 * Same CAS semantics as the Web bridge: only success consumes with ok:true; if it cannot be attached we do not consume and retry on the next tick, and the 3rd failure
 * consumes with ok:false, reason; an empty selection consumes with ok:false straight away (there is nothing to retry).
 */
export async function selectionTick(deps) {
    const { port, chips, notify, state } = deps;
    const body = await getJson(port, '/host/selection/latest');
    if (!body || body.ok !== true || body.unconsumed !== true || !body.selection)
        return;
    const seq = Number(body.seq) || 0;
    if (seq <= state.lastSeq)
        return;
    const selection = body.selection;
    const txt = selectionMessageText({ selection: selection });
    const done = async (ok, extra) => {
        state.lastSeq = seq;
        state.fails = 0;
        bridge.lastSeq = seq;
        bridge.lastOk = ok;
        bridge.lastReason = ok ? null : text(extra.reason);
        bridge.lastAt = Date.now();
        await postJson(port, '/host/selection/consume', Object.assign({ seq: seq, ok: ok }, extra));
    };
    if (!txt) {
        await done(false, { reason: 'no object names to insert (empty selection)' });
        return;
    }
    let staged;
    try {
        staged =
            chips.attachContext({
                key: CHIP_KEY,
                title: selectionChipTitle(selection),
                content: txt,
            }) === true;
    }
    catch {
        staged = false;
    }
    if (staged) {
        await done(true, { how: 'tui-chip' });
        if (notify)
            notify('Blender selection received · attached to the next message (not sent)', 'success');
        return;
    }
    state.fails = (state.fails || 0) + 1;
    const reason = 'the input box did not take the Blender selection (no bound session, or the host refused it)';
    if (state.fails === 1 && notify)
        notify('Blender selection not attached: ' + reason, 'warning');
    if (state.fails >= 3)
        await done(false, { reason: reason });
}
//# sourceMappingURL=selection.js.map