# Começando no projeto

Da máquina limpa até o sistema rodando. Se der tudo certo são uns 20 minutos, e
a maior parte é download de modelo.

Depois disto, leia o `CONTEXTO.md` — ele conta o que foi decidido e por quê, que
é o que não dá para deduzir lendo o código.

---

## O que instalar antes

| | por quê | como conferir |
|---|---|---|
| **Windows + PowerShell** | os scripts do projeto são `.ps1` | você já está nele |
| **[uv](https://docs.astral.sh/uv/)** | cria o venv e instala o Python 3.11 | `uv --version` |
| **Node 20+** | o frontend é Next.js 16 | `node --version` |
| **Git** | | `git --version` |
| **Docker Desktop** | *opcional* — só para login e chamadas | `docker ps` |

**Python 3.11 especificamente.** O `paddlepaddle` ainda não publica wheels para
3.13+, e o `uv` resolve isso sozinho — não precisa instalar Python à mão.

**Docker é opcional.** Sem ele você roda com `-SemAuth` e perde só o login e a
chamada por vídeo. Tudo o mais funciona.

---

## Primeira execução

```powershell
git clone https://gitlab.level33lab.cloud/ia/advocacia-ia
cd advocacia-ia\ocr-extrator
```

Salve o arquivo de configuração que veio junto como `.env` nesta pasta. **Ele
funciona como está, sem preencher nada** — cada bloco lá dentro liga um recurso
a mais, e explica o que você perde deixando vazio.

```powershell
.\iniciar.ps1 -SemAuth
```

Na primeira vez ele vai criar o venv, instalar as dependências Python, rodar
`npm install` e baixar os modelos. O PaddleOCR baixa ~100MB para
`~/.paddlex/official_models`; o Whisper, ~500MB.

Quando parar de escrever, abra **http://localhost:3000**.

> `-SemAuth` desliga a autenticação e dispensa o Docker. É como você vai rodar
> no dia a dia enquanto estiver mexendo em OCR, entrevista ou contrato.

### Com login

```powershell
docker compose up -d keycloak
.\iniciar.ps1
```

Login do app: **`guinb` / `123`**. Console do Keycloak em
http://localhost:8180 (`admin` / `admin`).

Essas senhas são de desenvolvimento e estão no repositório de propósito — o que
NÃO pode acontecer é elas seguirem assim quando o sistema sair da máquina.

---

## O que sobe

| serviço | porta | sobe com |
|---|---|---|
| Backend (FastAPI + PaddleOCR) | `8100` | `iniciar.ps1` |
| Frontend (Next.js) | `3000` | `iniciar.ps1` |
| Transcrição (Whisper) | `8200` | `iniciar.ps1` |
| Keycloak | `8180` | `docker compose up -d keycloak` |
| Jitsi (chamadas) | `8081` | à parte — ver `docs/CHAMADA.md` |

`Ctrl+C` no terminal derruba backend, frontend e transcrição juntos. Keycloak e
Jitsi ficam de pé entre execuções, como containers.

Documentação interativa da API: **http://127.0.0.1:8100/docs**.

**As portas não são as óbvias** e isso é intencional: a 8000 costuma estar
ocupada (WSL, outros projetos). A 3000 é a padrão do Next, então ela colide com
qualquer outro projeto Next aberto — se o script parar em "porta em uso",
derrube o outro ou use `.\iniciar.ps1 -Porta 3100`.

---

## Um passeio de dez minutos

1. **Análise avulsa** — jogue a foto de um RG ou CNH na tela inicial. O OCR lê,
   confere os dígitos verificadores e mede a legibilidade. Leva de 10 a 14s com
   a máquina livre.
2. **Entrevista guiada** — clique em *Conduzir entrevista guiada*, ligue o
   microfone no topo e responda uma pergunta marcada `VOZ`. Ao finalizar, se as
   chaves estiverem preenchidas, aparece a conferência do que ficou faltando.
3. **Contrato** — conclua a entrevista e clique em *Gerar contrato*. Ele baixa
   um `.docx` preenchido com a qualificação.
4. **Caso e portal** — crie o caso, gere o link do portal e abra numa aba
   anônima: é o que o cliente vê para mandar os documentos.

O contrato exige o modelo oficial em `docs/CONTRATO*.docx`, que **não está no
repositório** (traz tabela de honorários, CNPJ e as OAB do escritório, e o repo
é público). Peça ao Guilherme. Sem ele, a rota responde 503 explicando.

---

## Testes

Não há `pytest` instalado: cada suíte é um script que roda sozinho e imprime
PASS/FALHA.

```powershell
.venv\Scripts\python.exe -m tests.test_contrato
.venv\Scripts\python.exe -m tests.test_assinatura
.venv\Scripts\python.exe -m tests.test_analise_resposta
.venv\Scripts\python.exe -m tests.test_casos
```

Nenhuma delas toca serviço externo — DeepSeek, ZapSign e pgvector entram
dublados. Rodam offline e não gastam crédito.

Frontend:

```powershell
cd frontend
npm run typecheck
npm run build
```

> `tests.test_roteiros` falha com 401 quando o Keycloak está no ar: ela chama
> rota protegida sem token. É falha conhecida da suíte, não do seu ambiente.

---

## Onde as coisas estão

```
app/
  main.py            rotas; middleware de auth por allowlist
  pipeline.py        OCR → extração de campos → validação
  extractors.py      os campos de cada tipo de documento
  roteiros.py        as perguntas da entrevista
  contrato.py        preenche o .docx do escritório (não redige cláusula)
  assinatura.py      ZapSign
  analise_resposta.py  a conferência de cada resposta
  triagem.py         classifica a entrevista
  rag.py             busca vetorial em precedentes
frontend/
  components/Roteiro.tsx        a entrevista
  components/PainelContrato.tsx contrato e assinatura
  app/portal/[token]/           o que o cliente vê
scripts/estado_rag.py           diagnóstico do banco vetorial
dados/                          SQLite + arquivos dos clientes (fora do git)
```

Os documentos dos clientes ficam em `dados/` e **nunca** vão para o
repositório. Se precisar de dado para testar, use os seus.

---

## Quando não sobe

**"porta em uso"** — outro projeto Next ou uma execução anterior que não morreu:

```powershell
Get-NetTCPConnection -LocalPort 3000,8100,8200 -State Listen |
  Select-Object LocalPort, OwningProcess
```

**"Keycloak nao respondeu"** — o container não subiu. `docker compose up -d
keycloak`, ou rode com `-SemAuth`.

**Uma rota nova responde 404 e você jurava tê-la escrito** — o backend não
recarrega sozinho. Derrube o `iniciar.ps1` e suba de novo. Para confirmar o que
o processo em execução realmente serve:

```powershell
(Invoke-WebRequest http://127.0.0.1:8100/openapi.json -UseBasicParsing).Content |
  ConvertFrom-Json | ForEach-Object { $_.paths.PSObject.Properties.Name }
```

**"ConnectionTimeout" no banco vetorial** — normal, a rede até ele é instável.
Tente de novo; a primeira conexão costuma estourar e a segunda passar.
`.venv\Scripts\python.exe -m scripts.estado_rag` separa "a rede não chega" de
"a credencial foi recusada" de "o banco está vazio".

**A transcrição não escreve nada** — o serviço registra uma linha por trecho
transcrito, **no próprio terminal do `iniciar.ps1`**:

```
parcial: cauda=4.1s inferencia=14ms nivel=0.0021 chegada=0.60x segmentos=0
```

Cada número aponta para uma causa diferente:

| campo | o que significa quando está ruim |
|---|---|
| `nivel` | RMS do áudio. Perto de zero é microfone mudo ou trocado |
| `chegada` | segundos de áudio por segundo de relógio. Abaixo de 1,0 a transcrição não acompanha a fala |
| `inferencia` | tempo do modelo. Dezenas de ms é o normal com GPU |
| `segmentos` | trechos que o detector de voz achou. Zero com `nivel` alto é problema de VAD; zero com `nivel` baixo é microfone |

Para acompanhar num arquivo em vez do terminal, suba a transcrição sozinha:

```powershell
.venv\Scripts\python.exe -m uvicorn app.servico_transcricao:app --port 8200 `
  --ws-ping-interval 0 --ws-ping-timeout 0 *> transcricao.out.log
```

**O OCR demora 200s** — a máquina está saturada. Medido: 10-14s com ela livre.
O gargalo é CPU/RAM, não o código; várias alternativas já foram testadas e
descartadas por medição (está no `CONTEXTO.md`).

---

## Antes do primeiro commit

- **Nunca commite `.env`** — o `.gitignore` cobre, mas confira com
  `git status` antes de `git add -A`.
- **Há dois remotos**, e o do GitHub é **público**:
  ```powershell
  git push origin main    # GitLab
  git push github main    # GitHub, PÚBLICO
  ```
- Antes de subir, uma olhada no que vai junto:
  ```powershell
  git diff --cached | Select-String -Pattern "sk-|senha|password|token"
  ```
- Os comentários deste projeto explicam **por que**, não o que o código faz. Se
  você tomou uma decisão que o próximo dev vai querer reverter sem saber o
  motivo, escreva o motivo ali.
