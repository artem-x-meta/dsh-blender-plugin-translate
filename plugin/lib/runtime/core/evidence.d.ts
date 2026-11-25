import type { DiskCatalog } from '../catalog/index.js';
declare const RUNTIME_DIR: string;
export declare const PLUGIN_VERSION: string | null;
declare function sha12(buf: string | Buffer): string;
/** Facade entry: candidates for the build layout lib/runtime/engine.js and, under the source layout, the in-package lib/runtime/engine.js */
export declare const ENGINE_SOURCE_PATH: string;
export interface EngineSelf {
    sourcePath: string;
    loadedAt: number;
    loadedAtText: string;
    loadedHash: string | null;
    loadedBytes: number | null;
    error: string | null;
}
export interface PathWarning {
    code: string;
    evidence?: string;
    value?: string;
    hint?: string;
    [k: string]: unknown;
}
export interface DiskVerdict {
    ok: boolean;
    note?: string;
    matchesLoadedCatalog?: boolean;
    families?: number;
    opsCount?: number;
    catalogHash?: string;
    pluginVersion?: unknown;
}
export interface Provenance {
    sourcePath: string;
    pluginVersion: string | null;
    hashAlgo: string;
    loadedAt: string;
    loadedHash: string | null;
    loadedBytes: number | null;
    loadedReadError: string | null;
    currentHash: string | null;
    currentBytes: number | null;
    currentMtime: string | null;
    verdict: 'current' | 'stale' | 'unknown';
    stale: boolean | null;
    staleReason: string | null;
    catalogHash: string;
    families: number;
    opsCount: number;
    toolDetailKeys: number;
    commandCatalogKeys: number;
    note: string;
    diskCatalog?: DiskCatalog;
    diskVerdict?: DiskVerdict;
}
declare const ENGINE_SELF: EngineSelf;
declare function runtimeFingerprint(): Record<string, string>;
declare function pidAlive(pid: unknown): boolean;
declare function pathAudit(stdout: unknown, stderr: unknown): PathWarning[];
export declare function engineProvenance(opts?: unknown): Provenance;
/**
 * v2.6 (feedback #3 this round): multi-light hygiene — a **structured warning** for EEVEE shadow pool overflow.
 *
 * Field case (thousands of lines within 4 hours): 36 lights → the console printed on every frame
 *   Error: Shadow buffer full, may result in missing shadows and lower performance. (3040 / 2048)
 * while scene.eevee.shadow_pool_size = 4096 was **silently ineffective** — it is an enum, and the cap is 2048 (2 GB).
 * Old behavior: the warning flooded stderr and the model had to interpret it; new behavior: it goes into the receipt's warnings[] with a fix that can be pasted straight in.
 */
export declare function sceneHygieneAudit(stdout: unknown, stderr: unknown): PathWarning[];
export { sha12, ENGINE_SELF, RUNTIME_DIR, runtimeFingerprint, pidAlive, pathAudit };
