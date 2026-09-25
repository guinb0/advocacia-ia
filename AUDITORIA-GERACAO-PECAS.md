# Auditoria da geração de petições

Caso de teste: `d62366d7…` (o mesmo que gerou `Peticao inicial - v2 (2).pdf`).
Referência qualitativa: `RASCUNHO - Peticao Inicial - Paulo Sergio Leandro Burcaos x ECT.pdf`.
Toda afirmação abaixo vem do código, do trace gravado no banco ou de uma chamada real feita durante a auditoria.

## 1. Pipeline encontrado (o que executa em runtime)

`Frontend (Dossiê → "Gerar")` → rota assíncrona em `app/main.py` (thread de fundo no serviço `api`, sem worker) → `app/agente/peticao_fluxo.gerar_completo` → `peticao_local.gerar`:

1. `_montar_contexto`: identidade, entrevista (até 55 mil chars), `case_brief` (análise dos documentos), OCR de até 20 documentos, checklist.
2. `case_brief.montar` → `analise_documentos.analisar` (modelo `google/gemini-3.7-flash` via OpenRouter).
3. Retrieval: julgados (`jurimetria_caso` → pgvector), legislação (`rag.buscar_legislacao`), peças do acervo (`rag.buscar_pecas_conteudisticas`). Todos começam por uma chamada de embeddings.
4. `_outline_juridico` (planejamento) → **uma** chamada de redação ao `deepseek-chat` com `CONTRATO_DE_REDACAO` + skill + contexto, devolvendo as 8 seções em JSON.
5. Pós: aprofundamento pela referência (novo) → conferência contra os autos → validação contra brief e skill → DOCX.

## 2. Causa raiz

Não foi uma causa única. O trace da peça v2 (gravado às 21:32, seis minutos depois do deploy do meu código, portanto código novo em execução) mostra três falhas independentes, todas silenciosas:

| Evidência no trace do v2 | Causa |
|---|---|
| `case_brief`: 0 fatos, 0 eventos, 58 documentos | A análise de documentos **falhava sempre**: o commit `ade7dba` manda `reasoning: {"effort":"none"}` ao `gemini-3.7-flash` e o OpenRouter responde `400 "Reasoning is mandatory for this endpoint and cannot be disabled"`. A mensagem exibida era "o modelo não respondeu a tempo". |
| `precedentes/legislacao/pecas_modelo = False`, `referencias_do_acervo = []` | O retrieval falhou nos três canais em produção (o mesmo pipeline funciona na minha máquina). O motivo **não era registrado**. Causa exata em produção ainda não confirmada — ver §11. |
| 2.084 palavras, sem prescrição, "Juízo 100% Digital", Gratuidade duas vezes, "Das Provas" | Estrutura ditada por texto fixo (código e banco) que competia com a skill — ver §6. |

## 3. Por que a skill não surtia o efeito esperado

A skill de arquivo **estava** chegando (`orientacao_do_escritorio: True`). O problema era de precedência:

- O prompt acrescentava, **depois** da skill, uma "skill GERAL" gravada no Postgres (`peticao_skills`, 2.526 chars, "extraída de 85 iniciais") que fixa outra estrutura: Juízo 100% Digital e Gratuidade obrigatórios, "Das Provas", honorários como seção própria, títulos em CAIXA ALTA. Para o modelo, o que vem por último pesa mais: a estrutura antiga vencia a nova.
- `CONTRATO_DE_REDACAO` dizia "Sua prioridade NÃO é produzir texto longo", contradizendo a regra de ouro da skill ("nunca entregar petição resumida ou enxuta").
- O bloco "PADRÃO OBRIGATÓRIO" em `gerar()` repetia a estrutura antiga.

Comparação com a skill (`estrutura_peca.md`, `regras_redacao.md`): o v2 não trata prescrição (obrigatória), não tem subcapítulos, tem "Das Provas" (a skill e o rascunho não têm), e a Gratuidade aparece na preliminar e de novo como capítulo VIII.

## 4. Como as ~800 peças estavam sendo usadas

- 803 registros em `pecas_conteudo` (200 simples, 597 complexas, 6 sem categoria), 795 com texto útil.
- `metadados` só tinha `{origem, caminho_original, extensao}`: **nenhuma** dimensão jurídica.
- Recuperação: similaridade vetorial do texto do caso contra o acervo inteiro, top 8 chunks, cortados em 1.000 dos 1.800 caracteres → ~8 mil chars por geração.
- Em produção, no v2: **zero** peças chegaram ao modelo (`referencias_do_acervo = []`).

## 5. Problemas encontrados no retrieval

1. Falha silenciosa: só um booleano, sem motivo.
2. Sem dimensão de assunto/tipo: 4 das 6 primeiras peças recuperadas eram **impugnações à contestação**, e depois 5 de 8 eram **quesitos de perícia**.
3. Corte de 1.000 chars por chunk.
4. Sem meta de profundidade derivada do acervo.
5. Não existe reranker (cross-encoder). Ordenação atual: assunto → tipo inicial → distância vetorial. Ver §11.

## 6. Hardcodes encontrados → responsabilidade correta

| Hardcode | Onde | Responsabilidade correta | Ação |
|---|---|---|---|
| "prioridade NÃO é texto longo" | `CONTRATO_DE_REDACAO` | skill (regra de ouro) | reescrito para seguir a skill |
| Juízo 100% Digital + Gratuidade obrigatórios, CAIXA ALTA, capítulo "Das Provas" | bloco "PADRÃO OBRIGATÓRIO" em `gerar()` | skill (`estrutura_peca.md`) + acervo | substituído por "onde cada coisa entra no JSON"; skill vence em conflito; prescrição sempre tratada; capítulos numerados |
| Estrutura antiga | skill GERAL no Postgres | skill de arquivo | anexada **antes** e rotulada como complementar; **conteúdo não alterado** (§11) |
| Margens 3,74/1,89/1,25/3,0 e `FONTE_PADRAO = "Times New Roman"` | `peticao_local.py` | `formatacao.md` | extraídos da skill por regex; a skill manda até sobre o modelo visual enviado. Conferido no PDF de referência: fonte `LiberationSans` (Arial) |
| Seção `EVIDENCE` e lista fixa de 8 códigos de seção | `SECOES_PADRAO`, schema JSON | skill | **não alterado** (§11) |

## 7. Alterações realizadas

- `analise_documentos.py`: `reasoning: {effort: low, exclude: true}`, retry sem o parâmetro em caso de 400 de reasoning, erro com o status e corpo reais.
- `case_brief.py`: campo `analise_erro`; `case_brief_estado.py` (estado humano do insight, já existente).
- `peticao_local.py`: diagnóstico por canal (`_DIAG`), `trace.pipeline` (skill/hash/tokens/contagens/fallbacks/modelo), log de erro em cada fallback, validador não roda contra brief vazio, aprofundamento pela referência, precedência skill > orientação cadastrada, prompts sem os hardcodes acima, chunk do acervo de 1.000 → 1.800 chars.
- `rag.py`: preferência por peça do mesmo assunto **e** do tipo petição inicial (`metadados.tipo_peca`, com heurística de nome como reserva); devolve `chars_peca`.
- `scripts/classificar_pecas.py`: passa a classificar `tipo_peca`; `--chave tipo_peca` completa só o que falta.
- `peticao_skill_arquivos.py`: `resumo()` (arquivos, assunto, hash, tamanho) e formatação vinda de `formatacao.md`.
- `main.py`: `GET /api/diagnostico/geracao?caso_id=…`.

## 8. Arquitetura final

`caso + documentos + entrevista` → `case_brief` (fatos/eventos com fonte; estado humano por cima) → `skill de arquivo (assunto detectado)` → retrieval (assunto → tipo inicial → similaridade) → outline → redação → **aprofundamento** (meta = mediana das iniciais recuperadas ÷ 6,2 chars/palavra; só roda se a peça ficar < 80%) → conferência contra os autos → validação contra brief e skill → DOCX. O código orquestra o contexto; estrutura, ordem de capítulos e formato vêm da skill e do acervo.

## 9. Evidências

Execução real no caso de teste (`trace.pipeline` da versão 5):

```
skill: escritorio-trabalhista | arquivos: estrutura_peca, regras_redacao, regras_complementares,
       citacoes_juridicas, doenca_ocupacional_acidente_trabalho | sha256: 4c9ab66d427e7ae2 | 19.804 chars
documentos do caso: 58 | fatos no brief: 7 | eventos: 5
recuperação: precedentes n=15 ok | legislação n=14 ok | peças n=8, mesmo_assunto=8, chars_injetados≈13,4 mil
tokens (aprox.): caso 14,8k | skill 5,0k | acervo 3,8k | precedentes 6,7k | legislação 5,0k | outline 3,5k
modelo: deepseek-chat | fallback acionado: não
aprofundamento: alvo 6.904 palavras | 3.150 → 4.327 palavras
cobertura: 6/6 fatos e 5/5 eventos do brief presentes na peça | validação: 0 problemas
```

Para provar o retrieval de uma geração: `trace.pipeline.recuperacao.pecas` lista `arquivos`, `scores`, `mesmo_assunto` e `chars_injetados`; o `trace.case_brief.source_map` liga cada fato ao documento e trecho.

## 10. Antes / referência / depois

| | v2 (antes) | Rascunho (referência) | Versão 5 (depois) |
|---|---|---|---|
| Palavras | 2.084 | 5.368 | 4.522 |
| Páginas (PDF) | 9 | 15 | — (DOCX não convertido) |
| Fatos | 387 palavras, sem subcapítulos | 4 subcapítulos | 927 palavras, 8 subcapítulos numerados |
| Direito | 1 bloco, 5.763 chars | 9 subcapítulos | 8 subcapítulos, 2.297 palavras |
| Prescrição | ausente | III.1 | I – DA PRESCRIÇÃO |
| Brief | 0 fatos | — | 7 fatos, 5 eventos, 100% usados |
| Acervo no prompt | 0 peças | — | 8 peças iniciais do assunto |
| Fallback | silencioso | — | nenhum, e registrado |
| "Das Provas" / Gratuidade duplicada / 100% Digital | sim / sim / sim | não / não / não | sim (só Provas e 100% Digital) / não / sim |

Avaliação honesta: a profundidade factual e o encadeamento fato → prova → tese melhoraram de forma clara (mais que o dobro de palavras, cronologia completa, prescrição tratada, 100% dos fatos usados). Ainda **não** iguala o rascunho: 84% do tamanho, sem a subdivisão fina do Direito (III.1–III.9), e o texto ainda traz "Juízo 100% Digital" e "Das Provas". A versão 5 também inclui um subcapítulo "DA DIVERGÊNCIA DOCUMENTAL IRRELEVANTE" nos Fatos, que não deveria estar no corpo da peça.

## 11. Pendências

1. **Retrieval em produção não confirmado.** Falhou nos três canais no v2; local funciona. Chame `GET /api/diagnostico/geracao?caso_id=<id>` no ambiente de produção: ele executa embeddings, banco vetorial e análise dentro do container e devolve o erro de cada um. Suspeitas: chave `EMBEDDINGS_API_KEY` sem crédito (já ocorreu em 18/09) ou banco vetorial inacessível a partir do container.
2. **A skill GERAL no Postgres (`peticao_skills`) ainda contém a estrutura antiga.** Não a alterei (é configuração editada pela tela). Recomendo substituí-la pelo conteúdo da skill nova ou esvaziá-la — enquanto existir, o modelo ainda reproduz "Juízo 100% Digital" e "Das Provas".
3. **Schema fixo de 8 seções** (`SECOES_PADRAO`, `EVIDENCE`): a peça de referência não tem "Das Provas". Remover exige mexer em DOCX, editor e validação; não fiz nesta rodada.
4. **Classificação `tipo_peca`** das ~795 peças estava em andamento (parcial); até terminar, a heurística de nome cobre o resto.
5. **Sem reranker** de verdade; **sem geração por seção** (uma chamada escreve tudo, depois o aprofundamento reescreve). Gerar Fatos e cada tese do Direito em chamadas separadas é o passo seguinte para alcançar a subdivisão do rascunho.
6. **Tempo de geração ≈ 10 minutos** com as passadas extras (redação + aprofundamento + conferência + validação). Roda em background com progresso, mas vale acompanhar.
7. `custos_api` não existe no banco local (aviso de telemetria); irrelevante para a geração.
8. Testes que exigem banco de teste não foram executados; rodaram os que não dependem dele (formatação, visual, fila SQL, OCR saúde).
