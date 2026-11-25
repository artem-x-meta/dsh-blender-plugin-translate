/**
 * Addon protocol - supports only the **flat protocol** of this repo's `DSH Blender Bridge` (since v2.3).
 *
 * History (removed): before v2.0 this also supported the upstream `MCP for Blender` (module `blender_mcp`) and
 * harveyxiacn `blender_mcp_addon` (category-action protocol). Since v2.3, selection/collection/activity
 * all depend on this repo's addon v1.8, and keeping old addon compatibility only left users in a half-broken state
 * ("model tools work, new features never do"), so **old addon support and the dual-name fallback are both removed**; users must use this repo's addon.
 *
 * Protocol shape (flat / no framing):
 *   request   {"type":"get_scene_info","params":{}}
 *   response  {"status":"success","result":{…}} / {"status":"error","message":"…"}
 */
/** Wire shape of an addon request (flat protocol). */
export interface AddonWire {
    type: string;
    params: Record<string, unknown>;
}
/** plan() output: wire is required; local/post are optional protocol hooks (unused by the flat protocol). */
export interface ProtocolPlan {
    wire: AddonWire;
    local?: () => unknown;
    post?: (data: unknown) => unknown;
}
export type ProtocolDecode = {
    ok: true;
    data: unknown;
} | {
    ok: false;
    message: string;
};
export interface AddonProtocol {
    id: string;
    label: string;
    framing: string;
    panelHint: string;
    plan(type: string, params?: Record<string, unknown>): ProtocolPlan;
    encode(wire: AddonWire): string;
    decode(raw: string): ProtocolDecode;
}
/** Protocol descriptor for this repo's addon (the only kind). */
export declare const PROTOCOLS: Record<string, AddonProtocol>;
export declare const PROTOCOL_IDS: string[];
/**
 * Probe once: send a flat ping; any JSON response proves the peer is this repo's addon.
 * @returns {Promise<{id:string, ms:number}|null>} null = addon absent / port unreachable
 */
export declare function detectProtocol(host: string, port: number, timeoutMs?: number): Promise<{
    id: string;
    ms: number;
} | null>;
/** Kept for old call sites (there is no cache any more; the export stays so callers do not break). */
export declare function resetProtocolCache(): void;
/**
 * Get the protocol descriptor actually in use. Flat protocol only - the `prefer` argument exists only for old call sites and is ignored.
 * @returns {Promise<{proto:object, from:'config'}>}
 */
export interface ProtocolInfo {
    proto: AddonProtocol;
    from: string;
    detected?: unknown;
}
export declare function resolveProtocol(_opts?: {
    host?: string;
    port?: number;
    prefer?: string;
    timeoutMs?: number;
}): Promise<ProtocolInfo>;
