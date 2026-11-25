import { readFileSync } from 'node:fs';
import { asArray, asRecord, text } from '../contracts/dynamic.js';
/** PNG → durable attachment (since v0.9.2 a failure is **no longer silent**: it returns {ref} or {why}, and the caller writes it into the tool text) */
export async function toAttachment(ctx, data, name) {
    try {
        const host = ctx;
        const attachments = host.get('attachments');
        if (!attachments)
            return { why: 'the host has no attachments service (ctx.get("attachments") is empty)' };
        const mediaTypes = attachments.imageLimits?.mediaTypes ?? [];
        if (!mediaTypes.includes('image/png'))
            return {
                why: 'host imageLimits.mediaTypes does not include image/png (' + JSON.stringify(mediaTypes) + ')',
            };
        const ref = await attachments.saveImage({ data, mediaType: 'image/png', name });
        return {
            ref: {
                attachmentId: ref.attachmentId,
                mediaType: ref.mediaType,
                bytes: ref.bytes,
                width: ref.width,
                height: ref.height,
                ...(ref.name === undefined ? {} : { name: ref.name }),
            },
        };
    }
    catch (e) {
        return { why: 'saveImage failed: ' + (e instanceof Error ? e.message : String(e)) };
    }
}
/** Windows / UNC path → WSL path (this DSH runs inside WSL; on a Windows host it returns as-is). */
export function toWslPath(p) {
    const s = String(p == null ? '' : p);
    if (!s)
        return s;
    // Windows host: D:\... is already a usable local path; converting it to /mnt/d/... makes it unreadable (no such mount on Windows).
    if (process.platform === 'win32')
        return s;
    if (/^[A-Za-z]:[\\/]/.test(s))
        return '/mnt/' + s[0].toLowerCase() + s.slice(2).replace(/\\/g, '/');
    const m = s.match(/^\\\\wsl\.localhost\\[^\\]+\\(.*)$/i);
    if (m)
        return '/' + String(m[1]).replace(/\\/g, '/');
    return s;
}
/** Read a local PNG (returns null on failure; the caller is responsible for writing why into the text, never silently) */
export function readLocalPng(p) {
    const s = String(p == null ? '' : p);
    if (!s)
        return null;
    const converted = toWslPath(s);
    const candidates = converted === s ? [s] : [converted, s];
    for (const candidate of candidates) {
        try {
            return readFileSync(candidate);
        }
        catch {
            /* try next form */
        }
    }
    return null;
}
/** Batch image attachment: ≤max images; returns the attachments attached plus a failure list (path/reason) */
export async function attachPaths(ctx, paths, tag, max = 2) {
    const images = [], used = [], failed = [];
    const seen = new Set();
    for (const p of paths || []) {
        if (images.length >= max)
            break;
        const s = String(p == null ? '' : p);
        if (!s || seen.has(s))
            continue;
        seen.add(s);
        const data = readLocalPng(s);
        if (!data) {
            failed.push(s + ' (unreadable)');
            continue;
        }
        const att = await toAttachment(ctx, data, tag + '-' + String(Date.now()) + '-' + String(images.length) + '.png');
        if (att.ref) {
            images.push(att.ref);
            used.push(s);
        }
        else
            failed.push(s + ' (' + String(att.why || 'attachment failed') + ')');
    }
    return { images, used, failed };
}
/** Collect attachable paths from a plan receipt (≤2; only well-known artifact fields) */
export function planImagePaths(res) {
    const r = asRecord(res);
    const out = [];
    const push = (x) => {
        if (typeof x === 'string') {
            out.push(x);
            return;
        }
        const rec = asRecord(x);
        const s = text(rec.path) || text(rec.crop) || text(rec.out) || text(rec.file);
        if (s)
            out.push(s);
    };
    const images = r.images;
    if (Array.isArray(images))
        for (const x of images)
            push(x);
    else if (images && typeof images === 'object') {
        for (const k of ['overlay', 'sheet', 'crops', 'per_view']) {
            const v = images[k];
            if (Array.isArray(v))
                for (const x of v)
                    push(x);
            else if (v)
                push(v);
        }
    }
    for (const k of ['overlay', 'sheet', 'diff_heat', 'annotated', 'atlas', 'out'])
        push(r[k]);
    for (const c of asArray(r.crops))
        push(c);
    for (const v of asArray(r.views))
        push(v);
    const overlay = asRecord(r.overlay);
    if (overlay.path)
        push(overlay.path);
    const sheet = asRecord(r.sheet);
    if (sheet.path)
        push(sheet.path);
    return out;
}
//# sourceMappingURL=image.js.map