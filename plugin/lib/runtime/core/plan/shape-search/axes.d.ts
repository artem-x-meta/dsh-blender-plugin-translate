export interface AxisSpec {
    kind: 'enum' | 'range';
    values?: unknown[];
    min?: number;
    max?: number;
    step?: number;
    integer?: boolean;
}
/** Python literal (JSON's true/false/null are not written that way in Python — a plain JSON.stringify raises NameError) */
export declare function pyLit(v: unknown): string;
export declare const pyIndent: (src: unknown, pad: string) => string;
/** Candidate values for one axis (parameter dimension): enum takes values directly; range is cut by step (10 evenly spaced buckets when step is omitted) */
export declare function searchAxisValues(spec0: AxisSpec, cap: number): unknown[];
