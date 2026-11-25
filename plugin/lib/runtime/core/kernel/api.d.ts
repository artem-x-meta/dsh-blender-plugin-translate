import type { AddonClient } from '../../transport/probes.js';
export interface KernelDeps {
    RENDER_FLAG_WIN: string;
    addon: AddonClient;
    injected: Set<string>;
}
export interface KernelIoDeps {
    addon: AddonClient;
    injected: Set<string>;
}
/** Read a python module source under runtime (used to assemble preload / job scripts) */
export declare function readModuleSource(name: string): string;
/**
 * v0.9.1 (93-B3): script path resolution. headless's `file=` semantics are **.blend** (an old member passing a .py got
 * `File format is not supported`), so now: an explicit `scriptFile=` accepts .py; when `file=` receives a .py it is
 * automatically treated as a script and a hint is given. Both Windows paths (D:\ or \\wsl.localhost\) and WSL paths (/home/...) are accepted.
 */
export declare function readScriptPath(p: unknown): {
    win: string;
    wsl: string;
};
/**
 * v0.9.0: preloading several modules requires each of them to get its own namespace.
 * The old implementation **spliced multiple module sources into the same globals**, and every runtime module defines _j/_kernel/_store/_now ->
 * the next module clobbered the previous module's helpers. Observed: `preload="txn,deliver"` outright crashed txn (KeyError: 'marks').
 * Approach: each module is exec'd into its own dict; private names (starting with _) are not leaked, while public names and common imports are copied back into globals as before
 * (backward compatible: the previous style of calling public functions such as `dsh_loop_start` / `audit_mesh` directly still works).
 * A module's trailing `K.dsh_x_api = {...}` goes through the real dsh_rt_kernel module object -> the API still lands on K.
 */
export declare function preloadChunk(name: unknown): string;
export declare function injectModule(deps: KernelIoDeps, file: string, marker: string, versionExpr?: string, prelude?: string): Promise<boolean>;
export declare function needFile(f: string, what: string): string;
export declare function sceneEpoch(deps: KernelIoDeps): Promise<unknown>;
export declare function createKernelInternals(E: KernelDeps): {
    sceneEpoch: () => Promise<unknown>;
    MODULE_ATTR: Record<string, string>;
    readModuleSource: typeof readModuleSource;
    readScriptPath: typeof readScriptPath;
    preloadChunk: typeof preloadChunk;
    injectModule: (file: string, marker: string, versionExpr?: string, prelude?: string) => Promise<boolean>;
    needFile: typeof needFile;
};
