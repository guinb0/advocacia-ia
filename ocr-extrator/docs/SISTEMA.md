# Advocacia IA — o que é, como está feito, e onde dói

Documento para quem chega de fora. Descreve o sistema como ele está hoje, com os
números medidos e as limitações reais — a ideia é que dê para olhar isto e
dizer "essa arquitetura não escala por causa de X".

Não é material de marketing. Onde algo está frágil, está escrito que está.

---

## 1. O problema

Um escritório de advocacia trabalhista (Lara & Melo, Brasília/DF) atende
trabalhadores dos Correios em ações de acidente de trabalho, assalto durante o
serviço e doença ocupacional.

O gargalo não é a petição — é o **acolhimento**. Cada cliente novo passa por:

1. uma entrevista de 20–30 minutos, guiada por um roteiro de **86 perguntas**
   que o escritório escreveu, com ramificações (quem não sofreu assalto não
   responde o módulo de assalto);
2. a triagem do caso (qual tipo de ação);
3. contrato de honorários, procuração e declaração de hipossuficiência,
   assinados;
4. a coleta de **14 a 33 documentos** por caso, cada um conferido à mão (foto
   ilegível, documento trocado, dado divergente).

Feito por pessoas, isso consome o dia inteiro de uma atendente por cliente, e o
erro caro aparece semanas depois — CPF digitado errado que atravessou contrato,
procuração e petição; documento que ninguém percebeu que faltava.

**O que o sistema faz:** conduz a entrevista, transcreve e preenche o roteiro
sozinho enquanto a conversa corre, gera os três documentos a partir dos modelos
do escritório, manda assinar, abre um portal para o cliente enviar os documentos
e lê cada um com OCR conferindo os campos.

---

## 2. Como está montado hoje

Tudo roda **numa máquina só** — um notebook com RTX 4050 (6 GB). Cinco processos:

| processo | porta | o que faz |
|---|---|---|
| **Frontend** | 3000 | Next.js 16 + React 19. Sem lib de UI, sem state manager. |
| **API** | 8100 | FastAPI. 54 rotas. Carrega o PaddleOCR no processo, **em CPU**. |
| **Transcrição** | 8200 | FastAPI + faster-whisper (`medium`, CUDA). WebSocket. |
| **Keycloak** | 8180 | contêiner. OIDC + PKCE; a API valida o JWT localmente por JWKS. |
| **Jitsi** | 8081 | 4 contêineres (web, prosody, jicofo, jvb). Videoconferência. |

Fora da máquina: **Postgres + pgvector** (RAG de jurisprudência), **DeepSeek**
(o LLM de todas as tarefas de linguagem) e **ZapSign** (assinatura eletrônica).

Volume de código: ~14 mil linhas de Python, ~15 mil de TypeScript.

### Quem usa a GPU, e quem não usa

Só o Whisper. O PaddleOCR roda **inteiramente em CPU** — a dependência é
`paddlepaddle` (a wheel de CPU), não `paddlepaddle-gpu`, e não há `device=` em
lugar nenhum. A RTX 4050 carrega apenas os 4.230 dos 6.141 MiB do Whisper, com
~1,9 GB ociosos.

Isso importa porque muda o diagnóstico: a disputa entre OCR e transcrição é por
**CPU e RAM**, nunca por VRAM. Todo plano que proponha "lock de GPU entre os
dois" está resolvendo um problema que este sistema não tem.

### Por que a transcrição é um processo separado

Não é gosto arquitetural — é medição. PaddleOCR e Whisper no mesmo processo
disputavam CPU (11s de áudio levavam **227s**) e as DLLs de MKL/OpenMP dos dois
conflitavam no Windows. Separados, o áudio sai em ~1x tempo real.

### O OCR, por etapa

Medido em máquina livre (`app/pipeline.py` registra `tempo_etapas_s` em cada
documento processado). São as amostras sintéticas de `tests/amostras`, de
1000×640 — uma foto de celular real, reduzida ao teto de 2.000px, tem ~4x mais
pixels, e é daí que vêm os 10-14s registrados no `CONTEXTO.md`:

| documento | tamanho | passadas | total |
|---|---|---|---|
| `cnh.png` | 1000×640 | 1 | **4,36s** |
| `ctps.png` | 1000×640 | 1 | 4,32s |
| `cpf.png` | 1000×640 | 1 | 7,28s |
| `cnh_borrada.png` | 1000×640 | **4** | 9,38s |
| `ruido.png` | 900×700 | **4** | 13,83s |

Duas coisas que só aparecem com o cronômetro por etapa:

**A inferência é 99% do tempo.** Decodificar, preparar (CLAHE + redimensionar),
avaliar qualidade, classificar, extrair campos e salvar somam **menos de 0,15s**
juntos. Não há nada a otimizar fora do modelo.

**A foto ruim custa 3x, e ninguém tinha notado.** Quando a primeira leitura
pontua abaixo de 60, `ocr_com_rotacao` testa 90°, 180° e 270°: quatro inferências
no lugar de uma. É o multiplicador que faltava na conta — um documento ilegível
não custa "um pouco mais", custa o triplo, e numa máquina já saturada é assim que
se chega aos ~200s de um único documento. A ironia é que a passada extra só é
gasta em fotos que vão acabar reprovadas de qualquer forma.

Os modelos em uso são `PP-OCRv5_server_det` (detecção, variante pesada) +
`latin_PP-OCRv5_mobile_rec` (reconhecimento, variante leve).

### A GPU foi testada, é 17x mais rápida, e foi rejeitada

Vale contar inteiro, porque a conclusão é contraintuitiva e custou um dia.

A hipótese era boa: sobram ~1,7 GB na placa, os modelos do PP-OCR são pequenos,
e o OCR é o gargalo. Instalada a wheel `paddlepaddle-gpu==3.0.0` (cu126) num
ambiente isolado, com o Whisper carregado para medir na condição real:

| configuração | inferência média | pico de VRAM | caracteres lidos |
|---|---|---|---|
| CPU, detector server (hoje) | ~4,2s | — | — |
| GPU, detector server | 0,70s | 2.490 MiB ✗ | 1.494 |
| GPU, detector mobile | **0,25s** | 916 MiB ✓ | 1.507 |

Dezessete vezes mais rápido, cabendo na VRAM, lendo *mais* texto. E mesmo assim
não entrou.

**O que quebrou:** `tests/test_pipeline.py` saiu de 2 falhas para 9. O caminho
CUDA devolve caixas de texto com geometria diferente das da CPU — mais coladas,
agrupadas de outro jeito. Como a associação rótulo→valor em `extractors.py` é
geométrica, os campos saem trocados:

```
nome = 'ANTONIO CARLOS SANTOS'          esperado 'MARIA APARECIDA DA SILVA SANTOS'
nome = 'PATA PENASCIMENTO'              esperado 'ANA BEATRIZ RODRIGUES COSTA'
nome = 'CARLOS EDUARDO FERREIRAMARTINS' esperado 'CARLOS EDUARDO FERREIRA MARTINS'
```

O primeiro caso é o que decide a questão: o nome do **pai** saindo no campo do
titular. É a mesma classe de erro que a seção 4 descreve como inaceitável — um
dado errado que segue calado para o contrato, a procuração e a petição. Trocar
4,2s por 0,25s não paga isso.

Não é culpa do detector mobile: com o detector `server` em GPU são 9 falhas
também. É a GPU.

**O que ficou pronto para quando for a hora:** `app/ocr_engine.py` aceita
`OCR_DISPOSITIVO=gpu`, `OCR_DETECTOR` e `OCR_LIMITE_VRAM_MB`, com queda
automática para CPU na construção *e* durante a inferência (a VRAM pode faltar
depois do boot, quando o Whisper cresce). O teto de VRAM não é opcional: sem ele
o alocador do Paddle vai a 2,5 GB e derruba a placa — com a entrevista ao vivo
dentro dela.

O que falta é reajustar `_agrupar_em_linhas` (tolerância vertical e `limite_gap`)
para a saída da GPU, com a suíte como critério. É projeto próprio, não troca de
dependência.

### PDF de várias páginas

`pdf_para_imagem` empilha as páginas numa imagem só, que depois é reduzida para
2.000px de lado maior. Num contrato de 3 páginas isso vai de 1224×5000 para
490×2000 — os caracteres encolhem 2,5x.

Testado, porque parecia perda séria de texto e **não é**: 5.541 caracteres
empilhado contra 6.002 página a página (8% a mais), com confiança média de 0,973
contra 0,982, ao custo de **3,5x mais tempo** (12,7s contra 44,3s). A troca está
aceita conscientemente. O teste foi num PDF gerado digitalmente; um PDF
escaneado de várias páginas provavelmente degrada mais, e isso não foi medido.

### Persistência

**SQLite**, um arquivo. Cinco tabelas: `casos`, `entregas`, `assinaturas`,
`entrevistas`, `vinculos_agente`. Os arquivos enviados ficam em disco, em
`dados/casos/<id>/`.

A escolha foi deliberada e está documentada: os arquivos são de clientes e não
devem sair da máquina do escritório; sem servidor de banco, o backup é copiar
uma pasta. **É também o primeiro limite de escala** — ver a seção 5.

### O RAG de jurisprudência

`pgvector` remoto com **52.926 chunks** de 5.824 documentos (sentenças e acórdãos
do TRT8, TST, DJEN, DEJT), cobrindo 1.745 processos. Cada chunk carrega número do
processo, órgão, assuntos e o desfecho calculado. CPF e e-mail são redigidos
antes de ir para o serviço de embeddings.

Serve a duas coisas: a análise da resposta durante a entrevista ("o que falta
neste ponto", com precedentes) e a estratégia do caso.

---

## 3. O fluxo, ponta a ponta

```
        ┌──────────────── ATENDIMENTO (uma única rolagem) ────────────────┐
        │                                                                │
Nome+CPF│  Roteiro guiado ──► Google Meu Negócio ──► Relatório (PDF)      │
digitados  (86 perguntas)      (avaliação)          (com precedentes)     │
   │    │        │                                        │              │
   │    │        ▼                                        ▼              │
   │    │  microfone aberto                     3 documentos + ZapSign    │
   │    │  transcrição ao vivo                          │                 │
   │    │  escuta preenche                              ▼                 │
   │    │  o roteiro sozinho              criar o caso ──► portal + sala   │
   │    │                                                │                │
   │    │                                                ▼                │
   │    │                                    checklist recebendo documentos│
   │    │                                    (OCR conferindo cada um)      │
   │    │                                                │                │
   │    └────────────────────────────────────────────────┼────────────────┘
   │                                                     ▼
   └──── vídeo, áudio e transcrição bruta ──────► encerrar o atendimento
```

O ponto que define o sistema: **a entrevista não é um formulário**. O microfone
abre uma vez no "podemos começar?" e não fecha mais. Cada trecho de fala que o
Whisper confirma vai para um LLM junto com as perguntas ainda abertas, e ele diz
o que aquele trecho respondeu. O cliente que conta a história inteira de uma vez
tem cinco campos preenchidos de uma vez, e as perguntas correspondentes somem.

Sobre isso há uma regra do escritório que vale citar, porque moldou a interface:

> *"Não é o que o cliente quer ou nós entendemos — tem que ser o que o advogado
> determina."*

Daí a **barra de condução**: uma pergunta por vez, na ordem do documento, com um
relógio. Dez segundos sem a pergunta atual respondida e a tela cobra em vermelho,
com a frase pronta para ler ao cliente. É deliberadamente rígido.

---

## 4. Decisões que custaram medição

Estas estão aqui porque são o tipo de coisa que se descobre errado depois.

**Nome e CPF são digitados, nunca ouvidos.** Já foram sugestão da transcrição. No
áudio real, o Whisper `small` escrevia *"Meu nome é com o Patrã Guilherme, nome de
Bezerra"*, e o LLM — corretamente — recusava-se a preencher a partir daquilo. Hoje
os dois são digitados e é o preenchimento deles que **libera o microfone**.

**Whisper `medium`, não `small`.** Mesmo áudio de 96,8s: o `small` escrevia
"Guilherme Inunes" e "o CIDA de Mando Tensão Industrial"; o `medium` acertou
"Guilherme Nunes" e "auxiliar de manutenção industrial" — e foi **mais rápido**
(31,5x contra 27,1x o tempo real). Ocupa 4.230 dos 6.141 MiB da placa.

**O modelo aquece no boot.** Carregar os pesos não é estar pronto: a primeira
inferência de verdade compila kernels CUDA e custava **30s** numa fala de 2,3s.
Agora uma inferência de mentira roda na subida.

**Nenhum número sai de fala.** RG, datas e documentos são bloqueados em duas
camadas (a lista mandada ao modelo e a conferência do que ele devolveu). Errar
uma palavra num relato é visível e corrigível; errar um dígito segue calado para
o contrato, a procuração e a petição.

**O trecho que abre um módulo é lido duas vezes.** "Fui assaltado, tenho o BO e a
CAT, e fiquei afastado pelo INSS" preenchia 1 campo — as perguntas do módulo de
assalto só existem depois de o rastreio dar positivo, e o resto da frase morria.
Hoje, quando um rastreio abre um módulo, o mesmo trecho é reprocessado contra as
perguntas recém-nascidas: passou a preencher 4.

**A gravação de tela é presa à aba do sistema.** `getDisplayMedia` com
`preferCurrentTab`, e se o navegador entregar outra coisa a gravação **não
começa**. Gravar a área de trabalho de um escritório por 40 minutos é vazar o
caso de outro cliente dentro do vídeo deste.

---

## 5. Onde dói — e é sobre isto que eu quero ideias

Esta é a seção honesta.

### Escala

- **SQLite num arquivo, numa máquina.** Serve um escritório com um atendente por
  vez. O banco não é o gargalo.
- **O gargalo é a CPU, não a placa.** O OCR roda em CPU e é o que satura: 4s num
  documento com a máquina livre, ~200s com ela cheia. A GPU tem só o Whisper e
  ~1,9 GB ociosos.
- **Cinco atendentes cabem na placa; não cabem na CPU.** Os 4.230 MiB do Whisper
  são dos *pesos*, compartilhados entre sessões — não por sessão. A 31,5x o tempo
  real, cinco entrevistas simultâneas pedem 5x e a placa entrega 31,5x. Quem não
  escala é o OCR.
- **Fila só no OCR, e só dentro do processo.** O upload é assíncrono desde sempre
  (POST responde em ~0,3s, a tela faz polling), mas quem executa é uma
  `ThreadPoolExecutor(max_workers=1)` em `app/ocr_engine.py` — obrigatória,
  porque o predictor do Paddle tem afinidade de thread. Não há persistência de
  job: se o processo cai no meio, a entrega fica em `processando` para sempre.
  Não há retentativa nem prioridade.
- **Sem observabilidade** além de log em arquivo. Não há métrica, trace nem
  alerta. O `tempo_etapas_s` por documento é o que existe hoje de mais próximo.

### Distribuição

- **Não há HTTPS**, e isso não é preguiça: navegador só libera microfone e câmera
  em contexto seguro. Hoje o atendimento remoto **só funciona na máquina do
  escritório** (`localhost`). Cliente no celular dele, em casa: não funciona.
  É o bloqueio número um.
- **Sem TURN** no Jitsi — em redes móveis e corporativas a conexão direta não
  fecha.
- O portal do cliente manda a senha do caso em texto claro. HTTPS resolve os dois.

### Dados

- **Retenção não decidida.** O áudio das entrevistas fica em claro em
  `dados/entrevistas/`, sem prazo. Relato de entrevista tem CPF e dado de saúde —
  há uma decisão de LGPD pendente antes de popular a tabela `entrevistas`.
- **Sem multi-tenant.** O sistema assume um escritório.

### Acoplamento

- Um provedor de LLM (DeepSeek) para triagem, escuta, análise e estratégia. Sem
  abstração de provedor.
- Um provedor de assinatura (ZapSign), com os links expirando em 60 minutos — daí
  o download passar pelo backend e o PDF ficar em disco.

---

## 6. As perguntas que eu levaria para uma revisão de arquitetura

1. **Do monolito na máquina para quê?** Um escritório com 5 atendentes
   simultâneos: como o gargalo é CPU do OCR, a pergunta não é "fila ou serviço
   gerenciado" — é *comprar CPU* ou *mandar o OCR para outra máquina*. Fila
   (Celery/RQ) só ajuda no segundo caso; no primeiro ela organiza a espera sem
   encurtá-la. A GPU ociosa já foi tentada e está bloqueada pela extração, não
   pela memória — ver a seção 2.
2. **Quanto do processamento pode sair da máquina** sem violar o compromisso de
   que documento de cliente não circula? Hoje o áudio já sai (embeddings vão para
   um serviço externo com CPF redigido) — onde está a linha?
3. **SQLite → Postgres, quando?** O que quebra primeiro: concorrência de escrita,
   backup, ou a necessidade de dois escritórios no mesmo sistema?
4. **A escuta ao vivo é uma máquina de estados escondida.** Trecho → LLM →
   preenchimento → condução. Existe um padrão melhor para isso (event sourcing?
   streaming com janelas?) do que a fila serializada que uso hoje?
5. **Como testar um sistema cuja saída é probabilística?** Há uma suíte que mede
   a triagem com relatos gerados por LLM, mas a escuta e a análise não têm
   equivalente.

---

## 7. Referência rápida

| assunto | onde |
|---|---|
| Decisões técnicas, com o porquê | `CONTEXTO.md` (o documento principal) |
| Como rodar | `README.md`, `iniciar.ps1` |
| A chamada de vídeo | `docs/CHAMADA.md` |
| Plano de bancos | `docs/PLANO-BANCOS.md` |
| Roteiro da entrevista | `app/roteiros.py` (fiel ao .docx do escritório) |
| Escuta ao vivo | `app/escuta.py` |
| Transcrição | `app/transcricao.py`, `app/servico_transcricao.py` |
| Contrato/procuração/declaração | `app/contrato.py` + `docs/*.docx` |

Stack: FastAPI · Next.js 16 · React 19 · SQLite · Postgres/pgvector ·
faster-whisper · PaddleOCR · Keycloak · Jitsi · DeepSeek · ZapSign.
