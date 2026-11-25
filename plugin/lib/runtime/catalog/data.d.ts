export interface PlanFamily {
    f: string;
    prefix: string;
    when: string;
    not: string;
    sk: string;
    ops: string[];
    key: string;
}
export interface DiskCatalog {
    ok: boolean;
    error?: string;
    catalogHash?: string;
    families?: number;
    opsCount?: number;
    pluginVersion?: unknown;
    [k: string]: unknown;
}
export declare const PLAN_CATALOG: PlanFamily[];
/** Top-level tools outside plan: first decide "which tool", then decide the op */
/**
 * Description budget: the long tail of heavy tools' parameters (the part moved out of the tool descriptions).
 * Usage: blender_rt_plan(op="catalog", args={tool:"rt_headless"}) (served locally by the backend)
 * Motivation: the schemas of 15 tools are a fixed cost every turn; at the moment of calling, the model only needs parameter names + one line of explanation.
 * Maintenance: put explanatory text removed from tool descriptions here; do not let it creep back (tests/unit/js/contract/description-budget.test.ts has a budget gate).
 */
/** All known plan op names (with the family prefix, for nearest-neighbor matching) */
export declare function planOpNames(): string[];
export declare const PLAN_TOOL_MAP: Array<{
    t: string;
    use: string;
}>;
export declare const PLAN_READ_ONLY_OPS: string[];
export declare const PLAN_READ_ONLY: Set<string>;
