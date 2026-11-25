/**
 * addon protocol — supports only this repo's `DSH Blender Bridge` **flat protocol** (since v2.3).
 *
 * History (removed): before v2.0 the upstream `MCP for Blender` (module `blender_mcp`) and
 * harveyxiacn `blender_mcp_addon` (category-action protocol) were also supported. Since v2.3
 * selection/collections/activity all depend on this repo's addon v1.8, and keeping compatibility
 * with the old addon only left users in a half-broken state where "the model's tools work, new
 * features never do", so **support for the old addon and the dual-name fallback were removed
 * entirely**; users must use this repo's addon.
 *
 * Protocol shape (flat / unframed):
 *   request   {"type":"get_scene_info","params":{}}
 *   response  {"status":"success","result":{…}} / {"status":"error","message":"…"}
 */
import net from 'node:net';
/** This repo's addon protocol descriptor (the only one). */
export const PROTOCOLS = {
    flat: {
        id: 'flat',
        label: 'direct addon · flat protocol (unframed; measured: both v1.7/v1.8 work — for the live version see rt_cmd get_addon_info)',
        framing: 'none',
        panelHint: '"DSH Blender Bridge" panel → Connect',
        plan(type, params) {
            return { wire: { type: type, params: params || {} } };
        },
        encode(wire) {
            return JSON.stringify(wire);
        },
        decode(raw) {
            const o = JSON.parse(raw);
            if (o.status === 'error')
                return { ok: false, message: String(o.message || 'addon error') };
            return { ok: true, data: o.result === undefined ? {} : o.result };
        },
    },
};
export const PROTOCOL_IDS = Object.keys(PROTOCOLS);
/**
 * Probe once: send a flat ping; a JSON reply proves the other side is this repo's addon.
 * @returns {Promise<{id:string, ms:number}|null>} null = addon absent / port unreachable
 */
export async function detectProtocol(host, port, timeoutMs = 1000) {
    const t0 = Date.now();
    const proto = PROTOCOLS.flat;
    return new Promise((resolve) => {
        const s = net.connect({ host: host, port: port });
        let buf = '';
        let settled = false;
        const done = (v) => {
            if (settled)
                return;
            settled = true;
            clearTimeout(t);
            try {
                s.destroy();
            }
            catch (e) {
                /* ignore */
            }
            resolve(v);
        };
        const t = setTimeout(() => done(null), timeoutMs);
        s.once('connect', () => {
            try {
                s.write(proto.encode(proto.plan('ping', {}).wire));
            }
            catch (e) {
                done(null);
            }
        });
        s.once('error', () => done(null));
        s.on('data', (d) => {
            buf += d.toString('utf8');
            try {
                JSON.parse(buf.trim());
                done({ id: 'flat', ms: Date.now() - t0 });
            }
            catch (e) {
                /* keep buffering */
            }
        });
    });
}
/** Kept for old call sites (there is no cache any more; the export is kept so callers do not break). */
export function resetProtocolCache() {
    /* no-op */
}
export async function resolveProtocol(_opts) {
    return { proto: PROTOCOLS.flat, from: 'config' };
}
//# sourceMappingURL=addon-protocol.js.map