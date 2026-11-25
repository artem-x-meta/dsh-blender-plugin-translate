import type { EngineApiDeps } from './index.js';
/**
 * addon-side stage budgets. The host's backendJson defaults to 20s and T.commands has a static deadline of 60s;
 * the budgets here must land before the host's, otherwise the model only gets "aborted" and no structured diagnosis.
 */
/**
 * Budget for /status's bpy round trip (REGION_CODE): 5s — the honest value after the fix (startup probing no longer takes the head of the serial queue;
 * before the fix it could only get 3.5s). Note that installAddonSend runs one more diagnose() after a transport
 * error (about 2.5s on a half-open addon), so this cannot sit right up against the host's 20s; keep enough headroom (half-open steady state ≈5s + 2.5s).
 */
export declare const ADDON_STATUS_TIMEOUT_MS = 5000;
/** /doctor's status stage budget: 4s (callback after the fix; half-open case ≈4s + reused diagnosis ≈2.5s, still <10s target). */
export declare const ADDON_DOCTOR_STATUS_TIMEOUT_MS = 4000;
/** /commands' FLAGS + 5 integrations must fit entirely inside the client budget: 15s + 5×(3s+~2.5s diagnosis)≈42.5s < 45s client < 60s host. */
export declare const ADDON_FLAGS_TIMEOUT_MS = 15000;
/** /commands per-integration status budget (5 in series; each failure also runs one more ~2.5s diagnosis, hence 3s). */
export declare const ADDON_INTEGRATION_TIMEOUT_MS = 3000;
/** Whether this is a "no addon reply" kind of error (timeout/aborted): attributes the failure to the addon/bpy rather than the backend process. */
export declare function isAddonTimeout(e: unknown): boolean;
export declare function statusView(E: EngineApiDeps, opts?: {
    addonTimeoutMs?: number;
}): Promise<Record<string, unknown>>;
/**
 * (PR review): attribution when the addon explicitly returned an error (not a timeout).
 * Such a failure means the channel is there (TCP is up, the addon responds); do not attribute it to main-thread-busy / blender-unreachable.
 */
export declare function addonErrorDiagnosis(error: string): Record<string, unknown>;
export declare function createDoctorApi(E: EngineApiDeps): {
    protocol(): Promise<import("../../transport/probes.js").ProtocolInfoView>;
    /** Live health check: really run one bpy round trip (status); ok only if it succeeds, otherwise fall through to the three-level verdict */
    doctor(): Promise<Record<string, unknown>>;
    /** 3D viewport region rect / window size / shading mode */
    status(): Promise<Record<string, unknown>>;
    commands(): Promise<{
        scene: unknown;
        file: unknown;
        total: number;
        available: string[];
        disabled: string[];
        gates: Record<string, unknown>;
        integrations: Record<string, unknown>;
    }>;
};
