/**
 * S6 · Modeling class guide ("which kind of modeling -> first step + which operators to use + what you must not hand-roll + acceptance gate")
 *
 * Why it is a separate table: catalog takes the "capability family" view (audit/qc/vehicle/…), while the model thinks "what do I want to build".
 * Field lesson: another modeling AI had the vehicle_* recipes and knew Recipe 17/18/19, yet still hand-rolled a parametric loft =>
 * one continuous smooth surface, no edges, no seams, 6 structural defects. The root cause was not missing docs, it was a missing "entry point + forbidden hand-rolling + numerically judgeable acceptance gate".
 * This table pins all three per **modeling class** and lets the catalog be queried by class:
 *   blender_rt_plan(op="catalog", args={classes:true})         -> all classes
 *   blender_rt_plan(op="catalog", args={class:"recon"})        -> a single class (entry/operator chain/forbidden hand-rolling/acceptance gate)
 * Completeness is mechanically checked by tests/unit/js/contract/guidance.test.ts (a missing field or a wrong op name turns red).
 */
export interface ModelingClassGuide {
    c: string;
    name: string;
    entry: string;
    chain: string;
    forbid: string;
    gate: string;
}
export declare const MODELING_CLASS_GUIDE: ModelingClassGuide[];
/** Short rendering of a single class (readable on one screen for the model: entry -> chain -> forbidden -> gate) */
export declare function renderClassText(r: ModelingClassGuide): string;
/** For the mechanical check: a class with a missing field is reported red by the guidance contract test */
export declare function classGuideStats(): {
    classes: number;
    keys: string[];
    missing: string[];
};
/** Model-facing tool list (15 entries; v2.3 removed blender_rt_pick): compared name by name with capability.lock.json (guarded by the guidance contract test) */
export declare const MODEL_FACING_TOOLS: string[];
/**
 * Subagent handoff block (S6-b): the main model pastes it **verbatim into the subagent prompt**.
 *
 * Why it is required: a subagent is a self-contained context (it cannot see the catalog the main model read), and it tends to write Python directly to bypass the plan channel;
 * the observed consequence is "no vehicle_* used, a hand-rolled loft -> one smooth surface with no edges and no seams".
 * Goal: **short** (it has to fit into a subagent prompt) and **only what the decision needs** (class -> first step -> forbidden hand-rolling + tool names + hard rules + channel discipline).
 */
export declare function renderHandoff(): string;
