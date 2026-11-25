// headless options: path / script / input-file resolution (split out of options.ts)
import fs from 'node:fs';
import { winToWsl, wslToWin } from '../../../config.js';
import { WIN_TMP } from '../../../paths.js';
import { describeMissingInput, validateFileOpt } from '../../../file_guard.js';
import { fileFingerprint } from '../../../core/scripts.js';
import { errorMessage } from '../../../core/json.js';
import { slipFixPath } from '../../../core/output/index.js';
export function resolveHeadlessPaths(opts, deps) {
    // ---- v0.9.3: outdir accepts WSL paths (/home/…, /mnt/d/…) as well as Windows paths.
    // The old version handed the argument **as is** to Windows blender.exe → '/home/x' was taken as a relative drive root and silently written to C:\home\x.
    // Now: the Node side reads and writes via outdirWsl, the Blender side uses outdirWin (/home/… → \\wsl.localhost\<distro>\home\…).
    const outdirArg = opts.outdir ? slipFixPath(String(opts.outdir), null) : null;
    const outdirWsl = outdirArg ? winToWsl(outdirArg) : null;
    const outdirWin = outdirArg ? wslToWin(outdirArg) : WIN_TMP;
    // v0.9.1 (93-B3): scriptFile= explicitly accepts .py; passing a .py as file= automatically treats it as a script (old semantics: file= is still .blend)
    let scriptFileInfo = null;
    let script = opts.script ? String(opts.script) : '';
    const fileOpt = validateFileOpt(opts.file); // F-09: empty string / wrong type errors explicitly (fallback for a direct /headless call; the tool side also has ALIAS interception)
    const fileLooksPython = !!(fileOpt && /\.py$/i.test(String(fileOpt)));
    if (opts.scriptFile || fileLooksPython) {
        const given = String(opts.scriptFile || fileOpt);
        try {
            const rp = deps.readScriptPath(given);
            script = fs.readFileSync(rp.wsl, 'utf8');
            scriptFileInfo = {
                given: given,
                resolved: rp.win,
                bytes: script.length,
                auto_from_file: !opts.scriptFile && fileLooksPython,
            };
        }
        catch (e) {
            throw Object.assign(new Error('cannot read script file: ' + given + ' — ' + errorMessage(e).slice(0, 160)), {
                hint: 'scriptFile takes a .py path (Windows D:\\… or WSL /home/… both fine); file= is a .blend',
            });
        }
    }
    // ---- v0.9.3: inputFile fingerprint — the probe ran on the 02:55 build and only at 04:07 was it noticed the file had been re-saved (4 probes wasted)
    // (must come after fileLooksPython: otherwise TDZ ReferenceError — measured in practice)
    const inputFileInfo = fileOpt && !fileLooksPython
        ? fileFingerprint(wslToWin(String(fileOpt)), winToWsl(String(fileOpt)))
        : describeMissingInput(fileOpt, fileLooksPython); // F-09: null → {given,opened,reason} (shape frozen: the truthy branch untouched, character for character)
    return {
        outdirArg,
        outdirWsl,
        outdirWin,
        scriptFileInfo,
        fileOpt,
        fileLooksPython,
        inputFileInfo,
        script,
    };
}
//# sourceMappingURL=paths.js.map