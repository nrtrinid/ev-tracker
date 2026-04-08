param(
    [string]$BaseUrl = "http://localhost:8000",
    [string]$EnvFile = ".\backend\.env"
)

if (-not (Test-Path $EnvFile)) {
    Write-Output "Env file missing: $EnvFile"
    exit 1
}

$token = $null
foreach ($line in Get-Content $EnvFile) {
    if (-not $token -and $line -match '^\s*CRON_TOKEN\s*=\s*(.+?)\s*$') {
        $raw = $matches[1].Trim()
        if ($raw -match '^"(.*)"$') { $raw = $matches[1] }
        elseif ($raw -match "^'(.*)'$") { $raw = $matches[1] }
        $token = $raw
    }
}

if ([string]::IsNullOrWhiteSpace($token)) {
    Write-Output "CRON_TOKEN not found or empty in $EnvFile"
    exit 1
}

$headers = @{ "X-Ops-Token" = $token }
$paths = @(
    "/api/ops/research-opportunities/summary",
    "/api/ops/model-calibration/summary",
    "/api/ops/pickem-research/summary"
)

function Get-StatusCode {
    param([string]$Url, [hashtable]$RequestHeaders)
    try {
        $resp = Invoke-WebRequest -Uri $Url -Method GET -Headers $RequestHeaders -TimeoutSec 30 -ErrorAction Stop
        return [string][int]$resp.StatusCode
    }
    catch {
        if ($_.Exception.Response -and $_.Exception.Response.StatusCode) {
            return [string][int]$_.Exception.Response.StatusCode.value__
        }
        return "ERR"
    }
}

Write-Output "Token source: backend/.env (CRON_TOKEN loaded; value hidden)"
Write-Output "Sequential calls (10 per endpoint):"

foreach ($path in $paths) {
    $counts = @{}
    for ($i = 1; $i -le 10; $i++) {
        $status = Get-StatusCode -Url ($BaseUrl + $path) -RequestHeaders $headers
        if ($counts.ContainsKey($status)) { $counts[$status]++ } else { $counts[$status] = 1 }
    }
    $summary = ($counts.GetEnumerator() | Sort-Object Name | ForEach-Object { "$($_.Key):$($_.Value)" }) -join ', '
    Write-Output ("{0} -> {1}" -f $path, $summary)
}

Write-Output "Parallel batch (3 calls total, one per endpoint):"
$jobs = foreach ($path in $paths) {
    Start-Job -ScriptBlock {
        param($Base, $Path, $Token)
        try {
            $resp = Invoke-WebRequest -Uri ($Base + $Path) -Method GET -Headers @{ "X-Ops-Token" = $Token } -TimeoutSec 30 -ErrorAction Stop
            [pscustomobject]@{ Path = $Path; Status = [string][int]$resp.StatusCode }
        }
        catch {
            $status = "ERR"
            if ($_.Exception.Response -and $_.Exception.Response.StatusCode) {
                $status = [string][int]$_.Exception.Response.StatusCode.value__
            }
            [pscustomobject]@{ Path = $Path; Status = $status }
        }
    } -ArgumentList $BaseUrl, $path, $token
}

Receive-Job -Job $jobs -Wait -AutoRemoveJob | Sort-Object Path | ForEach-Object {
    Write-Output ("{0} -> {1}" -f $_.Path, $_.Status)
}
