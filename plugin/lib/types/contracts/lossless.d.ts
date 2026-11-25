export declare function losslessSanitize(root: unknown): {
    value: unknown;
    fixes: string[];
};
/** Plain object/array test (used to decide whether to take the toJSON branch) */
export declare function isPlainObjectLike(v: unknown): boolean;
