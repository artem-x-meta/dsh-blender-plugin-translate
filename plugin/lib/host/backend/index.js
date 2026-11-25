/** host/backend shared entry: port resolution, health probe, start/self-heal, timeout wrapper and the pause switch. */
import { readFileSync } from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { ABORT_HINT, HERE, HOSTNAME } from '../../constants.js';
import { asRecord } from '../../contracts/dynamic.js';
import { execSignal } from '../exec-context.js';
import { decideStart, probeHttp } from '../runtime-bridge.js';
import { childAlive, killStaleChild, spawnChild } from './spawn.js';
export { childAlive, getChild, killChildHandle, spawnChild } from './spawn.js';
export { killBackendByCmd } from './process-scan.js';
/**
 * Port resolution (same source chain as runtime/config.ts, so the two configs cannot drift):
 *   plugin config port → DSH_BLENDER_HTTP_PORT → $DSH_BLENDER_CONFIG → <package root>/dsh-blender.config.json
 *   → ~/.dsh/dsh-blender.config.json → 9877
 */
export function resolveHttpPort() {
    const env = Number(process.env.DSH_BLENDER_HTTP_PORT);
    if (Number.isFinite(env) && env > 0)
        return env;
    const cands = [
        process.env.DSH_BLENDER_CONFIG,
        path.join(HERE, '..', 'dsh-blender.config.json'),
        path.join(os.homedir(), '.dsh', 'dsh-blender.config.json'),
    ].filter((p) => Boolean(p));
    for (const p of cands) {
        try {
            const j = asRecord(JSON.parse(readFileSync(p, 'utf8')));
            const n = Number(j.httpPort);
            if (Number.isFinite(n) && n > 0)
                return n;
        }
        catch {
            /* no such file, or not JSON: skip */
        }
    }
    return 9877;
}
/** The user stopped it explicitly with op=stop → the watchdog no longer auto-starts it (op=start clears this) */
let paused = false;
export function base(port) {
    return 'http://' + HOSTNAME + ':' + String(port);
}
export const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
export async function probe(port, timeoutMs = 1500) {
    const ac = new AbortController();
    const timer = setTimeout(() => ac.abort(), timeoutMs);
    try {
        const r = await fetch(base(port) + '/health', { signal: ac.signal });
        return r.ok;
    }
    catch {
        return false;
    }
    finally {
        clearTimeout(timer);
    }
}
export async function ensureBackend(port) {
    if (await probe(port))
        return true;
    if (paused)
        return false;
    // Test-only guard: contract tests exercise the unreachable-backend path on a
    // closed port; never spawn a real server from inside the unit/integration suite.
    if (process.env.DSH_BLENDER_TEST_NO_SPAWN === '1')
        return false;
    try {
        await startBackend(port);
    }
    catch {
        /* ignore */
    }
    for (let i = 0; i < 25; i++) {
        if (await probe(port))
            return true;
        await sleep(300);
    }
    return false;
}
/**
 * Fix: **probe the port first**, stop trusting stale handles/pidfiles.
 * Field bug: when the handle was still there (childAlive) but nothing was listening on the port, the old implementation answered 'already-spawned',
 * handing the user a backend they could not reach; conversely a real start answered 'start failed' because the wait window was too short.
 * Now: the port serves ⇒ already-running; the port is dead but the handle exists ⇒ judged a stale handle, SIGTERM then respawn.
 */
export async function startBackend(port) {
    const url = base(port) + '/health';
    const portUp = await probeHttp(url, 800);
    const decision = decideStart({ portUp, childAlive: childAlive() });
    if (decision === 'already-running')
        return 'already-running';
    if (decision === 'stale-handle') {
        const stalePid = killStaleChild();
        return 'stale-handle(pid=' + String(stalePid) + ')->' + spawnChild(port);
    }
    return spawnChild(port);
}
/**
 * v0.9.2: merge "the plugin's own timeout" with "the host exec.signal".
 * Both only affect **waiting**: a Blender-side task the server already started still runs to completion (existing headless/job semantics
 * = client disconnect ≠ task failure, reclaimed by runId).
 */
export async function withTimeout(path, init, timeoutMs) {
    const ac = new AbortController();
    const ext = execSignal();
    let fired = false;
    const timer = setTimeout(() => {
        fired = true;
        ac.abort();
    }, timeoutMs);
    const signal = ext ? AbortSignal.any([ext, ac.signal]) : ac.signal;
    try {
        return await fetch(path, { ...(init || {}), signal });
    }
    catch (e) {
        if (!fired && ext && ext.aborted)
            throw new Error(ABORT_HINT, { cause: e });
        throw e;
    }
    finally {
        clearTimeout(timer);
    }
}
/** The user stopped it explicitly with op=stop → the watchdog no longer auto-starts it (op=start clears this). Read and written through an accessor across modules so there is exactly one live state. */
export function isPaused() {
    return paused;
}
export function setPaused(v) {
    paused = v;
}
//# sourceMappingURL=index.js.map