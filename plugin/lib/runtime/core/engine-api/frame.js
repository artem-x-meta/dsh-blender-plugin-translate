// engine API: screenshots / render performance / object slimming (split out of server-compat.ts)
import fs from 'node:fs';
import { LIVE_PNG_WIN, LIVE_PNG_WSL } from '../../paths.js';
import { KERNEL_BOOTSTRAP } from '../kernel/index.js';
export function createFrameApi(E) {
    const { addon } = E;
    return {
        async frameArea(areaIndex = 0) {
            const code = [
                'import bpy',
                'p = r"' + LIVE_PNG_WIN + '"',
                'scr = bpy.context.screen',
                'areas = list(scr.areas)',
                'idx = min(max(0, int(' + String(Number(areaIndex) || 0) + ')), len(areas) - 1)',
                'a = areas[idx]',
                'win = next(w for w in bpy.context.window_manager.windows if w.screen == scr)',
                'with bpy.context.temp_override(window=win, area=a):',
                '    bpy.ops.screen.screenshot_area(filepath=p)',
                'print("AREA_SHOT " + a.type + " " + p)',
            ].join('\n');
            const out = await addon.send('execute_code', { code: KERNEL_BOOTSTRAP + '\n' + code }, 60000);
            const outRec = (out || null);
            const txt = outRec && typeof outRec.result === 'string' ? outRec.result : '';
            if (!txt.includes('AREA_SHOT'))
                throw new Error('area screenshot failed: ' + txt.slice(0, 200));
            const png = fs.readFileSync(LIVE_PNG_WSL);
            return { png: png, meta: { method: 'screenshot_area', info: txt.trim() } };
        },
        // Render-performance perf / object-slimming opt are HTTP/script aliases of perfCall; this used to be a
        // pure one-level forward, and 4.4 consolidated it into the surface assembly in core/engine/assemble.ts (this file keeps only frame/frameArea).
        /** Grab one viewport PNG frame (overwrites a fixed file) */
        async frame(maxSize = 560) {
            const res = await addon.send('get_viewport_screenshot', {
                max_size: maxSize,
                filepath: LIVE_PNG_WIN,
                format: 'png',
            });
            const resRec = (res || null);
            if (resRec && resRec.error)
                throw new Error(String(resRec.error));
            const png = fs.readFileSync(LIVE_PNG_WSL);
            return { png: png, meta: res };
        },
        /** Custom-viewpoint capture: from/look_at/lens/ortho/... (view.py) — does not touch objects or the user's viewport */
    };
}
//# sourceMappingURL=frame.js.map