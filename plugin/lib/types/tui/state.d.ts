export interface WiredState {
    chips: boolean;
    toast: boolean;
    status: boolean;
    mentions: boolean;
    commands: boolean;
    commandTree: boolean;
}
export interface BridgeState {
    lastSeq: number;
    lastOk: null | boolean;
    lastReason: null | string;
    lastAt: null | number;
}
/** Wiring state for doctor: which seams are hooked up, plus the selection bridge's latest result */
export declare const wired: WiredState;
export declare const bridge: BridgeState;
