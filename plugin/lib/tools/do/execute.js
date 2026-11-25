import { BACKEND_HINT } from '../../constants.js';
import { ensureBackend } from '../../host/backend/index.js';
import { backendPost, fetchFrame, leasedText, numTriple } from '../../host/http.js';
import { frameDedupe, dedupeNote } from '../../utils/frame-cache.js';
import { toAttachment, readLocalPng } from '../../utils/image.js';
import { asRecord, text } from '../../contracts/dynamic.js';
import { isHostAbort, toolError } from '../errors.js';
import { formatActText, formatSessionExec, formatSessionSee } from './envelope.js';
const LF = String.fromCharCode(10);
export async function executeDo(args, ctx, port) {
    if (!(await ensureBackend(port)))
        return toolError('backend_unreachable', 'Backend unavailable (127.0.0.1:' + String(port) + ')', BACKEND_HINT);
    const code = String(args.code || '');
    const file = args.file ? String(args.file) : null;
    if (!code && !file)
        return toolError('invalid_params', 'one of code or file is required', 'pass code=<python> or file=<script path>');
    const sessOpts = {
        code: code,
        file: file,
        session: args.session,
        preload: args.preload,
        see: !(args.see === false),
        max_size: args.max_size,
        from: args.from,
        look_at: args.look_at,
        lens: args.lens,
        ortho: args.ortho,
        ortho_scale: args.ortho_scale,
        view_size: args.view_size,
    };
    // explicit session → skip the GUI probe and go straight to the persistent headless session (exec + see; callable repeatedly within one turn)
    if (args.session) {
        const s = await doViaSession(ctx, port, sessOpts);
        return (s ||
            toolError('backend_unreachable', 'headless interactive session failed: worker unavailable (session=' + String(args.session) + ')', 'first run blender_rt_worker op=start name=' + String(args.session) + ', then retry'));
    }
    return doAct(ctx, port, args, code, file, sessOpts);
}
async function doAct(ctx, port, args, code, file, sessOpts) {
    const body = { code: code };
    if (file)
        body.file = file;
    let r;
    try {
        r = await backendPost(port, '/act', body, 180000);
    }
    catch (e) {
        if (isHostAbort(e))
            throw e;
        if (args.auto !== false) {
            const s = await doViaSession(ctx, port, sessOpts);
            if (s)
                return s;
        }
        return toolError('backend_unreachable', 'ACT failed · 127.0.0.1:' + String(port) + ' · ' + text(e), BACKEND_HINT);
    }
    const lt = leasedText(r);
    if (lt)
        return { text: lt };
    // with the GUI offline /act returns ok:false + connect timeout — fall back automatically to the persistent headless session
    if (r.ok === false && args.auto !== false) {
        const s = await doViaSession(ctx, port, sessOpts);
        if (s)
            return s;
    }
    if (r.ok !== true)
        return toolError('backend_error', 'ACT failed · ' + text(r.error || r.raw || 'unknown'), 'use blender_viewport op=status to confirm the backend and addon; keep auto=true when you want the fallback');
    const parts = formatActText(r);
    const image = await maybeActSee(ctx, port, args, parts);
    const out = { text: parts.join(LF) };
    if (image)
        out.image = image;
    return out;
}
async function maybeActSee(ctx, port, args, parts) {
    if (args.see === false)
        return undefined;
    try {
        const size = Math.max(120, Math.min(1600, Number(args.max_size || 560)));
        const f = await fetchFrame(port, size);
        // v0.9.4: in consecutive rt_do calls, don't re-attach the frame when nothing changed (the most common waste in an iteration loop)
        const dd = frameDedupe('do-see:' + String(size), f.hash, !!args.force);
        if (dd.dup) {
            parts.push('SEE ' +
                String(size) +
                'px · ' +
                String(f.ms) +
                'ms · hash ' +
                f.hash +
                dedupeNote(dd.repeats));
            return undefined;
        }
        const att = await toAttachment(ctx, f.png, 'viewport-' + String(Date.now()) + '.png');
        if (!att.ref)
            parts.push('⚠ image not returned: ' + text(att.why || 'unknown reason'));
        parts.push('SEE ' + String(size) + 'px · ' + String(f.ms) + 'ms · hash ' + f.hash);
        return att.ref;
    }
    catch (e) {
        parts.push('SEE failed: ' + text(e));
        return undefined;
    }
}
/** One interactive headless step: exec code + optional see (persistent worker; not a job / not an async turn). */
export async function doViaSession(ctx, port, opts) {
    try {
        const nm = String(opts.session || 'interactive');
        const preload = opts.preload ? String(opts.preload) : '';
        if (preload) {
            const bad = await startSession(port, nm, preload);
            if (bad)
                return bad;
        }
        const code = readSessionCode(opts);
        if (code === null)
            return { text: 'cannot read the script file: ' + String(opts.file) };
        if (!code)
            return null;
        const r = await backendPost(port, '/worker', { op: 'exec', name: nm, code: code, isolated: true }, 180000);
        const rr = asRecord(r.result);
        if (r.ok !== true) {
            return toolError('backend_error', 'ACT(session) failed · ' + text(r.error || rr.error || 'unknown'), 'first run blender_rt_worker op=start name=' + nm + ', or check the backend /worker route');
        }
        const parts = formatSessionExec(rr, nm);
        const image = opts.see !== false ? await sessionSee(ctx, port, nm, opts, parts) : undefined;
        const out = { text: parts.join(LF) };
        if (image)
            out.image = image;
        return out;
    }
    catch {
        return null;
    }
}
async function startSession(port, nm, preload) {
    const st = await backendPost(port, '/worker', { op: 'start', name: nm, preload: preload, engine: 'workbench', warmup: true, isolated: true }, 120000);
    if (st.ok === true)
        return null;
    return toolError('backend_error', 'headless session failed to start · ' + text(st.error || st.raw || 'unknown'), 'first run blender_rt_worker op=start to launch the persistent worker, or check the backend /worker route');
}
function readSessionCode(opts) {
    let code = String(opts.code || '');
    if (!code && opts.file) {
        const data = readLocalPng(opts.file);
        if (!data)
            return null;
        code = Buffer.from(data).toString('utf8');
    }
    return code || '';
}
async function sessionSee(ctx, port, nm, opts, parts) {
    const size = Math.max(120, Math.min(1600, Number(opts.max_size || 560)));
    const spec = {
        from: numTriple(opts.from) || [7, -7, 5],
        look_at: numTriple(opts.look_at) || [0, 0, 1],
        lens: opts.lens === undefined ? undefined : Number(opts.lens),
        ortho: opts.ortho === undefined ? undefined : !!opts.ortho,
        ortho_scale: opts.ortho_scale === undefined ? undefined : Number(opts.ortho_scale),
        width: size,
        height: Math.max(120, Math.round((size * 9) / 16)),
    };
    const mm = String(opts.view_size || '').match(/^(\d+)\s*[x×]\s*(\d+)$/);
    if (mm) {
        spec.width = Number(mm[1]);
        spec.height = Number(mm[2]);
    }
    const sr = await backendPost(port, '/worker', { op: 'see', name: nm, spec: spec, isolated: true }, 90000);
    const sres = asRecord(sr.result);
    if (sres.ok === false) {
        parts.push('SEE(session) failed: ' + text(sres.error || 'unknown'));
        return undefined;
    }
    const image = await attachSessionSee(ctx, sres, 'session-see-' + String(Date.now()) + '.png');
    parts.push(formatSessionSee(sres, spec));
    if (!image.ref)
        parts.push('⚠ image not returned: ' + text(image.why || 'unknown reason'));
    return image.ref;
}
async function attachSessionSee(ctx, sres, name) {
    let data = null;
    if (sres.png_b64) {
        try {
            data = Buffer.from(String(sres.png_b64), 'base64');
        }
        catch {
            data = null;
        }
    }
    if (!data && sres.path)
        data = readLocalPng(sres.path);
    return data ? toAttachment(ctx, data, name) : { why: 'no png_b64/path' };
}
//# sourceMappingURL=execute.js.map