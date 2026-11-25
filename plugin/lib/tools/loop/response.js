/** loop response text: the session channel and the GUI channel each have their own wording. */
export function loopSessionText(op, nm, result) {
    return 'LOOP ' + op + ' (session=' + nm + ') ok · ' + JSON.stringify(result).slice(0, 6000);
}
export function loopResultText(op, result) {
    return 'LOOP ' + op + ' ' + JSON.stringify(result);
}
export function loopSessionError(_op, _nm, detail) {
    // v2.6.2 behaviour frozen: the old implementation's failure text was only 'LOOP session failed · ', without op/session.
    return 'LOOP session failed · ' + detail;
}
//# sourceMappingURL=response.js.map