# Extrator de Documentos — PaddleOCR

Lê fotos de documentos brasileiros, extrai os campos, gera **JSON e XML temporários**
e **valida** se a extração é confiável e se a foto é legível.

Roda 100% na sua máquina — nenhuma imagem sai do computador.

**Stack:** FastAPI + PaddleOCR no backend, Next.js 16 + React 19 no frontend.

---

## Como rodar

```powershell
cd ocr-extrator
.\iniciar.ps1          # desenvolvimento
.\iniciar.ps1 -Prod    # usa o build de produção do Next
```

Abra <http://localhost:3100>.

São **dois processos**:

| | porta | o que é |
|---|---|---|
| API | `8100` | FastAPI + PaddleOCR (docs interativos em `/docs`) |
| Web | `3100` | Next.js |

Portas 8100/3100 em vez das óbvias 8000/3000 porque estas costumam já estar
ocupadas na máquina (WSL, outros projetos Next).

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

## O que ele faz

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

## API

| Método | Rota | Descrição |
|---|---|---|
| `GET` | `/` | interface web |
| `POST` | `/api/extrair` | multipart: `arquivo`, `idioma` (`pt`), `tipo` (`auto` ou código) |
| `GET` | `/api/tipos` | tipos de documento suportados |
| `GET` | `/api/saude` | status do modelo |
| `POST` | `/api/aquecer` | pré-carrega os modelos |
| `GET` | `/api/temp/{id}.json\|.xml` | baixa o arquivo temporário |
| `DELETE` | `/api/temp` | limpa os temporários expirados |

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

```powershell
.\.venv\Scripts\python.exe -m tests.test_validators     # dígitos verificadores
.\.venv\Scripts\python.exe -m tests.test_pipeline       # end-to-end com documentos sintéticos
.\.venv\Scripts\python.exe -m tests.test_concorrencia   # 3 OCRs simultâneos
.\.venv\Scripts\python.exe -m tests.bench               # custo do classificador de orientação
```

Rode os testes com o servidor **parado**: dois processos Paddle disputando os mesmos
núcleos inflam os tempos em até 10× e confundem a leitura dos resultados.

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
app/                     backend
  main.py                API FastAPI e rotas
  pipeline.py            orquestra OCR -> campos -> validação -> JSON/XML
  ocr_engine.py          wrapper do PaddleOCR, thread dedicada, colunas -> linhas
  extractors.py          classificação do tipo, geometria da página e extração
  validators.py          dígitos verificadores dos documentos brasileiros
  quality.py             métricas de legibilidade e pré-processamento
frontend/                Next.js 16 (App Router) + React 19
  app/page.tsx           página única, orquestra os componentes
  components/            painéis do resultado (campos, validação, qualidade, JSON/XML)
  lib/api.ts             cliente HTTP do backend
  lib/types.ts           espelho tipado do JSON de /api/extrair
  lib/useExtracao.ts     estado do upload, do modelo e dos tipos
static/index.html        mesma UI em HTML puro, servida pelo FastAPI (plano B sem Node)
tests/                   validadores, end-to-end, concorrência e benchmark
tmp/                     JSON/XML temporários (TTL 30 min)
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

- **Somente imagens** — PDF não é aceito (converta para JPG/PNG antes).
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
