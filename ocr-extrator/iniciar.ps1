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
$UrlKeycloak  = "http://localhost:8180"

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

# O frontend le estas na hora do build/dev -- precisam do prefixo NEXT_PUBLIC_.
$env:NEXT_PUBLIC_KEYCLOAK_URL       = $env:KEYCLOAK_URL
$env:NEXT_PUBLIC_KEYCLOAK_REALM     = "advocacia"
$env:NEXT_PUBLIC_KEYCLOAK_CLIENT_ID = "acervo-frontend"
$env:ORIGENS_PERMITIDAS             = "http://localhost:$Porta,http://127.0.0.1:$Porta"
$env:URL_PORTAL                     = "http://localhost:$Porta"

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
Write-Host "Frontend : http://localhost:$Porta" -ForegroundColor Cyan
if (-not $SemAuth) {
    Write-Host "Keycloak : $UrlKeycloak  (admin/admin) -- login do app: guinb / 123" -ForegroundColor Cyan
}
Write-Host "Ctrl+C encerra o backend e o frontend (o Keycloak segue no container).`n" -ForegroundColor DarkGray

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
    # O "--" repassa a porta ao next, sobrepondo a que esta nos scripts do
    # package.json -- assim `-Porta 3100` volta ao arranjo antigo sem editar nada.
    if ($Prod) { npm run start -- -p $Porta } else { npm run dev -- -p $Porta }
} finally {
    Pop-Location -ErrorAction SilentlyContinue
    if ($backend -and -not $backend.HasExited) {
        Write-Host "`nEncerrando o backend..." -ForegroundColor DarkGray
        Stop-Process -Id $backend.Id -Force -ErrorAction SilentlyContinue
    }
}
