import type { EngineApiDeps } from './index.js';
export declare function createHostApi(E: EngineApiDeps): {
    hostSceneItems(spec?: Record<string, unknown>): Promise<Record<string, unknown>>;
    /**
     * Connect the persistent socket at startup.
     *
     * Fix (serial tax): the first version also fired a "best effort", un-awaited `get_addon_info` here.
     * AddonClient requests go through a **serial queue** (queue.then(run) in transport/probes.ts), so this un-awaited probe
     * occupied the queue head for up to its 3s timeout - the /status and /doctor calls right after it had to queue behind it
     * and their budgets were squeezed to 3.5s/3s. That probe's result was never used and the connection itself comes from
     * ensure(); removing it means the serial queue no longer pays tax for startup probing (lifecycle's failure diagnose has its own job).
     */
    start(): Promise<boolean>;
    stop(): void;
};
