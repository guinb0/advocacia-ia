$ErrorActionPreference = "Stop"
# Este script mora em ia/, mas o código da ingestão (scripts.*, app.*) é Python do
# backend: roda de dentro de back/, com o .venv da raiz do repositório.
$raiz = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath (Join-Path $raiz "back")

$python = Join-Path $raiz ".venv\Scripts\python.exe"
$log = Join-Path $PSScriptRoot "rag-sincronizacao.log"
$agora = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
Add-Content -LiteralPath $log -Value "`n[$agora] Inicio RAG"

function Invoke-ComRetentativas {
    param(
        [string[]]$Argumentos,
        [string]$Etapa,
        [int]$Tentativas = 30
    )
    for ($tentativa = 1; $tentativa -le $Tentativas; $tentativa++) {
        # O Python pode escrever avisos no stderr. Com ErrorActionPreference=Stop,
        # o redirecionamento direto transforma isso em erro terminante e impede
        # que o laço de retentativas seja executado.
        $preferenciaAnterior = $ErrorActionPreference
        $ErrorActionPreference = "Continue"
        & $python @Argumentos 2>&1 | Out-File -LiteralPath $log -Append -Encoding utf8
        $codigoSaida = $LASTEXITCODE
        $ErrorActionPreference = $preferenciaAnterior
        if ($codigoSaida -eq 0) { return }
        $agoraTentativa = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
        Add-Content -LiteralPath $log -Value `
            "[$agoraTentativa] $Etapa falhou (tentativa $tentativa/$Tentativas); nova tentativa em 60s."
        Start-Sleep -Seconds 60
    }
    throw "$Etapa falhou depois de $Tentativas tentativas"
}

Invoke-ComRetentativas `
    -Etapa "Ingestao" `
    -Argumentos @("-m", "scripts.ingerir_jurimetria", "--sem-embeddings")

Invoke-ComRetentativas `
    -Etapa "Embeddings" `
    -Argumentos @("-m", "scripts.vetorizar_pendentes")

$agora = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
Add-Content -LiteralPath $log -Value "[$agora] Fim RAG"
