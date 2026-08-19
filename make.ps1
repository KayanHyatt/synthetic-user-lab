<#
.SYNOPSIS
    make.ps1 stands in for `make` on Windows, where make is not installed.
    Targets mirror the Makefile described in CLAUDE.md / PROJECT_SPEC.md.

.USAGE
    .\make.ps1 install
    .\make.ps1 check
    .\make.ps1 test
    .\make.ps1 demo
    .\make.ps1 validate
#>
param(
    [Parameter(Position = 0)]
    [ValidateSet("install", "check", "test", "demo", "validate")]
    [string]$Target = "check"
)

$ErrorActionPreference = "Stop"

function Invoke-Step {
    param(
        [string]$Description,
        [string[]]$Command
    )
    Write-Host "==> $Description" -ForegroundColor Cyan
    & $Command[0] $Command[1..($Command.Length - 1)]
    if ($LASTEXITCODE -ne 0) {
        Write-Host "FAILED: $Description (exit $LASTEXITCODE)" -ForegroundColor Red
        exit $LASTEXITCODE
    }
}

function Install {
    Invoke-Step "uv sync" @("uv", "sync")
    Invoke-Step "install pre-commit hooks" @("uv", "run", "pre-commit", "install")
}

function Test {
    Invoke-Step "pytest" @("uv", "run", "pytest")
}

function Check {
    Invoke-Step "ruff check" @("uv", "run", "ruff", "check", ".")
    Invoke-Step "ruff format --check" @("uv", "run", "ruff", "format", "--check", ".")
    Invoke-Step "mypy" @("uv", "run", "mypy")
    Test
    Write-Host "All checks passed." -ForegroundColor Green
}

function Demo {
    Write-Host "demo: not implemented yet (lands in M7 - Interface and packaging)." -ForegroundColor Yellow
}

function Validate {
    Invoke-Step "sul validate" @("uv", "run", "sul", "validate")
}

switch ($Target) {
    "install" { Install }
    "check" { Check }
    "test" { Test }
    "demo" { Demo }
    "validate" { Validate }
}
