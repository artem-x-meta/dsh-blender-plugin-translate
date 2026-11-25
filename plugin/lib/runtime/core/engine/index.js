import { assembleEngine, createEngineContext } from './assemble.js';
/**
 * Assemble the engine. The only parameter is opts.address (addon address override), same as before the split.
 * Note: no business logic lives here; this only wires each factory onto the same deps object,
 * guaranteeing the closures share one addon / metrics / ledger / jobs (matching the pre-split single-closure semantics).
 */
export function createEngine(opts = {}) {
    const ctx = createEngineContext(opts);
    const { surface, trajectory } = assembleEngine(ctx);
    return trajectory.withTrajectory(surface);
}
//# sourceMappingURL=index.js.map
