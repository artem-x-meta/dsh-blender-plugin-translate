/** host/backend/spawn: child-process handle and lifecycle (the issue #51 win32 trio is centralised here). */
import { spawn } from 'node:child_process';
import { SERVER_PATH } from '../../constants.js';
import { winKillPids } from '../runtime-bridge.js';
let child = null;
/** Whether the child is really still alive: when killed by a signal exitCode stays null and only signalCode has a value */
export function childAlive() {
    return !!(child && child.exitCode === null && child.signalCode === null && child.pid);
}
export function spawnChild(port) {
    // issue #51 (win32 host): all three must be set explicitly; inheriting them from the environment is not enough.
    //   ① ELECTRON_RUN_AS_NODE: when the host runs inside Electron, process.execPath is the **GUI executable**,
    //      and without this variable it starts another GUI instance (or is swallowed by the single-instance lock) instead of a node child;
    //   ② windowsHide: a console-subsystem executable allocates a new console when the "host has no console" (same family as #38/#43);
    //   ③ detached: equivalent to DETACHED_PROCESS on win32, so the backend outlives host exit (established semantics).
    const spawned = spawn(process.execPath, [SERVER_PATH, '--port', String(port)], {
        env: { ...process.env, ELECTRON_RUN_AS_NODE: '1' },
        stdio: 'ignore',
        detached: true,
        windowsHide: true,
    });
    child = spawned;
    // ★ Attach the listener first, then unref: a spawn failure (EPERM / EACCES / ENOENT) arrives as an **asynchronous 'error' event**.
    //   With no listener it bubbles up to the host's uncaughtException — in the field (#51) this showed up as dsh-desktop-host being
    //   killed outright every 15 s (retried whenever ENSURE_INTERVAL_MS fires), leaving a stray backend holding the port.
    //   With a listener the failure only degrades to "backend unavailable" and the host keeps running.
    spawned.on('error', (err) => {
        if (child === spawned)
            child = null;
        try {
            console.error('[dsh-blender] Backend child process failed to start (degraded, host unaffected): ' + err.message);
        }
        catch {
            /* Logging failures must not affect the main flow */
        }
    });
    spawned.on('exit', () => {
        if (child === spawned)
            child = null;
    });
    spawned.unref();
    return 'spawned pid=' + String(spawned.pid);
}
/** stale-handle branch: handle exists but the port is dead → stop the untrustworthy old handle per platform and return its pid. */
export function killStaleChild() {
    const stalePid = child?.pid;
    if (!stalePid)
        return null;
    try {
        if (process.platform === 'win32')
            winKillPids([stalePid]);
        else
            process.kill(stalePid, 'SIGTERM');
    }
    catch {
        /* already gone */
    }
    child = null;
    return stalePid;
}
export function getChild() {
    return child;
}
/** Kill and clear the current child handle; returns whether a handle existed (the caller writes the receipt from it). */
export function killChildHandle() {
    if (!child)
        return false;
    try {
        child.kill();
    }
    catch {
        /* already exited */
    }
    child = null;
    return true;
}
//# sourceMappingURL=spawn.js.map