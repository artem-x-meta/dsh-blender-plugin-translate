/** headless receipt entry point (split up): the exports keep the v2.6.2 public set. */
export { HEADLESS_WAIT_MS, newRunId, startJobThenMaybeWait, promotedFromTimeout, fetchJobStatus, } from './envelope.js';
export { normalizeShots, receiptEnvelope, headlessReceipt, promotedReceipt, type ToolReceipt, } from './envelope.js';
export { headlessHumanText, type ReceiptContext } from './human-text.js';
