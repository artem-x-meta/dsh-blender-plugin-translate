/** host/backend/process-scan: cross-platform "find this plugin's older backends by command line and stop them" (hot-reload fallback). */
import { execFileSync } from 'node:child_process';
import { readdirSync, readFileSync } from 'node:fs';
import { IS_WIN } from '../../constants.js';
import { serverPidsFromProcRows, winKillPids, winSamePortHolders } from '../runtime-bridge.js';
/**
 * Scan /proc for "backends started by earlier generations of this plugin" and stop them with signal (SIGTERM by default).
 * A hot reload loses the child handle (held by the previous generation's fiber), and the handle alone cannot stop the leftover process -- this is the fallback.
 * v1.0.1: added the signal parameter (a process whose event loop is pinned by synchronous work only answers to SIGKILL).
 */
export function killBackendByCmd(port, signal = 'SIGTERM') {
    const killed = [];
    // issue #51 (win32): neither candidate chain below (/proc, ps -ax) exists on Windows -- the old code
    // silently caught and returned [] all the way, so after op=stop / op=restart the zombie backend still held the port and could never be cleared.
    // It now goes through win_proc: first match command-line ownership (server.js + exact --port), then fall back to "port listener ∩ same image name".
    if (IS_WIN) {
        try {
            return winKillPids(winSamePortHolders(port));
        }
        catch {
            return [];
        }
    }
    // macOS support: "list processes" is abstracted into a portable candidate chain -- /proc exists only on Linux,
    // not on macOS; the old code read /proc only and silently returned [] on mac (leftover backends after a hot reload could not be stopped).
    const rows = [];
    let listed = false;
    // ① Linux: read /proc directly (most accurate, no external dependency)
    try {
        for (const d of readdirSync('/proc')) {
            if (!/^[0-9]+$/.test(d))
                continue;
            if (Number(d) === process.pid)
                continue;
            try {
                const toks = readFileSync('/proc/' + d + '/cmdline', 'utf8')
                    .split(String.fromCharCode(0))
                    .filter(Boolean);
                rows.push({ pid: Number(d), toks });
            }
            catch {
                /* the process may already have exited */
            }
        }
        listed = true;
    }
    catch {
        /* no /proc (macOS/Windows) → use ② */
    }
    // ② macOS / generic POSIX: ps prints pid + full command line
    if (!listed) {
        try {
            for (const line of execFileSync('ps', ['-ax', '-o', 'pid=,command='], {
                encoding: 'utf8',
                timeout: 5000,
            }).split(String.fromCharCode(10))) {
                const m = /^\s*(\d+)\s+(.*)$/.exec(line);
                if (!m)
                    continue;
                const pid = Number(m[1]);
                if (pid === process.pid)
                    continue;
                rows.push({ pid, toks: m[2].trim().split(/\s+/) });
            }
        }
        catch {
            /* no ps available means no fallback */
        }
    }
    for (const pid of serverPidsFromProcRows(rows, port)) {
        try {
            process.kill(pid, signal);
            killed.push(String(pid));
        }
        catch {
            /* already gone */
        }
    }
    return killed;
}
//# sourceMappingURL=process-scan.js.map
