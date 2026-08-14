# Acervo

Acompanha o atendimento de um escritório trabalhista **da entrevista até a
papelada completa**: conduz o roteiro, transcreve a voz do cliente, sugere o tipo
de ação, preenche o contrato de honorários, manda assinar, e então cobra e
confere os documentos um a um.

Roda na máquina do advogado. Os arquivos do cliente ficam em `dados/` e não saem
dali — o que sai para fora são só quatro coisas, todas opcionais: o texto da
entrevista para o modelo de linguagem, o CEP para a base pública, o `.docx` para
a assinatura eletrônica, e a consulta ao banco de precedentes.

**Stack:** FastAPI + PaddleOCR + faster-whisper no backend, Next.js 16 + React 19
no frontend, SQLite local e um PostgreSQL com pgvector para os precedentes.

## O fluxo

```
entrevista → triagem → contrato → assinatura → caso → checklist
    ↑            ↓                                        ↓
 transcrição  conferência                          cliente envia
 (Whisper)   (precedentes)                        pelo portal → OCR valida
```

1. **Entrevista guiada.** O roteiro pergunta na ordem do escritório; as narrativas
   são ditadas e transcritas, os dados são digitados. Fechada cada resposta
   narrativa, o sistema diz o que faltou perguntar, fundamentado em processos
   semelhantes do TRT8.
2. **Triagem.** O relato vira uma sugestão de categoria, com o trecho que a
   sustenta. **Não cria caso** — quem confirma é o advogado.
3. **Contrato.** O modelo `.docx` do escritório é preenchido com a qualificação e
   pode seguir para assinatura eletrônica, ou ser baixado para assinar à mão.
4. **Caso e checklist.** Aberto o caso, o checklist da categoria define o que
   pedir. O portal dá ao cliente um link com senha para mandar as fotos.
5. **Conferência automática.** Cada arquivo passa por OCR, tem os dígitos
   verificadores validados e a legibilidade medida. O checklist se atualiza
   sozinho: foto ilegível ou documento trocado volta para "conferir" e entra no
   próximo pedido, com o motivo.

Nada de status marcado à mão: tudo é derivado dos arquivos entregues.

---

## Por onde começar

| você quer | leia |
|---|---|
| rodar o projeto pela primeira vez | [`docs/COMECANDO.md`](docs/COMECANDO.md) |
| entender o que foi decidido e por quê | [`CONTEXTO.md`](CONTEXTO.md) |
| usar ou consertar a chamada por vídeo | [`docs/CHAMADA.md`](docs/CHAMADA.md) |
| saber a direção visual da interface | [`docs/GUIA-VISUAL.md`](docs/GUIA-VISUAL.md) |
| ver o que cada rota faz, interativo | <http://127.0.0.1:8100/docs> |

O **`CONTEXTO.md`** é o mais importante dos quatro. Ele registra o estado real do
projeto e as decisões que não dá para deduzir lendo o código — inclusive as
alternativas que já foram testadas e descartadas por medição. Antes de "melhorar"
alguma coisa que pareça estranha, procure lá: é provável que já tenha sido tentada.

---

## Como rodar

**Primeira vez no projeto?** O passo a passo completo — pré-requisitos,
configuração e o que fazer quando não sobe — está em
[`docs/COMECANDO.md`](docs/COMECANDO.md).

```powershell
cd ocr-extrator
.\iniciar.ps1            # desenvolvimento
.\iniciar.ps1 -SemAuth   # sem login, dispensa o Docker
.\iniciar.ps1 -Prod      # usa o build de produção do Next
```

Abra <http://localhost:3000>.

São **três processos**:

| | porta | o que é |
|---|---|---|
| API | `8100` | FastAPI + PaddleOCR (docs interativos em `/docs`) |
| Web | `3000` | Next.js |
| Transcrição | `8200` | Whisper, em processo próprio |

A API fica na 8100 em vez da óbvia 8000 porque esta costuma já estar ocupada na
máquina (WSL, outros projetos). A web usa a 3000, que é a padrão do Next — então
ela colide com qualquer outro projeto Next aberto; `-Porta 3100` troca sem
editar nada.

A transcrição roda separada do OCR de propósito: os dois modelos disputavam CPU
e o mesmo áudio que leva 3s isolado levava 227s dividindo processo.

Na primeira execução o PaddleOCR baixa os modelos (~100MB) para `~/.paddlex/official_models`.
A barra de status no topo da página mostra quando o modelo está pronto.

Para subir cada um manualmente:

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8100 --timeout-keep-alive 65
cd frontend; npm run dev
```

O `--timeout-keep-alive 65` importa: o padrão do uvicorn é 5s, curto demais para o pool
de conexões de um cliente HTTP moderno, que reusaria um socket já fechado do lado do
servidor e quebraria a requisição com `socket hang up` (ECONNRESET).

### Sem Node

`static/index.html` é a mesma interface em HTML/JS puro, servida pelo próprio FastAPI
em <http://127.0.0.1:8100>. Serve de plano B quando só o Python está disponível.

---

## Como o OCR decide

A parte mais densa do sistema, e a que mais surpreende quem chega: o que o
checklist mostra não é status marcado à mão, é consequência do que estas três
etapas concluíram sobre cada arquivo.

**1. Analisa a legibilidade da foto** (antes e depois do OCR)

| Métrica | Como é medida | Peso |
|---|---|---|
| `resolucao` | menor lado em pixels (mínimo 600px) | 1.0 |
| `nitidez` | variância do Laplaciano, normalizada para 1000px | 2.0 |
| `brilho` | média da luminância (faixa aceita: 55–240) | 1.0 |
| `contraste` | desvio padrão da luminância | 1.0 |
| `reflexo` | % de pixels estourados (flash no plástico) | 0.5 |
| `confianca_ocr` | confiança média devolvida pelo PaddleOCR | 2.5 |
| `texto_detectado` | nº de blocos e de caracteres lidos | 2.0 |

Cada métrica vira um score 0–100; a média ponderada é o **score de legibilidade**.
Abaixo de 55 (ou com confiança de OCR < 60%) a imagem é marcada como **ilegível**.

O teto de brilho é folgado de propósito: papel branco sobe a média legitimamente
(um scan de página passa de 230). Quem detecta superexposição de verdade é a métrica
de `reflexo`, que conta pixels estourados.

**2. Classifica o tipo do documento** por palavras-chave ponderadas:
CPF · RG · CIN · CNH · CTPS · Título de eleitor · Cartão SUS · Comprovante de residência · Certidão.
Você também pode forçar o tipo no seletor da interface.

**3. Extrai os campos** associando rótulo e valor **por geometria**, não por ordem de linha.

Documentos de identidade são diagramados em colunas — "FILIAÇÃO" à esquerda e "CAT. HAB."
à direita, na mesma altura. O agrupamento de caixas do OCR quebra em coluna nova quando o
espaço horizontal passa de ~2 alturas de linha, e a busca de valor olha as linhas
**logo abaixo que compartilham a mesma coluna**. Sem isso, "JOANA PEREIRA DA SILVA" sai
como "JOANA PEREIRA DA SILVA AB" e a data de validade recebe o valor da data de nascimento.

Cada campo é validado:

| Campo | Validação |
|---|---|
| CPF | dígitos verificadores (módulo 11) |
| CNPJ | dígitos verificadores |
| PIS/PASEP/NIT | dígito verificador |
| CNH (nº de registro) | algoritmo do Denatran |
| Título de eleitor | DVs + faixa de UF (01–28) |
| CNS (Cartão SUS) | módulo 11, definitivo e provisório |
| CEP | formato de 8 dígitos |
| Datas | data real + idade entre 0 e 120 anos |
| Nome, filiação, endereço | heurística — **sem** validação formal |

Também são extraídos sem validação formal: `nome_mae`, `nome_pai`, `naturalidade`,
`sexo`, `orgao_emissor`, `categoria_cnh`, `numero_ctps`, `serie_ctps`, `zona`, `secao`.

Nomes, RG e endereço não têm regra nacional de verificação — vêm marcados como
"confira manualmente" e o veredito nunca depende só deles.

**4. Emite um veredito**

| Veredito | Significado |
|---|---|
| `APROVADO` | tudo extraído e validado, e a foto não tem nenhuma ressalva de qualidade |
| `APROVADO_COM_RESSALVAS` | ou faltam campos, ou a foto tem problemas de qualidade |
| `REPROVADO` | ilegível ou nada extraído — peça uma nova foto |

Dois booleanos separam as duas perguntas:

- **`dados_utilizaveis`** — "posso usar esses dados?" (legível, nada faltando, nada reprovado no DV).
  É este que você consulta num fluxo automatizado.
- **`aprovado`** — `dados_utilizaveis` **e** foto sem nenhuma ressalva.

Uma foto escura que o OCR ainda assim leu perfeitamente sai como
`dados_utilizaveis: true` / `aprovado: false`, com o aviso de iluminação anexado.

Junto vêm `erros`, `avisos` e `sugestoes` (texto pronto para mostrar ao usuário,
tipo "Desligue o flash e evite luz direta sobre o plástico do documento").

**5. Grava JSON e XML temporários** em `tmp/`, expostos em `/api/temp/<id>.json|.xml`
e apagados automaticamente após 30 minutos.

---

## Status de cada item

| Status | Quando | O que acontece |
|---|---|---|
| `pendente` | nenhum arquivo enviado | entra no pedido ao cliente |
| `conferir` | chegou, mas ilegível ou com o tipo trocado | entra no pedido como "reenviar", com o motivo |
| `entregue` | chegou e passou na validação | sai do pedido |

Um item aceita **vários arquivos** (Atestados médicos costuma ter cinco) e basta um bom
para dar o item por entregue.

### Como o sistema pega arquivo trocado

Quando o item tem `tipo_ocr`, o classificador roda **por conta própria**, mesmo o
advogado tendo dito qual documento é aquele — se ele apenas confirmasse o palpite do
usuário, jamais acusaria uma CNH enviada no lugar do RG. O tipo informado orienta a
extração dos campos; o tipo detectado é o que vale para a conferência.

Por isso o JSON traz os dois: `tipo.codigo` (usado na extração) e `tipo.detectado`
(a leitura independente).

## Onde ficam os dados

| Caminho | O quê |
|---|---|
| `dados/casos.db` | SQLite: casos, entregas e o índice das assinaturas |
| `dados/casos/<id>/` | os arquivos que o cliente mandou |
| `dados/contratos/<id>.pdf` | contratos assinados, baixados da ZapSign |
| `dados/.portal-segredo` | assina as sessões do portal; sorteado no 1º boot |
| `~/.paddlex/official_models` | modelos do OCR (~100 MB), fora do projeto |

`dados/` está no `.gitignore` — **documento de cliente nunca vai para o repositório**.
Backup é copiar essa pasta; apagar um caso pela interface apaga os arquivos junto.

Os contratos assinados ficam **fora** de `dados/casos/` de propósito: o contrato é
assinado na entrevista, antes de o caso existir, e apagar um caso não pode levar
junto a via assinada.

Fora da máquina existe só um lugar: o **PostgreSQL com pgvector** dos precedentes
(52.926 trechos de processos públicos do TRT8, TST, DJEN e DEJT). Ele não guarda
nada de cliente — é consultado, não alimentado.

## Categorias e checklists

Cada tipo de ação tem um checklist de documentos a cobrar do cliente. Eles ficam em
[`app/categorias.py`](app/categorias.py), transcritos dos documentos que o escritório
manda em `.docx` (guardados em [`docs/`](docs/)).

Implementadas até agora:

| Categoria | Documentos | Obrigatórios |
|---|---|---|
| Acidente do Trabalho (Correios) | 33 | 14 |
| Ações de Acidente de Trabalho Geral | 35 | 22 |
| Doença Ocupacional | 37 | 23 |
| Assalto a Carteiro | 19 | 11 |
| Auxílio-Acidente | 11 | 5 |

No `.docx` original os obrigatórios estão **em vermelho**; na transcrição isso virou o
campo `obrigatorio`. O campo `tipo_ocr` liga o item ao classificador de documentos —
quando preenchido (RG, CPF, comprovante de residência, CTPS), o sistema confere sozinho
se o arquivo enviado é mesmo o documento pedido.

### Transcrever um checklist novo

```powershell
.\.venv\Scripts\python.exe -m tests.ler_checklist_docx "docs\CHECK LIST ....docx"
```

Ele imprime cada linha marcando `[X]` para os itens em vermelho. Transcreva o resultado
para uma nova `Categoria` em `app/categorias.py` e rode `tests.test_categorias`, que
compara a lista do código com o `.docx` item a item — nome, numeração e obrigatoriedade.

## API

Lista completa e interativa em <http://127.0.0.1:8100/docs>. O que segue é o mapa
por assunto.

**Tudo exige token do Keycloak**, exceto: `/`, `/api/saude`, `/api/config`,
`/api/chamada/config`, e o prefixo `/api/portal/` — este protegido pela senha do
caso, porque o cliente não tem conta. A lista é de exceções de propósito: rota
nova nasce fechada (ver `PUBLICAS` em `main.py`).

**Entrevista**

| Método | Rota | Descrição |
|---|---|---|
| `GET` | `/api/roteiros` · `/api/roteiros/{codigo}` | as perguntas, na ordem do escritório |
| `POST` | `/api/triagem` | sugere a categoria a partir do relato. Não cria caso |
| `POST` | `/api/entrevista/analise` | o que ESTA resposta não trouxe, com precedentes |
| `POST` | `/api/estrategia` | parecer do caso inteiro: ações, riscos e lacunas |
| `GET` | `/api/cep/{cep}` | endereço a partir do CEP (BrasilAPI, ViaCEP de reserva) |

**Contrato e assinatura**

| Método | Rota | Descrição |
|---|---|---|
| `POST` | `/api/contrato` | preenche o modelo oficial e devolve o `.docx` |
| `GET` | `/api/contrato/campos` | marcadores do modelo e os que a entrevista não responde |
| `GET` | `/api/assinatura/config` | se o envio para assinatura está ligado |
| `POST` | `/api/contrato/assinatura` | gera e manda assinar (ZapSign) |
| `GET` | `/api/assinaturas` · `/api/assinaturas/{id}` | quem assinou e quem falta |
| `GET` | `/api/assinaturas/{id}/arquivo` | o PDF assinado, com trilha de auditoria |

**Casos, checklist e documentos**

| Método | Rota | Descrição |
|---|---|---|
| `GET` | `/api/categorias` · `/api/categorias/{codigo}` | categorias e seus checklists |
| `POST` `GET` | `/api/casos` | cria (`cliente`, `categoria`) e lista |
| `GET` `PATCH` `DELETE` | `/api/casos/{id}` | checklist com status; renomear; apagar caso **e arquivos** |
| `GET` | `/api/casos/{id}/pedido` | texto pronto para mandar ao cliente |
| `POST` | `/api/casos/{id}/documentos` | envia um documento para um item |
| `POST` | `/api/casos/{id}/identidade-unificada` | uma CNH/CIN vale por RG **e** CPF |
| `GET` `DELETE` | `/api/entregas/{id}` | a entrega com a extração; remover |
| `GET` | `/api/entregas/{id}/arquivo` | baixa o arquivo enviado |
| `POST` | `/api/extrair` | análise avulsa: `arquivo`, `idioma`, `tipo` |
| `GET` | `/api/tipos` | tipos de documento suportados |

**Portal do cliente** — sem Keycloak; protegido pela senha do caso

| Método | Rota | Descrição |
|---|---|---|
| `POST` | `/api/casos/{id}/portal` | gera link e senha. A senha aparece **uma vez** |
| `POST` | `/api/portal/{token}/entrar` | o cliente entra com a senha |
| `GET` | `/api/portal/{token}/situacao` | o que ele vê: o que falta, sem os alertas internos |
| `POST` | `/api/portal/{token}/documentos` | o cliente envia um arquivo |

**Serviço**

| Método | Rota | Descrição |
|---|---|---|
| `GET` | `/api/saude` · `/api/config` · `/api/eu` | status do modelo, config do Keycloak, quem está autenticado |
| `POST` | `/api/aquecer` | pré-carrega os modelos de OCR |
| `POST` | `/api/chamada/sala` | sorteia uma sala de chamada e devolve o link |
| `GET` `DELETE` | `/api/temp/{nome}` · `/api/temp` | JSON/XML temporários da análise avulsa |

A transcrição fica em **outro processo**, na porta 8200:
`WS /ws/transcricao` recebe PCM e devolve o texto parcial e o final.

```powershell
curl.exe -F "arquivo=@meu_rg.jpg" -F "tipo=auto" http://127.0.0.1:8100/api/extrair
```

### Por que o navegador chama a API direto

O caminho óbvio seria proxiar `/api` do Next para o Python com `rewrites`. Não dá:

- o proxy do Next **derruba a conexão em 30s**, e é um timeout fixo, sem opção de
  configuração — mas uma foto de celular leva de 3 a 30s para OCR;
- ele **bufferiza o upload inteiro na memória do Node**, e acima de
  `proxyClientMaxBodySize` (10MB por padrão) **trunca o corpo em silêncio** em vez de
  rejeitar: o backend receberia uma imagem corrompida sem ninguém perceber.

Então o frontend fala direto com o FastAPI (`lib/api.ts`), que habilita CORS. Para
apontar para outro host, defina `NEXT_PUBLIC_OCR_API`.

### Resposta (resumida)

```json
{
  "id": "3f2b...",
  "tipo": { "codigo": "cnh", "descricao": "CNH (Carteira Nacional de Habilitação)" },
  "campos": [
    { "nome": "cpf", "rotulo": "CPF", "valor": "111.444.777-35",
      "confianca": 0.97, "valido": true, "observacao": "Dígitos verificadores conferem." }
  ],
  "validacao": {
    "veredito": "APROVADO", "aprovado": true, "imagem_legivel": true,
    "score_legibilidade": 88, "completude_percentual": 100,
    "campos_faltando": [], "erros": [], "avisos": [], "sugestoes": []
  },
  "qualidade_imagem": { "score_legibilidade": 88, "legivel": true, "metricas": [...] },
  "texto_linhas": [ { "texto": "...", "confianca": 0.98 } ],
  "arquivos_temporarios": { "json": "/api/temp/3f2b....json", "xml": "/api/temp/3f2b....xml" }
}
```

---

## Testes

**Não há `pytest`.** Cada arquivo é um script que roda sozinho e imprime
PASS/FALHA, com a explicação do que cada asserção protege.

```powershell
$py = ".\.venv\Scripts\python.exe"
& $py -m tests.test_validators       # dígitos verificadores
& $py -m tests.test_categorias       # checklist do código vs. o .docx do escritório
& $py -m tests.test_casos            # fluxo do caso (banco temporário)
& $py -m tests.test_contrato         # cláusulas intactas, .docx que o Word abre
& $py -m tests.test_assinatura       # ZapSign dublada: papéis, estados, download
& $py -m tests.test_analise_resposta # conferência: formato, disjuntor, prazos
& $py -m tests.test_transcricao      # janela do texto ao vivo (sem Whisper)
& $py -m tests.test_roteiros         # roteiro como a tela o recebe
& $py -m tests.test_consultas        # CEP -> endereço (sem rede)
& $py -m tests.test_pdf              # PDF -> imagem
& $py -m tests.test_uploads_api      # limites e recusas do upload
& $py -m tests.test_rag              # recuperação de precedentes
& $py -m tests.test_chamada          # sinalização WebRTC (ver ressalva abaixo)
& $py -m tests.test_pipeline         # end-to-end com documentos sintéticos
& $py -m tests.test_concorrencia     # 3 OCRs simultâneos
```

Nenhum toca serviço externo: DeepSeek, ZapSign e pgvector entram dublados. Rodam
offline e não gastam crédito.

Frontend: `cd frontend; npm run typecheck; npm run build`.

Ferramentas, não testes:

```powershell
& $py -m tests.avaliar_triagem 4        # mede a triagem com relatos gerados por LLM
& $py -m tests.ler_checklist_docx "docs\CHECK LIST ....docx"
& $py -m tests.bench                    # custo do classificador de orientação
& $py -m scripts.estado_rag             # estado do banco vetorial
```

Rode os testes com o servidor **parado**: dois processos Paddle disputando os mesmos
núcleos inflam os tempos em até 10× e confundem a leitura dos resultados.

Duas ressalvas conhecidas, para não perder tempo achando que é o seu ambiente:

- **`test_roteiros` falha com 401** quando o Keycloak está no ar — ele chama rota
  protegida sem token.
- **`test_chamada` cobre a sinalização WebRTC própria**, que o Jitsi substituiu.
  O código continua lá e passa, mas nenhuma tela o usa mais.

O teste de pipeline gera documentos falsos em `tests/amostras/` — CNH, CTPS, cartão CPF
e título de eleitor, mais versões **deitada (90°), borrada, escura e ruído puro** — e
confere valor a valor: tipo detectado, cada campo esperado, campos que **não** podem
aparecer, e se as imagens ruins são reprovadas.

As asserções de valor exato existem para travar regressões reais já encontradas: o nome
da mãe vindo contaminado com a categoria da coluna vizinha, e o nº de registro da CNH
(que também passa no dígito verificador do PIS) sendo publicado como PIS.

---

## Estrutura

```
app/                     backend (FastAPI)
  main.py                rotas; middleware de auth por allowlist
  auth.py                valida o JWT do Keycloak. Vazio = autenticação desligada
  ── entrevista
  roteiros.py            as perguntas, os blocos e o roteamento por rastreio
  transcricao.py         janela do texto ao vivo; sessões de resposta
  servico_transcricao.py o Whisper num processo PRÓPRIO (porta 8200)
  triagem.py             classifica o relato (LLM + fallback local por termos)
  analise_resposta.py    o que cada resposta não trouxe, com precedentes
  rag.py                 busca vetorial em pgvector e o parecer do caso
  consultas.py           bases públicas que adiantam a entrevista (só CEP)
  ── contrato
  contrato.py            preenche o .docx do escritório. Não redige cláusula
  assinatura.py          assinatura eletrônica (ZapSign) e quem já assinou
  ── caso e documentos
  categorias.py          categorias de processo e seus checklists
  casos.py               status de cada item e o texto do pedido ao cliente
  armazenamento.py       SQLite: casos, entregas, assinaturas, arquivos em disco
  portal.py              senha e sessão do portal do cliente
  pipeline.py            orquestra OCR -> campos -> validação -> JSON/XML
  ocr_engine.py          wrapper do PaddleOCR, thread dedicada
  extractors.py          classificação do tipo, geometria da página e extração
  validators.py          dígitos verificadores dos documentos brasileiros
  quality.py             métricas de legibilidade e pré-processamento
  pdf.py                 renderiza PDF para imagem antes do OCR
  chamada.py             sorteia a sala da chamada

frontend/                Next.js 16 (App Router) + React 19
  app/page.tsx           Carteira · Checklist · análise avulsa
  app/portal/[token]/    o que o cliente vê para mandar documentos
  app/chamada/[sala]/    o que o cliente vê para entrar na chamada
  components/
    TriagemEntrevista    entrada da entrevista e da triagem
    EntrevistaComChamada roteiro à esquerda, chamada à direita
    Roteiro.tsx          conduz as perguntas, grava e transcreve
    ConferenciaResposta  o que faltou nesta resposta
    PainelContrato.tsx   gera o contrato e acompanha a assinatura
    Carteira · Checklist · ItemChecklistLinha · PedidoCliente · Resultado
    Retratos.tsx         os participantes da chamada
  lib/api.ts             cliente HTTP do backend
  lib/transcricao.ts     captura de áudio e streaming para o Whisper
  lib/chamadaJitsi.ts    a chamada sobre lib-jitsi-meet
  lib/types.ts           espelho tipado do JSON da API

scripts/                 rodados à mão, com `python -m scripts.<nome>`
  estado_rag.py          diagnóstico do banco vetorial
  ingerir_jurimetria.py  importa processos do TRT8/TST/DJEN/DEJT
  vetorizar_pendentes.py preenche os embeddings em lotes retomáveis
sql/                     migrações do pgvector, aplicadas em ordem
docs/                    guias, checklists do escritório e o contrato oficial
tests/                   cada arquivo roda sozinho e imprime PASS/FALHA
dados/                   SQLite + arquivos dos clientes — FORA do git
tmp/                     JSON/XML temporários da análise avulsa (TTL 30 min)
static/index.html        mesma UI em HTML puro (plano B sem Node)
```

---

## Concorrência

O predictor nativo do Paddle tem **afinidade de thread**: usá-lo a partir de threads
diferentes derruba a inferência com `RuntimeError: Unknown exception`, mesmo quando as
chamadas são serializadas por um lock. Por isso toda a inferência roda numa **única
thread dedicada** (`ThreadPoolExecutor(max_workers=1)` em `ocr_engine.py`), que constrói
o modelo e é dona dele pelo resto da vida do processo.

Uploads simultâneos entram numa fila — o que é o comportamento desejado num servidor de
CPU, já que rodar dois OCRs ao mesmo tempo só deixaria os dois mais lentos. O endpoint
`/api/extrair` usa `run_in_threadpool`, então o event loop continua livre e o servidor
responde a outras rotas enquanto processa.

`tests/test_concorrencia.py` cobre esse caso: 3 threads disparando OCR ao mesmo tempo.

## Desempenho

Medido em CPU, imagem de 1000×640 (`tests/bench.py`):

| | por imagem |
|---|---|
| OCR sem classificador de orientação | ~2,4s |
| OCR com `use_doc_orientation_classify` | ~2,8s |

O classificador de orientação custa ~0,4s e é o que permite ler foto deitada
corretamente, então compensa. A primeira chamada do processo carrega os modelos
(~3s a mais) — use `POST /api/aquecer` para tirar isso do caminho do primeiro upload.

## Limitações conhecidas

- **O contrato é preenchido, não redigido.** As cláusulas, percentuais, foro e as
  inscrições na OAB saem do `docs/CONTRATO*.docx` palavra por palavra — nenhum
  modelo de linguagem escreve nada ali. Trocar de versão é soltar o arquivo novo
  em `docs/`; o mais recente vence. Campo que a entrevista não respondeu sai
  entre colchetes, à vista, em vez de em branco.
- **O modelo do contrato não está no repositório.** Este repo é público, e o
  arquivo traz a tabela de honorários, o CNPJ e as inscrições na OAB do
  escritório. Para gerar contratos, copie o `.docx` oficial para `docs/` — sem
  ele, a rota `/api/contrato` responde 503 com a explicação e o
  `tests.test_contrato` pula a parte que depende do arquivo.

- **A assinatura eletrônica gasta documento de verdade.** Não há sandbox
  configurado: cada envio consome uma unidade do plano ZapSign e manda e-mail
  real para o endereço que estiver na entrevista. Testando, use um e-mail seu.
- **A conferência da resposta depende de um banco remoto e instável.** Quando ele
  não responde, a análise ainda sai, mas **marcada** como "sem precedentes" — e aí
  ela é a leitura do modelo sobre o texto, não o que os processos semelhantes
  mostram. As duas coisas não podem ser lidas como iguais. `python -m
  scripts.estado_rag` diz de qual das três causas se trata.
- **A conferência é assistiva, e assistiva de um ponto só.** Ela olha UMA
  resposta, não o caso; não conhece prazo, não faz juízo de mérito e não substitui
  a leitura do advogado. Precedente citado é ponto de partida para conferir, não
  fundamento pronto para petição.
- **A transcrição sai do microfone da máquina**, que capta a sala inteira —
  inclusive o entrevistador. Houve uma versão em que a voz do cliente vinha
  isolada pela chamada; ela chegava muda e foi desligada. O porquê está no
  cabeçalho de `Roteiro.tsx`.
- **Só o CEP é preenchido por base pública.** CPF não vira nome: a consulta
  oficial é da Receita Federal, exige certificado digital e convênio, e os sites
  que prometem isso de graça vendem base vazada — usar um deles põe o escritório
  do lado errado da LGPD. Com o CPF dá para conferir o dígito verificador, o que
  já pega o erro de digitação. PIS/NIT também não: o CNIS é do INSS e pede o
  gov.br do próprio cliente.
- **O texto ao vivo é aproximação.** O parcial transcreve só a cauda da fala, com
  menos contexto que o texto final — que é refeito sobre o áudio inteiro quando a
  resposta fecha. Divergências entre o que apareceu enquanto se falava e o texto
  final são esperadas; o registro é o final.

- **A chamada depende do stack do Jitsi no ar.** São quatro contêineres (web,
  prosody, jicofo, videobridge) que ficam de pé entre execuções, como o Keycloak.
  Sem eles, a tela avisa e a entrevista presencial (microfone da máquina) continua
  funcionando. Subir: `cd docker-jitsi-meet; docker compose up -d`.
- **O cliente precisa de HTTPS** para o navegador liberar o microfone. Em `localhost`
  funciona; num IP de rede local sem TLS, o `getUserMedia` nem existe. Publicar o
  portal por trás de um certificado é pré-requisito da chamada, não detalhe de
  produção.

- **PDFs de até 10 páginas** são aceitos e renderizados localmente para OCR (limite de 20MB por arquivo).
  PDFs protegidos por senha, corrompidos ou grandes demais para conversão precisam ser divididos ou exportados como imagem.
- **Nome, RG e endereço** saem por heurística de layout; a taxa de acerto cai em
  documentos com fundo estampado ou fonte estilizada.
- A **CNH digital e o CIN têm QR Code / MRZ** com os dados assinados digitalmente —
  este projeto lê só o texto impresso, sem verificar a autenticidade do documento.
- **Validar o DV não prova que o documento é verdadeiro**: um CPF inventado que
  passe no módulo 11 é aceito. Para conferir se o CPF existe e a quem pertence é
  preciso consultar a Receita Federal.
- Fotos **inclinadas** (não ortogonais) podem falhar. Rotações de 90/180/270 são
  tratadas: o PaddleOCR endireita a página com `use_doc_orientation_classify`, e o
  pipeline ainda testa as quatro rotações como rede de segurança quando a leitura
  inicial rende pouco texto.
