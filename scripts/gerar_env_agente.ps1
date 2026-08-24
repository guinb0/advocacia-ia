param([switch]$Force)

$ErrorActionPreference = "Stop"
$raizAcervo = Split-Path $PSScriptRoot -Parent
$raizAgente = Resolve-Path (Join-Path $raizAcervo "..\ia-juridica")
$origem = Join-Path $raizAcervo ".env"
$destino = Join-Path $raizAgente ".env"

if (-not (Test-Path $origem)) { throw "Falta .env na raiz do projeto." }
if ((Test-Path $destino) -and -not $Force) {
    throw "ia-juridica/.env já existe. Use -Force para atualizá-lo."
}

$dados = @{}
foreach ($linha in Get-Content $origem -Encoding UTF8) {
    $texto = $linha.Trim()
    if (-not $texto -or $texto.StartsWith("#") -or -not $texto.Contains("=")) { continue }
    $nome, $valor = $texto.Split("=", 2)
    $dados[$nome.Trim()] = $valor.Trim().Trim('"').Trim("'")
}

foreach ($obrigatoria in @("SQLSERVER_HOST", "SQLSERVER_USER", "SQLSERVER_PASSWORD", "SQLSERVER_DATABASE")) {
    if (-not $dados[$obrigatoria]) { throw "Falta $obrigatoria no .env da raiz." }
}

$usuario = [uri]::EscapeDataString($dados.SQLSERVER_USER)
$senha = [uri]::EscapeDataString($dados.SQLSERVER_PASSWORD)
$porta = if ($dados.SQLSERVER_PORT) { $dados.SQLSERVER_PORT } else { "1433" }
$banco = $dados.SQLSERVER_DATABASE
$urlBanco = "mssql://${usuario}:${senha}@$($dados.SQLSERVER_HOST):${porta}/${banco}"

$linhas = @(
    "APP_NAME=legal-agent",
    "ENVIRONMENT=development",
    "DEBUG=false",
    "DATABASE_URL=$urlBanco",
    "DATABASE_POOL_SIZE=10",
    "DATABASE_MAX_OVERFLOW=5",
    "REDIS_URL=redis://localhost:6380/2",
    "LOG_LEVEL=INFO",
    "LOG_FORMAT=console",
    "AUTH_ENABLED=false",
    "DEV_ORGANIZATION_ID=00000000-0000-0000-0000-000000000001",
    "DEV_USER_SUBJECT=acervo-bridge",
    "DEV_USER_ROLES=ADMIN",
    "DEEPSEEK_API_KEY=$($dados.DEEPSEEK_API_KEY)",
    "DEEPSEEK_BASE_URL=$($dados.DEEPSEEK_BASE_URL)",
    "DEEPSEEK_MODEL=$($dados.DEEPSEEK_MODEL)",
    "EMBEDDINGS_API_KEY=$($dados.EMBEDDINGS_API_KEY)",
    "EMBEDDINGS_BASE_URL=$($dados.EMBEDDINGS_BASE_URL)",
    "EMBEDDINGS_MODEL_NAME=$($dados.EMBEDDINGS_MODEL_NAME)",
    "EMBEDDINGS_DIMENSIONS=$($dados.EMBEDDINGS_DIMENSIONS)",
    "JURISPRUDENCE_DATABASE_URL=$($dados.DATABASE_URL)",
    "JURISPRUDENCE_TIMEOUT_SECONDS=30",
    "PII_REDACTION_ENABLED=true",
    "PII_REHYDRATE_OUTPUT=true"
)

$linhas -join "`n" | Set-Content -Encoding UTF8 $destino
Write-Host "ia-juridica/.env atualizado (segredos não exibidos e arquivo ignorado pelo Git)." -ForegroundColor Green
