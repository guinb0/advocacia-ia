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
# O login e proprio: o backend assina o JWT e o grava num cookie HttpOnly (ver
# app/auth.py). Nao ha mais container de identidade para subir. `-SemAuth` zera
# o JWT_SECRET e deixa a API aberta como antes -- util para depurar o OCR.
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


# Uma janela fechada à força deixa os filhos do `uv` vivos no Windows. Dois
# workers com o mesmo nome consomem a mesma fila de forma invisível e um upload
# pode cair no processo antigo, sem o modelo aquecido. Antes de criar a nova
# topologia, encerra somente processos Celery desta instalação do projeto.
$celeryAntigos = @()
if (Test-Path ".\.venv\Scripts\python.exe") {
    $pythonProjeto = (Resolve-Path ".\.venv\Scripts\python.exe").Path
    $processosAtuais = @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue)
    $celeryAntigos = $processosAtuais | Where-Object {
        $_.CommandLine -and
        $_.CommandLine.Contains($pythonProjeto) -and
        $_.CommandLine -match "-m\s+celery\s+-A\s+app\.celery_app:celery_app"
    }
    foreach ($processoAntigo in $celeryAntigos) {
        $filhos = $processosAtuais | Where-Object { $_.ParentProcessId -eq $processoAntigo.ProcessId }
        foreach ($filho in $filhos) {
            Stop-Process -Id $filho.ProcessId -Force -ErrorAction SilentlyContinue
        }
        Stop-Process -Id $processoAntigo.ProcessId -Force -ErrorAction SilentlyContinue
    }
}
if ($celeryAntigos) { Start-Sleep -Milliseconds 500 }

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

# Por que o Jitsi nao subiu -- em vez de so dizer que nao subiu.
#
# "Jitsi nao respondeu depois de 120 segundos" e verdade e nao ajuda: quem le
# isso na primeira vez que roda o projeto nao tem como saber se falta Docker,
# se a porta esta ocupada, ou se o endereco no .env e de outro computador -- que
# e o caso mais comum, porque o .env nao vai no git e todo mundo copia o do
# colega, IP da maquina dele junto. Cada causa pede uma acao diferente.
function Diagnostico-Jitsi([string]$Url, [double]$Segundos = 120) {
    $alvo = ([Uri]$Url).Host
    $causa = ""

    # `$host` e variavel automatica do PowerShell: usar esse nome aqui
    # sobrescreveria o console. Dai `$alvo`.
    $locais = @("localhost", "127.0.0.1", "::1")
    try { $locais += (Get-NetIPAddress -AddressFamily IPv4 -ErrorAction Stop).IPAddress } catch {}

    if ($alvo -match "^\d+\.\d+\.\d+\.\d+$" -and $locais -notcontains $alvo) {
        $causa = "O endereco $alvo nao pertence a esta maquina. O JITSI_PUBLIC_URL do seu .env veio " +
                 "do computador de outra pessoa. Troque por http://localhost:8081 e rode de novo."
    } elseif (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
        $causa = "O Docker nao esta instalado (ou nao esta no PATH). O Jitsi roda em containers."
    } else {
        docker info 2>&1 | Out-Null
        if ($LASTEXITCODE -ne 0) {
            $causa = "O Docker esta instalado mas o servico nao responde. Abra o Docker Desktop e espere ficar verde."
        } else {
            $emPe = (docker ps --filter "name=jitsi" --format "{{.Names}}" | Measure-Object -Line).Lines
            if ($emPe -eq 0) {
                $causa = "O Docker responde, mas nenhum container do Jitsi subiu. Veja o erro com: " +
                         "cd ..\docker-jitsi-meet; docker compose up"
            } else {
                $causa = "Os containers do Jitsi estao de pe, mas $Url nao responde. A porta pode estar " +
                         "ocupada por outro projeto: Get-NetTCPConnection -LocalPort 8081"
            }
        }
    }

    return ("Jitsi nao respondeu em {0} depois de {1:N0} segundos.`n`n" -f $Url, $Segundos) +
           "  Causa provavel: $causa`n`n" +
           "  Para seguir sem chamadas por enquanto:  .\iniciar.ps1 -SemJitsi`n" +
           "  O resto do sistema funciona; so a videoconferencia fica indisponivel."
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

function Wait-WorkerOcr {
    param(
        [System.Diagnostics.Process]$Processo,
        [string]$Destino,
        [int]$TimeoutSegundos = 120
    )

    $limite = [DateTime]::UtcNow.AddSeconds($TimeoutSegundos)
    while ([DateTime]::UtcNow -lt $limite) {
        if ($Processo.HasExited) {
            throw "O worker de OCR encerrou durante a inicializacao."
        }
        # Enquanto o worker aquece, o Celery escreve "No nodes replied" em
        # stderr. Isso significa "ainda nao", nao falha fatal do inicializador.
        $preferenciaAnterior = $ErrorActionPreference
        $ErrorActionPreference = "Continue"
        try {
            $resposta = & ".\.venv\Scripts\celery.exe" -A app.celery_app:celery_app `
                inspect ping -d $Destino --timeout 2 2>&1 | Out-String
        } finally {
            $ErrorActionPreference = $preferenciaAnterior
        }
        if ($LASTEXITCODE -eq 0 -and $resposta -match "pong") { return $true }
        Start-Sleep -Seconds 1
    }
    return $false
}

$PortaBackend = 8100
$PortaTranscricao = 8200
$HostEscuta = if ($env:APP_BIND_HOST) { $env:APP_BIND_HOST } else { "0.0.0.0" }
$UrlFrontend = if ($env:APP_PUBLIC_URL) { $env:APP_PUBLIC_URL.TrimEnd("/") } else { "http://localhost:$Porta" }
$UrlApi = if ($env:OCR_API_PUBLIC_URL) { $env:OCR_API_PUBLIC_URL.TrimEnd("/") } else { "http://127.0.0.1:$PortaBackend" }
$UrlTranscricao = if ($env:TRANSCRICAO_PUBLIC_URL) { $env:TRANSCRICAO_PUBLIC_URL.TrimEnd("/") } else { "http://127.0.0.1:$PortaTranscricao" }
# Servidor de chamadas (Jitsi). Sobe com:
#   cd ..\..\docker-jitsi-meet; docker compose up -d
# A porta e 8081 e nao a 8000 do padrao porque a 8000 ja estava ocupada aqui.
$UrlJitsi = if ($env:JITSI_PUBLIC_URL) { $env:JITSI_PUBLIC_URL.TrimEnd("/") } else { "http://localhost:8081" }

# --------------------------------------------------------------------- login
# O backend so exige sessao quando JWT_SECRET esta definido (ver app/auth.py):
# deixa-lo vazio e o que desliga a autenticacao. O frontend le
# NEXT_PUBLIC_AUTH_DESATIVADA e o proxy.ts le o mesmo JWT_SECRET -- os tres
# precisam concordar, senao sobra tela pedindo login com a API aberta.
#
# " " e nao "": o CreateProcess do Windows descarta do bloco de ambiente do
# processo filho qualquer variavel com valor vazio, entao o Python nunca veria
# JWT_SECRET="" -- ele a enxergaria como INEXISTENTE e o carregar_env() do .env
# preencheria de volta com o valor real, religando a autenticacao sem avisar.
# Um espaco sobrevive ao CreateProcess; app/auth.py da .strip() nele antes de
# checar. Mesma armadilha que o Nelson mapeou para o KEYCLOAK_URL.
if ($SemAuth) {
    $env:JWT_SECRET = " "
    $env:AUTH_DESATIVADA = "1"
    $env:NEXT_PUBLIC_AUTH_DESATIVADA = "1"
    Write-Host "AUTENTICACAO DESLIGADA -- a API responde sem sessao." -ForegroundColor Yellow
} else {
    $env:AUTH_DESATIVADA = "0"
    $env:NEXT_PUBLIC_AUTH_DESATIVADA = "0"
    if (-not $env:JWT_SECRET) {
        throw "Falta JWT_SECRET no .env. Gere um com:`n" +
              "  python -c `"import secrets; print(secrets.token_urlsafe(48))`"`n" +
              "ou rode com -SemAuth para subir sem autenticacao."
    }
    # O cookie de sessao so acompanha a chamada se front e API forem o mesmo
    # site. Em desenvolvimento os dois sao `localhost`; se a API for anunciada
    # como 127.0.0.1 o navegador as trata como hosts diferentes e o login falha
    # com 401 logo apos entrar -- um sintoma que nao menciona cookie nenhum.
    if ($UrlApi -match "127\.0\.0\.1" -and $UrlFrontend -match "localhost") {
        $UrlApi = $UrlApi -replace "127\.0\.0\.1", "localhost"
        Write-Host "API anunciada como $UrlApi (o cookie de sessao exige o mesmo host do frontend)." -ForegroundColor DarkGray
    }
    Write-Host "Login proprio (JWT em cookie HttpOnly)." -ForegroundColor Green
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
    # Espera por RELOGIO, nao por numero de tentativas. Contar 120 iteracoes de
    # "1 segundo" dava 8 minutos de espera real: cada Testar-Http gasta ate 3s
    # montando a excecao quando a conexao e recusada, e isso nao aparecia em
    # lugar nenhum -- a mensagem final ainda dizia "120 segundos". Quem esperava
    # concluia que o script tinha travado, e matava o terminal antes do erro.
    $limiteSegundos = 120
    $relogio = [Diagnostics.Stopwatch]::StartNew()
    $jitsiPronto = $false
    while ($relogio.Elapsed.TotalSeconds -lt $limiteSegundos) {
        if (Testar-Http "$UrlJitsi/libs/lib-jitsi-meet.min.js") { $jitsiPronto = $true; break }
        Start-Sleep -Seconds 1
    }
    $relogio.Stop()
    if (-not $jitsiPronto) { throw (Diagnostico-Jitsi $UrlJitsi $relogio.Elapsed.TotalSeconds) }
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
        NEXT_PUBLIC_AUTH_DESATIVADA = $env:NEXT_PUBLIC_AUTH_DESATIVADA
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
# O iniciar.ps1 e a entrada unica dos dois projetos. A ponte continua de mao
# unica; isto apenas orquestra os processos, e o agente le a PROPRIA .env.
# AGENTE_API_URL tem um default local para que um clone corretamente preparado
# nao suba apenas metade do produto por uma configuracao esquecida.
$agenteApi = $null
$agenteWorker = $null
if (-not $SemAgente) {
    if (-not $env:AGENTE_API_URL) {
        $env:AGENTE_API_URL = "http://127.0.0.1:8011"
    }
    $urlAgente = $env:AGENTE_API_URL.TrimEnd("/")
    if (Testar-Http "$urlAgente/health") {
        Write-Host "Agente juridico ja estava no ar: $urlAgente" -ForegroundColor Green
    } else {
        $raizAgente = Resolve-Path (Join-Path $PSScriptRoot "..\ia-juridica") -ErrorAction SilentlyContinue
        if (-not $raizAgente -or -not (Test-Path (Join-Path $raizAgente ".env"))) {
            throw "Nao foi possivel iniciar os dois projetos: falta ia-juridica/.env ou o repositorio vizinho. Use -SemAgente somente para diagnostico isolado."
        }

        $pythonAgente = Join-Path $raizAgente ".venv\Scripts\python.exe"
        if (-not (Test-Path $pythonAgente)) {
            Write-Host "Preparando o ambiente do Agente Juridico (primeira execucao)..." -ForegroundColor Yellow
            Push-Location $raizAgente
            try { uv sync --frozen | Out-Null } finally { Pop-Location }
        }
        if (-not (Test-Path $pythonAgente)) {
            throw "O ambiente ia-juridica/.venv nao pode ser criado."
        }

        # O worker do agente depende de Redis. Primeiro reaproveita a instancia
        # local que o Acervo ja pode ter iniciado; isso evita colisao da porta
        # 6379 e deixa reinicios praticamente instantaneos.
        $redisPronto = $false
        try {
            $redisTeste = New-Object System.Net.Sockets.TcpClient
            $redisTeste.Connect("127.0.0.1", 6379)
            $redisTeste.Close()
            $redisPronto = $true
        } catch { }
        if (-not $redisPronto) {
            Write-Host "Iniciando a fila do Agente Juridico..." -ForegroundColor Yellow
            docker compose --project-directory $raizAgente up -d redis | Out-Null
            if ($LASTEXITCODE -ne 0) {
                throw "Nao foi possivel iniciar o Redis do Agente Juridico."
            }
        }

        try {
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
                throw "O Agente Juridico nao respondeu em $urlAgente. Os dois projetos precisam iniciar juntos."
            }
        } catch {
            foreach ($p in @($agenteApi, $agenteWorker)) {
                if ($p -and -not $p.HasExited) {
                    Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue
                }
            }
            throw
        }
    }
} else {
    Write-Host "Agente Juridico nao iniciado (-SemAgente, somente diagnostico)." -ForegroundColor Yellow
}

Write-Host "`nBackend  : $UrlApi  (docs interativos em /docs)" -ForegroundColor Cyan
Write-Host "Frontend : $UrlFrontend" -ForegroundColor Cyan
Write-Host "Transcricao : $UrlTranscricao  (Whisper, processo separado)" -ForegroundColor Cyan
if (-not $SemAgente) { Write-Host "Agente juridico : $urlAgente" -ForegroundColor Cyan }
Write-Host "Flower    : http://localhost:5555" -ForegroundColor Cyan
Write-Host "Grafana   : http://localhost:3001" -ForegroundColor Cyan
Write-Host "Ctrl+C encerra o backend e o frontend.`n" -ForegroundColor DarkGray

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
$instanciaCelery = ([Guid]::NewGuid().ToString("N")).Substring(0, 8)
# Instancias orfas desta instalacao ja foram encerradas no inicio do script via
# Win32_Process. Nao envie `celery control shutdown` aqui: numa inicializacao
# limpa ele escreve "No nodes replied" em stderr e o PowerShell 5.1, com
# ErrorActionPreference=Stop, transforma a ausencia esperada em erro fatal.
$workerOcr = Start-Process -PassThru -NoNewWindow `
    -FilePath ".\.venv\Scripts\python.exe" `
    -ArgumentList "-m", "celery", "-A", "app.celery_app:celery_app", "worker",
                  "--pool=solo", "--concurrency=1", "-Q", "gpu_background", "-n", "ocr@%h-$instanciaCelery"
$workerBackground = Start-Process -PassThru -NoNewWindow `
    -FilePath ".\.venv\Scripts\python.exe" `
    -ArgumentList "-m", "celery", "-A", "app.celery_app:celery_app", "worker",
                  "--pool=solo", "--concurrency=1", "-Q", "ai,documents,default,low", "-n", "background@%h-$instanciaCelery"
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

    Write-Host "Preparando o leitor de documentos..." -ForegroundColor Yellow
    $destinoWorkerOcr = "ocr@$env:COMPUTERNAME-$instanciaCelery"
    if (-not (Wait-WorkerOcr -Processo $workerOcr -Destino $destinoWorkerOcr -TimeoutSegundos 180)) {
        throw "O worker de OCR nao respondeu em 180 segundos. O sistema foi interrompido para nao deixar documentos presos na fila."
    }
    Write-Host "Leitor de documentos pronto." -ForegroundColor Green

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
    # PORT em vez de "npm run dev -- -p $Porta": o npm.ps1 do Windows PowerShell
    # descarta o nome da flag (-p ou --port) ao repassar argumentos depois do
    # "--", entregando ao next so o numero solto, que ele le como diretorio do
    # projeto ("next dev 3000" -> "Invalid project directory"). O next le PORT
    # nativamente, sem passar pelo parser de args do npm. O "--" ainda repassa
    # o host, que nao tem esse problema de parsing.
    $env:PORT = $Porta
    if ($Prod) { npm run start -- -H $HostEscuta } else { npm run dev -- -H $HostEscuta }
} finally {
    Pop-Location -ErrorAction SilentlyContinue
    foreach ($p in @($backend, $transcricao, $workerOcr, $workerBackground, $beat, $agenteApi, $agenteWorker)) {
        if ($p -and -not $p.HasExited) {
            Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue
        }
    }
    Write-Host "`nBackend e transcricao encerrados." -ForegroundColor DarkGray
}
