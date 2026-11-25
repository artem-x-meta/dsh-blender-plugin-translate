// Ledger entry point: in-memory store + disk reconciliation combined
import { createLedgerStore } from './state.js';
import { createLedgerRecover } from './recover.js';
export function createLedger(_E) {
    const store = createLedgerStore();
    const recover = createLedgerRecover();
    const api = {
        runs: store.runs,
        LEDGER: store.LEDGER,
        ledgerAppend: store.ledgerAppend,
        ledgerState: store.ledgerState,
        ledgerList: store.ledgerList,
        runSnapshot: recover.runSnapshot,
        reconcileLedger: recover.reconcileLedger,
    };
    return api;
}
//# sourceMappingURL=index.js.map