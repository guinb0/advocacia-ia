# Documentos do Cliente

Ajuda o advogado a **cobrar documentos do cliente**: escolhe a categoria da ação, o
sistema mostra o checklist, marca o que já chegou, confere a legibilidade de cada foto
e gera a mensagem pronta com o que ainda falta.

Roda 100% na sua máquina — nenhuma imagem sai do computador.

**Stack:** FastAPI + PaddleOCR no backend, Next.js 16 + React 19 no frontend, SQLite.

## O fluxo

1. **Criar o caso** — nome do cliente + categoria (ex.: Acidente do Trabalho / Correios).
2. **Copiar o pedido** e mandar no WhatsApp: a lista dos 14 obrigatórios, com dicas de
   como tirar a foto.
3. **Enviar cada documento** que o cliente responder, no item correspondente. O OCR lê,
   valida os dígitos verificadores e mede a legibilidade.
4. **O checklist se atualiza sozinho.** Se a foto veio ilegível ou o cliente mandou o
   arquivo errado, o item fica em "conferir" e entra no próximo pedido, com o motivo.

Nada de status marcado à mão: tudo é derivado dos arquivos entregues.

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
| `dados/casos.db` | SQLite com os casos e as entregas |
| `dados/casos/<id>/` | os arquivos que o cliente mandou |

`dados/` está no `.gitignore` — **documento de cliente nunca vai para o repositório**.
Backup é copiar essa pasta; apagar um caso pela interface apaga os arquivos junto.

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

| Método | Rota | Descrição |
|---|---|---|
| `GET` | `/` | interface web |
| `GET` | `/api/categorias` | categorias com seus checklists |
| `GET` | `/api/categorias/{codigo}` | uma categoria |
| `POST` | `/api/casos` | cria o caso (`cliente`, `categoria`) |
| `GET` | `/api/casos` | lista os casos |
| `GET` | `/api/casos/{id}` | checklist com o status de cada item e o progresso |
| `PATCH` | `/api/casos/{id}` | renomeia o cliente / muda a observação |
| `DELETE` | `/api/casos/{id}` | apaga o caso e **todos** os arquivos dele |
| `GET` | `/api/casos/{id}/pedido` | texto pronto para mandar ao cliente |
| `POST` | `/api/casos/{id}/documentos` | envia um documento para um item (`item`, `arquivo`) |
| `GET` | `/api/entregas/{id}` | uma entrega, com a extração completa |
| `GET` | `/api/entregas/{id}/arquivo` | baixa o arquivo enviado |
| `DELETE` | `/api/entregas/{id}` | remove a entrega e o arquivo |
| `POST` | `/api/extrair` | multipart: `arquivo`, `idioma` (`pt`), `tipo` (`auto` ou código) |
| `GET` | `/api/tipos` | tipos de documento suportados |
| `POST` | `/api/contrato` | preenche o modelo oficial com a entrevista e devolve o .docx |
| `GET` | `/api/contrato/campos` | marcadores que o modelo pede, e quais a entrevista não responde |
| `GET` | `/api/cep/{cep}` | endereço a partir do CEP (BrasilAPI, com ViaCEP de reserva) |
| `GET` | `/api/chamada/config` | servidores ICE da chamada de voz (público) |
| `WS` | `/ws/chamada/{sala}?papel=` | sinalização WebRTC; `sala` é o token do portal |
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
.\.venv\Scripts\python.exe -m tests.test_categorias     # checklist do código vs. o .docx
.\.venv\Scripts\python.exe -m tests.test_casos          # fluxo do caso (banco temporário)
.\.venv\Scripts\python.exe -m tests.test_chamada        # sinalização da chamada de voz
.\.venv\Scripts\python.exe -m tests.test_transcricao    # janela do texto ao vivo (sem Whisper)
.\.venv\Scripts\python.exe -m tests.test_consultas      # CEP -> endereço (sem rede)
.\.venv\Scripts\python.exe -m tests.test_roteiros       # roteiro como a tela o recebe
.\.venv\Scripts\python.exe -m tests.test_contrato       # contrato: cláusulas intactas, .docx válido
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
  categorias.py          categorias de processo e seus checklists de documentos
  armazenamento.py       SQLite: casos, entregas e os arquivos em disco
  casos.py               status de cada item e o texto do pedido ao cliente
  pipeline.py            orquestra OCR -> campos -> validação -> JSON/XML
  ocr_engine.py          wrapper do PaddleOCR, thread dedicada, colunas -> linhas
  extractors.py          classificação do tipo, geometria da página e extração
  validators.py          dígitos verificadores dos documentos brasileiros
  quality.py             métricas de legibilidade e pré-processamento
  chamada.py             salas da chamada de voz: repassa SDP/ICE, não toca no áudio
  consultas.py           bases públicas que adiantam a entrevista (CEP)
  contrato.py            preenche o .docx de honorários do escritório
docs/                    modelos do escritório: checklists e o contrato oficial
  transcricao.py         janela do texto ao vivo e o Whisper (processo à parte)
frontend/                Next.js 16 (App Router) + React 19
  app/page.tsx           alterna entre a lista de casos, o checklist e a análise avulsa
  components/
    ListaCasos.tsx       criar caso e escolher qual abrir
    Checklist.tsx        progresso, filtros e a lista de itens
    ItemChecklistLinha   um item: status, envio e as entregas já feitas
    PedidoCliente.tsx    o texto para mandar ao cliente, com botão de copiar
    Resultado.tsx        painéis da análise avulsa (campos, qualidade, JSON/XML)
    ChamadaAoVivo.tsx    chamada com o cliente e a transcrição da voz dele
  lib/api.ts             cliente HTTP do backend
  lib/chamadaJitsi.ts    chamada sobre lib-jitsi-meet e a faixa do entrevistado
  lib/transcricao.ts     captura de áudio e streaming para o Whisper
  lib/types.ts           espelho tipado do JSON da API
  lib/useCasos.ts        estado dos casos, do checklist e dos envios
  lib/useExtracao.ts     estado da análise avulsa
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
