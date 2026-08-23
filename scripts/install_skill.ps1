param(
    [string]$TargetRoot = ""
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
if ([string]::IsNullOrWhiteSpace($TargetRoot)) {
    $codexRoot = if ($env:CODEX_HOME) { $env:CODEX_HOME } else { Join-Path $HOME ".codex" }
    $TargetRoot = Join-Path $codexRoot "skills"
}
$target = Join-Path $TargetRoot "fujian-ip-litigation"
New-Item -ItemType Directory -Force -Path $target | Out-Null
Copy-Item -Path (Join-Path $repoRoot "SKILL.md") -Destination $target -Force
Copy-Item -Path (Join-Path $repoRoot "agents") -Destination $target -Recurse -Force
Copy-Item -Path (Join-Path $repoRoot "references") -Destination $target -Recurse -Force
Copy-Item -Path (Join-Path $repoRoot "scripts") -Destination $target -Recurse -Force
if (Test-Path (Join-Path $repoRoot "data")) {
    Copy-Item -Path (Join-Path $repoRoot "data") -Destination $target -Recurse -Force
}
Write-Host "已安装：$target"
Write-Host "在 Codex 中使用：`$fujian-ip-litigation"
