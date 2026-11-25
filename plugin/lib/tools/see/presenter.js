/** blender_rt_see presentation layer: frame text / empty-frame warning (does not change any verdict). */
import { asRecord, text } from '../../contracts/dynamic.js';
const LF = String.fromCharCode(10);
export function formatHeadlessSeeText(res) {
    return ('headless see (Workbench offscreen, downgrades automatically when the GUI is not connected) · ' +
        text(res.ms) +
        'ms · ' +
        text(res.width) +
        'x' +
        text(res.height) +
        ' · ' +
        text(res.bytes || 0) +
        'B' +
        (res.coverage_estimate === null || res.coverage_estimate === undefined
            ? ''
            : ' · coverage ' + (Number(res.coverage_estimate) * 100).toFixed(2) + '%') +
        ' · scene and user viewport untouched');
}
export function formatCustomViewText(spec, fv) {
    const mt = asRecord(fv.meta);
    return ('custom view ' +
        text(mt.mode || spec.mode || 'viewport') +
        ' · ' +
        text(spec.width) +
        'x' +
        text(spec.height) +
        ' · ' +
        text(fv.ms) +
        'ms · ' +
        text(fv.png.length) +
        'B · hash ' +
        String(fv.hash) +
        ' · from ' +
        JSON.stringify(spec.from) +
        ' → look_at ' +
        JSON.stringify(spec.look_at) +
        (mt.fallback_from ? ' · (viewport unavailable, downgraded to render: ' + text(mt.fallback_from) + ')' : '') +
        (mt.coverage_estimate === undefined || mt.coverage_estimate === null
            ? ''
            : ' · coverage ' + (Number(mt.coverage_estimate) * 100).toFixed(2) + '%') +
        ' · scene and user viewport both untouched');
}
export function appendEmptyFrameWarning(t, raw) {
    const warning = asRecord(raw);
    if (warning.code !== 'frame_looks_empty')
        return t;
    const sceneBbox = asRecord(warning.scene_bbox);
    const suggest = asRecord(warning.suggest);
    return (t +
        LF +
        '⚠ frame_looks_empty: ' +
        text(warning.why || 'almost nothing but the background colour is in frame') +
        (warning.scene_bbox
            ? LF +
                '  scene bbox: center=' +
                JSON.stringify(sceneBbox.center) +
                ' span=' +
                text(sceneBbox.span) +
                ' objects=' +
                text(sceneBbox.objects)
            : '') +
        (warning.suggest
            ? LF +
                '  suggest re-shooting with this set: from=' +
                JSON.stringify(suggest.from) +
                ' look_at=' +
                JSON.stringify(suggest.look_at)
            : LF + '  ' + text(warning.hint)));
}
export function formatPlainFrameText(size, full, f) {
    return ((full ? 'region screenshot (screenshot_area) · ' : 'viewport frame ' + String(size) + 'px · ') +
        String(f.ms) +
        'ms · ' +
        String(f.png.length) +
        'B · hash ' +
        f.hash);
}
//# sourceMappingURL=presenter.js.map