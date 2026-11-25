/** Minimal shape of the host attachments service (covers only the fields this plugin uses). */
export interface AttachmentRef {
    attachmentId: string;
    mediaType: string;
    bytes: number;
    width: number;
    height: number;
    name?: string;
}
/** PNG → durable attachment (since v0.9.2 failures are **no longer silent**: it returns {ref} or {why}, and the caller writes it into the tool text) */
export declare function toAttachment(ctx: unknown, data: Uint8Array, name: string): Promise<{
    ref?: AttachmentRef;
    why?: string;
}>;
/** Windows / UNC path → WSL path (this machine's DSH runs in WSL; on a Windows host the path is returned as-is). */
export declare function toWslPath(p: unknown): string;
/** Read a local PNG (returns null on failure; the caller is responsible for writing why into the text, never silent) */
export declare function readLocalPng(p: unknown): Uint8Array | null;
/** Batch attachments: ≤max images; returns the attached ones and the failure list (path/reason) */
export declare function attachPaths(ctx: unknown, paths: readonly unknown[], tag: string, max?: number): Promise<{
    images: AttachmentRef[];
    used: string[];
    failed: string[];
}>;
/** Collect attachable paths from a plan receipt (≤2; only well-known artifact fields are recognized) */
export declare function planImagePaths(res: unknown): string[];
