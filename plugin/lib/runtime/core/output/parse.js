// stdout marker parsing / path rewriting (split out of output.ts, behaviour frozen)
import fs from 'node:fs';
import { winToWsl } from '../../config.js';
function extractTag(out, tag) {
    const rec = out && typeof out === 'object' ? out : null;
    const txt = rec && typeof rec.result === 'string' ? rec.result : '';
    const m = txt.match(new RegExp(tag + ' ([\\s\\S]*)'));
    if (!m)
        throw new Error(tag + ' has no reply: ' + txt.slice(0, 200));
    return JSON.parse(m[1]);
}
function extractLoop(out) {
    return extractTag(out, 'LOOP');
}
function jsonFromStdout(out) {
    const rec = out && typeof out === 'object' ? out : null;
    const txt = rec && typeof rec.result === 'string'
        ? rec.result
        : typeof out === 'string'
            ? out
            : JSON.stringify(out);
    const m = txt.match(/\{[\s\S]*\}/);
    return m ? JSON.parse(m[0]) : null;
}
/** Path mapping is in config.mjs: winToWsl / wslToWin (returned as-is on Windows) */
/** The python script used by a headless run lands in a Windows-visible directory; if /mnt is not writable it falls back to the in-package tmp + UNC */
/** v0.8.10: long output becomes "head + tail + elision marker" — the old version returned only the tail and ate the head of long JSON */
function clipMiddle(s, head, tail) {
    const t = String(s == null ? '' : s);
    if (t.length <= head + tail)
        return t;
    return (t.slice(0, head) +
        '\n…[omitted ' +
        String(t.length - head - tail) +
        ' characters; see the logs path for the full text]…\n' +
        t.slice(-tail));
}
/**
 * v0.9.6 (field report: "second prefix" on WSL absolute paths): a path like `home/.../DSH/sample/x.py` that **lost its leading /**
 * gets joined to cwd as a relative path, yielding `...DSH\home\sixtyseven67\DSH\sample\x.py`.
 * Criterion: it really exists after prepending "/" → correct it and log one note (also writing it to backend stderr, to make debugging easier).
 */
function slipFixPath(p, notes) {
    const s = String(p == null ? '' : p);
    if (!s || s.startsWith('/') || s.startsWith('\\\\') || /^[A-Za-z]:[\\/]/.test(s))
        return s;
    if (!/^(home|mnt|tmp|usr|opt|srv|var|etc|root|data)\//.test(s))
        return s;
    const cand = '/' + s;
    let hit;
    try {
        hit = fs.existsSync(winToWsl(cand)) || fs.existsSync(cand);
    }
    catch (e) {
        hit = false;
    }
    if (!hit)
        return s;
    const msg = 'WSL absolute path is missing the leading "/": ' + s + ' → treated as ' + cand;
    if (notes)
        notes.push(msg);
    try {
        process.stderr.write('[dsh-blender] ' + msg + String.fromCharCode(10));
    }
    catch (e) { }
    return cand;
}
export { extractTag, extractLoop, jsonFromStdout, clipMiddle, slipFixPath };
//# sourceMappingURL=parse.js.map
