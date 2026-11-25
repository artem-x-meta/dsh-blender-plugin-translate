/** Wiring state for doctor: which seams are hooked up, and the selected bridge's latest result */
export const wired = {
    chips: false,
    toast: false,
    status: false,
    mentions: false,
    commands: false,
    commandTree: false,
};
export const bridge = {
    lastSeq: 0,
    lastOk: null,
    lastReason: null,
    lastAt: null,
};
//# sourceMappingURL=state.js.map