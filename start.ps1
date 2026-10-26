param(
    [ValidateSet('setup', 'api', 'worker', 'web', 'test', 'stop')]
    [string]$Action = 'setup'
)
$ErrorActionPreference = 'Stop'
$projectRoot = $PSScriptRoot

function Check-Exit {
    if ($LASTEXITCODE -ne 0) { throw "Command failed with exit code $LASTEXITCODE" }
}

switch ($Action) {
    'setup' {
        Set-Location -LiteralPath $projectRoot
        docker compose up -d postgres redis minio etcd milvus
        Check-Exit
        Set-Location -LiteralPath (Join-Path $projectRoot 'backend')
        uv sync --frozen
        Check-Exit
        uv run python -c "from pathlib import Path; import secrets; p=Path('.env'); t=Path('.env.example').read_text(); p.write_text(t.replace('replace-with-a-random-secret',secrets.token_urlsafe(32)).replace('replace-with-an-independent-random-secret',secrets.token_urlsafe(32))) if not p.exists() else None"
        Check-Exit
        $ready = $false
        for ($attempt = 0; $attempt -lt 30; $attempt++) {
            docker compose -f (Join-Path $projectRoot 'compose.yaml') exec -T postgres pg_isready -U nexus -d nexus_agent
            if ($LASTEXITCODE -eq 0) { $ready = $true; break }
            Start-Sleep -Seconds 2
        }
        if (-not $ready) { throw 'PostgreSQL did not become ready.' }
        uv run python -m app.cli migrate
        Check-Exit
        uv run python -m app.cli seed
        Check-Exit
        Set-Location -LiteralPath (Join-Path $projectRoot 'frontend')
        npm.cmd ci
        Check-Exit
        Write-Host 'Setup complete. Run start.ps1 api, worker, and web in separate terminals.'
    }
    'api' {
        Set-Location -LiteralPath (Join-Path $projectRoot 'backend')
        uv run python -m app.cli serve
        Check-Exit
    }
    'worker' {
        Set-Location -LiteralPath (Join-Path $projectRoot 'backend')
        uv run python -m app.cli worker
        Check-Exit
    }
    'web' {
        Set-Location -LiteralPath (Join-Path $projectRoot 'frontend')
        npm.cmd run dev -- --host 127.0.0.1
        Check-Exit
    }
    'test' {
        Set-Location -LiteralPath (Join-Path $projectRoot 'backend')
        uv run ruff check app alembic tests
        Check-Exit
        uv run pytest -q
        Check-Exit
        Set-Location -LiteralPath (Join-Path $projectRoot 'frontend')
        npm.cmd run build
        Check-Exit
    }
    'stop' {
        Set-Location -LiteralPath $projectRoot
        docker compose stop
        Check-Exit
    }
}
