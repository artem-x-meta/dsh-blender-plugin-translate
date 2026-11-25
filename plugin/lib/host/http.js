import { createHash } from 'node:crypto';
import { ABORT_HINT, HOLDER } from '../constants.js';
import { execSignal } from './exec-context.js';
import { base, withTimeout } from './backend/index.js';
import { asRecord, isRecord, text } from '../contracts/dynamic.js';
export async function backendJson(port, path, timeoutMs = 20000, init) {
    const r = await withTimeout(base(port) + path, init, timeoutMs);
    const body = await r.text();
    try {
        const parsed = JSON.parse(body);
        // The backend protocol only returns JSON objects. A primitive is a protocol
        // violation; keep the historical passthrough instead of inventing a wrapper
        // shape that no caller or endpoint has ever produced.
        return isRecord(parsed) ? parsed : parsed;
    }
    catch {
        return { ok: false, raw: body.slice(0, 500) };
    }
}
/**
 * Parse the backend response (v0.8.9 fix): the backend has two shapes --
 *   ① a normal route: the whole body is one JSON;
 *   ② a streaming route (/headless /worker /txn /preset): NDJSON, **a line is written every 15 s** {"heartbeat":true,...}, and only the last line is the result.
 * The old implementation JSON.parse'd the whole body, so any call **longer than 15 s** threw Extra data → the caller only saw exit=undefined (the subprocess had actually finished).
 * Now: when parsing fails, scan backwards line by line for the last non-heartbeat JSON; also record the heartbeat count in __heartbeats for the tool layer to hint on.
 */
export function parseBackendBody(body) {
    const t = String(body == null ? '' : body);
    try {
        const parsed = JSON.parse(t);
        if (isRecord(parsed))
            return parsed;
    }
    catch {
        /* streaming response, keep going */
    }
    const lines = t
        .split('\n')
        .map((s) => s.trim())
        .filter(Boolean);
    let last = null;
    let beats = 0;
    for (let i = lines.length - 1; i >= 0; i--) {
        let parsed;
        try {
            parsed = JSON.parse(lines[i]);
        }
        catch {
            continue;
        }
        if (!isRecord(parsed))
            continue;
        if (parsed.heartbeat === true)
            continue;
        last = parsed;
        break;
    }
    for (let i = 0; i < lines.length; i++) {
        try {
            const parsed = JSON.parse(lines[i]);
            if (isRecord(parsed) && parsed.heartbeat === true)
                beats++;
        }
        catch {
            /* not a JSON line */
        }
    }
    if (last) {
        last.__heartbeats = beats;
        last.__streamLines = lines.length;
        return last;
    }
    return {
        ok: false,
        raw: t.slice(-500),
        streamLines: lines.length,
        parseError: 'no JSON line found',
    };
}
/**
 * Every write operation goes through this: it attaches holder automatically (for the lease gate) and keeps the HTTP status code so 409 can be recognized.
 *
 * v0.9.3 (critical): **the timer must stay alive until the body is fully read**.
 * The old version was withTimeout(fetch) → fetch resolves as soon as the **response headers** arrive (the streaming /headless route sends headers immediately + a heartbeat every 15 s),
 * so the timeout budget only covered "waiting for the headers" and the following r.text() waited indefinitely -- the client wait window was nominal,
 * and the moment the outer run_code deadline hit, the whole result was dropped (exactly the reported symptom).
 * Now text() lives inside the same AbortController: on expiry abort → fetch / body read both throw AbortError.
 */
export async function backendPost(port, path, body, timeoutMs = 60000) {
    const ac = new AbortController();
    const ext = execSignal();
    let fired = false;
    const timer = setTimeout(() => {
        fired = true;
        ac.abort();
    }, timeoutMs);
    const signal = ext ? AbortSignal.any([ext, ac.signal]) : ac.signal;
    try {
        const r = await fetch(base(port) + path, {
            method: 'POST',
            headers: { 'content-type': 'application/json' },
            body: JSON.stringify({ ...asRecord(body), holder: HOLDER }),
            signal,
        });
        const bodyText = await r.text();
        const parsed = parseBackendBody(bodyText);
        parsed.__status = r.status;
        return parsed;
    }
    catch (e) {
        if (!fired && ext && ext.aborted)
            throw new Error(ABORT_HINT, { cause: e });
        throw e;
    }
    finally {
        clearTimeout(timer);
    }
}
/** v0.9.1: tool input tolerance -- the harness type:"json" sometimes hands an object over as a **string** (both forms were observed in the same session),
 *  the old typeof x === 'object' silently dropped the argument (showing up as "the parameter did not take effect yet ok:true", very hard to trace). */
export function jsonPayload(v) {
    if (v === undefined || v === null || v === '')
        return {};
    if (typeof v === 'string') {
        try {
            const parsed = JSON.parse(v);
            return isRecord(parsed) ? parsed : {};
        }
        catch {
            return {};
        }
    }
    if (typeof v === 'object' && !Array.isArray(v))
        return { ...asRecord(v) };
    return {};
}
/** Split a string like "‑‑flag \"a b\" c" into argv (a matched quote pair is not a separator; v0.8.9 fixed the headless args quoting problem)
 *  v0.9.1: arrays pass straight through (the old String([...]) turned into a single token like "[delta]" with brackets) */
export function splitArgs(s) {
    if (Array.isArray(s))
        return s.map((x) => String(x));
    const str = String(s == null ? '' : s);
    const out = [];
    let cur = '';
    let q = null;
    for (let i = 0; i < str.length; i++) {
        const c = str[i];
        if (q) {
            if (c === q)
                q = null;
            else
                cur += c;
            continue;
        }
        if (c === '"' || c === "'") {
            q = c;
            continue;
        }
        if (/\s/.test(c)) {
            if (cur) {
                out.push(cur);
                cur = '';
            }
            continue;
        }
        cur += c;
    }
    if (cur)
        out.push(cur);
    return out;
}
/** 409 leased → give the model one sentence it can act on (instead of dumping JSON) */
export function leasedText(r) {
    const body = asRecord(r);
    if (body.error !== 'leased')
        return undefined;
    return ('the write channel is held by another session (holder=' +
        text(body.holder) +
        ', ' +
        String(Math.round(Number(body.expiresInMs || 0) / 1000)) +
        's left). ' +
        text(body.hint) +
        '; to force-take it: blender_viewport op=lease force=true' +
        '\ncode: lease_conflict' +
        '\nnext_action: retry after the lease is released, or force-take it with blender_viewport op=lease force=true');
}
/** Fetch one PNG frame's bytes (with timing); full=true goes through screenshot_area (whole window/area) */
export async function fetchFrame(port, size, full = false, area = 0) {
    const t0 = Date.now();
    const url = base(port) + '/frame.png?' + (full ? 'full=1&area=' + String(area) : 'size=' + String(size));
    const r = await withTimeout(url, {}, 60000);
    if (!r.ok)
        throw new Error('frame http ' + String(r.status));
    const buf = new Uint8Array(await r.arrayBuffer());
    return {
        png: buf,
        ms: Date.now() - t0,
        hash: createHash('md5').update(buf).digest('hex').slice(0, 8),
    };
}
/** Render from a custom view: POST /view (view.py) -- changes no objects and no user viewport */
export async function fetchView(port, spec, timeoutMs = 180000) {
    const t0 = Date.now();
    const r = await withTimeout(base(port) + '/view', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify(asRecord(spec)),
    }, timeoutMs);
    if (!r.ok) {
        const bodyText = await r.text();
        let parsed;
        try {
            const candidate = JSON.parse(bodyText);
            parsed = isRecord(candidate) ? candidate : null;
        }
        catch {
            parsed = null;
        }
        throw new Error('view http ' +
            String(r.status) +
            ' · ' +
            String(parsed ? parsed.error : bodyText.slice(0, 300)));
    }
    let meta;
    try {
        const rawHdr = String(r.headers.get('x-dsh-view') || 'null');
        // v0.9.1: the header value is URL-encoded (non-ASCII cannot go into a header) -- the old backend sent bare JSON, both are supported
        const txt = rawHdr.indexOf('%7B') === 0 ? decodeURIComponent(rawHdr) : rawHdr;
        const candidate = JSON.parse(txt);
        meta = isRecord(candidate) ? candidate : null;
    }
    catch {
        meta = null;
    }
    const buf = new Uint8Array(await r.arrayBuffer());
    return {
        png: buf,
        ms: Date.now() - t0,
        meta: meta,
        hash: createHash('md5').update(buf).digest('hex').slice(0, 8),
    };
}
export function numTriple(v) {
    if (v === undefined || v === null || v === '')
        return undefined;
    if (Array.isArray(v))
        return v.map((x) => Number(x));
    return String(v)
        .split(/[,\s]+/)
        .filter(Boolean)
        .map((x) => Number(x));
}
//# sourceMappingURL=http.js.map
