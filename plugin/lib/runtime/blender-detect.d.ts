/** Detection dependency surface: defaults = production implementations; tests override as needed (keys left out still use production) */
export interface BlenderDetectDeps {
    env: Record<string, string | undefined>;
    isWin: boolean;
    isMac: boolean;
    homedir: () => string;
    exists: (p: string) => boolean;
    listDir: (p: string) => string[];
    readText: (p: string) => string | null;
    exec: (cmd: string, args: string[]) => string;
    /** Config-file contents (config.ts's FILE.cfg); passed separately so env/config overrides can also be tested */
    fileCfg: Record<string, unknown>;
}
export interface BlenderDetectResult {
    /** The blender executable that was found; null when there is none */
    exe: string | null;
    /** Provenance: config / auto:install / auto:steam / auto:path / not-found */
    from: string;
}
export declare function detectBlenderExe(over?: Partial<BlenderDetectDeps>): BlenderDetectResult;
