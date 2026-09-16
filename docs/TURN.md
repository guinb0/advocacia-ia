# Fazer o áudio chegar em qualquer rede — o que falta e como subir

Documento de execução. O *porquê* está em `docs/CHAMADA.md`; aqui é o passo a
passo do que ainda não está no ar.

---

## O estado, medido em 16/09/2026

| peça | estado |
|---|---|
| HTTPS no app (`advocacia.levelhom.com.br`) | ✅ no ar |
| HTTPS no Jitsi (`jitsi.level33lab.cloud`) | ✅ no ar, serve a lib |
| Mídia pelo videobridge (P2P desligado) | ✅ feito no código |
| **TURN / relay em 443** | ❌ **não existe** |

`turn.level33lab.cloud` **não resolve no DNS**, e o `coturn` nunca subiu.

## O que já funciona sem o TURN, e o que não funciona

Desligar o P2P (feito em `chamadaJitsi.entrarNaSala`) resolve o caso comum: o
celular deixa de tentar alcançar o outro navegador e passa a mandar UDP para o
IP público do videobridge. Isso atravessa o NAT simétrico do 4G, que era o que
derrubava a chamada.

**Continua sem resolver:** rede que bloqueia UDP em porta alta — parte das redes
corporativas, Wi-Fi de hotel, alguns provedores. Nesses casos não há caminho
nenhum a não ser um relay escutando numa porta que ninguém bloqueia: 443/TCP.
É isto que o `coturn` faz.

## Conferir se há relay, em 30 segundos

Com a chamada de pé, abra `chrome://webrtc-internals` e procure os candidatos
ICE:

- só `host` e `srflx` → **não há relay**;
- aparece `relay` → o TURN está funcionando.

---

## Subir o coturn

### 1. DNS

Criar o registro `A` de `turn.level33lab.cloud`. Hoje o Jitsi e o app respondem
os dois em `187.77.239.138` — confirme por qual IP o TURN vai sair antes de
apontar.

### 2. Certificado

O coturn lê `cert.pem` e `privkey.pem` do disco; ele não fala com o Let's
Encrypt sozinho. Se o Traefik já emite por DNS challenge, o caminho mais curto é
um job que exporte o par para `TURN_CERTS_PATH` (padrão `/opt/certs/turn`).

### 3. Variáveis

Copiar `deploy/jitsi/coturn.env.exemplo` e preencher:

```bash
TURN_PUBLIC_IP=...          # IP público do nó que roda o coturn
TURN_REALM=level33lab.cloud
TURN_SECRET=$(openssl rand -hex 32)
TURN_CERTS_PATH=/opt/certs/turn
```

### 4. A porta 443

**A 443 do TURN e a 443 do Traefik são a mesma porta**, e não cabem no mesmo IP.
Três saídas, em ordem de preferência:

1. um segundo IP público só para o TURN — mais simples de operar;
2. TURN em **5349/TCP** (é o que `jitsi.env.producao` traz hoje) — resolve o 4G,
   mas não a rede corporativa que só libera 80 e 443, que é metade do motivo de
   existir;
3. Traefik na frente com roteamento TCP/SNI, separando por hostname.

### 5. Subir

```bash
docker compose -f deploy/jitsi/docker-compose.coturn.yml up -d
```

### 6. Ligar o Jitsi ao TURN

No `.env` do `docker-jitsi-meet`, as linhas da seção 3 de
`deploy/jitsi/jitsi.env.producao`:

```ini
TURN_HOST=turn.level33lab.cloud
TURN_PORT=5349
TURN_TRANSPORT=tcp
TURN_CREDENTIALS=<o MESMO valor de TURN_SECRET>
```

> `TURN_CREDENTIALS` e `--static-auth-secret` do coturn precisam ser **iguais**.
> Divergindo, o TURN recusa todo mundo sem dizer por quê — e o sintoma volta a
> ser a chamada muda, que é o mais difícil de diagnosticar.

Depois, `docker compose restart prosody jvb`. A imagem do Prosody só carrega o
módulo `external_services` quando `TURN_HOST` existe; com ele, param também os
dois `Strophe error: service-unavailable` que hoje aparecem no console a cada
entrada na sala.

---

## Enquanto o TURN não sobe

Peça ao cliente que entre pelo **Wi-Fi**, não pelo 4G. Com o P2P desligado o 4G
já deve funcionar, mas o Wi-Fi tira a variável da mesa — e numa entrevista real
não há tempo de diagnosticar rede.
