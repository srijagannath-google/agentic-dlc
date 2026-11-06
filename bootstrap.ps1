<#
.SYNOPSIS
  Enterprise Agentic DLC (agentic-dlc) — Windows Developer Laptop Installer
.DESCRIPTION
  Installs the agentic-dlc plugin, skills, subagents, and router rules into
  $HOME\.gemini\config\ and scaffolds the target <PROJECT_ROOT> directory structure.
.EXAMPLE
  .\bootstrap.ps1 -ProjectRoot "C:\projects\my-modernized-app"
#>
[CmdletBinding()]
param(
  [string]$ProjectRoot = "",
  [switch]$InstallPlaywright
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$CallerPwd = (Get-Location).Path
$CallerBase = Split-Path -Leaf $CallerPwd
$Utf8NoBom = New-Object System.Text.UTF8Encoding $false

function Write-Utf8NoBom([string]$Path, [string]$Content) {
  # Set-Content -Encoding UTF8 writes a BOM on Windows PowerShell 5.1, which breaks plain-text consumers.
  [IO.File]::WriteAllText($Path, $Content, $Utf8NoBom)
}

function Test-PluginDirName([string]$Name) {
  # Case-insensitive, exact plugin directory names only (agentic-dlc, agentic-dlc-v4, ...).
  # A project called "agentic-dlc-demo-app" is a legitimate <PROJECT_ROOT>.
  return ($Name -match '^(?i)agentic-dlc(-v\d+)?$')
}

function Test-PluginLayout([string]$Dir) {
  return (Test-Path -LiteralPath (Join-Path $Dir "plugin.json")) -and (Test-Path -LiteralPath (Join-Path $Dir "skills") -PathType Container)
}

function Get-CanonicalPath([string]$Path) {
  return (Resolve-Path -LiteralPath $Path).ProviderPath.TrimEnd('\')
}

$GeminiConfig = Join-Path $HOME ".gemini\config"
$PluginDest = Join-Path $GeminiConfig "plugins\agentic-dlc"

# 0. Resolve <PROJECT_ROOT> safely: never the installer folder, never silently the current directory.
if (-not [string]::IsNullOrWhiteSpace($ProjectRoot)) {
  $leaf = Split-Path -Leaf $ProjectRoot.TrimEnd('\', '/')
  $sameAsScript = (Test-Path -LiteralPath $ProjectRoot) -and ((Get-CanonicalPath $ProjectRoot) -ieq (Get-CanonicalPath $ScriptDir))
  if ((Test-PluginDirName $leaf) -or $sameAsScript) {
    Write-Error "$ProjectRoot is the plugin/installer directory and can never be a <PROJECT_ROOT>."
    exit 2
  }
} else {
  $callerIsPlugin = ($CallerPwd -ieq $ScriptDir) -or (Test-PluginDirName $CallerBase) -or (Test-PluginLayout $CallerPwd)
  $generalPurpose = @($HOME, (Join-Path $HOME "Downloads"), (Join-Path $HOME "Desktop"), (Join-Path $HOME "Documents"))
  if (-not $callerIsPlugin) {
    if ($generalPurpose | Where-Object { $_ -ieq $CallerPwd.TrimEnd('\') }) {
      Write-Host "NOTE: $CallerPwd is a general-purpose folder and will not be used as a project root."
    } elseif ([Environment]::UserInteractive -and -not [Console]::IsInputRedirected) {
      $answer = Read-Host "Bind the current directory as <PROJECT_ROOT>? [$CallerPwd] (y/N)"
      if ($answer -match '^(y|yes)$') { $ProjectRoot = $CallerPwd }
    } else {
      Write-Host "NOTE: no -ProjectRoot given and not running interactively; the current directory was NOT bound as a project root."
    }
  }
}

Write-Host "=============================================================================="
Write-Host " Installing Enterprise Agentic DLC (agentic-dlc)"
Write-Host "=============================================================================="

# 1. Remove any stale global skills (the shared global rules file is handled separately below — it is backed up, not deleted)
Write-Host "[1/5] Removing any stale global skills..."
$StalePaths = @(
  (Join-Path $GeminiConfig "skills\00-setup-and-connection"),
  (Join-Path $GeminiConfig "skills\01-discovery-and-grouping"),
  (Join-Path $GeminiConfig "skills\02-spec-architect-and-judge"),
  (Join-Path $GeminiConfig "skills\03-story-and-sprint-planner"),
  (Join-Path $GeminiConfig "skills\04-solution-architect"),
  (Join-Path $GeminiConfig "skills\05-test-plan-designer"),
  (Join-Path $GeminiConfig "skills\06-coding-agent"),
  (Join-Path $GeminiConfig "skills\07-test-runner-and-healer"),
  (Join-Path $GeminiConfig "skills\08-container-and-gdc-packager"),
  (Join-Path $GeminiConfig "skills\09-gdc-fleet-deployer-and-observability"),
  (Join-Path $GeminiConfig "skills\10-drift-and-evolution"),
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

# Files that belong to the development checkout but never to an installation.
$InstallExcludeDirs = @(".git", "__pycache__")
$InstallExcludeFiles = @("push-to-github.sh", "*.pyc")

$SrcReal = Get-CanonicalPath $ScriptDir
$DestReal = if (Test-Path -LiteralPath $PluginDest) { Get-CanonicalPath $PluginDest } else { "" }
if ($DestReal -and ($SrcReal -ieq $DestReal)) {
  # Running from the installed location itself: nothing to copy, and never delete files we are executing from.
  Write-Host "      Already running from $PluginDest — skipping self-copy."
} elseif ($DestReal -and $SrcReal.StartsWith($DestReal + '\', [StringComparison]::OrdinalIgnoreCase)) {
  Write-Error "$ScriptDir is inside the install destination $PluginDest; refusing to replace the destination from within it."
  exit 2
} else {
  if (Test-Path $PluginDest) {
    Remove-Item -Recurse -Force $PluginDest
  }
  New-Item -ItemType Directory -Force -Path $PluginDest | Out-Null
  $robocopy = Get-Command robocopy.exe -ErrorAction SilentlyContinue
  if ($robocopy) {
    # robocopy exit codes 0-7 are success (8+ = failure)
    & $robocopy.Source $ScriptDir $PluginDest /E /NFL /NDL /NJH /NJS /NP /XD $InstallExcludeDirs /XF $InstallExcludeFiles | Out-Null
    if ($LASTEXITCODE -ge 8) { throw "robocopy failed with exit code $LASTEXITCODE" }
  } else {
    Copy-Item -Recurse -Force (Join-Path $ScriptDir "*") $PluginDest
    foreach ($d in $InstallExcludeDirs) {
      Get-ChildItem -LiteralPath $PluginDest -Recurse -Force -Directory -Filter $d -ErrorAction SilentlyContinue |
        ForEach-Object { Remove-Item -Recurse -Force $_.FullName }
    }
    foreach ($f in $InstallExcludeFiles) {
      Get-ChildItem -LiteralPath $PluginDest -Recurse -Force -File -Filter $f -ErrorAction SilentlyContinue |
        ForEach-Object { Remove-Item -Force $_.FullName }
    }
  }
}

# Sync rules, skills, and subagents for global discovery.
# The global rules file is shared with other plugins: back it up instead of discarding user content.
$GlobalRules = Join-Path $GeminiConfig "rules\AGENTS.md"
$PluginRules = Join-Path $PluginDest "rules\AGENTS.md"
if (Test-Path -LiteralPath $GlobalRules) {
  $existing = [IO.File]::ReadAllText($GlobalRules)
  $incoming = [IO.File]::ReadAllText($PluginRules)
  if ($existing -ne $incoming) {
    $backup = "$GlobalRules.bak-$(Get-Date -Format 'yyyyMMdd-HHmmss')"
    Copy-Item -LiteralPath $GlobalRules -Destination $backup -Force
    Write-Warning "Existing $GlobalRules differs from the agentic-dlc router rules and was backed up to: $backup"
    Write-Warning "Re-apply any custom rules from the backup after installation."
  }
}
Copy-Item -Force $PluginRules $GlobalRules
Get-ChildItem -Directory (Join-Path $PluginDest "skills") | ForEach-Object {
  $destSkill = Join-Path $GeminiConfig ("skills\" + $_.Name)
  if (Test-Path $destSkill) { Remove-Item -Recurse -Force $destSkill }
  Copy-Item -Recurse -Force $_.FullName $destSkill
}
Get-ChildItem -File (Join-Path $PluginDest "agents\*.md") | ForEach-Object {
  Copy-Item -Force $_.FullName (Join-Path $GeminiConfig ("agents\" + $_.Name))
}

# 3. Create ALM credentials template if not present (UTF-8 without BOM, ACL restricted to the current user)
$EnvFile = Join-Path $GeminiConfig "agentic-dlc.env"
if (-not (Test-Path $EnvFile)) {
  Write-Host "[3/5] Creating ALM credentials template at $EnvFile..."
  $envTemplate = @"
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

# Google Distributed Cloud (GDC) Fleet deployment: targets and connectivity come from
# specs/target_stack.json#deployment. Only Stage 8 `--live` (kubectl apply) reads optional per-environment
# kube contexts; uncomment and set as needed:
# GDC_KUBE_CONTEXT_ON_PREM_GDC=
# GDC_KUBE_CONTEXT_GCP=
# GDC_KUBE_CONTEXT_AWS=
# GDC_KUBE_CONTEXT_AZURE=
"@
  Write-Utf8NoBom $EnvFile ($envTemplate -replace "`r?`n", "`n")
  # Equivalent of chmod 600: drop inheritance and grant only the current user.
  $icacls = Get-Command icacls.exe -ErrorAction SilentlyContinue
  if ($icacls) {
    $me = [Security.Principal.WindowsIdentity]::GetCurrent().Name
    & $icacls.Source $EnvFile /inheritance:r /grant:r "${me}:(F)" | Out-Null
    if ($LASTEXITCODE -ne 0) { Write-Warning "Could not restrict permissions on $EnvFile (icacls exit $LASTEXITCODE). Restrict it manually." }
  } else {
    Write-Warning "icacls.exe not found — restrict permissions on $EnvFile manually."
  }
} else {
  Write-Host "[3/5] Preserving existing ALM credentials file at $EnvFile."
}

# 4. Scaffold <PROJECT_ROOT> if provided (or confirmed interactively).
#    Only the authoring folders are created; deploy/ is created by Stage 7 (08-container-and-gdc-packager)
#    so an empty deploy/ never makes the pipeline think Stages 7/8 are in scope.
if (-not [string]::IsNullOrWhiteSpace($ProjectRoot)) {
  New-Item -ItemType Directory -Force -Path $ProjectRoot | Out-Null
  $ResolvedRoot = Get-CanonicalPath $ProjectRoot
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
    "src"
  )) {
    New-Item -ItemType Directory -Force -Path (Join-Path $ResolvedRoot $sub) | Out-Null
  }
  Write-Utf8NoBom (Join-Path $GeminiConfig "project_root.txt") ($ResolvedRoot + "`n")
  Write-Host "      Saved active project root -> $(Join-Path $GeminiConfig 'project_root.txt')"
} else {
  Write-Host "[4/5] No -ProjectRoot specified (global plugin installed)."
  Write-Host "      To bind a project folder later, run:"
  Write-Host "        $PluginDest\bootstrap.ps1 -ProjectRoot C:\path\to\your-project"
}

# 5. Optional Playwright install
if ($InstallPlaywright) {
  Write-Host "[5/5] Installing Python Playwright + Chromium..."
  python -m pip install --user --upgrade playwright
  if ($LASTEXITCODE -eq 0) {
    python -m playwright install chromium
  } else {
    Write-Warning "Playwright pip install failed. Try 'pipx install playwright; playwright install chromium', a virtualenv, or install Google Chrome / Edge and set CHROME_BIN."
  }
} else {
  Write-Host "[5/5] Done. (Optional: run 'python -m pip install --user playwright; python -m playwright install chromium' for full Playwright browser inspection.)"
}

Write-Host "=============================================================================="
Write-Host " Installation Complete!"
Write-Host " - Plugin Path  : $PluginDest"
Write-Host " - ALM Env File : $EnvFile"
if (-not [string]::IsNullOrWhiteSpace($ProjectRoot)) {
  Write-Host " - Project Root : $ResolvedRoot"
  Write-Host " Next Step: Place your legacy files or BRD in $ResolvedRoot\resources\inputs\"
  Write-Host "            then start with Stage 0 (skill 00-setup-and-connection) to connect ALM and initialise the gate ledger."
}
Write-Host "=============================================================================="
