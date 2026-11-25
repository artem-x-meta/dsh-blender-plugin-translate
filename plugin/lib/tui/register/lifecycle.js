/** tui/register/lifecycle: the two "continuous polling" seams — selection chip and footer status (toasts are queued by the selection bridge and sent here). */
import { SELECTION_POLL_MS, STATE_POLL_MS, TOAST_DRAIN_MS } from '../constants.js';
import { footerField } from '../footer.js';
import { getJson } from '../http.js';
import { selectionTick } from '../selection.js';
import { wired } from '../state.js';
/** Register a "runs at a fixed interval inside the host effect's lifetime, non-reentrant" poll; the returned cleanup is managed by c.effect. */
export function every(c, ms, fn, label) {
    c.effect(() => {
        let busy = false;
        const run = () => {
            if (busy)
                return;
            busy = true;
            fn()
                .catch(() => { })
                .finally(() => {
                busy = false;
            });
        };
        const t = setInterval(run, ms);
        if (t && typeof t.unref === 'function')
            t.unref();
        run();
        return () => clearInterval(t);
    }, label);
}
/** ① selection → chip (toast optional: hint when available, still attach the chip without it) */
export function registerSelectionSurface(host, opts, tag) {
    //    dsh-TUI identifies the caller by **the activation the current async context belongs to**: toast can only be called inside tuiToast's own inject,
    //    so the selection bridge only queues the hint and the small timer here sends it out (measured: calling it directly across injects is rejected).
    const toastQueue = [];
    const notify = (txt, color) => {
        if (wired.toast && toastQueue.length < 5)
            toastQueue.push([txt, color]);
    };
    host.inject(['tuiToast'], (c) => {
        const svc = c.tuiToast;
        if (!svc || typeof svc.show !== 'function')
            return;
        c.effect(() => {
            wired.toast = true;
            const t = setInterval(() => {
                while (toastQueue.length) {
                    const item = toastQueue.shift();
                    if (!item)
                        break;
                    const [txt, color] = item;
                    try {
                        svc.show(txt, { color: color });
                    }
                    catch {
                        /* a toast is only a hint */
                    }
                }
            }, TOAST_DRAIN_MS);
            if (t && typeof t.unref === 'function')
                t.unref();
            return () => {
                clearInterval(t);
                toastQueue.length = 0;
                wired.toast = false;
            };
        }, tag + 'toast');
    });
    host.inject(['tuiContextChips'], (c) => {
        const chips = c.tuiContextChips;
        if (!chips || typeof chips.attachContext !== 'function')
            return;
        const state = { lastSeq: 0, fails: 0 };
        c.effect(() => {
            wired.chips = true;
            return () => {
                wired.chips = false;
            };
        }, tag + 'selection bridge flag');
        every(c, SELECTION_POLL_MS, () => selectionTick({
            port: opts.port,
            chips: chips,
            notify: notify,
            state: state,
        }), tag + 'selection bridge');
    });
}
/** ② footer field (tuiStatus.setField is a newer dsh-TUI seam: older versions only have set(), and we do not degrade to a whole-line status here) */
export function registerStatusSurface(host, opts, tag) {
    host.inject(['tuiStatus'], (c) => {
        const status = c.tuiStatus;
        if (!status || typeof status.setField !== 'function')
            return;
        wired.status = true;
        let last = '';
        let clear;
        let misses = 0;
        every(c, STATE_POLL_MS, async () => {
            const st = await getJson(opts.port, '/host/state');
            // One occasional failed fetch (backend busy / just restarted) does not immediately switch to "backend not running"; only two in a row count
            misses = st ? 0 : misses + 1;
            if (!st && misses < 2 && last)
                return;
            const f = footerField(st, opts.holder, opts.port);
            const key = f.text + '|' + f.tone + '|' + f.detail;
            if (key === last)
                return;
            last = key;
            // setField hands back a disposer that clears only "this one write" each time: keep the newest and use it on unmount
            clear = status.setField('blender', f.text, {
                slot: 'right-head',
                tone: f.tone,
                maxCells: 24,
                minColumns: 60,
                detail: f.detail,
            });
        }, tag + 'footer field');
        c.effect(() => () => {
            wired.status = false;
            try {
                if (typeof clear === 'function')
                    clear();
            }
            catch {
                /* the host cleans up along with the activation */
            }
        }, tag + 'footer field clear');
    });
}
//# sourceMappingURL=lifecycle.js.map