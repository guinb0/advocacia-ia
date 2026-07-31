# Sobe o backend (FastAPI :8100) e o frontend (Next :3100) juntos.
#   .\iniciar.ps1          -> modo desenvolvimento (hot reload no front)
#   .\iniciar.ps1 -Prod    -> usa o build de producao do Next
#
# Portas 8100/3100 em vez das obvias 8000/3000 porque estas costumam ja estar
# ocupadas por outros servicos da maquina (WSL, outros projetos Next).
param([switch]$Prod)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$PortaBackend = 8100

# ---------------------------------------------------------------- backend
if (-not (Test-Path ".\.venv\Scripts\python.exe")) {
    Write-Host "Criando o ambiente Python..." -ForegroundColor Yellow
    uv venv --python 3.11      # o paddlepaddle ainda nao publica wheels para 3.13+
    uv pip install -r requirements.txt
}

# ---------------------------------------------------------------- frontend
if (-not (Test-Path ".\frontend\node_modules")) {
    Write-Host "Instalando as dependencias do frontend..." -ForegroundColor Yellow
    Push-Location .\frontend; npm install; Pop-Location
}
if ($Prod -and -not (Test-Path ".\frontend\.next\BUILD_ID")) {
    Write-Host "Compilando o frontend..." -ForegroundColor Yellow
    Push-Location .\frontend; npm run build; Pop-Location
}

Write-Host "`nBackend  : http://127.0.0.1:$PortaBackend  (docs interativos em /docs)" -ForegroundColor Cyan
Write-Host "Frontend : http://localhost:3100" -ForegroundColor Cyan
Write-Host "Ctrl+C encerra os dois.`n" -ForegroundColor DarkGray

# --timeout-keep-alive 65: o padrao do uvicorn e 5s, curto demais para o pool de
# conexoes de um cliente HTTP moderno, que reusaria um socket ja fechado do lado
# do servidor e quebraria a requisicao com "socket hang up" (ECONNRESET).
$backend = Start-Process -PassThru -NoNewWindow `
    -FilePath ".\.venv\Scripts\python.exe" `
    -ArgumentList "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1",
                  "--port", "$PortaBackend", "--timeout-keep-alive", "65"

try {
    # Espera a API subir antes de seguir, senao a primeira tela do front ja da erro.
    for ($i = 0; $i -lt 90; $i++) {
        try {
            Invoke-WebRequest "http://127.0.0.1:$PortaBackend/api/saude" -UseBasicParsing -TimeoutSec 2 | Out-Null
            break
        } catch { Start-Sleep -Milliseconds 500 }
    }

    Push-Location .\frontend
    if ($Prod) { npm run start } else { npm run dev }
} finally {
    Pop-Location -ErrorAction SilentlyContinue
    if ($backend -and -not $backend.HasExited) {
        Write-Host "`nEncerrando o backend..." -ForegroundColor DarkGray
        Stop-Process -Id $backend.Id -Force -ErrorAction SilentlyContinue
    }
}
