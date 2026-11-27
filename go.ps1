<#
.SYNOPSIS
    Runner for the 12-Module Python 3.14 & Software Engineering Fundamentals Lab.

.EXAMPLE
    .\go.ps1 -Check
    .\go.ps1 -Module m01
    .\go.ps1 -VerifySolutions
#>
[CmdletBinding()]
param(
    [switch]$Check,
    [string]$Module,
    [switch]$VerifySolutions
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Ensure-LabVenv {
    $venvPyWin = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
    $venvPyPosix = Join-Path $PSScriptRoot ".venv/bin/python"
    if ((Test-Path $venvPyWin) -or (Test-Path $venvPyPosix)) {
        return
    }

    Write-Host "==> Provisioning .venv via uv..." -ForegroundColor Cyan
    if (-not $env:UV_DEFAULT_INDEX) {
        $pipCfg = (& python -m pip config list 2>$null) -join "`n"
        if ($pipCfg -match "global\.index-url='([^']+)'") {
            $env:UV_DEFAULT_INDEX = $Matches[1]
        }
    }
    & uv venv
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    & uv pip install --system-certs "pytest>=8.0" "hypothesis>=6.100" "ruff>=0.9" "pyright>=1.1.390"
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

Push-Location $PSScriptRoot
try {
    if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
        throw "Required tool 'uv' was not found on PATH. Install uv from https://docs.astral.sh/uv/ first."
    }

    Ensure-LabVenv

    if ($Check) {
        Write-Host "==> Checking toolchain environment..." -ForegroundColor Cyan
        & uv --version
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

        & uv run --no-sync python --version
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

        Write-Host "==> Running full starter + 12-solution verification suite..." -ForegroundColor Cyan
        & uv run --no-sync python scripts/verify_all.py
        exit $LASTEXITCODE
    }

    if ($Module) {
        if ($VerifySolutions) {
            & uv run --no-sync python scripts/eval_module.py $Module --use-solutions
        } else {
            & uv run --no-sync python scripts/eval_module.py $Module
        }
        exit $LASTEXITCODE
    }

    if ($VerifySolutions) {
        Write-Host "==> Evaluating all 12 reference solutions across Gates 1-5..." -ForegroundColor Cyan
        & uv run --no-sync python scripts/eval_module.py all --use-solutions
        exit $LASTEXITCODE
    }

    Write-Host "Usage:" -ForegroundColor Yellow
    Write-Host "  .\go.ps1 -Check              # Verify environment, starter negative checks, and all 12 solutions"
    Write-Host "  .\go.ps1 -Module m01         # Run Gates 1-5 on your workspace code for a module (m01..m12 or full slug)"
    Write-Host "  .\go.ps1 -VerifySolutions    # Run Gates 1-5 against all 12 reference solutions"
    exit 0
}
finally {
    Pop-Location
}
