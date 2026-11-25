// engine API: custom-viewpoint capture (split out of server-compat.ts)
import fs from 'node:fs';
import { winToWsl } from '../../config.js';
import { VIEW_PNG_WIN } from '../../paths.js';
import { extractTag } from '../output/index.js';
import { KERNEL_BOOTSTRAP } from '../kernel/index.js';
export function createViewApi(E) {
    const { addon, ensureView, metrics } = E;
    return {
        async view(spec = {}) {
            await ensureView();
            metrics.views++;
            // when no output path is given, use the working directory from the config (so both Blender and the host can reach it)
            const spec2 = Object.assign({}, spec || {});
            if (!spec2.path)
                spec2.path = VIEW_PNG_WIN;
            const j = JSON.stringify(spec2);
            const body = 'import json as _json' +
                '\n' +
                'print("VIEW " + K.dsh_view_api["capture"](_json.dumps(_json.loads(' +
                JSON.stringify(j) +
                '))))';
            const info = extractTag(await addon.send('execute_code', { code: KERNEL_BOOTSTRAP + '\n' + body }, Math.max(30000, Number(spec.timeoutMs) || 120000)), 'VIEW');
            if (!info || info.ok === false)
                throw new Error('view failed: ' + JSON.stringify(info).slice(0, 300));
            metrics.lastView = { at: Date.now(), ms: info.ms, mode: info.mode, path: info.path };
            return { png: fs.readFileSync(winToWsl(info.path)), meta: info };
        },
        /**
         * Host integration (/host/view/capture, contract §1.4): grabs **that frame of the current GUI viewport**.
         * Division of labour with view(): view() is "take a look from an arbitrary position" (its own matrix, does not touch the user's viewport);
         * this method is "whatever the user is seeing right now is this frame" (the matrix comes straight from region_3d) → panel display + click back-projection.
         * Zero scene / zero viewport changes; when the matrix is unavailable view.py returns ok=false (the caller then sets pickable to false rather than lying).
         */
        /** Host integration (/host/scene-items, contract §1.6): the data source for `@` mentions (objects/materials/collections). */
    };
}
//# sourceMappingURL=view.js.map