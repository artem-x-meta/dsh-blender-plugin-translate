/**
 * v0.9.4 frame dedupe: **never attach the same frame twice**.
 *
 * Why: the hash is already the first 8 hex digits of the PNG bytes' md5 (both fetchFrame and fetchView compute it),
 * and a repeated attachment only burns **model-side vision tokens** — measured in practice, the same frame sent 5 times gave an identical
 * hash (`038c7439`), with a single frame of 116,870 B. Equal hash ⇒ byte-identical pixels ⇒ skipping the attachment **loses nothing**.
 * To force a resend (for example to look again), pass `force:true`.
 *
 * The cache is keyed by "channel": default viewport frame / custom view (by view signature) / rt_do's see — they never interfere.
 */
export const FRAME_CACHE = new Map();
/** Pure decision: hit ⇒ dup=true and count +1; miss ⇒ record the new hash. force=true always counts as a miss and resets. */
export function frameDedupe(key, hash, force = false) {
    const k = String(key || 'default');
    const h = String(hash || '');
    const cur = FRAME_CACHE.get(k);
    if (!force && cur && h && cur.hash === h) {
        cur.repeats += 1;
        return { dup: true, repeats: cur.repeats, firstAt: cur.firstAt };
    }
    const firstAt = Date.now();
    FRAME_CACHE.set(k, { hash: h, firstAt, repeats: 0 });
    if (FRAME_CACHE.size > 32) {
        // Keys are few (a handful of channels); a hard cap guards against unexpected growth
        const oldest = FRAME_CACHE.keys().next().value;
        if (oldest !== undefined && oldest !== k)
            FRAME_CACHE.delete(oldest);
    }
    return { dup: false, repeats: 0, firstAt };
}
/** Test-only: clear the dedupe cache */
export function resetFrameCache() {
    FRAME_CACHE.clear();
}
/** Shared wording for a dedupe hit (states "identical, not attached, how to get it back" so an agent does not assume it saw the image) */
export function dedupeNote(repeats) {
    return (' · **identical to the previous frame** (repeat #' + String(repeats + 1) + ') ⇒ attachment not resent; pass force:true to resend');
}
//# sourceMappingURL=frame-cache.js.map