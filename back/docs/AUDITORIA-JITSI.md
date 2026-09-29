# Relatório de auditoria Jitsi

Data da auditoria: 20/09/2026

## Arquitetura atual

O aplicativo não usa `JitsiMeetExternalAPI` nem iframe para a chamada. `ChamadaJitsi`
carrega `/libs/lib-jitsi-meet.min.js` do próprio servidor Jitsi, chama `init`, cria
faixas com `createLocalTracks`, cria `JitsiConnection`, inicializa uma
`JitsiConference`, publica as faixas e anexa áudio remoto a elementos `<audio>`.
`ProvedorChamada` mantém uma instância única na raiz React, portanto a troca de tela
não desmonta a chamada. A voz remota também é exposta como `MediaStreamTrack` para a
transcrição.

## Referência oficial

O repositório local `jitsi-meet/` é um checkout do projeto oficial (`efd3d3f35`). A
implementação oficial confirma que `createLocalTracks` aceita `devices`,
`micDeviceId`, `cameraDeviceId` e `resolution`, e possui tratamento próprio de
falhas de captura, tracks, autoplay e reconexão. A documentação da IFrame API também
confirma que a API é uma alternativa de embed completa, mas não expõe as faixas
`MediaStreamTrack` ao aplicativo hospedeiro; por isso a escolha pela lib direta é
coerente com a transcrição.

## Confirmado

### TURN de produção pendente — severidade ALTA, confiança ALTA

`deploy/jitsi/jitsi.env.producao` deixa `TURN_HOST`, `TURN_PORT`, `TURN_TRANSPORT` e
`TURN_CREDENTIALS` como configuração a preencher, e `docs/TURN.md` registra a
pendência. Sem relay TURN em TCP/TLS 443, uma rede que bloqueia UDP/10000 pode
permitir entrada na sala e sinalização, mas não transportar áudio/vídeo. Isso explica
“entrou, mas ninguém ouve/vê” e não é corrigível no frontend.

### A observabilidade anterior era insuficiente — severidade MÉDIA, confiança ALTA

Antes do modo diagnóstico não havia correlação local entre permissão, lista de
dispositivos, autoplay, ICE, tracks e estado da rede. A integração agora registra
esses eventos em modo opt-in e mantém até 120 eventos na memória, sem áudio, vídeo,
nome da sala ou identificador de participante.

## Provável

### Falhas de autoplay em Safari/iOS — severidade MÉDIA, confiança MÉDIA

Áudio remoto é anexado dinamicamente. A implementação tenta `play()`, repete em
`loadedmetadata`, `canplay` e `unmute`, e libera as saídas no próximo gesto do
usuário. Ainda assim, a política do navegador pode exigir um gesto posterior; o
evento `AUTOPLAY_BLOCKED` agora torna isso distinguível de ICE/TURN.

### Troca simultânea de captura em mobile — severidade MÉDIA, confiança MÉDIA

A entrada pede áudio e vídeo em uma única chamada e possui recuperação da faixa de
áudio. A ativação de câmera durante uma chamada ainda requer uma segunda captura,
portanto iOS/Android podem encerrar temporariamente a faixa de áudio; a recuperação
automática cobre o caso, mas precisa de reprodução real em aparelhos-alvo.

## Hipóteses restantes

- `JVB_ADVERTISE_IPS` incorreto, UDP 10000 bloqueada ou IPv4/IPv6 assimétrico no
  ambiente publicado.
- Permissão concedida ao domínio errado, WebView embutida ou navegador dentro de
  aplicativo (Facebook/Instagram/WhatsApp).
- Falha específica de codec, Bluetooth ou suspensão de aba que só pode ser fechada
  com logs do modo diagnóstico e `chrome://webrtc-internals`/Safari Web Inspector.

## Alterações realizadas

- `front/src/lib/diagnosticoJitsi.ts`: retrato inclui estado online e métricas
  disponíveis da conexão (`effectiveType`, RTT, downlink e economia de dados).
- `front/src/lib/chamadaJitsi.ts`: registra transições online/offline e remove os
  listeners no dispose; já registra captura, permissões, dispositivos, tracks,
  autoplay, ICE, conferência, participantes e dispose.
- `front/src/components/chamada/DiagnosticoJitsi.tsx` e `app/layout.tsx`:
  painel opt-in no app, ativado por `NEXT_PUBLIC_JITSI_DIAGNOSTIC=1`,
  `localStorage.setItem('jitsi-diagnostic','1')` ou `?jitsiDiagnostic=1`.

## Como diagnosticar

1. Ative o modo diagnóstico e reproduza a falha em uma chamada nova.
2. Exporte/copiar o console `[JITSI_DIAGNOSTIC]` sem dados de mídia.
3. Compare a sequência: `PERMISSION_STATE`/`*_FAILURE` indica dispositivo ou
   permissão; `AUTOPLAY_BLOCKED` indica saída de áudio; `ICE_STATE_CHANGED`,
   `CONNECTION_INTERRUPTED` ou ausência de `TRACK_CREATED` indica transporte/Jitsi.
4. No Chrome, capture também `chrome://webrtc-internals`; candidatos apenas `host`
   e `srflx` confirmam que não houve relay TURN.

## Matriz de compatibilidade

Não foram executados testes físicos nesta auditoria; portanto todos os quadrantes
abaixo permanecem **NÃO TESTADO**. O código e os logs não substituem uma matriz de
dispositivos reais.

| Plataforma | Browser | Áudio | Vídeo | Risco | Possível causa |
|---|---|---|---|---|---|
| Windows | Chrome | NÃO TESTADO | NÃO TESTADO | Médio | dispositivo/ICE |
| Windows | Edge | NÃO TESTADO | NÃO TESTADO | Médio | dispositivo/ICE |
| Windows | Firefox | NÃO TESTADO | NÃO TESTADO | Médio | compatibilidade WebRTC |
| macOS | Chrome | NÃO TESTADO | NÃO TESTADO | Médio | autoplay/ICE |
| macOS | Safari | NÃO TESTADO | NÃO TESTADO | Alto | autoplay/captura |
| Android | Chrome | NÃO TESTADO | NÃO TESTADO | Alto | troca de rede/captura |
| iOS | Safari | NÃO TESTADO | NÃO TESTADO | Alto | autoplay/background/captura |

## Próximos passos ordenados

1. Configurar e validar TURN em TCP/TLS 443 e confirmar DNS, credenciais e firewall.
2. Rodar a matriz acima com o modo diagnóstico ativo.
3. Testar rede corporativa com UDP bloqueado e comparar ICE candidates.
4. Só depois ajustar constraints ou heurísticas específicas de browser; não há
   evidência para reescrever a arquitetura ou adicionar iframe.
