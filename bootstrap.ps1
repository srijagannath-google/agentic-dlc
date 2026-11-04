<#
.SYNOPSIS
  Enterprise Agentic DLC (agentic-dlc) — Windows Developer Laptop Installer
.DESCRIPTION
  Installs the agentic-dlc plugin, skills, subagents, and router rules into
  $HOME\.gemini\config\ and scaffolds the target <PROJECT_ROOT> directory structure.
.EXAMPLE
  .\bootstrap.ps1 -ProjectRoot "C:\projects\my-modernized-app"
#>
param(
  [string]$ProjectRoot = "",
  [switch]$InstallPlaywright
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$CallerPwd = (Get-Location).Path
$CallerBase = Split-Path -Leaf $CallerPwd

if ([string]::IsNullOrWhiteSpace($ProjectRoot)) {
  if (($CallerPwd -ne $ScriptDir) -and (-not ($CallerBase -like "*agentic-dlc*"))) {
    $ProjectRoot = $CallerPwd
  }
}

$GeminiConfig = Join-Path $HOME ".gemini\config"
$PluginDest = Join-Path $GeminiConfig "plugins\agentic-dlc"

Write-Host "=============================================================================="
Write-Host " Installing Enterprise Agentic DLC (agentic-dlc)"
Write-Host "=============================================================================="

# 1. Remove any stale paths
Write-Host "[1/5] Removing any stale global rules/skills..."
$StalePaths = @(
  (Join-Path $GeminiConfig "plugins\agentic-dlc"),
  (Join-Path $GeminiConfig "rules\AGENTS.md"),
  (Join-Path $GeminiConfig "skills\01-discovery-and-grouping"),
  (Join-Path $GeminiConfig "skills\02-spec-architect-and-judge"),
  (Join-Path $GeminiConfig "skills\03-story-and-sprint-planner"),
  (Join-Path $GeminiConfig "skills\04-solution-architect"),
  (Join-Path $GeminiConfig "skills\05-test-plan-designer"),
  (Join-Path $GeminiConfig "skills\06-coding-agent"),
  (Join-Path $GeminiConfig "skills\07-test-runner-and-healer"),
  (Join-Path $GeminiConfig "skills\08-container-and-gdc-packager"),
  (Join-Path $GeminiConfig "skills\09-gdc-fleet-deployer-and-observability"),
  (Join-Path $GeminiConfig "skills\google-cloud-ui-design")
)
foreach ($p in $StalePaths) {
  if (Test-Path $p) {
    Remove-Item -Recurse -Force $p
  }
}

# 2. Install plugin
Write-Host "[2/5] Installing plugin to $PluginDest..."
New-Item -ItemType Directory -Force -Path (Join-Path $GeminiConfig "plugins") | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $GeminiConfig "rules") | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $GeminiConfig "skills") | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $GeminiConfig "agents") | Out-Null

if (Test-Path $PluginDest) {
  Remove-Item -Recurse -Force $PluginDest
}
Copy-Item -Recurse -Force $ScriptDir $PluginDest
if (Test-Path (Join-Path $PluginDest ".git")) {
  Remove-Item -Recurse -Force (Join-Path $PluginDest ".git")
}

Copy-Item -Force (Join-Path $PluginDest "rules\AGENTS.md") (Join-Path $GeminiConfig "rules\AGENTS.md")
Get-ChildItem -Directory (Join-Path $PluginDest "skills") | ForEach-Object {
  $destSkill = Join-Path $GeminiConfig ("skills\" + $_.Name)
  if (Test-Path $destSkill) { Remove-Item -Recurse -Force $destSkill }
  Copy-Item -Recurse -Force $_.FullName $destSkill
}
Get-ChildItem -File (Join-Path $PluginDest "agents\*.md") | ForEach-Object {
  Copy-Item -Force $_.FullName (Join-Path $GeminiConfig ("agents\" + $_.Name))
}

# 3. Create ALM credentials template if not present
$EnvFile = Join-Path $GeminiConfig "agentic-dlc.env"
if (-not (Test-Path $EnvFile)) {
  Write-Host "[3/5] Creating ALM credentials template at $EnvFile..."
  @"
# Atlassian Jira Cloud (optional — leave blank for offline CSV/JSON mode)
JIRA_URL=
JIRA_EMAIL=
JIRA_API_TOKEN=
JIRA_PROJECT_KEY=
JIRA_BOARD_ID=

# Microsoft Azure DevOps Boards (optional)
ADO_ORG_URL=
ADO_PROJECT=
ADO_PAT=

# Default Sprint Velocity Capacity (story points per sprint, default 21)
DLC_SPRINT_CAPACITY_POINTS=21

# Google Distributed Cloud (GDC) Fleet & Multi-Cloud / On-Prem Deployment (optional)
GDC_FLEET_PROJECT=
GDC_CONNECTIVITY_MODE=gdc-connected
GDC_CONTAINER_REGISTRY=registry.gdc.local
GDC_TARGET_ENVIRONMENTS=on-prem-gdc,gcp,aws,azure
"@ | Set-Content -Path $EnvFile -Encoding UTF8
} else {
  Write-Host "[3/5] Preserving existing ALM credentials file at $EnvFile."
}

# 4. Scaffold <PROJECT_ROOT> if provided
if (-not [string]::IsNullOrWhiteSpace($ProjectRoot)) {
  New-Item -ItemType Directory -Force -Path $ProjectRoot | Out-Null
  $ResolvedRoot = (Resolve-Path $ProjectRoot).Path
  Write-Host "[4/5] Initializing project directory structure at $ResolvedRoot..."
  foreach ($sub in @(
    "resources\inputs",
    "resources\design_references",
    "resources\policies_and_statutes",
    "resources\shared_services",
    "specs",
    "backlog",
    "design",
    "test",
    "src",
    "deploy\containers",
    "deploy\gdc\base",
    "deploy\gdc\overlays\on-prem-gdc",
    "deploy\gdc\overlays\gcp",
    "deploy\gdc\overlays\aws",
    "deploy\gdc\overlays\azure",
    "deploy\gdc\policy-controller",
    "deploy\gdc\service-mesh",
    "deploy\gdc\config-sync",
    "deploy\observability"
  )) {
    New-Item -ItemType Directory -Force -Path (Join-Path $ResolvedRoot $sub) | Out-Null
  }
  Set-Content -Path (Join-Path $GeminiConfig "project_root.txt") -Value $ResolvedRoot -NoNewline -Encoding UTF8
  Write-Host "      Saved active project root -> $(Join-Path $GeminiConfig 'project_root.txt')"
} else {
  Write-Host "[4/5] No -ProjectRoot specified (global plugin installed)."
}

# 5. Optional Playwright install
if ($InstallPlaywright) {
  Write-Host "[5/5] Installing Python Playwright + Chromium..."
  python -m pip install --upgrade playwright
  python -m playwright install chromium
} else {
  Write-Host "[5/5] Done. (Optional: run 'python -m pip install playwright; python -m playwright install chromium' for full Playwright browser inspection.)"
}

Write-Host "=============================================================================="
Write-Host " Installation Complete!"
Write-Host " - Plugin Path  : $PluginDest"
Write-Host " - ALM Env File : $EnvFile"
if (-not [string]::IsNullOrWhiteSpace($ProjectRoot)) {
  Write-Host " - Project Root : $ResolvedRoot"
}
Write-Host "=============================================================================="
