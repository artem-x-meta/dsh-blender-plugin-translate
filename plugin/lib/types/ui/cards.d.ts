export type CardBlock = {
    type: 'text';
    text: string;
} | {
    type: 'image';
    attachment: unknown;
};
export declare function renderOne(_args: unknown, value: unknown): CardBlock[];
/** Safe JSON.stringify (circular references / large objects do not blow up; returns null when over-long so the caller can supply a path) */
export declare function safeStringify(v: unknown): string | null;
/** Truncation (keeps head and tail, elides the middle) — same convention as the backend's clipMiddle */
export declare function clipText(s: unknown, head: number, tail: number): string;
/** Tool receipt with a structured envelope: value = {text, envelope?, image?, images?} */
export declare function renderStructured(_args: unknown, value: unknown): CardBlock[];
export interface CardSpec {
    kind: string;
    title: (a: Record<string, unknown>) => string;
    /** Code executed by this call (goes into the card body when present; on a result card it is appended after the summary) */
    code?: (a: Record<string, unknown>) => {
        label: string;
        code: string;
    } | null;
}
export declare const CARD_SPECS: Record<string, CardSpec>;
/** For vTool: give presentCall / presentResult by tool name (unregistered tools / specs that bring their own are not overridden) */
export declare function cardPresenters(spec: unknown): Record<string, unknown>;
/**
 * v0.9.3: client-side ceiling for a single wait. Past it the client does **not keep waiting**; it switches to the job layer and returns a jobId (matching bash's promoted semantics).
 * Default 100 s: the outer run_code default deadline is 120 s, leaving 20 s of headroom for receipts and status queries (the promoted path is just one quick /job query).
 * Raising it = allowing one synchronous wait to last longer (cost: when the outer deadline hits, it is more likely that "the result is on the server but the client cannot get it").
 */
