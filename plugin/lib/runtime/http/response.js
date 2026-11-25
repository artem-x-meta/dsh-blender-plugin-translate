import { errorMessage, errorField } from '../core/json.js';
// HTTP response primitives: JSON / ndjson streaming / request-body reading / host CORS.
// Behaviour frozen: status codes, content-type, cache-control, heartbeat interval (15 s) and body limit (4 MiB) all unchanged.
function json(res, code, obj) {
    const body = JSON.stringify(obj);
    res.writeHead(code, {
        'content-type': 'application/json; charset=utf-8',
        'cache-control': 'no-store',
    });
    res.end(body);
}
/**
 * Streaming response (ndjson) — required for long jobs: the client fetch header timeout defaults to 300 s (measured in practice as UND_ERR_HEADERS_TIMEOUT),
 * while the server only replies once the child process finishes → a long job is bound to hit that timeout. So we send the headers immediately plus periodic heartbeats, and the result is the last line.
 */
async function streamJson(res, producer, hbMs = 15000) {
    const t0 = Date.now();
    res.writeHead(200, {
        'content-type': 'application/x-ndjson; charset=utf-8',
        'cache-control': 'no-store',
        'x-dsh-stream': '1',
    });
    let done = false;
    const hb = setInterval(() => {
        if (done)
            return;
        try {
            res.write(JSON.stringify({ heartbeat: true, elapsedMs: Date.now() - t0 }) + '\n');
        }
        catch (e) {
            /* client hung up, never mind */
        }
    }, hbMs);
    let obj;
    try {
        obj = await producer();
    }
    catch (e) {
        obj = { ok: false, error: errorMessage(e), diagnosis: errorField(e, 'diagnosis') || null };
    }
    done = true;
    clearInterval(hb);
    try {
        res.write(JSON.stringify(obj) + '\n');
    }
    catch (e) {
        /* ignore */
    }
    res.end();
    return obj;
}
function readBody(req, limit = 1 << 22) {
    return new Promise((resolve, reject) => {
        let n = 0;
        const chunks = [];
        req.on('data', (c) => {
            n += c.length;
            if (n > limit) {
                reject(new Error('body too large'));
                req.destroy();
                return;
            }
            chunks.push(c);
        });
        req.on('end', () => resolve(Buffer.concat(chunks).toString('utf8')));
        req.on('error', reject);
    });
}
// CORS governs whether a browser may read the response; it is not authentication and does not stop non-browser clients from forging Origin.
const HOST_ORIGIN_RE = /^(http:\/\/(127\.0\.0\.1|localhost)(:\d+)?|dsh-app:\/\/app)$/;
function hostCorsHeaders(origin) {
    const h = {
        'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
        'Access-Control-Allow-Headers': 'content-type',
        'Access-Control-Max-Age': '600',
        Vary: 'Origin',
    };
    if (origin && HOST_ORIGIN_RE.test(String(origin)))
        h['Access-Control-Allow-Origin'] = String(origin);
    return h;
}
function hostJson(res, code, obj, origin) {
    res.writeHead(code, Object.assign({ 'content-type': 'application/json; charset=utf-8', 'cache-control': 'no-store' }, hostCorsHeaders(origin)));
    res.end(JSON.stringify(obj));
}
function hostErrText(e) {
    return errorMessage(e);
}
/** Limit for `@` mentions: clamped to [1,1000], default 200 (legacy viewstore convention, still used by routes). */
function clampItemsLimit(v, dflt = 200) {
    const n = Number(v);
    if (!Number.isFinite(n))
        return dflt;
    return Math.max(1, Math.min(1000, Math.round(n)));
}
function hostNormEmpty(v) {
    return v === '' || v == null ? null : v;
}
export { json, streamJson, readBody, hostCorsHeaders, hostJson, hostErrText, clampItemsLimit, hostNormEmpty, };
//# sourceMappingURL=response.js.map