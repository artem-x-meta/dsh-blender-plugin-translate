import type { DiskCatalog, PlanFamily } from './data.js';
export declare function planEditDistance(a: string, b: string): number;
/** Nearest-neighbor suggestion for an unknown op (with a minimal skeleton) — turns "wrote it wrong" into "fix it in one step" */
export interface PlanSuggestion {
    op: string;
    distance: number;
    family: string | null;
    skeleton: string | null;
    when: string | null;
}
export declare function planOpSuggestion(opName: unknown): PlanSuggestion | null;
export declare function name0StartsWith(s: unknown, p: string): boolean;
/** rt_cmd cross-channel correction: when a plan op is sent as an addon command, tell it straight away which tool to use (this really happened in practice) */
export declare function planOpCrossChannelHint(addonName: unknown): string | null;
/**
 * The catalog's own content fingerprint — hashes only "what would actually answer" (ordered, order-sensitive).
 * Purpose: ① cross-process comparison (a clean process importing the on-disk engine.mjs must produce an equal catalogHash)
 *          ② turn "did the catalog change" into a comparable 12-digit hex value, instead of "feels like a few families were added".
 */
export interface CatalogFingerprint {
    catalogHash: string;
    families: number;
    opsCount: number;
    toolDetailKeys: number;
    commandCatalogKeys: number;
}
export declare function catalogFingerprint(): CatalogFingerprint;
/** Start a clean node process and import the **on-disk** engine.js facade — only it is the judge of "what the next request will get" */
export declare function probeDiskCatalog(timeoutMs: unknown): DiskCatalog;
/**
 * Compare the content fingerprints of the loaded version and the on-disk version.
 * Reads disk once by default (~0.2 ms); only `verify:true` starts a clean process for the comparison (~120 ms), so you pay on demand.
 */
/** Short rendering of a single family (progressive disclosure: catalog first, then family, then *_help) */
export declare function renderFamilyText(e: PlanFamily): string;
/**
 * Payload of op="catalog". By default it returns **short text only** (≈2–3k characters): for a flash-level model, "short enum + criteria + skeleton" works far better than
 * 4.7k characters of prose; structured detail is only included with args={full:true} (that is for machines/retrospectives).
 *   op="catalog"                         → one catalog page (one line per family + ops + skeleton highlights)
 *   op="catalog", args={family:"sculpt"}  → expand only that family
 *   op="catalog", args={full:true}        → also include structured families/tools
 */
/**
 * Single source of truth: the /plan channel's read-only op allowlist (the only declaration site) (this file is the only declaration site).
 * server.mjs consumes it directly; tests/unit/js/contract/single-source.test.ts compares it name by name against a frozen baseline, catching lost/extra entries during migration.
 * Criteria: does not modify the scene, does not touch object transforms, does not register handlers. Adding a read-only op changes only this one place.
 */
