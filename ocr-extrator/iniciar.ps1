# Sobe o backend (FastAPI :8100) e o frontend (Next :3000) juntos.
#   .\iniciar.ps1          -> modo desenvolvimento (hot reload no front)
#   .\iniciar.ps1 -Prod    -> usa o build de producao do Next
#
# O backend fica na 8100 em vez da obvia 8000 porque esta costuma ja estar
# ocupada por outros servicos da maquina (WSL, outros projetos). O frontend usa
# a 3000 por pedido do usuario -- e a porta padrao do Next, entao ela colide com
# qualquer outro projeto Next da maquina; se o script parar em "porta em uso",
# derrube o outro dev server antes (ver -Porta abaixo para trocar sem editar).
#
# O login usa um Keycloak em container (docker compose up -d keycloak). Sem ele
# no ar, `-SemAuth` deixa a API aberta como era antes -- util para depurar o OCR
# sem depender do Docker.
param([switch]$Prod, [int]$Porta = 3000, [switch]$SemAuth)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$PortaBackend = 8100
$PortaTranscricao = 8200
$UrlKeycloak  = "http://localhost:8180"
# Servidor de chamadas (Jitsi). Sobe com:
#   cd ..\..\docker-jitsi-meet; docker compose up -d
# A porta e 8081 e nao a 8000 do padrao porque a 8000 ja estava ocupada aqui.
$UrlJitsi = "http://localhost:8081"

# ---------------------------------------------------------------- keycloak
# O backend so exige token quando KEYCLOAK_URL esta definida (ver app/auth.py):
# deixa-la vazia e o que desliga a autenticacao.
if ($SemAuth) {
    $env:KEYCLOAK_URL = ""
    Write-Host "AUTENTICACAO DESLIGADA -- a API responde sem token." -ForegroundColor Yellow
} else {
    Write-Host "Subindo o Keycloak..." -ForegroundColor Yellow
    docker compose up -d keycloak | Out-Null

    # Esperar o realm, nao so o container: o import leva alguns segundos e um
    # login tentado antes disso devolve 404 no endpoint de autorizacao.
    $pronto = $false
    for ($i = 0; $i -lt 90; $i++) {
        try {
            Invoke-WebRequest "$UrlKeycloak/realms/advocacia/.well-known/openid-configuration" `
                -UseBasicParsing -TimeoutSec 2 | Out-Null
            $pronto = $true; break
        } catch { Start-Sleep -Seconds 1 }
    }
    if (-not $pronto) {
        throw "Keycloak nao respondeu em $UrlKeycloak. Suba com 'docker compose up -d keycloak' ou rode com -SemAuth."
    }

    $env:KEYCLOAK_URL       = $UrlKeycloak
    $env:KEYCLOAK_REALM     = "advocacia"
    $env:KEYCLOAK_CLIENT_ID = "acervo-frontend"
    Write-Host "Keycloak pronto (realm advocacia)." -ForegroundColor Green
}

# Broker durável e painéis. Redis usa AOF; Flower, Prometheus e Grafana ficam
# disponíveis sem compartilhar processo com a API.
Write-Host "Subindo Redis e observabilidade..." -ForegroundColor Yellow
docker compose up -d --wait --wait-timeout 60 redis jobs-db flower prometheus grafana | Out-Null
$env:REDIS_URL = "redis://localhost:6380/0"
$env:CELERY_BROKER_URL = "redis://localhost:6380/0"
$env:CELERY_RESULT_BACKEND = "redis://localhost:6380/1"
if (-not $env:JOBS_DATABASE_URL) {
    $env:JOBS_DATABASE_URL = "postgresql://advocacia:advocacia_local@localhost:5434/advocacia_jobs"
}

# O frontend le estas na hora do build/dev -- precisam do prefixo NEXT_PUBLIC_.
$env:NEXT_PUBLIC_KEYCLOAK_URL       = $env:KEYCLOAK_URL
$env:NEXT_PUBLIC_KEYCLOAK_REALM     = "advocacia"
$env:NEXT_PUBLIC_KEYCLOAK_CLIENT_ID = "acervo-frontend"
$env:ORIGENS_PERMITIDAS             = "http://localhost:$Porta,http://127.0.0.1:$Porta"
$env:URL_PORTAL                     = "http://localhost:$Porta"
$env:NEXT_PUBLIC_JITSI_URL          = $UrlJitsi

# O Jitsi nao sobe junto: e um stack proprio (Prosody, Jicofo, Videobridge) que
# fica de pe entre execucoes, como o Keycloak. Aviso em vez de derrubar tudo --
# entrevista presencial, pelo microfone da maquina, funciona sem ele.
try {
    Invoke-WebRequest "$UrlJitsi/libs/lib-jitsi-meet.min.js" -Method Head -UseBasicParsing -TimeoutSec 3 | Out-Null
    Write-Host "Chamadas  : $UrlJitsi (Jitsi no ar)" -ForegroundColor Green
} catch {
    Write-Host "AVISO: servidor de chamadas fora do ar em $UrlJitsi." -ForegroundColor Yellow
    Write-Host "       Suba com: cd ..\..\docker-jitsi-meet; docker compose up -d" -ForegroundColor DarkGray
}

# Segredo que assina as sessoes do portal do cliente. Sorteado uma vez e guardado
# em dados/ (que o .gitignore ja cobre), para as sessoes sobreviverem a um
# restart sem que nenhum segredo entre no repositorio.
$arquivoSegredo = ".\dados\.portal-segredo"
if (-not (Test-Path $arquivoSegredo)) {
    New-Item -ItemType Directory -Force ".\dados" | Out-Null
    # RNGCryptoServiceProvider em vez de RandomNumberGenerator::Fill: o segundo
    # so existe no .NET Core, e o Windows PowerShell 5.1 roda em .NET Framework.
    $bytes = New-Object byte[] 32
    $rng = New-Object System.Security.Cryptography.RNGCryptoServiceProvider
    $rng.GetBytes($bytes)
    $rng.Dispose()
    [Convert]::ToBase64String($bytes) | Set-Content -NoNewline -Encoding utf8 $arquivoSegredo
    Write-Host "Segredo do portal gerado em $arquivoSegredo" -ForegroundColor DarkGray
}
$env:PORTAL_SEGREDO = (Get-Content -Raw $arquivoSegredo).Trim()

# ---------------------------------------------------------------- backend
if (-not (Test-Path ".\.venv\Scripts\python.exe")) {
    Write-Host "Criando o ambiente Python..." -ForegroundColor Yellow
    uv venv --python 3.11      # o paddlepaddle ainda nao publica wheels para 3.13+
}
# Sincroniza também ambientes já existentes; pulls podem adicionar dependências.
uv pip install --python .\.venv\Scripts\python.exe -r requirements.txt | Out-Null

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
Write-Host "Frontend : http://localhost:$Porta" -ForegroundColor Cyan
Write-Host "Transcricao : http://127.0.0.1:$PortaTranscricao  (Whisper, processo separado)" -ForegroundColor Cyan
Write-Host "Flower    : http://localhost:5555" -ForegroundColor Cyan
Write-Host "Grafana   : http://localhost:3001" -ForegroundColor Cyan
if (-not $SemAuth) {
    Write-Host "Keycloak : $UrlKeycloak  (admin/admin) -- login do app: guinb / 123" -ForegroundColor Cyan
}
Write-Host "Ctrl+C encerra o backend e o frontend (o Keycloak segue no container).`n" -ForegroundColor DarkGray

# --timeout-keep-alive 65: o padrao do uvicorn e 5s, curto demais para o pool de
# conexoes de um cliente HTTP moderno, que reusaria um socket ja fechado do lado
# do servidor e quebraria a requisicao com "socket hang up" (ECONNRESET).
# Transcricao em processo proprio: o Whisper e o PaddleOCR disputavam CPU no
# mesmo processo (11s de audio levavam 227s) e as DLLs de MKL/OpenMP dos dois
# conflitavam no Windows.
$env:NEXT_PUBLIC_TRANSCRICAO_API = "http://127.0.0.1:$PortaTranscricao"
$transcricao = Start-Process -PassThru -NoNewWindow `
    -FilePath ".\.venv\Scripts\python.exe" `
    -ArgumentList "-m", "uvicorn", "app.servico_transcricao:app", "--host", "127.0.0.1",
                  "--port", "$PortaTranscricao",
                  # Ping desligado: a inferencia do Whisper segura o GIL o
                  # bastante para o loop nao responder ao ping a tempo, e a
                  # conexao morria no meio da gravacao. Em 127.0.0.1 o ping nao
                  # agrega liveness. Se um dia isto for para a rede, mover a
                  # inferencia para um ProcessPoolExecutor em vez de religar.
                  "--ws-ping-interval", "0", "--ws-ping-timeout", "0"

$backend = Start-Process -PassThru -NoNewWindow `
    -FilePath ".\.venv\Scripts\python.exe" `
    -ArgumentList "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1",
                  "--port", "$PortaBackend", "--timeout-keep-alive", "65"

# No Windows, pool=solo evita o prefork incompatível e garante uma inferência
# por worker. As filas impedem OCR, IA e manutenção de se bloquearem no broker.
$workerOcr = Start-Process -PassThru -NoNewWindow `
    -FilePath ".\.venv\Scripts\python.exe" `
    -ArgumentList "-m", "celery", "-A", "app.celery_app:celery_app", "worker",
                  "--pool=solo", "--concurrency=1", "-Q", "gpu_background", "-n", "ocr@%h"
$workerBackground = Start-Process -PassThru -NoNewWindow `
    -FilePath ".\.venv\Scripts\python.exe" `
    -ArgumentList "-m", "celery", "-A", "app.celery_app:celery_app", "worker",
                  "--pool=solo", "--concurrency=1", "-Q", "ai,documents,default,low", "-n", "background@%h"
$beat = Start-Process -PassThru -NoNewWindow `
    -FilePath ".\.venv\Scripts\python.exe" `
    -ArgumentList "-m", "celery", "-A", "app.celery_app:celery_app", "beat"

try {
    # Espera a API subir antes de seguir, senao a primeira tela do front ja da erro.
    for ($i = 0; $i -lt 90; $i++) {
        try {
            Invoke-WebRequest "http://127.0.0.1:$PortaBackend/api/saude" -UseBasicParsing -TimeoutSec 2 | Out-Null
            break
        } catch { Start-Sleep -Milliseconds 500 }
    }

    Push-Location .\frontend
    # O "--" repassa a porta ao next, sobrepondo a que esta nos scripts do
    # package.json -- assim `-Porta 3100` volta ao arranjo antigo sem editar nada.
    if ($Prod) { npm run start -- -p $Porta } else { npm run dev -- -p $Porta }
} finally {
    Pop-Location -ErrorAction SilentlyContinue
    foreach ($p in @($backend, $transcricao, $workerOcr, $workerBackground, $beat)) {
        if ($p -and -not $p.HasExited) {
            Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue
        }
    }
    Write-Host "`nBackend e transcricao encerrados." -ForegroundColor DarkGray
}
