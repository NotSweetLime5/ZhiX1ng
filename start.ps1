param(
    [ValidateSet('setup', 'up', 'api', 'a2a', 'mcp', 'worker', 'web', 'test', 'stop')]
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
        docker compose --profile search --profile obs up -d postgres redis minio etcd milvus searxng jaeger prometheus grafana
        Check-Exit
        docker build -f backend/deployments/sandbox.Dockerfile -t nexus-python-sandbox:local backend
        Check-Exit
        Set-Location -LiteralPath (Join-Path $projectRoot 'backend')
        uv sync --frozen
        Check-Exit
        uv run python -c "from pathlib import Path; import secrets; p=Path('.env'); t=Path('.env.example').read_text(); p.write_text(t.replace('replace-with-a-random-secret',secrets.token_urlsafe(32)).replace('replace-with-an-independent-random-secret',secrets.token_urlsafe(32)).replace('replace-with-an-admin-password',secrets.token_urlsafe(24))) if not p.exists() else None"
        Check-Exit
        $ready = $false
        for ($attempt = 0; $attempt -lt 30; $attempt++) {
            docker compose -f (Join-Path $projectRoot 'compose.yaml') exec -T postgres pg_isready -U nexus
            if ($LASTEXITCODE -eq 0) { $ready = $true; break }
            Start-Sleep -Seconds 2
        }
        if (-not $ready) { throw 'PostgreSQL did not become ready.' }
        uv run python -m app.cli createdb
        Check-Exit
        uv run python -m app.cli migrate
        Check-Exit
        uv run python -m app.cli seed
        Check-Exit
        Set-Location -LiteralPath (Join-Path $projectRoot 'frontend')
        npm.cmd ci
        Check-Exit
        Write-Host 'Setup complete. Run start.ps1 up for all backend services, then start.ps1 web.'
        Write-Host 'For a new installation, the admin password is NX_ADMIN_PASSWORD in backend/.env.'
    }
    'up' {
        Set-Location -LiteralPath $projectRoot
        docker compose --profile search --profile obs up -d --wait postgres redis minio etcd milvus searxng jaeger prometheus grafana
        Check-Exit
        Set-Location -LiteralPath (Join-Path $projectRoot 'backend')
        uv run --frozen python -m app.cli migrate
        Check-Exit
        Set-Location -LiteralPath $projectRoot
        docker build -f backend/deployments/sandbox.Dockerfile -t nexus-python-sandbox:local backend
        Check-Exit
        docker compose --profile app --profile search --profile obs up -d --build
        Check-Exit
        docker compose exec -T api python -m app.scripts.enable_integrations --mcp-url http://mcp:8086/mcp --a2a-url http://a2a:8082
        Check-Exit
    }
    'a2a' {
        Set-Location -LiteralPath (Join-Path $projectRoot 'backend')
        uv run --frozen python -m app.cli a2a
        Check-Exit
    }
    'mcp' {
        Set-Location -LiteralPath (Join-Path $projectRoot 'backend')
        uv run --frozen python -m app.cli mcp
        Check-Exit
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
