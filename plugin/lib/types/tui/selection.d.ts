import type { ChipService, SelectionState } from './types.js';
/** v2.4 sub-element selection (mesh vertices/edges/faces, bones, curve/lattice control points) -> text. Identical character for character to subSelectionText in lib/client.js. */
export declare function subSelectionText(sel: unknown): string | null;
/** selection payload -> the text handed to the model (null for an empty selection). Identical character for character to selectionMessageText in lib/client.js. */
export declare function selectionMessageText(payload: unknown): string | null;
/** chip title (one line, <= 80 cells): re-sending the same key **replaces** the previous chip, so the title only says "what it is and how many" */
export declare function selectionChipTitle(sel: unknown): string;
/**
 * One polling pass (exported for self-checks): take the unconsumed selection -> attach a chip -> consume.
 * Same CAS semantics as the Web bridge: only on success consume(ok:true); if it cannot be attached nothing is consumed and the next tick retries, and on the 3rd failure
 * consume(ok:false, reason); an empty selection is consumed directly with consume(ok:false) (there is nothing to retry).
 */
export declare function selectionTick(deps: {
    port: number;
    chips: ChipService;
    notify?: (text: string, color: string) => void;
    state: SelectionState;
}): Promise<void>;
