export declare const IS_WIN: boolean;
export interface WinProcOptions {
    timeoutMs?: number;
}
/**
 * Parse the LISTENING lines of `netstat -ano -p TCP` and return the PIDs holding the target port (deduplicated, ascending).
 *
 * Real output (Windows 10/11, columns separated by runs of spaces):
 *   TCP    0.0.0.0:9877     0.0.0.0:0      LISTENING     1234
 *   TCP    [::]:9877        [::]:0         LISTENING     5678
 *   TCP    127.0.0.1:9877   127.0.0.1:5013 ESTABLISHED   1234   <- not a listener, ignore
 *
 * * LISTENING only: ESTABLISHED lines also carry a local port, and treating them as "occupants" would drag in servers that are merely connected.
 * * The port must match **exactly**: 9877 must not hit 98770 / 19877.
 */
export declare function parseNetstatListeners(text: string | null | undefined, port: unknown): number[];
/**
 * Parse one line of `tasklist /FO CSV /NH` -> image name (such as `"node.exe"` / `"DeepSeek Harness.exe"`).
 * Returns '' when it cannot parse (callers then skip conservatively: rather not kill than kill by mistake).
 */
export declare function parseTasklistImage(text: string | null | undefined): string;
/** Image name for a PID (tasklist). Returns '' when unavailable. */
export declare function tasklistImageName(pid: unknown, timeoutMs?: number): string;
/**
 * Criterion 1: scan for "this plugin's backend processes" by **command-line ownership** (CIM / Win32_Process).
 * The command line must satisfy both: `server.js` / `server.mjs` appears as a standalone argv entry, and `--port <port>` matches exactly.
 * Consistent with the same self-inflicted lesson on the POSIX side (2026-09-29: substring matching also killed the caller's own shell).
 */
export declare function winServerPidsByCmdline(port: unknown, opts?: WinProcOptions): number[];
/**
 * Criteria 2 + 3: port listeners intersected with (image name == current process image name).
 * Fallback only when 1 is unavailable (PowerShell / CIM blocked by policy); PIDs that fail the ownership criteria are never returned.
 */
export declare function winPortHolderPids(port: unknown, opts?: WinProcOptions): number[];
/** "Same-family backends holding this port" on Windows: command-line ownership first, then port + same image name as fallback. */
export declare function winSamePortHolders(port: unknown): number[];
/**
 * Kill process trees with taskkill. Windows has no graceful SIGTERM (process.kill calls TerminateProcess directly),
 * so `/T /F` is used uniformly: a leftover backend may still own headless children, and killing only the parent leaves orphans.
 * Returns the **PID strings taskkill actually ran on** (same convention as the POSIX killed array).
 */
export declare function winKillPids(pids: ReadonlyArray<unknown>, opts?: WinProcOptions): string[];
