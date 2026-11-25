import type { HostRoutesDeps } from './index.js';
/**
 * v2.6.1: response body of GET /host/state (pure memory, zero Blender round trips; any piece that cannot be obtained gets a conservative default, never throws).
 * "AI paused" can only be known after the addon rejects a command (the backend does not poll Blender for it), and one success clears it.
 */
export declare function hostStateView(E: HostRoutesDeps): Record<string, unknown>;
/** Contract §1.6 @-mention data source (GET /host/scene-items) */
export declare function handleSceneItems(E: HostRoutesDeps, url: URL, res: import('node:http').ServerResponse, origin: unknown): Promise<void>;
