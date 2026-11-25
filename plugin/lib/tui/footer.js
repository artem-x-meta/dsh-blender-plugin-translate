import { asRecord } from '../contracts/dynamic.js';
/** '/host/state' response → one footer cell (text / tone / hover detail). Pure function, exported for self-checks. */
export function footerField(state, holder, port) {
    const st = asRecord(state);
    if (st.ok !== true) {
        return {
            text: 'Blender ○',
            tone: 'dim',
            detail: 'backend not running (127.0.0.1:' +
                String(port) +
                ') · have the model run blender_viewport(op="start"), or /blender doctor',
        };
    }
    const ch = asRecord(st.channel);
    const lease = asRecord(st.lease);
    const jobs = Number(asRecord(st.jobs).running || 0);
    const jobsTail = jobs > 0 ? ' · jobs ' + String(jobs) : '';
    const jobsDetail = jobs > 0 ? ' · ' + String(jobs) + ' headless jobs running (/blender jobs)' : '';
    if (ch.aiPaused) {
        return {
            text: 'Blender ⏸ AI paused',
            tone: 'warning',
            detail: 'AI operations are paused in Blender: in the N panel, under "activity status", click "resume AI operations"' + jobsDetail,
        };
    }
    const render = asRecord(st.render);
    if (render.busy) {
        const s = Math.round(Number(render.ageMs || 0) / 1000);
        return {
            text: 'Blender ● rendering' + jobsTail,
            tone: 'warning',
            detail: 'Blender is rendering (' + String(s) + ' s) · main-thread commands return busy immediately' + jobsDetail,
        };
    }
    if (ch.diagnosis === 'main-thread-busy') {
        return {
            text: 'Blender ● busy' + jobsTail,
            tone: 'warning',
            detail: 'the Blender main thread is held by a render or a modal operation · wait for it to free up, or take the headless route' + jobsDetail,
        };
    }
    if (ch.lastOkAgeMs == null ||
        ch.diagnosis === 'blender-unreachable' ||
        ch.diagnosis === 'addon-thread-stuck') {
        return {
            text: 'Blender ○ not connected' + jobsTail,
            tone: 'dim',
            detail: 'GUI Blender is not connected yet (the addon has not connected, or Blender is not running) · in Blender press N → Connect; the headless route is unaffected' +
                jobsDetail,
        };
    }
    if (lease.active && lease.holder && lease.holder !== holder) {
        return {
            text: 'Blender ● lease held by someone else' + jobsTail,
            tone: 'warning',
            detail: 'the write lease is held by another session (' + String(lease.holder) + ') · write operations will 409; reads are unaffected' + jobsDetail,
        };
    }
    const mine = lease.active && lease.holder === holder ? ' · this session holds the write lease' : '';
    return {
        text: 'Blender ●' + jobsTail,
        tone: 'success',
        detail: 'GUI channel connected' + mine + jobsDetail,
    };
}
//# sourceMappingURL=footer.js.map
