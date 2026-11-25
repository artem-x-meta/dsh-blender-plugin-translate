/**
 * runtime/win_proc.ts — primitives for "process / port occupancy" on Windows (issue #51).
 *
 * Background: cleaning up leftover backends used to be POSIX-only — Linux reads /proc, macOS uses `ps -ax`.
 * Windows has neither, so `killBackendByCmd` (host-side stop/restart) and
 * `samePortHolders` (backend EADDRINUSE self-healing) **silently returned []** on win32:
 * after op=stop / op=restart a zombie backend still held 9877 (or a custom port) and nothing cleaned it up.
 *
 * Three criteria are provided here, **ordered by reliability** (callers use them in this order too):
 *   ① Command-line ownership (CIM / Win32_Process): the command line contains `server.js` and `--port <n>` matches exactly
 *      — the only criterion that never kills the wrong thing, and the one that must pass before any kill;
 *   ② Port listener (`netstat -ano`): gives the PID holding the port, but it **must** then be filtered by image name;
 *   ③ Process image name (`tasklist`): provides the ownership filter for ② — only an executable with the **same name**
 *      as the current process is accepted (the win32 backend is launched via process.execPath), so another program
 *      holding a port with the same name is not killed.
 *
 * Conventions: on non-Windows platforms always return an empty array (callers keep their own POSIX path);
 *       every child-process call passes `windowsHide: true` (same family of conventions as issue #38 / #43);
 *       the parsers are pure functions, so the unit tests do not need Windows (tests/unit/js/win-spawn.test.ts).
 */
import { execFileSync } from 'node:child_process';
import path from 'node:path';
export const IS_WIN = process.platform === 'win32';
function timeoutOption(value, fallback, min, max) {
    return Math.max(min, Math.min(max, Number(value) || fallback));
}
/**
 * Parse the LISTENING lines of `netstat -ano -p TCP` and return the PIDs holding the target port (deduplicated, ascending).
 *
 * Real output (Windows 10/11, columns separated by runs of spaces):
 *   TCP    0.0.0.0:9877     0.0.0.0:0      LISTENING     1234
 *   TCP    [::]:9877        [::]:0         LISTENING     5678
 *   TCP    127.0.0.1:9877   127.0.0.1:5013 ESTABLISHED   1234   ← not a listener, ignore
 *
 * ★ Only LISTENING counts: ESTABLISHED lines also carry the local port, and treating them as "occupants" would drag the server side of a normal connection in.
 * ★ The port must match **exactly**: 9877 must not match 98770 / 19877.
 */
export function parseNetstatListeners(text, port) {
    const want = Number(port);
    const pids = new Set();
    if (!Number.isInteger(want) || want <= 0)
        return [];
    for (const rawLine of String(text == null ? '' : text).split(/\r?\n/)) {
        const cols = rawLine.trim().split(/\s+/);
        if (cols.length < 5)
            continue;
        if (!/^TCP$/i.test(cols[0]))
            continue;
        if (!/^LISTENING$/i.test(cols[3]))
            continue;
        const m = /:(\d+)$/.exec(cols[1]); // handles both "0.0.0.0:9877" and "[::]:9877"
        if (!m || Number(m[1]) !== want)
            continue;
        const pid = Number(cols[4]);
        if (Number.isInteger(pid) && pid > 0 && pid !== process.pid)
            pids.add(pid);
    }
    return [...pids].sort((a, b) => a - b);
}
/**
 * Parse one line of `tasklist /FO CSV /NH` → image name (like `"node.exe"` / `"DeepSeek Harness.exe"`).
 * Returns '' when it cannot be parsed (callers then skip conservatively: better not to kill than to kill the wrong thing).
 */
export function parseTasklistImage(text) {
    const line = String(text == null ? '' : text).split(/\r?\n/)[0] || '';
    const m = /^"([^"]*)"/.exec(line.trim());
    return m ? m[1] : '';
}
/** Image name of a PID (tasklist). Returns '' when unavailable. */
export function tasklistImageName(pid, timeoutMs = 3000) {
    if (!IS_WIN)
        return '';
    const id = Number(pid);
    if (!Number.isInteger(id) || id <= 0)
        return '';
    try {
        const out = execFileSync('tasklist.exe', ['/FI', 'PID eq ' + String(id), '/FO', 'CSV', '/NH'], {
            encoding: 'utf8',
            timeout: timeoutOption(timeoutMs, 3000, 1000, 15000),
            windowsHide: true,
            stdio: ['ignore', 'pipe', 'ignore'],
        });
        return parseTasklistImage(out);
    }
    catch {
        return '';
    }
}
/**
 * Criterion ①: scan for "this plugin's backend processes" by **command-line ownership** (CIM / Win32_Process).
 * The command line must satisfy both: `server.js` / `server.mjs` appears as its own argv entry, and `--port <port>` matches exactly.
 * Consistent with the same self-inflicted lesson on the POSIX side (2026-09-29: substring matching also killed the caller's own shell).
 */
export function winServerPidsByCmdline(port, opts = {}) {
    if (!IS_WIN)
        return [];
    const p = String(Math.trunc(Number(port)));
    if (!/^\d+$/.test(p))
        return [];
    const timeoutMs = timeoutOption(opts.timeoutMs, 8000, 2000, 15000);
    const script = [
        '$ErrorActionPreference = "SilentlyContinue";',
        'Get-CimInstance Win32_Process |',
        "Where-Object { $_.ProcessId -ne $PID -and $_.CommandLine -and $_.CommandLine -match '(server\\.(mjs|js))' -and $_.CommandLine -match '--port\\s+" +
            p +
            "(\\s|$)' } |",
        'ForEach-Object { [string]$_.ProcessId }',
    ].join(' ');
    try {
        const out = execFileSync('powershell.exe', ['-NoProfile', '-NonInteractive', '-Command', script], {
            encoding: 'utf8',
            timeout: timeoutMs,
            windowsHide: true,
            stdio: ['ignore', 'pipe', 'ignore'],
        });
        const pids = [];
        for (const line of String(out).split(/\r?\n/)) {
            const n = Number(line.trim());
            if (Number.isInteger(n) && n > 0 && n !== process.pid)
                pids.push(n);
        }
        return [...new Set(pids)].sort((a, b) => a - b);
    }
    catch {
        return [];
    }
}
/**
 * Criteria ② + ③: port listeners ∩ (image name == the current process's image name).
 * Used only as a fallback when ① is unavailable (PowerShell / CIM blocked by policy); PIDs that fail the ownership criterion are never returned.
 */
export function winPortHolderPids(port, opts = {}) {
    if (!IS_WIN)
        return [];
    const timeoutMs = timeoutOption(opts.timeoutMs, 4000, 1000, 10000);
    let text;
    try {
        text = execFileSync('netstat.exe', ['-ano', '-p', 'TCP'], {
            encoding: 'utf8',
            timeout: timeoutMs,
            windowsHide: true,
            stdio: ['ignore', 'pipe', 'ignore'],
        });
    }
    catch {
        return [];
    }
    const want = path.basename(process.execPath).toLowerCase();
    const out = [];
    for (const pid of parseNetstatListeners(text, port)) {
        const image = tasklistImageName(pid).toLowerCase();
        if (image && image === want)
            out.push(pid);
    }
    return out;
}
/** On Windows, "same-family backends holding this port": command-line ownership first, then port + same-name image as a fallback. */
export function winSamePortHolders(port) {
    if (!IS_WIN)
        return [];
    const byCmd = winServerPidsByCmdline(port);
    if (byCmd.length)
        return byCmd;
    return winPortHolderPids(port);
}
/**
 * Kill the process tree with taskkill. Windows has no graceful SIGTERM (process.kill calls TerminateProcess directly),
 * so `/T /F` is used uniformly here: a leftover backend may still have child headless processes, and killing only the parent leaves orphans.
 * Returns the **PID strings for which taskkill actually ran** (same caliber as the POSIX killed array).
 */
export function winKillPids(pids, opts = {}) {
    const out = [];
    if (!IS_WIN)
        return out;
    const timeoutMs = timeoutOption(opts.timeoutMs, 5000, 1000, 15000);
    for (const raw of pids || []) {
        const pid = Number(raw);
        if (!Number.isInteger(pid) || pid <= 0 || pid === process.pid)
            continue;
        try {
            execFileSync('taskkill.exe', ['/PID', String(pid), '/T', '/F'], {
                stdio: 'ignore',
                timeout: timeoutMs,
                windowsHide: true,
            });
            out.push(String(pid));
        }
        catch {
            /* already exited / insufficient permission: treat as "not killed" and let the caller report it */
        }
    }
    return out;
}
//# sourceMappingURL=win_proc.js.map