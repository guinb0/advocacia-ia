param(
    [string]$Destino = (Join-Path $PSScriptRoot "..\..\..\docker-jitsi-meet"),
    [string]$Versao = "stable",
    [int]$PortaHttp = 8081
)

$ErrorActionPreference = "Stop"

function Novo-Segredo {
    $bytes = New-Object byte[] 32
    $rng = New-Object System.Security.Cryptography.RNGCryptoServiceProvider
    try { $rng.GetBytes($bytes) } finally { $rng.Dispose() }
    return ([Convert]::ToBase64String($bytes) -replace '[+/=]', '')
}

function Definir-Env([System.Collections.Generic.List[string]]$Linhas, [string]$Nome, [string]$Valor) {
    $padrao = "^\s*#?\s*" + [Regex]::Escape($Nome) + "="
    for ($i = 0; $i -lt $Linhas.Count; $i++) {
        if ($Linhas[$i] -match $padrao) {
            $Linhas[$i] = "$Nome=$Valor"
            return
        }
    }
    $Linhas.Add("$Nome=$Valor")
}

$Destino = [IO.Path]::GetFullPath($Destino)
if (-not (Test-Path (Join-Path $Destino "docker-compose.yml"))) {
    if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
        throw "Git nao encontrado. Instale o Git para o bootstrap baixar o Jitsi oficial."
    }
    Write-Host "Baixando o docker-jitsi-meet oficial..." -ForegroundColor Yellow
    git clone --depth 1 https://github.com/jitsi/docker-jitsi-meet.git $Destino
    if ($LASTEXITCODE -ne 0) { throw "Falha ao clonar docker-jitsi-meet em $Destino." }
}

$arquivoEnv = Join-Path $Destino ".env"
if (-not (Test-Path $arquivoEnv)) {
    $exemplo = Join-Path $Destino "env.example"
    if (-not (Test-Path $exemplo)) { throw "env.example do Jitsi nao encontrado em $Destino." }

    $linhas = [System.Collections.Generic.List[string]]::new()
    foreach ($linha in Get-Content $exemplo -Encoding UTF8) { $linhas.Add($linha) }

    # Configuracao autocontida: dados persistentes ficam ao lado do clone e nao
    # dependem de pastas previamente criadas no perfil do usuario.
    Definir-Env $linhas "CONFIG" "./.jitsi-meet-cfg"
    Definir-Env $linhas "HTTP_PORT" "$PortaHttp"
    Definir-Env $linhas "HTTPS_PORT" "8444"
    Definir-Env $linhas "PUBLIC_URL" "http://localhost:$PortaHttp"
    Definir-Env $linhas "JVB_ADVERTISE_IPS" "127.0.0.1"
    Definir-Env $linhas "JITSI_IMAGE_VERSION" $Versao
    Definir-Env $linhas "DISABLE_HTTPS" "1"
    Definir-Env $linhas "ENABLE_XMPP_WEBSOCKET" "1"
    Definir-Env $linhas "ENABLE_AUTH" "0"
    Definir-Env $linhas "ENABLE_GUESTS" "1"

    foreach ($nome in @(
        "JICOFO_AUTH_PASSWORD", "JVB_AUTH_PASSWORD", "JIGASI_XMPP_PASSWORD",
        "JIBRI_RECORDER_PASSWORD", "JIBRI_XMPP_PASSWORD"
    )) { Definir-Env $linhas $nome (Novo-Segredo) }

    $linhas | Set-Content -LiteralPath $arquivoEnv -Encoding UTF8
    Write-Host "Configuracao local do Jitsi criada em $arquivoEnv" -ForegroundColor Green
}

$pastas = @(
    "web", "storage\web", "storage\transcripts", "tmp\web-crontabs",
    "tmp\web-load-test", "prosody\config", "prosody\prosody-plugins-custom",
    "storage\prosody", "jicofo", "jvb"
)
foreach ($pasta in $pastas) {
    New-Item -ItemType Directory -Force -Path (Join-Path $Destino ".jitsi-meet-cfg\$pasta") | Out-Null
}

Push-Location $Destino
try {
    docker compose up -d
    if ($LASTEXITCODE -ne 0) { throw "docker compose do Jitsi terminou com erro." }
} finally {
    Pop-Location
}

Write-Output $Destino
