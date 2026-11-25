/**
 * Boundary parsing: JSON / environment variables / subprocess output are all unknown at the type level.
 *
 * Rule: narrow unknown into concrete types only at the boundary; business code must not swallow boundary data with `as SomeType`,
 * and must not use an explicit any. When a new field is needed, add a guard/reader here first, then declare the interface in the module.
 */
/** A JSON object (excludes null and arrays). */
export type JsonRecord = Record<string, unknown>;
export declare function isRecord(v: unknown): v is JsonRecord;
export declare function isArray(v: unknown): v is unknown[];
export declare function isString(v: unknown): v is string;
export declare function isNumber(v: unknown): v is number;
export declare function isBoolean(v: unknown): v is boolean;
/** Any value -> string; returns undefined for null/undefined (never fabricates an empty string). */
export declare function readString(v: unknown): string | undefined;
/** Any value -> finite number; returns fallback when it cannot be converted or is not positive (config-item semantics). */
export declare function readPositiveNumber(v: unknown, fallback: number): number;
/** Any value -> finite number; returns fallback when it cannot be converted. */
export declare function readNumber(v: unknown, fallback: number): number;
/** Error object/string -> readable message (equivalent to the old String((e && e.message) || e)). */
export declare function errorMessage(e: unknown): string;
/** Error object/string -> error code (Node system errors carry a code). */
export declare function errorCode(e: unknown): string | undefined;
/** Custom extension fields on an error object (dynamic boundaries such as the old e.diagnosis / e.hint / e.code). */
export declare function errorField(e: unknown, key: string): unknown;
/** Error object/string -> details (stack when available, otherwise the message; the semantics of /router's 500 receipt). */
export declare function errorDetail(e: unknown): string;
/** Any value -> plain record (an empty object for non-objects, used for optional config fragments). */
export declare function readRecord(v: unknown): JsonRecord;
