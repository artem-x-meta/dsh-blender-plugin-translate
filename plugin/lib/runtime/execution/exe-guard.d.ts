/**
 * Throws a structured blender_exe_missing when blenderExe is empty/blank (code + an actionable configuration hint).
 * retryTool is the retry action at the end of the hint (worker and job differ).
 */
export declare function assertBlenderExe(exe: unknown, detectedFrom?: unknown, retryTool?: string): void;
export declare function blenderExeSource(): string;
