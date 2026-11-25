// Asset-gate switches and read-only query payloads
// @imports
export const GATE_FLAGS = [
    'dshbb_use_polyhaven',
    'dshbb_use_hyper3d',
    'dshbb_use_sketchfab',
    'dshbb_use_polypizza',
    'dshbb_use_hunyuan3d',
];
const REGION_CODE = [
    'import bpy, json',
    'w = bpy.context.window',
    'res = []',
    'for a in bpy.context.screen.areas:',
    '    if a.type == "VIEW_3D":',
    '        r = next(x for x in a.regions if x.type == "WINDOW")',
    '        res.append({"region": [r.x, r.y, r.width, r.height], "area": [a.x, a.y, a.width, a.height], "shading": a.spaces.active.shading.type})',
    'print(json.dumps({"window": [w.width, w.height], "views": res}))',
].join('\n');
/**
 * Python payload that reads the 5 integration switches (used by `/commands`).
 * Reads only this repo's addon `dshbb_use_*` (the old addon is no longer supported since v2.3).
 */
export const FLAGS_CODE = [
    'import bpy, json',
    's = bpy.context.scene',
    'names = ' + JSON.stringify(GATE_FLAGS),
    'flags = {}',
    'for n in names:',
    '    flags[n] = bool(getattr(s, n, None))',
    'print(json.dumps({"scene": s.name, "file": bpy.data.filepath, "flags": flags}))',
].join('\n');
export { REGION_CODE };
//# sourceMappingURL=flags.js.map