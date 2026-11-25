export interface LaunchOpts {
    addonPort?: unknown;
    waitMs?: unknown;
    exe?: unknown;
    file?: unknown;
    force?: unknown;
    interop?: unknown;
    addonFile?: unknown;
    addonModule?: unknown;
    dryRun?: unknown;
    [k: string]: unknown;
}
export declare function tryLaunchAgent(opts: LaunchOpts, addonPort: number, steps: string[], base: Record<string, unknown>): Promise<Record<string, unknown> | null>;
/**
 * **Name hints** for automatic addon detection: only this repo's `DSH Blender Bridge` (module `dsh_blender_bridge`, prefix `dshbb_*`).
 * Since v2.3 the old `MCP for Blender` (module `blender_mcp`) is no longer scanned or supported.
 * In LAUNCH_BOOT_PY it is inlined via JSON.stringify as **the same** list; `addonNameHit()` is its JS mirror with identical semantics (for tests).
 */
export declare const ADDON_NAME_HINTS: string[];
/** JS check with the same semantics as `_name_hit()` in LAUNCH_BOOT_PY (lowercase substring hit) - for tests */
export declare function addonNameHit(name: unknown): boolean;
/** Source of the boot script injected into Blender (exported so self-checks can assert "the Python written to disk really hits both names") */
export declare const LAUNCH_BOOT_PY: string;
