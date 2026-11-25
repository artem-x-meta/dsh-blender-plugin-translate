// runtime/engine.ts — public facade (one of the two public facades allowed by finalization §1.1.2).
// Behavior frozen: this file only re-exports; the implementation lives in core/, execution/, transport/.
//
// Convergence rule: keep only the names consumed inside the repo **through the build output path lib/runtime/engine.js** —
// the parity probes of check-build / check-parity / install-smoke / catalog/logic.ts, plus the few
// tests that import the facade directly. Internal implementation code always imports concrete modules
// and never goes through this file.
// Adding/removing an export first requires editing the registry config/facades.json (check-no-shims rejects unregistered exports).
export { PLUGIN_VERSION, engineProvenance } from './core/evidence.js';
export { COMMAND_CATALOG, PLAN_CATALOG, TOOL_DETAIL, PLAN_TOOL_MAP, planOpNames, planOpSuggestion, planOpCrossChannelHint, catalogFingerprint, PLAN_READ_ONLY_OPS, PLAN_READ_ONLY, } from './catalog/index.js';
export { MODELING_CLASS_GUIDE, renderClassText, classGuideStats, renderHandoff, MODEL_FACING_TOOLS, } from './classes.js';
export { catalogPayload } from './core/output/index.js';
export { GATE_FLAGS, FLAGS_CODE } from './core/flags.js';
export { PATH_GUARD } from './core/scripts.js';
export { createEngine } from './core/engine/index.js';
//# sourceMappingURL=engine.js.map