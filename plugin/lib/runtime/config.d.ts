/**
 * Package root: there are two layouts, source and build, and both must be able to find package.json / dsh-blender.config.json:
 * - Source layout: <pkg>/runtime/config.ts -> the parent of HERE is the package root
 * - Build layout: <pkg>/lib/runtime/config.js -> the package root is two levels up (lib/ sits in between)
 */
export declare const PKG_ROOT: string;
export declare const IS_WIN: boolean;
/** macOS: host and Blender run on the same machine and OS, so there is no cross-OS path problem like Windows/WSL */
export declare const IS_MAC: boolean;
/**
 * Whether we are really running inside WSL (rather than native Linux) -- issue #11.
 *
 * Why this needs its own check: `wslToWin()` used to only distinguish Windows / macOS and treated
 * everything else as "Linux host => WSL + Blender on Windows", mapping host absolute paths to
 * `\\wsl.localhost\<distro>\…`. On native Linux, Blender and the host share the same machine and OS
 * (isomorphic, just like macOS), so that mapping makes Blender treat the string as a **relative path**,
 * the artifacts land in a literal backslash directory, and the backend reading the original path then hits
 * ENOENT => `blender_rt_see` always reports `frame http 502`.
 *
 * Detection: environment variables take priority (always present in an interactive WSL); otherwise fall back
 * to /proc/version -- when dsh runs inside a systemd service it does **not inherit** `WSL_DISTRO_NAME`
 * (issue #6 in the field), but that machine really is WSL and must not be misdetected as native Linux.
 * Kept as a pure function so the detection rule can be compared on **any platform** (tests/unit/js/platform-paths.test.ts [1]).
 */
export declare function detectWsl(platform: string, env: Record<string, string | undefined> | undefined, procVersion: unknown): boolean;
export declare const IS_WSL: boolean;
/** WSL distro name (used to build UNC paths); on non-WSL platforms only used for diagnostics display, see linuxDistroName() */
export declare const DISTRO: string;
/** Native Linux distro name (only feeds the display field of /doctor; WSL uses DISTRO) */
export declare function linuxDistroName(): string;
export declare const CONFIG_FILES: string[];
/** Windows path -> WSL path (D:\a\b -> /mnt/d/a/b; UNC -> /…; returned as-is on Windows) */
export declare function winToWsl(p: unknown): string;
/**
 * Host path -> a path usable on the Blender process side.
 *   Windows     -> backslash-normalized (as-is)
 *   WSL         -> /mnt/x/... -> X:\...; inside WSL -> \\wsl.localhost\<distro>\...
 *   native Linux -> **identity** (host and Blender share the same machine and OS, so no cross-OS rewrite, same as macOS) -- issue #11
 *   macOS       -> identity
 */
export declare function wslToWin(p: unknown): string;
export interface PathShare {
    shared: boolean | null;
    why: string;
    source?: string;
    fstype?: string;
    mount?: string;
}
export declare function wslPathShared(p: unknown): PathShare;
interface WorkDirFallback {
    requested: string;
    requestedFrom: string;
    why: string;
    used: string;
    usedFrom: string;
    errs: string[];
}
/** Final config (computed once, module-level constant) */
export declare const CFG: {
    addonHost: string;
    addonPort: number;
    httpPort: number;
    /**
     * Windows-side launch agent (default 127.0.0.1:9878).
     * WSL uses it to start GUI Blender => 0 interop calls for this launch, avoiding the relay idle leak of
     * microsoft/WSL#41173 (the Interop thread pegs a full core and cannot be released).
     * When the agent is offline it falls back to the old interop spawn; set it to "off" to force the fallback.
     */
    launchAgentUrl: string;
    holder: string;
    leaseTtlMs: number;
    workDirWin: string;
    workDirWsl: string;
    /** workDir probe-write result and fallback trace (null = the original candidate is writable; non-null = fell back, see errs) */
    workDirFallback: WorkDirFallback | null;
    workDirWritable: boolean;
    blenderExe: string | null;
    /** User Blender config directory (where the GPU preferences live): headless processes cannot read it by default -> set this to inherit it (together with factory_startup=false) */
    blenderUserConfig: string | null;
    blenderUserScripts: string | null;
    /** Local port of the hot headless worker (kept distinct from addon 9876 / backend 9877) */
    workerPort: number;
    source: {
        configFile: string | null;
        workDir: string;
        blenderExe: string;
    };
};
export declare const PATHS: {
    livePngWin: string;
    livePngWsl: string;
    viewPngWin: string;
    viewPngWsl: string;
};
/** Config summary (printed for self-check/troubleshooting; blender_rt_headless also uses it to hint when the exe is missing)
 *  over.httpPort: the port the backend actually listens on (the command line --port overrides the configured value, so the summary must follow it) */
export declare function describeConfig(over?: {
    httpPort?: number | string;
}): {
    platform: NodeJS.Platform;
    distro: string | null;
    addon: string;
    http: string;
    workDir: {
        win: string;
        wsl: string;
        from: string;
        fallback: WorkDirFallback | null;
        shared: PathShare;
    };
    blenderExe: string | null;
    blenderFrom: string;
    blenderUserConfig: string | null;
    blenderUserScripts: string | null;
    workerPort: number;
    configFile: string | null;
    holder: string;
    leaseTtlMs: number;
    env: {
        DSH_BLENDER_WORKDIR: string | null;
        DSH_BLENDER_EXE: string | null;
        DSH_BLENDER_HTTP_PORT: string | null;
        DSH_BLENDER_ADDON_PROTOCOL: string | null;
        DSH_BLENDER_CONFIG: string | null;
    };
};
export {};
