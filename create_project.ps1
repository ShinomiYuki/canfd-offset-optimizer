param(
    [string]$Root = "canfd-offset-optimizer"
)

$ErrorActionPreference = "Stop"
$target = Join-Path (Get-Location) $Root
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path

$directories = @(
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

$files = @(
    "README.md", "pyproject.toml", ".gitignore", "LICENSE",
    "input/config/project.yaml",
    "src/canfd_offset_optimizer/__init__.py",
    "src/canfd_offset_optimizer/__main__.py",
    "src/canfd_offset_optimizer/cli.py",
    "src/canfd_offset_optimizer/config.py",
    "src/canfd_offset_optimizer/models.py",
    "src/canfd_offset_optimizer/exceptions.py",
    "src/canfd_offset_optimizer/parsers/__init__.py",
    "src/canfd_offset_optimizer/parsers/dbc_parser.py",
    "src/canfd_offset_optimizer/parsers/arxml_parser.py",
    "src/canfd_offset_optimizer/parsers/project_loader.py",
    "src/canfd_offset_optimizer/timing/__init__.py",
    "src/canfd_offset_optimizer/timing/frame_time.py",
    "src/canfd_offset_optimizer/timeline/__init__.py",
    "src/canfd_offset_optimizer/timeline/slot_map.py",
    "src/canfd_offset_optimizer/timeline/state.py",
    "src/canfd_offset_optimizer/optimization/__init__.py",
    "src/canfd_offset_optimizer/optimization/objective.py",
    "src/canfd_offset_optimizer/optimization/greedy.py",
    "src/canfd_offset_optimizer/optimization/local_search.py",
    "src/canfd_offset_optimizer/optimization/gcls.py",
    "src/canfd_offset_optimizer/reporting/__init__.py",
    "src/canfd_offset_optimizer/reporting/csv_writer.py",
    "src/canfd_offset_optimizer/reporting/plotter.py",
    "src/canfd_offset_optimizer/reporting/summary_writer.py",
    "tests/unit/test_config.py",
    "tests/unit/test_models.py",
    "tests/unit/test_frame_time.py",
    "tests/unit/test_slot_map.py",
    "tests/unit/test_state.py",
    "tests/unit/test_objective.py",
    "tests/unit/test_greedy.py",
    "tests/unit/test_local_search.py",
    "tests/integration/test_end_to_end.py"
)

foreach ($dir in $directories) {
    New-Item -ItemType Directory -Force -Path (Join-Path $target $dir) | Out-Null
}

foreach ($file in $files) {
    $path = Join-Path $target $file
    $parent = Split-Path -Parent $path
    New-Item -ItemType Directory -Force -Path $parent | Out-Null
    if (-not (Test-Path $path)) {
        New-Item -ItemType File -Path $path | Out-Null
    }
}

# Copy the three Codex reference documents when they are placed beside this script.
$docs = @(
    "01_research_and_design.md",
    "02_project_structure_and_code_conventions.md",
    "03_implementation_plan.md"
)
foreach ($doc in $docs) {
    $sourceDoc = Join-Path $scriptDir $doc
    $targetDoc = Join-Path $target ("docs/" + $doc)
    if (Test-Path $sourceDoc) {
        Copy-Item $sourceDoc $targetDoc -Force
    } elseif (-not (Test-Path $targetDoc)) {
        New-Item -ItemType File -Path $targetDoc | Out-Null
    }
}

$yaml = @"
network:
  channel: CAN1
  nominal_bitrate: null
  data_bitrate: null
  brs: null

optimization:
  slot_ms: 5
  hyperperiod_ms: auto
  hyperperiod_cap_ms: 5000
  offset_min_ms: 15
  offset_max_ms: 100
  offset_step_ms: 5
  random_restarts: 20
  hot_slot_count: 3
  conflict_candidate_cap: 6
  pair_neighbor_steps: [1, 2, 3]

model:
  weight_mode: frame_time_us
  average_load_limit: 0.75
"@
Set-Content -Path (Join-Path $target "input/config/project.yaml") -Value $yaml -Encoding UTF8

Copy-Item $MyInvocation.MyCommand.Path (Join-Path $target "scripts/create_project.ps1") -Force

Write-Host "Project created: $target" -ForegroundColor Green
Write-Host "Next: read docs/01, docs/02, docs/03, then implement models.py first." -ForegroundColor Cyan
