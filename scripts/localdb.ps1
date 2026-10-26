<#
Local PostgreSQL 16 without Docker or admin rights (Windows).

Binaries come from conda-forge, installed once with:
  .tools\micromamba.exe create -y -p .tools\pg -c conda-forge --override-channels postgresql=16
Data lives in .tools\pgdata (git-ignored). Passwords come from .env:
  POSTGRES_SUPERUSER_PASSWORD   for the "postgres" superuser
  DATABASE_URL                  postgresql://tcg:<password>@localhost:5432/tcg  (app role and database)

Usage: scripts\localdb.ps1 init|start|stop|status
#>
param([Parameter(Mandatory)][ValidateSet("init", "start", "stop", "status")][string]$Command)
$ErrorActionPreference = "Stop"

$root = Split-Path $PSScriptRoot -Parent
$bin = Join-Path $root ".tools\pg\Library\bin"
$data = Join-Path $root ".tools\pgdata"
$log = Join-Path $root ".tools\postgres.log"
if (-not (Test-Path "$bin\pg_ctl.exe")) { throw "PostgreSQL binaries not found in $bin (see the install line at the top)" }

function Read-DotEnv {
    $vars = @{}
    Get-Content (Join-Path $root ".env") | Where-Object { $_ -match '^\s*([A-Z_]+)=(.*)$' } |
        ForEach-Object { $vars[$Matches[1]] = $Matches[2].Trim() }
    return $vars
}

switch ($Command) {
    "init" {
        if (Test-Path $data) { throw "$data already exists; refusing to re-initialise" }
        $envVars = Read-DotEnv
        if ($envVars.DATABASE_URL -notmatch '^postgresql://([^:]+):([^@]+)@[^/]+/(\w+)$') { throw "DATABASE_URL in .env is not postgresql://user:pass@host:port/db" }
        $appUser, $appPass, $appDb = $Matches[1], $Matches[2], $Matches[3]
        $pwFile = New-TemporaryFile
        try {
            [IO.File]::WriteAllText($pwFile, $envVars.POSTGRES_SUPERUSER_PASSWORD)
            & "$bin\initdb.exe" -D $data -U postgres --pwfile=$pwFile -A scram-sha-256 -E UTF8 --locale=C | Out-Null
            if ($LASTEXITCODE) { throw "initdb failed" }
        } finally { Remove-Item $pwFile }
        # listen on localhost only
        Add-Content "$data\postgresql.conf" "`nlisten_addresses = 'localhost'`nport = 5432"
        & "$bin\pg_ctl.exe" -D $data -l $log -w start | Out-Null
        $env:PGPASSWORD = $envVars.POSTGRES_SUPERUSER_PASSWORD
        & "$bin\psql.exe" -h localhost -U postgres -d postgres -v ON_ERROR_STOP=1 -q `
            -c "CREATE ROLE $appUser LOGIN PASSWORD '$appPass'" -c "CREATE DATABASE $appDb OWNER $appUser"
        if ($LASTEXITCODE) { throw "creating role/database failed" }
        Write-Host "initialised $data and created role/database '$appUser'/'$appDb'; server is running"
    }
    "start" { & "$bin\pg_ctl.exe" -D $data -l $log -w start }
    "stop" { & "$bin\pg_ctl.exe" -D $data -w stop }
    "status" { & "$bin\pg_ctl.exe" -D $data status }
}
