import { toAttachment, readLocalPng } from '../../utils/image.js';
import { asRecord, text } from '../../contracts/dynamic.js';
/** The headless worker's returned {frames,picks,code,...} → text + at most 6 attached frames. */
export async function workerWatchResponse(ctx, res) {
    const fr = Array.isArray(res.frames) ? res.frames : [];
    const hashes = fr.filter((x) => asRecord(x).ok).map((x) => asRecord(x).hash);
    const distinct = new Set(hashes).size;
    const parts = [];
    const codeInfo = asRecord(res.code);
    if (res.code)
        parts.push('code: ' +
            (codeInfo.ok ? 'ok' : 'failed') +
            (codeInfo.error ? ' · ' + text(codeInfo.error) : ''));
    parts.push('WATCH(headless) ' +
        text(res.sampled || fr.length) +
        ' frames · distinct views ' +
        String(distinct) +
        '/' +
        String(hashes.length) +
        ' · ' +
        text(res.ms || 0) +
        'ms' +
        (res.static_render ? ' · no animated frame range, repeated static sampling' : ''));
    parts.push('timeline: ' +
        fr
            .slice(0, 16)
            .map((x) => text(asRecord(x).frame) + ':' + text(asRecord(x).hash))
            .join(' '));
    const images = [];
    let whyNot = '';
    const picks = Array.isArray(res.picks) ? res.picks.slice(0, 6) : [];
    for (let i = 0; i < picks.length; i++) {
        const p = asRecord(picks[i]);
        let data = null;
        if (p.png_b64) {
            try {
                data = Buffer.from(String(p.png_b64), 'base64');
            }
            catch {
                data = null;
            }
        }
        if (!data && p.path)
            data = readLocalPng(p.path);
        if (!data) {
            if (!whyNot)
                whyNot = 'no png_b64/path';
            continue;
        }
        const att = await toAttachment(ctx, data, 'watch-hl-' + text(p.frame) + '-' + text(p.hash) + '.png');
        if (att.ref)
            images.push(att.ref);
        else if (!whyNot)
            whyNot = att.why || 'unknown reason';
    }
    parts.push('attached frames: ' + String(images.length) + (whyNot ? ' · ⚠ ' + whyNot : ''));
    return images.length
        ? { text: parts.join(String.fromCharCode(10)), images: images }
        : { text: parts.join(String.fromCharCode(10)) };
}
/** GUI per-frame sampling → text + evenly sampled attached frames. shots[i]={t,ms,hash,png}. */
export async function guiWatchResponse(ctx, shots, parts, seconds, fps) {
    const hashes = shots.map((s) => s.hash);
    const distinct = Array.from(new Set(hashes)).length;
    const avgMs = Math.round(shots.reduce((a, s) => a + Math.max(0, s.ms), 0) / Math.max(1, shots.length));
    parts.push('WATCH ' +
        String(seconds) +
        's @' +
        String(fps) +
        'fps → ' +
        String(shots.length) +
        ' frames · avg ' +
        String(avgMs) +
        'ms/frame · distinct views ' +
        String(distinct) +
        '/' +
        String(hashes.length));
    parts.push('timeline: ' + shots.map((s, i) => String(i) + '@' + String(s.t) + 'ms:' + s.hash).join(' '));
    const picks = [];
    const maxImages = 6;
    if (shots.length <= maxImages) {
        for (const s of shots)
            if (s.png)
                picks.push(s);
    }
    else {
        for (let k = 0; k < maxImages; k++) {
            const idx = Math.round((k * (shots.length - 1)) / (maxImages - 1));
            if (shots[idx] && shots[idx].png)
                picks.push(shots[idx]);
        }
    }
    const images = [];
    let whyNot;
    for (let k = 0; k < picks.length; k++) {
        const att = await toAttachment(ctx, picks[k].png, 'watch-' + String(k) + '-' + picks[k].hash + '.png');
        if (att.ref)
            images.push(att.ref);
        else if (!whyNot)
            whyNot = att.why;
    }
    parts.push('attached frames: ' +
        String(images.length) +
        ' (evenly sampled)' +
        (whyNot ? ' · ⚠ some frames were not returned: ' + whyNot : ''));
    const out = { text: parts.join(String.fromCharCode(10)) };
    if (images.length)
        out.images = images;
    return out;
}
//# sourceMappingURL=response.js.map