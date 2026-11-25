import type { EngineApiDeps } from './index.js';
export declare function createFrameApi(E: EngineApiDeps): {
    frameArea(areaIndex?: number): Promise<{
        png: NonSharedBuffer;
        meta: {
            method: string;
            info: string;
        };
    }>;
    /** Grab one viewport PNG frame (overwrites a fixed file) */
    frame(maxSize?: number): Promise<{
        png: NonSharedBuffer;
        meta: unknown;
    }>;
};
