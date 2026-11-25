import { asArray, asRecord, text } from '../contracts/dynamic.js';
import { MENTION_LIMIT, SCENE_CACHE_LIMIT, SCENE_CACHE_MS } from './constants.js';
import { getJson } from './http.js';
/** '/host/scene-items' response → mention entries. What gets inserted into the draft is the same model text the Web codec uses ('<blender-object>name</blender-object>'). */
export function mentionItems(body, limit = MENTION_LIMIT) {
    if (asRecord(body).ok !== true)
        return [];
    const b = asRecord(body);
    const out = [];
    const groups = [
        ['objects', 'object', null],
        ['materials', 'material', 'MATERIAL'],
        ['collections', 'collection', 'COLLECTION'],
    ];
    for (const [field, kind, label] of groups) {
        for (const it of asArray(b[field])) {
            const rec = asRecord(it);
            if (!rec.name || out.length >= limit)
                continue;
            const name = text(rec.name);
            out.push({
                label: name,
                detail: label || text(rec.type) || 'OBJECT',
                insertText: '<blender-' + kind + '>' + name + '</blender-' + kind + '>',
            });
        }
    }
    return out;
}
/** Local filtering: label contains query (case-insensitive); an empty query yields the first 50 entries. The host then re-sorts by its own fuzzy score. */
export function filterMentionItems(items, query) {
    const q = String(query || '')
        .trim()
        .toLowerCase();
    const out = [];
    for (const it of items) {
        if (out.length >= MENTION_LIMIT)
            break;
        if (!q || String(it.label).toLowerCase().indexOf(q) >= 0)
            out.push(it);
    }
    return out;
}
/**
 * Data source for '@' mentions: the first query pulls a full set (≤ 1000 entries) into a cache, after which filtering is local and returns immediately;
 * once the cache is older than 5 s it is refreshed in the background (without waiting for it). The very first cold start may exceed the
 * host's per-call deadline and be dropped, but the cache still fills, so the next keystroke has results. Blender is only touched when the user
 * actually types '@', never by polling.
 */
export function createSceneMentionSource(port) {
    const cache = { at: 0, items: null, inflight: null };
    const refresh = () => {
        if (cache.inflight)
            return cache.inflight;
        cache.inflight = getJson(port, '/host/scene-items?limit=' + String(SCENE_CACHE_LIMIT) + '&q=', undefined, 10000)
            .then((body) => {
            if (body && body.ok === true) {
                cache.items = mentionItems(body, SCENE_CACHE_LIMIT);
                cache.at = Date.now();
            }
        })
            .finally(() => {
            cache.inflight = null;
        });
        return cache.inflight;
    };
    return async (query, signal) => {
        if (Date.now() - cache.at >= SCENE_CACHE_MS) {
            const pending = refresh();
            if (!cache.items) {
                // cold start: wait for the first result, but return empty right away if the host aborted (the fetch keeps running in the background)
                await new Promise((resolve) => {
                    pending.then(resolve, resolve);
                    if (signal)
                        signal.addEventListener('abort', () => resolve(), { once: true });
                });
            }
        }
        return filterMentionItems(cache.items || [], query);
    };
}
//# sourceMappingURL=mentions.js.map
