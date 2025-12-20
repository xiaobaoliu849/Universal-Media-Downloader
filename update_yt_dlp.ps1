<#!
yt-dlp updater script (ASCII only to avoid encoding parse issues)
Features:
 1. Update stable or nightly channel
 2. Download latest assets (yt-dlp.exe + SHA2-256SUMS if present)
 3. SHA256 verification (optional skip)
 4. Backup old binary with timestamp
 5. Replace and print new version
Usage:
  .\update_yt_dlp.ps1                # stable
  .\update_yt_dlp.ps1 -Channel nightly
  .\update_yt_dlp.ps1 -DryRun
  .\update_yt_dlp.ps1 -SkipHash
#>
[CmdletBinding()]
param(
  [ValidateSet("stable","nightly")]
  [string]$Channel = "stable",
  [switch]$DryRun,
  [switch]$SkipHash
)

$ErrorActionPreference = 'Stop'

function Write-Info($msg){ Write-Host "[INFO] $msg" -ForegroundColor Cyan }
function Write-Warn($msg){ Write-Host "[WARN] $msg" -ForegroundColor Yellow }
function Write-Err($msg){ Write-Host "[ERROR] $msg" -ForegroundColor Red }

$repo = if ($Channel -eq "nightly") { "yt-dlp/yt-dlp-nightly-builds" } else { "yt-dlp/yt-dlp" }
Write-Info "Channel: $Channel  Repository: $repo"

$apiUrl = "https://api.github.com/repos/$repo/releases/latest"
Write-Info "Querying $apiUrl"
try {
  $release = Invoke-RestMethod $apiUrl -Headers @{ 'User-Agent' = 'curl/8.0' }
} catch {
  Write-Err "Failed to query release info: $_"; exit 1
}

$tag = $release.tag_name
Write-Info "Latest tag: $tag"

# assets: yt-dlp uses SHA2-256SUMS (fallback to SHA256SUMS if ever introduced)
$exeAsset  = $release.assets | Where-Object { $_.name -eq "yt-dlp.exe" }
$sumAsset  = $release.assets | Where-Object { $_.name -in @("SHA2-256SUMS","SHA256SUMS") }
if (-not $exeAsset){ Write-Err "yt-dlp.exe asset not found"; exit 2 }
if (-not $sumAsset){ Write-Warn "Checksum file not found (continuing without hash verify)" }

$downloadExe = Join-Path $PSScriptRoot "yt-dlp_new.exe"
$downloadSum = if ($sumAsset) { Join-Path $PSScriptRoot $sumAsset.name } else { $null }

Write-Info "Downloading executable -> $downloadExe"
Invoke-WebRequest -Uri $exeAsset.browser_download_url -OutFile $downloadExe

if ($sumAsset) {
  Write-Info "Downloading checksum file -> $downloadSum"
  Invoke-WebRequest -Uri $sumAsset.browser_download_url -OutFile $downloadSum
}

if ($sumAsset -and -not $SkipHash) {
  Write-Info "Verifying SHA256..."
  $localHash = (Get-FileHash $downloadExe -Algorithm SHA256).Hash.ToLower()
  $line = (Select-String -Path $downloadSum -Pattern 'yt-dlp.exe' -SimpleMatch | Select-Object -First 1).Line
  if (-not $line) { Write-Err "yt-dlp.exe line not found in checksum file"; exit 3 }
  $expected = ($line -split '\s+')[0].ToLower()
  if ($localHash -ne $expected) {
    Write-Err "Hash mismatch local=$localHash expected=$expected"; exit 4
  } else { Write-Info "Hash OK" }
} elseif (-not $sumAsset) {
  Write-Warn "Skip hash verify (no checksum file)"
} elseif ($SkipHash) {
  Write-Warn "User skipped hash verify"
}

if ($DryRun) {
  Write-Info "DryRun: not replacing current yt-dlp.exe"
  exit 0
}

$target = Join-Path $PSScriptRoot "yt-dlp.exe"
if (Test-Path $target) {
  $stamp = Get-Date -Format 'yyyyMMdd_HHmmss'
  $backup = Join-Path $PSScriptRoot ("yt-dlp_" + $stamp + "_backup.exe")
  Write-Info "Backup old binary -> $backup"
  Copy-Item $target $backup -Force
  Remove-Item $target -Force
}

Write-Info "Replacing with new version"
Rename-Item $downloadExe "yt-dlp.exe"

try { $ver = (& .\yt-dlp.exe --version) } catch { $ver = "UNKNOWN (execution failed)" }
Write-Host "Update done version=$ver" -ForegroundColor Green

Write-Info "Done"
