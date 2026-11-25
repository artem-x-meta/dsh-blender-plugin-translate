// extra hints for common Blender-side errors
// @imports
import { wslPathShared } from '../config.js';
import { WSL_TMP } from '../paths.js';
/** v0.8.7: append one actionable hint to errors from common Blender-side pitfalls (external feedback #4) */
export function enrichError(msg, tb) {
    const s = String(msg || '');
    const t = String(tb || '');
    const both = s + ' ' + t;
    if (/已使用的库|in use|Cannot overwrite/i.test(both)) {
        return (s +
            '  ← hint: this .blend was loaded as a library in this session. Release it first with bpy.data.libraries.remove(<that library>), or write a copy with bpy.ops.wm.save_as_mainfile(filepath=..., copy=True) (copy=True leaves the current filepath alone).');
    }
    if (/Cannot render, no camera/i.test(both)) {
        return (s +
            '  ← hint: the scene has no camera (it may have been deleted by a cleanup or a light-rebuild loop). Set scene.camera before a headless render, or render a custom view with blender_rt_see.');
    }
    // v0.8.9 (external session feedback): after open_mainfile every old reference is invalid + GUI context pointers are invalid
    if (/StructRNA of type .* has been removed|ReferenceError: StructRNA/i.test(both)) {
        return (s +
            '  ← hint: this is a "stale reference" — bpy.ops.wm.open_mainfile() rebuilds bpy.data, so every Object/Collection/material reference taken before the file switch is void. Fix: after open, fetch objects again from bpy.data.objects[...] / bpy.context.scene, do not reuse the old variables.');
    }
    if (/context is incorrect/i.test(both)) {
        return (s +
            '  ← hint: the bpy.ops context is not satisfied. After switching files or modes: first bpy.context.view_layer.objects.active = obj, obj.select_set(True), then call the op; if it still errors use with bpy.context.temp_override(view_layer=vl, active_object=obj, selected_objects=[obj]): bpy.ops.... (measured: temp_override lets join work after open); if that still fails, split it into two rt_do calls (every call is a new namespace = a fresh context).');
    }
    if (/No such file or directory|could not be opened|无法读取/i.test(both) &&
        /\/\/wsl/i.test(both)) {
        return (s +
            '  ← hint: `//wsl.localhost/…` (forward slashes) is treated by Blender as a **relative .blend** path. Use a backslash UNC path (\\\\wsl.localhost\\<distro>\\…), or copy the file to a Windows-visible directory first.');
    }
    if (/No such file or directory|could not be opened|无法读取/i.test(both) &&
        /wsl\.localhost|\\\\wsl/i.test(both)) {
        // v0.9.6: this used to be misdiagnosed as "a UNC formatting problem". The really common root cause is that **the mount is not shared**:
        // Node can write there (inside the WSL namespace) but the Windows-side Blender cannot see that mount point.
        const sh = wslPathShared(WSL_TMP);
        return (s +
            '  ← hint: the path is \\\\wsl.localhost\\<distro>\\…, but the Windows-side Blender cannot see that location.' +
            'current workDir=' +
            WSL_TMP +
            ' (shared=' +
            String(sh.shared) +
            ', ' +
            String(sh.why) +
            ').' +
            'Put the working directory somewhere Windows can read: a Windows drive (D:\\…) or a directory in the distro root filesystem' +
            ' (WSL /home/… ↔ \\\\wsl.localhost\\<distro>\\home\\…).' +
            'Since v0.9.6 headless avoids such directories automatically and explains it in the receipt fields scriptStaging / pathWarnings.');
    }
    return s;
}
//# sourceMappingURL=errors.js.map
