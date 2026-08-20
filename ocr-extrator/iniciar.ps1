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
param(
    [switch]$Prod,
    [int]$Porta = 3000,
    [switch]$SemAuth,
    [switch]$SemAgente,
    [switch]$SemJitsi
)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

# A máquina da infra não deve depender de variáveis deixadas por outro shell.
# Variável já definida pelo ambiente vence o arquivo (útil em CI/produção).
function Importar-Env([string]$Caminho) {
    if (-not (Test-Path $Caminho)) {
        throw "Arquivo de ambiente ausente: $Caminho. Copie .env.example para .env e preencha os segredos."
    }
    foreach ($linha in Get-Content $Caminho -Encoding UTF8) {
        $texto = $linha.Trim()
        if (-not $texto -or $texto.StartsWith("#") -or -not $texto.Contains("=")) { continue }
        $nome, $valor = $texto.Split("=", 2)
        $nome = $nome.Trim(); $valor = $valor.Trim().Trim('"').Trim("'")
        if (-not [Environment]::GetEnvironmentVariable($nome, "Process")) {
            [Environment]::SetEnvironmentVariable($nome, $valor, "Process")
        }
    }
}

Importar-Env ".\.env"

foreach ($comando in @("docker", "uv", "npm")) {
    if (-not (Get-Command $comando -ErrorAction SilentlyContinue)) {
        throw "Dependencia ausente: '$comando' nao foi encontrado no PATH. Instale-o e execute iniciar.ps1 novamente."
    }
}
docker info *> $null
if ($LASTEXITCODE -ne 0) {
    throw "Docker nao esta respondendo. Abra o Docker Desktop e execute iniciar.ps1 novamente."
}

function Testar-Http([string]$Url, [int]$Timeout = 3) {
    try {
        $r = Invoke-WebRequest $Url -UseBasicParsing -TimeoutSec $Timeout
        return $r.StatusCode -eq 200
    } catch { return $false }
}

function Wait-ModeloAquecido {
    param(
        [string]$Url,
        [System.Diagnostics.Process]$Processo,
        [int]$TimeoutSegundos
    )

    $limite = [DateTime]::UtcNow.AddSeconds($TimeoutSegundos)
    while ([DateTime]::UtcNow -lt $limite) {
        if ($Processo.HasExited) {
            throw "O processo encerrou durante o aquecimento: $Url"
        }
        try {
            $saude = Invoke-RestMethod $Url -TimeoutSec 2
            if ($saude.modelo_aquecido) { return $true }
        } catch {
            # A porta ainda pode estar fechada durante o início do Uvicorn.
        }
        Start-Sleep -Milliseconds 500
    }
    return $false
}

$PortaBackend = 8100
$PortaTranscricao = 8200
$HostEscuta = if ($env:APP_BIND_HOST) { $env:APP_BIND_HOST } else { "0.0.0.0" }
$UrlFrontend = if ($env:APP_PUBLIC_URL) { $env:APP_PUBLIC_URL.TrimEnd("/") } else { "http://localhost:$Porta" }
$UrlApi = if ($env:OCR_API_PUBLIC_URL) { $env:OCR_API_PUBLIC_URL.TrimEnd("/") } else { "http://127.0.0.1:$PortaBackend" }
$UrlTranscricao = if ($env:TRANSCRICAO_PUBLIC_URL) { $env:TRANSCRICAO_PUBLIC_URL.TrimEnd("/") } else { "http://127.0.0.1:$PortaTranscricao" }
$UrlKeycloak = if ($env:KEYCLOAK_PUBLIC_URL) { $env:KEYCLOAK_PUBLIC_URL.TrimEnd("/") } else { "http://localhost:8180" }
# Servidor de chamadas (Jitsi). Sobe com:
#   cd ..\..\docker-jitsi-meet; docker compose up -d
# A porta e 8081 e nao a 8000 do padrao porque a 8000 ja estava ocupada aqui.
$UrlJitsi = if ($env:JITSI_PUBLIC_URL) { $env:JITSI_PUBLIC_URL.TrimEnd("/") } else { "http://localhost:8081" }

# ---------------------------------------------------------------- keycloak
# O backend so exige token quando KEYCLOAK_URL esta definida (ver app/auth.py):
# deixa-la vazia e o que desliga a autenticacao.
if ($SemAuth) {
    $env:KEYCLOAK_URL = ""
    $env:AUTH_DESATIVADA = "1"
    Write-Host "AUTENTICACAO DESLIGADA -- a API responde sem token." -ForegroundColor Yellow
} else {
    $env:AUTH_DESATIVADA = "0"
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
    if (-not $env:KEYCLOAK_ADMIN_USER -or -not $env:KEYCLOAK_ADMIN_PASSWORD) {
        Write-Host "AVISO: cadastro de usuarios desligado; faltam KEYCLOAK_ADMIN_* na .env." -ForegroundColor Yellow
    } else {
        # O realm importado nasce aceitando localhost. Acrescenta a URL deste
        # ambiente para o login funcionar também por IP, homologação ou produção.
        try {
            $token = Invoke-RestMethod "$UrlKeycloak/realms/master/protocol/openid-connect/token" `
                -Method Post -ContentType "application/x-www-form-urlencoded" -Body @{
                    grant_type = "password"; client_id = "admin-cli"
                    username = $env:KEYCLOAK_ADMIN_USER; password = $env:KEYCLOAK_ADMIN_PASSWORD
                }
            $cabecalhos = @{ Authorization = "Bearer $($token.access_token)" }
            $clientes = Invoke-RestMethod "$UrlKeycloak/admin/realms/advocacia/clients?clientId=acervo-frontend" `
                -Headers $cabecalhos
            if ($clientes.Count -gt 0) {
                $cliente = Invoke-RestMethod "$UrlKeycloak/admin/realms/advocacia/clients/$($clientes[0].id)" `
                    -Headers $cabecalhos
                $redirect = "$UrlFrontend/*"
                $cliente.redirectUris = @($cliente.redirectUris + $redirect | Select-Object -Unique)
                $cliente.webOrigins = @($cliente.webOrigins + $UrlFrontend | Select-Object -Unique)
                $cliente.rootUrl = $UrlFrontend
                $cliente.attributes.'post.logout.redirect.uris' = ($cliente.redirectUris -join "##")
                Invoke-RestMethod "$UrlKeycloak/admin/realms/advocacia/clients/$($clientes[0].id)" `
                    -Method Put -Headers $cabecalhos -ContentType "application/json" `
                    -Body ($cliente | ConvertTo-Json -Depth 20) | Out-Null
            }
        } catch {
            throw "Keycloak subiu, mas nao foi possivel liberar $UrlFrontend no cliente acervo-frontend: $($_.Exception.Message)"
        }
    }
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
$env:NEXT_PUBLIC_OCR_API             = $UrlApi
$env:NEXT_PUBLIC_TRANSCRICAO_API     = $UrlTranscricao
$origens = @("http://localhost:$Porta", "http://127.0.0.1:$Porta", $UrlFrontend)
if ($env:ORIGENS_PERMITIDAS) { $origens += $env:ORIGENS_PERMITIDAS.Split(",") }
$env:ORIGENS_PERMITIDAS             = ($origens | ForEach-Object { $_.Trim().TrimEnd("/") } | Where-Object { $_ } | Select-Object -Unique) -join ","
$env:URL_PORTAL                     = $UrlFrontend
$env:NEXT_PUBLIC_JITSI_URL          = $UrlJitsi

# O stack oficial do Jitsi vive fora deste repositorio. Na primeira subida o
# bootstrap clona, cria uma .env com segredos locais e levanta web, Prosody,
# Jicofo e Videobridge. Nas seguintes apenas reconcilia os containers.
if (-not $SemJitsi) {
    if (-not (Testar-Http "$UrlJitsi/libs/lib-jitsi-meet.min.js")) {
        Write-Host "Preparando o servidor de chamadas Jitsi..." -ForegroundColor Yellow
        & ".\scripts\preparar_jitsi.ps1" `
            -Versao $(if ($env:JITSI_IMAGE_VERSION) { $env:JITSI_IMAGE_VERSION } else { "stable" }) `
            -UrlPublica $UrlJitsi `
            -IpsAnunciados $(if ($env:JITSI_ADVERTISE_IPS) { $env:JITSI_ADVERTISE_IPS } else { "127.0.0.1" })
    }
    $jitsiPronto = $false
    for ($i = 0; $i -lt 120; $i++) {
        if (Testar-Http "$UrlJitsi/libs/lib-jitsi-meet.min.js") { $jitsiPronto = $true; break }
        Start-Sleep -Seconds 1
    }
    if (-not $jitsiPronto) { throw "Jitsi nao respondeu em $UrlJitsi depois de 120 segundos." }
    Write-Host "Chamadas  : $UrlJitsi (Jitsi pronto)" -ForegroundColor Green
} else {
    Write-Host "Jitsi nao iniciado (-SemJitsi); chamadas remotas ficarao indisponiveis." -ForegroundColor Yellow
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
# Recompila quando o build esta VELHO, e nao so quando falta.
#
# Antes bastava existir um BUILD_ID para o script pular a compilacao -- e ai o
# `-Prod` servia o build antigo para sempre. O sintoma nao parece build velho: a
# alteracao simplesmente nao aparece na tela, e quem ve isso vai procurar defeito
# no codigo que acabou de escrever. Ja custou uma caca a um erro de login que
# estava consertado havia commits.
if ($Prod) {
    $buildId = ".\frontend\.next\BUILD_ID"
    $precisa = -not (Test-Path $buildId)
    if (-not $precisa) {
        $carimbo = (Get-Item $buildId).LastWriteTime
        # Varre as pastas de FONTE, uma a uma, em vez de `.\frontend` inteiro.
        # Dois motivos: `-Include` com `-Recurse` nao filtra como parece (devolve
        # vazio, e a checagem passaria batido sem erro nenhum), e varrer a raiz
        # entraria em node_modules, que sozinho tem dezenas de milhares de
        # arquivos e faria cada subida parecer travada.
        $fontes = @(".\frontend\app", ".\frontend\components", ".\frontend\lib",
                    ".\frontend\public") | Where-Object { Test-Path $_ }
        $maisNovo = Get-ChildItem $fontes -Recurse -File |
            Where-Object { $_.Extension -in ".ts", ".tsx", ".css", ".json", ".js" } |
            Sort-Object LastWriteTime -Descending | Select-Object -First 1
        if ($maisNovo -and $maisNovo.LastWriteTime -gt $carimbo) {
            Write-Host "Build do frontend esta atras de $($maisNovo.Name); recompilando." -ForegroundColor Yellow
            $precisa = $true
        }
    }
    # O Next congela NEXT_PUBLIC_* no build. Um carimbo explícito detecta tanto
    # URL ausente quanto build feito em -SemAuth e depois servido com auth (e o
    # inverso), sem procurar strings minificadas nos chunks.
    $publicEnv = [ordered]@{
        NEXT_PUBLIC_OCR_API = $env:NEXT_PUBLIC_OCR_API
        NEXT_PUBLIC_TRANSCRICAO_API = $env:NEXT_PUBLIC_TRANSCRICAO_API
        NEXT_PUBLIC_KEYCLOAK_URL = $env:NEXT_PUBLIC_KEYCLOAK_URL
        NEXT_PUBLIC_KEYCLOAK_REALM = $env:NEXT_PUBLIC_KEYCLOAK_REALM
        NEXT_PUBLIC_KEYCLOAK_CLIENT_ID = $env:NEXT_PUBLIC_KEYCLOAK_CLIENT_ID
        NEXT_PUBLIC_JITSI_URL = $env:NEXT_PUBLIC_JITSI_URL
    }
    $assinaturaPublica = $publicEnv | ConvertTo-Json -Compress
    $arquivoPublico = ".\frontend\.next\.public-env.json"
    if (-not $precisa) {
        $anterior = if (Test-Path $arquivoPublico) { (Get-Content -Raw $arquivoPublico).Trim() } else { "" }
        if ($anterior -ne $assinaturaPublica) {
            Write-Host "NEXT_PUBLIC_* mudou desde o ultimo build; recompilando." -ForegroundColor Yellow
            $precisa = $true
        }
    }
    if ($precisa) {
        Write-Host "Compilando o frontend..." -ForegroundColor Yellow
        Push-Location .\frontend; npm run build; Pop-Location
        $assinaturaPublica | Set-Content -NoNewline -Encoding UTF8 $arquivoPublico
    }
}

# ---------------------------------------------------------- agente juridico
# A ponte continua de mão única; isto só orquestra os dois processos. O agente
# lê a PRÓPRIA .env e nunca recebe DATABASE_URL do corpus do Acervo.
$agenteApi = $null
$agenteWorker = $null
if (-not $SemAgente -and $env:AGENTE_API_URL) {
    $urlAgente = $env:AGENTE_API_URL.TrimEnd("/")
    if (Testar-Http "$urlAgente/health") {
        Write-Host "Agente juridico ja estava no ar: $urlAgente" -ForegroundColor Green
    } else {
        $raizAgente = Resolve-Path (Join-Path $PSScriptRoot "..\..\ia-juridica") -ErrorAction SilentlyContinue
        if (-not $raizAgente -or -not (Test-Path (Join-Path $raizAgente ".env"))) {
            Write-Host "AVISO: agente fora do ar; falta ia-juridica/.env ou o repositorio vizinho." -ForegroundColor Yellow
        } elseif (-not (Test-Path (Join-Path $raizAgente ".venv\Scripts\python.exe"))) {
            Write-Host "AVISO: agente fora do ar; ambiente ia-juridica/.venv ausente." -ForegroundColor Yellow
        } else {
            $portaAgente = ([uri]$urlAgente).Port
            $salvas = @{}
            # Qualquer variável com o mesmo nome vence a .env no Pydantic. A
            # máquina já teve DEBUG=release global, suficiente para impedir o
            # boot. Limpa exatamente as chaves declaradas pelo agente, inicia
            # os filhos e restaura o ambiente do Acervo em seguida.
            $nomesAgente = Get-Content (Join-Path $raizAgente ".env") -Encoding UTF8 |
                ForEach-Object { if ($_ -match '^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=') { $Matches[1] } }
            foreach ($nome in @($nomesAgente) + @("PYTHONPATH")) {
                $salvas[$nome] = [Environment]::GetEnvironmentVariable($nome, "Process")
                [Environment]::SetEnvironmentVariable($nome, $null, "Process")
            }
            $env:PYTHONPATH = "src"
            try {
                $pythonAgente = Join-Path $raizAgente ".venv\Scripts\python.exe"
                $agenteApi = Start-Process -PassThru -NoNewWindow -WorkingDirectory $raizAgente `
                    -FilePath $pythonAgente `
                    -ArgumentList "-m", "uvicorn", "legal_agent.main:app", "--host", "$HostEscuta", "--port", "$portaAgente"
                $agenteWorker = Start-Process -PassThru -NoNewWindow -WorkingDirectory $raizAgente `
                    -FilePath $pythonAgente -ArgumentList "-m", "dramatiq", "legal_agent.workers", "--processes", "1", "--threads", "4"
            } finally {
                foreach ($nome in $salvas.Keys) {
                    [Environment]::SetEnvironmentVariable($nome, $salvas[$nome], "Process")
                }
            }
            for ($i = 0; $i -lt 30 -and -not (Testar-Http "$urlAgente/health"); $i++) {
                Start-Sleep -Seconds 1
            }
            if (Testar-Http "$urlAgente/health") {
                Write-Host "Agente juridico pronto: $urlAgente" -ForegroundColor Green
            } else {
                Write-Host "AVISO: agente nao respondeu; o Acervo seguira sem a ponte." -ForegroundColor Yellow
            }
        }
    }
}

Write-Host "`nBackend  : $UrlApi  (docs interativos em /docs)" -ForegroundColor Cyan
Write-Host "Frontend : $UrlFrontend" -ForegroundColor Cyan
Write-Host "Transcricao : $UrlTranscricao  (Whisper, processo separado)" -ForegroundColor Cyan
Write-Host "Flower    : http://localhost:5555" -ForegroundColor Cyan
Write-Host "Grafana   : http://localhost:3001" -ForegroundColor Cyan
if (-not $SemAuth) { Write-Host "Keycloak : $UrlKeycloak" -ForegroundColor Cyan }
Write-Host "Ctrl+C encerra o backend e o frontend (o Keycloak segue no container).`n" -ForegroundColor DarkGray

# --timeout-keep-alive 65: o padrao do uvicorn e 5s, curto demais para o pool de
# conexoes de um cliente HTTP moderno, que reusaria um socket ja fechado do lado
# do servidor e quebraria a requisicao com "socket hang up" (ECONNRESET).
# Transcricao e OCR ficam em processos separados por usarem runtimes numericos
# pesados e potencialmente incompativeis. O Paddle é aquecido pelo worker `ocr@`,
# que é quem recebe `/api/extrair/jobs`; a API não carrega uma segunda cópia.
$transcricao = $null

$backend = Start-Process -PassThru -NoNewWindow `
    -FilePath ".\.venv\Scripts\python.exe" `
    -ArgumentList "-m", "uvicorn", "app.main:app", "--host", "$HostEscuta",
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
    # Espera apenas a API responder. O worker OCR aquece seu próprio modelo e
    # só então passa a consumir a fila; um upload antecipado fica enfileirado.
    for ($i = 0; $i -lt 90; $i++) {
        if ($backend.HasExited) { throw "O backend encerrou durante a inicializacao." }
        try {
            Invoke-WebRequest "http://127.0.0.1:$PortaBackend/api/saude" -UseBasicParsing -TimeoutSec 2 | Out-Null
            break
        } catch { Start-Sleep -Milliseconds 500 }
    }

    Write-Host "Aquecendo Whisper..." -ForegroundColor Yellow
    $transcricao = Start-Process -PassThru -NoNewWindow `
        -FilePath ".\.venv\Scripts\python.exe" `
        -ArgumentList "-m", "uvicorn", "app.servico_transcricao:app", "--host", "$HostEscuta",
                      "--port", "$PortaTranscricao",
                      "--ws-ping-interval", "0", "--ws-ping-timeout", "0"

    $whisperPronto = Wait-ModeloAquecido `
        -Url "http://127.0.0.1:$PortaTranscricao/saude" `
        -Processo $transcricao `
        -TimeoutSegundos 180
    if (-not $whisperPronto) {
        throw "Whisper nao terminou o aquecimento em 180 segundos."
    }
    Write-Host "Whisper pronto." -ForegroundColor Green

    Push-Location .\frontend
    # O "--" repassa a porta ao next, sobrepondo a que esta nos scripts do
    # package.json -- assim `-Porta 3100` volta ao arranjo antigo sem editar nada.
    if ($Prod) { npm run start -- -H $HostEscuta -p $Porta } else { npm run dev -- -H $HostEscuta -p $Porta }
} finally {
    Pop-Location -ErrorAction SilentlyContinue
    foreach ($p in @($backend, $transcricao, $workerOcr, $workerBackground, $beat, $agenteApi, $agenteWorker)) {
        if ($p -and -not $p.HasExited) {
            Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue
        }
    }
    Write-Host "`nBackend e transcricao encerrados." -ForegroundColor DarkGray
}
