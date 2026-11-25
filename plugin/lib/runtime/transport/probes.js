// addon transport layer: TCP liveness probe, live diagnostics, protocol info and AddonClient
// @imports
import { ADDRESS } from '../paths.js';
import net from 'node:net';
import { resolveProtocol } from '../addon-protocol.js';
import { CFG } from '../config.js';
import { errorMessage } from '../core/json.js';
export async function tcpProbe(host = ADDRESS.host, port = ADDRESS.port, timeoutMs = 2000) {
    return new Promise((resolve) => {
        const s = net.connect({ host, port });
        let settled = false;
        const done = (ok) => {
            if (settled)
                return;
            settled = true;
            try {
                s.destroy();
            }
            catch (e) { }
            resolve(ok);
        };
        const t = setTimeout(() => done(false), timeoutMs);
        s.once('connect', () => {
            clearTimeout(t);
            done(true);
        });
        s.once('error', () => {
            clearTimeout(t);
            done(false);
        });
    });
}
export async function freshPing(host = ADDRESS.host, port = ADDRESS.port, timeoutMs = 2500) {
    const t0 = Date.now();
    const { proto } = await resolveProtocol({
        host,
        port,
        prefer: 'flat',
        timeoutMs: Math.min(timeoutMs, 1500),
    });
    const plan = proto.plan('ping', {});
    return new Promise((resolve, reject) => {
        const s = net.connect({ host, port });
        let buf = '';
        const t = setTimeout(() => {
            try {
                s.destroy();
            }
            catch (e) { }
            reject(new Error('ping timeout'));
        }, timeoutMs);
        s.once('error', (e) => {
            clearTimeout(t);
            try {
                s.destroy();
            }
            catch (x) { }
            reject(e);
        });
        s.on('data', (d) => {
            buf += d.toString('utf8');
            let r;
            try {
                r = proto.decode(buf.trim());
            }
            catch (e) {
                return;
            } // not a full record yet → keep buffering
            clearTimeout(t);
            try {
                s.destroy();
            }
            catch (e) { }
            if (!r.ok)
                reject(new Error(r.message || 'ping error'));
            else
                resolve(Date.now() - t0);
        });
        s.once('connect', () => s.write(proto.encode(plan.wire)));
    });
}
export async function diagnose() {
    const proto = await resolveProtocol({
        host: ADDRESS.host,
        port: ADDRESS.port,
        prefer: 'flat',
    }).catch(() => null);
    const panel = (proto && proto.proto.panelHint) || '"DSH Blender Bridge" panel → Connect';
    const tcp = await tcpProbe();
    if (!tcp) {
        return {
            kind: 'blender-unreachable',
            tcp: false,
            ping: null,
            summary: 'nothing is listening on port 9876 -- Blender is not running, or the addon is not connected',
            fix: '**the agent route: blender_viewport(op="launch") starts GUI Blender in one go and auto-connects the addon** (since v0.9.4, no human has to click the panel); ' +
                'the manual flow is: start Blender → press N in the 3D view → ' +
                panel +
                ' (the service listens on 127.0.0.1:' +
                String(CFG.addonPort) +
                ')',
            hint: 'TCP ' +
                CFG.addonHost +
                ':' +
                String(CFG.addonPort) +
                ' unreachable: Blender is not running, or the addon panel is not connected. ' +
                'one-click fix: blender_viewport(op="launch") (GUI + automatic Connect, idempotent); manual fix: N → ' +
                panel,
        };
    }
    try {
        const ms = await freshPing();
        return {
            kind: 'main-thread-busy',
            tcp: true,
            ping: true,
            ping_ms: ms,
            summary: 'the addon is alive (ping succeeds) but bpy commands are blocked by the main thread -- it is rendering / in a modal operation / running heavy work',
            fix: 'call again once it is idle; move long renders to blender_rt_headless (separate process, does not hold the GUI channel)',
            hint: 'the addon is alive and ping succeeds, but bpy commands time out → the Blender main thread is busy (rendering / modal operation / heavy work). Wait until it is idle, or move long renders to blender_rt_headless (separate process, does not hold the GUI channel)',
        };
    }
    catch (e) {
        // TCP is up but there is no flat-JSON reply: the addon thread is stuck, or the other side is not this repo addon at all.
        return {
            kind: 'addon-thread-stuck',
            tcp: true,
            ping: false,
            error: errorMessage(e),
            summary: 'the port is open but ping gets no reply -- the addon client thread is stuck, or the installed addon is not this repo "DSH Blender Bridge"',
            fix: 'do not fire more calls; wait for it to finish (in agent mode blender_rt_loop op=stop can emergency-stop it), and restart Blender if it still does not respond. ' +
                'If Blender has the old single-file addon or the old "MCP for Blender" installed, neither is supported any more: switch to addon/dsh_blender_bridge.zip (v1.11)',
            hint: 'TCP is up but ping gets no reply → the addon thread is stuck, or what is installed is not this repo addon; only DSH Blender Bridge v1.11+ (the zip package) is supported',
        };
    }
}
export async function protocolInfo() {
    try {
        const r = await resolveProtocol({ host: ADDRESS.host, port: ADDRESS.port, prefer: 'flat' });
        return {
            id: r.proto.id,
            label: r.proto.label,
            from: r.from,
            detected: r.detected || null,
            configured: 'flat',
        };
    }
    catch (e) {
        return { id: null, error: errorMessage(e), configured: 'flat' };
    }
}
export class AddonClient {
    addr;
    sock;
    queue;
    buf;
    pending;
    proto; // resolved on first use (explicit config → taken directly; auto → probe once and cache)
    protocolInfo;
    _seq;
    constructor(addr = ADDRESS) {
        this.addr = addr;
        this.sock = null;
        this.queue = Promise.resolve();
        this.buf = '';
        this.pending = null;
        this.proto = null;
        this.protocolInfo = null;
        this._seq = 0;
    }
    async protocol() {
        if (!this.proto) {
            const info = await resolveProtocol({
                host: this.addr.host,
                port: this.addr.port,
                prefer: 'flat',
            });
            this.protocolInfo = info;
            this.proto = info.proto;
            return info;
        }
        return this.protocolInfo;
    }
    connect(timeoutMs = 4000) {
        return new Promise((resolve, reject) => {
            const s = net.connect({ host: this.addr.host, port: this.addr.port });
            const t = setTimeout(() => {
                s.destroy();
                reject(new Error('connect timeout'));
            }, timeoutMs);
            s.once('connect', () => {
                clearTimeout(t);
                this.sock = s;
                resolve(true);
            });
            s.once('error', (e) => {
                clearTimeout(t);
                this.sock = null;
                reject(e);
            });
            s.on('data', (d) => this._onData(d));
            s.on('close', () => {
                this.sock = null;
                if (this.pending) {
                    this.pending.reject(new Error('socket closed'));
                    this.pending = null;
                }
            });
        });
    }
    _onData(d) {
        this.buf += d.toString('utf8');
        if (!this.pending)
            return;
        const proto = this.pending.proto;
        let r;
        try {
            r = proto.decode(this.buf.trim());
        }
        catch (e) {
            return;
        } // not fully received → keep buffering
        this.buf = '';
        const p = this.pending;
        this.pending = null;
        clearTimeout(p.timer);
        if (!r.ok) {
            p.reject(new Error(r.message));
            return;
        }
        try {
            p.resolve(p.post ? p.post(r.data) : r.data);
        }
        catch (err) {
            p.reject(err instanceof Error ? err : new Error(errorMessage(err)));
        }
    }
    async ensure() {
        if (!this.sock)
            await this.connect();
    }
    send(type, params = {}, timeoutMs = 120000, _opts) {
        const run = async () => {
            const info = await this.protocol();
            const proto = info.proto;
            const plan = proto.plan(type, params); // may throw: unknown command / missing parameters
            if (plan.local)
                return plan.local(); // a local stub (telemetry / integration status) does not take the socket
            await this.ensure();
            return new Promise((resolve, reject) => {
                const timer = setTimeout(() => {
                    this.pending = null;
                    this.buf = '';
                    reject(new Error('addon timeout: ' + type));
                }, timeoutMs);
                this.pending = {
                    resolve: resolve,
                    reject: reject,
                    timer: timer,
                    post: plan.post,
                    proto: proto,
                };
                this.sock?.write(proto.encode(plan.wire));
            });
        };
        const p = this.queue.then(run, run);
        this.queue = p.catch(() => { });
        return p;
    }
    close() {
        if (this.sock) {
            this.sock.end();
            this.sock = null;
        }
    }
}
//# sourceMappingURL=probes.js.map
