$ErrorActionPreference = "Stop"

$raiz = [IO.Path]::GetFullPath($PSScriptRoot)
$origem = [IO.Path]::GetFullPath((Join-Path $raiz "ocr-extrator"))
if (-not (Test-Path -LiteralPath (Join-Path $raiz ".git"))) {
    throw "Execute este script na raiz do repositório Git."
}
if (-not (Test-Path -LiteralPath (Join-Path $origem "app\main.py"))) {
    throw "A pasta ocr-extrator esperada não foi encontrada."
}
if (-not $origem.StartsWith($raiz + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
    throw "Origem fora da raiz do repositório."
}

Write-Host "Parando processos deste diretório..." -ForegroundColor Yellow
Get-CimInstance Win32_Process | Where-Object {
    $_.CommandLine -and $_.CommandLine.IndexOf($origem, [StringComparison]::OrdinalIgnoreCase) -ge 0 -and
    $_.ProcessId -ne $PID
} | ForEach-Object {
    Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
}

# Ambientes e saídas reproduzíveis não devem carregar caminhos absolutos antigos.
$gerados = @(
    ".venv", ".next", ".pytest_cache", ".ruff_cache", "tmp",
    "frontend\node_modules", "frontend\.next"
)
foreach ($relativo in $gerados) {
    $alvo = [IO.Path]::GetFullPath((Join-Path $origem $relativo))
    if (-not $alvo.StartsWith($origem + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Alvo gerado fora da origem: $alvo"
    }
    if (Test-Path -LiteralPath $alvo) { Remove-Item -LiteralPath $alvo -Recurse -Force }
}

# Os dois arquivos da raiz eram apenas pontes temporárias. A versão completa
# que está dentro do projeto passa a ocupar o lugar definitivo.
Remove-Item -LiteralPath (Join-Path $raiz "README.md") -Force -ErrorAction SilentlyContinue
Remove-Item -LiteralPath (Join-Path $raiz "iniciar.ps1") -Force -ErrorAction SilentlyContinue

Get-ChildItem -LiteralPath $origem -Force | ForEach-Object {
    $destino = Join-Path $raiz $_.Name
    if (Test-Path -LiteralPath $destino) {
        throw "Conflito ao migrar: $destino já existe."
    }
    Move-Item -LiteralPath $_.FullName -Destination $destino
}
Remove-Item -LiteralPath $origem -Force

Write-Host "Projeto migrado para $raiz" -ForegroundColor Green
