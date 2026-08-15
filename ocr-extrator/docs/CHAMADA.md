# A chamada da entrevista — como o pessoal roda

Guia prático da conversa por vídeo com o entrevistado. Quem quiser o *porquê* das
decisões técnicas, o lugar é o `CONTEXTO.md`; aqui é o passo a passo.

---

## Antes de tudo: hoje isto só funciona na própria máquina

**Leia esta seção antes de marcar entrevista com cliente de verdade.**

O link que a tela gera é `http://localhost:3000/chamada/<sala>`. `localhost`
significa "esta máquina" — no celular do cliente, esse endereço aponta para o
próprio celular dele, e não abre nada.

Trocar `localhost` pelo IP da máquina **não resolve**, e o motivo não é de rede:
navegador só libera microfone e câmera em **contexto seguro** (HTTPS, ou
`localhost`). Num `http://192.168.x.x:3000` o Chrome e o Safari recusam o
microfone, e sem microfone não há chamada nem transcrição.

Então, hoje:

| situação | funciona? |
|---|---|
| Testar sozinho, duas abas na mesma máquina | **sim** |
| Cliente presente na sala, no seu computador | **sim** |
| Cliente no celular dele, em casa | **não** — falta HTTPS |

Enquanto isso não muda, a entrevista à distância se faz por telefone com o
cliente **no viva-voz**, e a transcrição sai do microfone da sala (ver
`CONTEXTO.md`, seção da entrevista). O que falta para liberar o uso remoto está
no fim deste documento.

---

## O que precisa estar de pé

Tudo sobe com um comando só, da pasta `ocr-extrator`:

```powershell
.\iniciar.ps1
```

Ele levanta, nesta ordem: Keycloak (container), transcrição (`:8200`), backend
(`:8100`) e frontend (`:3000`). `Ctrl+C` derruba os três últimos; o Keycloak
segue no container.

O servidor de vídeo é **separado** e não sobe com o `iniciar.ps1`:

```powershell
cd ..\..\docker-jitsi-meet
docker compose up -d
```

Confira que respondeu:

```powershell
Invoke-WebRequest http://localhost:8081 -UseBasicParsing | Select-Object StatusCode
docker ps --filter name=jitsi --format "{{.Names}}`t{{.Status}}"
```

Devem aparecer quatro contêineres — `web`, `prosody`, `jicofo`, `jvb`. Faltando
algum, a chamada abre e ninguém se ouve.

> A porta é **8081**, e não a 8000 do padrão do Jitsi, porque a 8000 costuma
> estar ocupada nesta máquina.

---

## Conduzindo a entrevista

1. Entre em **http://localhost:3000** e faça login (`guinb` / `123`).
2. Clique em **Conduzir entrevista guiada**. A tela abre em duas colunas: o
   roteiro à esquerda, a chamada à direita.
3. Na coluna da direita, **Abrir chamada**. O navegador vai pedir o microfone —
   é preciso permitir. A sala é sorteada na hora (128 bits): quem tem o link
   entra, quem não tem não adivinha.
4. **Copiar link** (ou *Copiar mensagem*, que já vem com um texto pronto) e
   mandar ao entrevistado.
5. Do lado dele: ele digita como quer ser chamado, decide se liga a câmera e
   toca em **Entrar na chamada**. Sem conta, sem senha, sem instalar nada.
6. Quando ele entra, o retrato aparece na sua coluna e o estado vira
   **em chamada**.

A sala é efêmera: existe enquanto houver alguém dentro, e não é gravada em lugar
nenhum. Fechada a chamada, o link não serve mais.

**A chamada não cai ao trocar de tela.** Ao concluir a entrevista e abrir o caso
para acompanhar os documentos, a ligação continua — ela encolhe para um **painel
no canto da tela**, com os controles de mudo, câmera e desligar à mão. É o que
permite guiar o cliente pelo envio dos documentos sem largar a conversa. Só o
botão **Desligar** (no painel do canto) encerra; trocar de tela, não. O mesmo
vale do lado do cliente: a chamada segue enquanto ele envia os documentos.

---

## A voz da chamada alimenta a transcrição

Quando o cliente entra na chamada, a **voz dele — separada da sua** — vira a
fonte da transcrição, no lugar do microfone da máquina. É o WebRTC que entrega a
faixa do outro lado isolada, então o que sobe para o Whisper é só o entrevistado:
sem a sua pergunta no meio da resposta, sem o eco do viva-voz.

Não é preciso fazer nada para ligar isso: assim que o retrato do cliente aparece
(estado **em chamada**), a fonte troca sozinha. O aviso "a voz do entrevistado
está chegando" confirma.

> Isto já esteve desligado por um tempo, porque a faixa chegava muda. Era um
> descompasso de taxa de áudio (a chamada manda 48 kHz, e o código fixava o
> processamento em 16 kHz); corrigido. Se algum dia a transcrição da chamada
> voltar a sair vazia, é aqui que se olha — `worklet-pcm.js` e `CONTEXTO.md`.

**Sem chamada, a transcrição sai do microfone da máquina** (o **Ligar microfone**
no topo do roteiro), e aí ele capta a sala inteira, você inclusive — bom porque
pega o cliente no viva-voz, ruim porque as perguntas entram junto. Com a chamada,
esse problema não existe.

Em cada pergunta marcada `VOZ`:

| botão | o que faz |
|---|---|
| **Gravar resposta** | começa a transcrever |
| **Pausar** / **Retomar** | segura o envio sem fechar a resposta — o que for dito não entra |
| **Finalizar resposta** | fecha e transcreve o áudio inteiro |
| **Adicionar complemento** | grava de novo e **acrescenta** ao que já havia |

Depois de finalizar, o botão vira **Transcrevendo…** por alguns segundos: o
texto definitivo é transcrito da resposta inteira, e numa resposta longa isso
demora. É esperado, não é travamento.

Fechada a resposta, aparece embaixo da pergunta a **conferência**: o que faltou
e as perguntas prontas para ler em voz alta ao cliente.

---

## Quando não conecta

**"Servidor de chamadas fora do ar"** — o Jitsi não está de pé. Suba os
contêineres (seção acima).

**O cliente entrou mas ninguém se ouve** — quase sempre é o `jvb`. Confira se o
contêiner está no ar e se a **UDP 10000** está liberada; é por ela que o áudio
passa.

**"Permissão de microfone negada"** — no cadeado da barra de endereço, liberar o
microfone e recarregar.

**Conecta e cai, ou nunca conecta, no 4G do cliente** — falta servidor **TURN**.
Em algumas redes de celular e corporativas a ligação direta entre navegadores não
passa, e só STUN não resolve. É item conhecido e ainda não instalado.

**A chamada some ao recarregar a página** — é o esperado: a sala é efêmera. Abra
outra e mande o link novo.

---

## O que falta para atender cliente à distância

Em ordem de dependência:

1. **HTTPS.** Sem certificado, navegador nenhum libera microfone fora do
   `localhost`. É o bloqueio de verdade — os outros itens não adiantam sem este.
2. **Endereço alcançável** no `.env`, os dois apontando para o nome público:
   - `URL_PORTAL` — hoje `http://localhost:3000`, é o que monta o link do convite;
   - `NEXT_PUBLIC_JITSI_URL` — **não está no `.env`**, então o código cai no
     padrão `http://localhost:8081`. Publicando, precisa ser declarado.
3. **TURN**, para os clientes cujas redes não fecham conexão direta.

Vale notar que o portal do cliente tem o mesmo bloqueio, e por outro motivo: ele
manda a senha do caso em texto claro. HTTPS resolve os dois de uma vez.
