import type { EngineApiDeps } from './index.js';
export declare function createActApi(E: EngineApiDeps): {
    act(code: unknown, timeoutMs?: number, file?: unknown): Promise<{
        ok: boolean;
        executed: boolean;
        ms: number;
        mainThreadMs: number;
        stdout: {};
        stderr: {};
        error: string | null;
        traceback: {} | null;
        sceneEpoch: {} | null;
        file: {} | null;
        marker_missing?: undefined;
    } | {
        ok: boolean;
        executed: boolean;
        ms: number;
        mainThreadMs: number;
        stdout: string;
        stderr: string;
        error: null;
        traceback: null;
        marker_missing: boolean;
        file: {} | null;
        sceneEpoch?: undefined;
    }>;
    /** Generic command passthrough: any addon command name + params (even ones the MCP layer does not expose) */
    cmd(name: unknown, params?: Record<string, unknown>, timeoutMs?: number): Promise<unknown>;
};
