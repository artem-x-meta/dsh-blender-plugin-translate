/** Receipt context: the single declaration shared by envelope (envelope construction) and this file (human-readable narrative). */
export interface ReceiptContext {
    mode?: 'sync' | 'job' | 'promoted';
    runId?: string | null;
    jobId?: string | null;
    notes?: string[];
    hint?: string | null;
}
export declare function headlessHumanText(res: unknown, ctx: ReceiptContext): string;
