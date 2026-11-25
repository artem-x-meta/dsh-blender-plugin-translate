/**
 * v0.9.4 frame dedupe: **never attach the same frame twice**.
 *
 * Why: the hash is already the first 8 chars of the PNG bytes' md5 (both fetchFrame and fetchView compute it),
 * and duplicate attachments only burn **visual tokens on the model side** - measured: the same frame sent 5 times in a row had identical hashes
 * (`038c7439`) at 116,870 B per frame. Equal hash => byte-identical pixels => skipping the attachment **loses no information**.
 * To force a resend (e.g. to look at it again) pass `force:true`.
 *
 * The cache is keyed per "channel": default viewport frames / custom views (by view signature) / rt_do's see, so they do not interfere.
 */
export declare const FRAME_CACHE: Map<string, {
    hash: string;
    firstAt: number;
    repeats: number;
}>;
/** Pure decision: hit => dup=true and the counter goes up by 1; miss => record the new hash. force=true is always treated as a miss and resets it. */
export declare function frameDedupe(key: string, hash: string, force?: boolean): {
    dup: boolean;
    repeats: number;
    firstAt: number;
};
/** For tests: clear the dedupe cache */
export declare function resetFrameCache(): void;
/** Shared wording on a dedupe hit (state "identical, not attached, how to get it back" so the agent does not think it saw the image) */
export declare function dedupeNote(repeats: number): string;
