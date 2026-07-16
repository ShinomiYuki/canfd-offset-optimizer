param(
    [string]$Root = "canfd-offset-optimizer"
)

$ErrorActionPreference = "Stop"
$target = Join-Path (Get-Location) $Root
$source = Split-Path -Parent $MyInvocation.MyCommand.Path

$dirs = @(
    "input/dbc", "input/arxml", "input/config",
    "output/results", "output/plots", "output/logs",
    "docs", "scripts",
    "src/canfd_offset_optimizer/parsers",
    "src/canfd_offset_optimizer/timing",
    "src/canfd_offset_optimizer/timeline",
    "src/canfd_offset_optimizer/optimization",
    "src/canfd_offset_optimizer/reporting",
    "tests/fixtures/dbc", "tests/fixtures/arxml", "tests/fixtures/config",
    "tests/unit", "tests/integration"
)

foreach ($dir in $dirs) {
    New-Item -ItemType Directory -Force -Path (Join-Path $target $dir) | Out-Null
}

# Copy the complete scaffold when this script is run from the downloaded scaffold folder.
$items = @("input", "docs", "src", "tests", "pyproject.toml", "README.md", ".gitignore", "LICENSE")
foreach ($item in $items) {
    $src = Join-Path $source "..\$item"
    if (Test-Path $src) {
        Copy-Item $src (Join-Path $target $item) -Recurse -Force
    }
}

Copy-Item $MyInvocation.MyCommand.Path (Join-Path $target "scripts\create_project.ps1") -Force
$cmdSource = Join-Path $source "create_project.cmd"
if (Test-Path $cmdSource) {
    Copy-Item $cmdSource (Join-Path $target "scripts\create_project.cmd") -Force
}

Write-Host "Created project at: $target" -ForegroundColor Green
Write-Host "Read docs/01, docs/02, docs/03 before asking Codex to write code." -ForegroundColor Cyan
