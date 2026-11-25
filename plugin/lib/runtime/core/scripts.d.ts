declare function workdirBlock(p: unknown): string;
/**
 * v0.9.6 (field feedback #4 · hit during the MK1 smoke test): script_file content is **inlined** into dsh_headless_*.py,
 * so __file__ inside the script points at that temporary wrapper and the script's own directory is not on sys.path - a multi-file project
 * fails on its first import with ModuleNotFoundError: No module named 'spec'. This explicitly supplies the original path and directory to the script.
 */
declare function scriptFileBlock(origWinPath: unknown): string;
declare function envPrelude(envPairs: unknown): string;
/**
 * v0.9.3: path audit - Windows Blender treats '/home/x' as a "path relative to the current drive root"
 * and silently writes to C:\home\x (evidence: Saved: 'C:homesixtyseven67DSH…' followed by os.path.exists() -> false).
 * This checks scene.render.filepath when the script finishes, working together with the Saved: scan on stdout (pathAudit).
 *
 * The premise of this audit is "WSL host + Windows build of Blender": only that combination misreads POSIX absolute paths.
 * On native Linux, Blender and the host share the machine and OS and '/home/x' is already correct => it must be turned off, otherwise every normal script
 * returns a bogus `render_filepath_posix` warning and steers people toward "switch to Windows form" (issue #11).
 */
export declare const PATH_GUARD: string;
declare function shotsBlock(args: unknown): string;
export interface FileFingerprint {
    path: string | null;
    wsl: string | null;
    size?: number;
    mtimeMs?: number;
    mtime?: string;
    md5?: string;
    md5Partial?: boolean;
    md5Note?: string;
    error?: string;
}
/** File fingerprint: returns {path,size,mtimeMs,md5,md5Partial}; above 512MB only the first 64MB is hashed and marked partial */
declare function fileFingerprint(winPath: unknown, wslPath: string): FileFingerprint;
declare function md5File(p: string, limit?: number): string;
export { workdirBlock, scriptFileBlock, envPrelude, shotsBlock, fileFingerprint, md5File };
