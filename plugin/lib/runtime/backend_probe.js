/**
 * Backend probing and start decisions — start no longer trusts stale handles/pidfiles: **probe the port for real first**.
 *
 * Field bug: `op=start` only looked at the child-process handle (childAlive); when the handle still exists but the port
 * is not listening at all, it replies "already running (already-spawned)", so the user gets a **backend that cannot be reached**.
 * Here "can it connect" becomes the single source of truth; the handle only decides "should it be cleaned up first".
 */
import net from 'node:net';
/** Real TCP probe: connected means "listening". Lighter than an HTTP probe and unaffected by the host's fetch timeout. */
export function probeTcp(host, port, timeoutMs = 500) {
    return new Promise((resolve) => {
        const sock = new net.Socket();
        let done = false;
        const fin = (v) => {
            if (done)
                return;
            done = true;
            try {
                sock.destroy();
            }
            catch (e) {
                /* ignore */
            }
            resolve(v);
        };
        sock.setTimeout(timeoutMs);
        sock.once('connect', () => fin(true));
        sock.once('timeout', () => fin(false));
        sock.once('error', () => fin(false));
        try {
            sock.connect(port, host);
        }
        catch (e) {
            fin(false);
        }
    });
}
/** HTTP probe: only a 2xx counts as "the backend is really serving" (port open but backend not up ⇒ false). */
export async function probeHttp(url, timeoutMs = 1200) {
    const ac = new AbortController();
    const timer = setTimeout(() => ac.abort(), timeoutMs);
    try {
        const r = await fetch(url, { signal: ac.signal });
        return !!r && r.ok;
    }
    catch (e) {
        return false;
    }
    finally {
        clearTimeout(timer);
    }
}
export function decideStart({ portUp, childAlive, }) {
    if (portUp)
        return 'already-running';
    if (childAlive)
        return 'stale-handle';
    return 'spawn';
}
/** Poll until it can serve (op=start uses this for a real verdict instead of "sleep a fixed time then probe once"). */
export async function waitHttp(url, timeoutMs = 10000, intervalMs = 300) {
    const t0 = Date.now();
    for (;;) {
        if (await probeHttp(url, Math.min(1500, Math.max(300, timeoutMs))))
            return true;
        if (Date.now() - t0 >= timeoutMs)
            return false;
        await new Promise((resolve) => setTimeout(resolve, intervalMs));
    }
}
//# sourceMappingURL=backend_probe.js.map
