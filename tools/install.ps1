<#
Drop-in installer for the English localization of dsh-blender-plugin.

  pwsh tools/install.ps1 -Package "C:\Users\<you>\.dsh\profiles\desktop\node_modules\dsh-blender-plugin"
  pwsh tools/install.ps1 -Package "..." -DryRun      # show what would change
  pwsh tools/install.ps1 -Restore                    # roll back to the newest backup

The script backs up the package next to it as <package>.orig-<timestamp> before
touching anything, so -Restore always has something to go back to.
#>
param(
    [string]$Package,
    [switch]$Restore,
    [switch]$DryRun,
    [string]$RepoRoot = (Split-Path $PSScriptRoot -Parent)
)

$ErrorActionPreference = "Stop"
$source = Join-Path $RepoRoot "plugin"

if ($Restore) {
    if (-not $Package) { throw "-Package is required for -Restore" }
    $parent = Split-Path $Package -Parent
    $name = Split-Path $Package -Leaf
    $backup = Get-ChildItem $parent -Directory -Filter "$name.orig-*" |
        Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if (-not $backup) { throw "no backup found next to $Package (looked for $name.orig-*)" }
    Write-Host "restoring from $($backup.FullName)"
    if ($DryRun) { Write-Host "dry run: nothing written"; return }
    Copy-Item (Join-Path $backup.FullName '*') $Package -Recurse -Force
    Write-Host "restored. Restart the backend and Blender to load the original strings."
    return
}

if (-not $Package) {
    # try to find the package automatically
    $candidates = @(
        (Join-Path $env:USERPROFILE ".dsh\profiles\desktop\node_modules\dsh-blender-plugin"),
        (Join-Path $env:USERPROFILE ".dsh\profiles\default\node_modules\dsh-blender-plugin")
    )
    $found = $candidates | Where-Object { Test-Path (Join-Path $_ "package.json") }
    if (-not $found) { throw "package not found; pass -Package <path to node_modules\dsh-blender-plugin>" }
    $Package = @($found)[0]
}

if (-not (Test-Path (Join-Path $Package "package.json"))) { throw "not a plugin package: $Package" }
if (-not (Test-Path $source)) { throw "translated tree missing: $source" }

$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$backup = "$Package.orig-$stamp"

Write-Host "repo    : $RepoRoot"
Write-Host "package : $Package"
Write-Host "backup  : $backup"

if ($DryRun) {
    $n = (Get-ChildItem $source -Recurse -File).Count
    Write-Host "dry run: would copy $n files and create the backup above"
    return
}

Copy-Item $Package $backup -Recurse -Force
Write-Host "backup written"

$copied = 0
Get-ChildItem $source -Recurse -File | ForEach-Object {
    $rel = $_.FullName.Substring($source.Length).TrimStart('\')
    $dst = Join-Path $Package $rel
    $dir = Split-Path $dst -Parent
    if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
    Copy-Item $_.FullName $dst -Force
    $copied++
}
Write-Host "copied $copied files"

# The localization renames Chinese-named docs to ASCII slugs; the originals stay behind otherwise.
$stale = @(
    "docs\AI-安装提示词.md", "docs\DSH-更新适配.md", "docs\EEVEE-工作要点.md",
    "docs\flash建模上限-整合方案.md", "docs\Procedura-融合分析.md", "docs\假设驱动建模-cookbook.md",
    "docs\宿主集成-接口契约-v2.3增补.md", "docs\操作教程.md", "docs\给第三方的安装清单.md",
    "docs\证据分级与读图纪律.md", "docs\部署SOP.md", "docs\配置参考.md",
    "docs\archive\headless优先-路线决定.md", "docs\archive\v2.6.0-更新说明.md",
    "docs\archive\插件与技能优化验收.md",
    "skills\blender-modeling\references\参考图通用还原SOP.md",
    "skills\blender-modeling\references\曲面算法.md",
    "skills\blender-modeling\references\验收清单.md"
)
$removed = 0
foreach ($rel in $stale) {
    $p = Join-Path $Package $rel
    if (Test-Path $p) { Remove-Item $p -Force; $removed++ }
}
Write-Host "removed $removed renamed originals"

# Source maps still describe the original Chinese sources and are useless after translation.
$maps = Get-ChildItem $Package -Recurse -File -Filter "*.map"
$maps | Remove-Item -Force
Write-Host "removed $($maps.Count) stale source maps"

# stale bytecode would shadow nothing (Python recompiles), but it confuses greps
Get-ChildItem $Package -Recurse -Directory -Filter "__pycache__" | Remove-Item -Recurse -Force

Write-Host ""
Write-Host "Next:" -ForegroundColor Yellow
Write-Host "  1) restart the DSH Blender backend (it re-reads lib/*.js)"
Write-Host "  2) restart Blender, then reconnect the add-on (3D viewport: N -> DSH Blender Bridge -> Connect)"
Write-Host "  3) restart headless workers, if you use them"
Write-Host "  4) verify: python tools/verify_no_cjk.py `"$Package`""
Write-Host "  5) rollback at any time: pwsh tools/install.ps1 -Restore -Package `"$Package`""
