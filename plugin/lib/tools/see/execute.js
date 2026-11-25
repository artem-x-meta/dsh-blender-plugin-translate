import { BACKEND_HINT } from '../../constants.js';
import { ensureBackend } from '../../host/backend/index.js';
import { backendPost, fetchFrame, fetchView, numTriple } from '../../host/http.js';
import { frameDedupe, dedupeNote } from '../../utils/frame-cache.js';
import { toAttachment, readLocalPng } from '../../utils/image.js';
import { asRecord, text } from '../../contracts/dynamic.js';
import { redactSecrets, toolError } from '../errors.js';
import { appendEmptyFrameWarning, formatCustomViewText, formatHeadlessSeeText, formatPlainFrameText, } from './presenter.js';
export async function executeSee(args, ctx, port) {
    if (!(await ensureBackend(port)))
        return toolError('backend_unreachable', 'backend unavailable (127.0.0.1:' + String(port) + ')', BACKEND_HINT);
    const size = Math.max(120, Math.min(1600, Number(args.max_size || 560)));
    const frm = numTriple(args.from) ?? null;
    const look = numTriple(args.look_at) ?? null;
    // Explicit session → go straight to the headless worker (do not probe the GUI).
    const wantSession = args.session ? String(args.session) : '';
    if (wantSession)
        return executeSessionSee(args, ctx, port, size, frm, look, wantSession);
    if (frm || look)
        return executeCustomView(args, ctx, port, size, frm, look);
    return executePlainFrame(args, ctx, port, size, !!args.full, Number(args.area || 0));
}
async function executeSessionSee(args, ctx, port, size, frm, look, wantSession) {
    const spec = {
        from: frm || [7, -7, 5],
        look_at: look || [0, 0, 1],
        lens: args.lens === undefined ? undefined : Number(args.lens),
        ortho: args.ortho === undefined ? undefined : !!args.ortho,
        ortho_scale: args.ortho_scale === undefined ? undefined : Number(args.ortho_scale),
        shading: args.shading || undefined,
        width: size,
        height: Math.max(120, Math.round((size * 9) / 16)),
    };
    const mm = String(args.view_size || '').match(/^(\d+)\s*[x×]\s*(\d+)$/);
    if (mm) {
        spec.width = Number(mm[1]);
        spec.height = Number(mm[2]);
    }
    return ((await seeViaWorker(ctx, port, spec, wantSession)) ||
        toolError('backend_unreachable', 'headless see failed: worker session ' + wantSession + ' is unavailable', 'run blender_rt_worker op=start name=' + wantSession + ' first, or use the GUI channel instead'));
}
async function executeCustomView(args, ctx, port, size, frm, look) {
    const spec = {
        from: frm || [7, -7, 5],
        look_at: look || [0, 0, 1],
        lens: args.lens === undefined ? undefined : Number(args.lens),
        ortho: args.ortho === undefined ? undefined : !!args.ortho,
        ortho_scale: args.ortho_scale === undefined ? undefined : Number(args.ortho_scale),
        shading: args.shading || undefined,
        overlays: args.overlays === undefined ? undefined : !!args.overlays,
        mode: args.view_mode || undefined,
    };
    const mm = String(args.view_size || '').match(/^(\d+)\s*[x×]\s*(\d+)$/);
    if (mm) {
        spec.width = Number(mm[1]);
        spec.height = Number(mm[2]);
    }
    else {
        spec.width = size;
        spec.height = Math.max(120, Math.round((size * 9) / 16));
    }
    // v0.9.4: diagnostics is passed through only when given explicitly
    if (args.diagnostics !== undefined)
        spec.diagnostics = !!args.diagnostics;
    let fv;
    try {
        fv = await fetchView(port, spec);
    }
    catch (e) {
        if (args.auto !== false) {
            const fb = await seeViaWorker(ctx, port, spec, args.session ? String(args.session) : undefined);
            if (fb)
                return fb;
        }
        return toolError('backend_unreachable', 'frame fetch failed · 127.0.0.1:' + String(port) + ' · ' + text(e), BACKEND_HINT);
    }
    // v0.9.4: same view signature + same hash ⇒ do not re-send the image
    const dkey = 'view:' +
        JSON.stringify([
            spec.width,
            spec.height,
            spec.from,
            spec.look_at,
            spec.lens === undefined ? null : spec.lens,
            !!spec.ortho,
            spec.ortho_scale === undefined ? null : spec.ortho_scale,
            spec.shading || null,
            spec.overlays === undefined ? null : !!spec.overlays,
            spec.mode || null,
        ]);
    const dd = frameDedupe(dkey, fv.hash, !!args.force);
    const out = { text: formatCustomViewText(spec, fv) };
    // v0.9.1 (93-D2): warn directly when the custom view comes up empty + say how to aim
    if (fv.meta && fv.meta.warning)
        out.text = appendEmptyFrameWarning(text(out.text), fv.meta.warning);
    if (dd.dup) {
        out.text = text(out.text) + dedupeNote(dd.repeats);
    }
    else {
        const img = await toAttachment(ctx, fv.png, 'view-' + String(Date.now()) + '.png');
        if (img.ref)
            out.image = img.ref;
        else
            out.text =
                text(out.text) + String.fromCharCode(10) + '⚠ image not returned: ' + text(img.why || 'unknown reason');
    }
    return out;
}
async function executePlainFrame(args, ctx, port, size, full, area) {
    let f;
    try {
        f = await fetchFrame(port, size, full, area);
    }
    catch (e) {
        if (args.auto !== false) {
            const fb = await seeViaWorker(ctx, port, {
                from: [7, -7, 5],
                look_at: [0, 0, 1],
                width: size,
                height: Math.max(120, Math.round((size * 9) / 16)),
            }, args.session ? String(args.session) : undefined);
            if (fb)
                return fb;
        }
        return toolError('backend_unreachable', 'frame fetch failed · 127.0.0.1:' + String(port) + ' · ' + text(e), BACKEND_HINT);
    }
    // v0.9.4: default viewport frames are deduped the same way (the key includes size / area, so they never mix)
    const dd = frameDedupe(full ? 'area:' + String(area) : 'viewport:' + String(size), f.hash, !!args.force);
    const out = { text: formatPlainFrameText(size, full, f) };
    if (dd.dup) {
        out.text = text(out.text) + dedupeNote(dd.repeats);
    }
    else {
        const img = await toAttachment(ctx, f.png, (full ? 'area-' : 'viewport-') + String(Date.now()) + '.png');
        if (img.ref)
            out.image = img.ref;
        else
            out.text =
                text(out.text) + String.fromCharCode(10) + '⚠ image not returned: ' + text(img.why || 'unknown reason');
    }
    return out;
}
async function seeViaWorker(ctx, port, spec, name) {
    try {
        const r = await backendPost(port, '/worker', { op: 'see', name: name || 'default', spec: spec || {}, isolated: true }, 90000);
        if (r.ok !== true)
            return null;
        const res = asRecord(r.result);
        if (res.ok === false)
            return toolError('backend_error', 'headless see failed · ' + text(res.error || 'unknown'), 'check the headless worker with blender_rt_worker op=start; or use the GUI channel instead', res.traceback ? redactSecrets(res.traceback).slice(-1200) : undefined);
        let data = null;
        if (res.png_b64) {
            try {
                data = Buffer.from(String(res.png_b64), 'base64');
            }
            catch {
                data = null;
            }
        }
        if (!data && res.path)
            data = readLocalPng(res.path);
        const att = data
            ? await toAttachment(ctx, data, 'headless-see-' + String(Date.now()) + '.png')
            : { why: 'no png_b64/path provided' };
        const rendered = formatHeadlessSeeText(res);
        return att.ref
            ? { text: rendered, image: att.ref }
            : {
                text: rendered + String.fromCharCode(10) + '⚠ image not returned: ' + text(att.why || 'unknown reason'),
            };
    }
    catch {
        return null;
    }
}
//# sourceMappingURL=execute.js.map