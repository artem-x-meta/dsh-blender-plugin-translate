import type { MentionItem } from './types.js';
/** '/host/scene-items' response → mention items. What gets inserted into the draft is the same model text as the Web codec ('<blender-object>name</blender-object>'). */
export declare function mentionItems(body: unknown, limit?: number): MentionItem[];
/** Local filtering: label contains query (case-insensitive); an empty query gives the first 50. The host then re-sorts with its own fuzzy score. */
export declare function filterMentionItems(items: MentionItem[], query: string): MentionItem[];
/**
 * Data source for '@' mentions: the first query fetches the full set (≤ 1000) and caches it, after which filtering is local and returns immediately;
 * when the cache is older than 5 s it refreshes once in the background (without waiting for it). The cold-start call may exceed the host's per-call limit and be dropped,
 * but the cache still gets filled, so the next keypress has results. Blender is only touched when the user actually types '@'; no polling.
 */
export declare function createSceneMentionSource(port: number): (query: string, signal: AbortSignal) => Promise<MentionItem[]>;
