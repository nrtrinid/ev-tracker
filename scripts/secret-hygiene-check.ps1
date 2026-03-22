param()

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

$targets = @(
  "backend/.env",
  "frontend/.env.local"
)

$failed = $false

Write-Host "Secret hygiene audit" -ForegroundColor Cyan
Write-Host "Repo root: $repoRoot"
Write-Host ""

foreach ($target in $targets) {
  $exists = Test-Path $target
  $ignored = git check-ignore $target 2>$null
  $tracked = git ls-files -- $target

  Write-Host $target -ForegroundColor Yellow
  Write-Host "  exists:   $exists"
  Write-Host "  ignored:  $([bool]$ignored)"
  Write-Host "  tracked:  $([bool]$tracked)"

  if ($tracked) {
    Write-Host "  FAIL: secret file is tracked by git" -ForegroundColor Red
    $failed = $true
  } elseif (-not $ignored -and $exists) {
    Write-Host "  WARN: local secret file exists but is not ignored" -ForegroundColor DarkYellow
    $failed = $true
  } else {
    Write-Host "  OK" -ForegroundColor Green
  }

  Write-Host ""
}

$staged = git diff --cached --name-only
$stagedSecretLike = @($staged | Where-Object {
  $_ -match '(^|/)\.env($|\.|/)' -or $_ -match 'webhook' -or $_ -match 'secret'
})

Write-Host "Staged secret-like paths:" -ForegroundColor Yellow
if ($stagedSecretLike.Count -gt 0) {
  $stagedSecretLike | ForEach-Object { Write-Host "  $_" -ForegroundColor Red }
  $failed = $true
} else {
  Write-Host "  none" -ForegroundColor Green
}

Write-Host ""
if ($failed) {
  Write-Host "Secret hygiene audit failed." -ForegroundColor Red
  exit 1
}

Write-Host "Secret hygiene audit passed." -ForegroundColor Green
