import type { TrajWriteDeps } from './record.js';
/** Wrap the returned object in a recording layer: this still points at the original object (internal this.xxx() calls are not recorded twice) */
export declare function createTrajectoryWrapper(deps: TrajWriteDeps): (obj: Record<string, unknown>) => Record<string, unknown>;
