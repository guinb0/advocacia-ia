# Pipeline documental Mistral — entregas 0 a 9

Versão técnica: `mistral-documentos-v1`  
Modelo fixado: `mistral-ocr-4-1`

## Fluxo executável

```text
upload
  -> ocr_mistral
  -> classificar_documento
  -> extrair_schema_especifico
  -> validar_e_conciliar
  -> extrair_evidencias
  -> encaminhar_pos_validacao
       -> revisao_humana -> resumo_do_caso
       -> resumo_do_caso
```

Cada etapa possui status, tentativas, modelo, versão, resultado, erro e duração próprios no PostgreSQL. O OCR bruto é preservado e as etapas posteriores podem ser reprocessadas sem nova chamada paga à Mistral.

## Parte 0 — linha de base e conjunto-ouro

- Dataset sintético versionado em `tests/fixtures/documentos_ouro.json`.
- Casos mínimos: ocorrência policial, documento médico e CAT.
- Regressões obrigatórias: instituição não pode virar pessoa; certidão policial não pode virar certidão civil; afirmação sem citação deve ser rejeitada.
- Métricas principais: acerto do tipo, cobertura de campos obrigatórios, taxa de revisão humana, citações verificadas e duração por etapa.

## Parte 1 — entrada nativa e segura

- PDF segue como `document_url`; imagem como `image_url`.
- O arquivo original e seu SHA-256 ficam no armazenamento durável.
- DOCX e TXT digitais não consomem OCR visual.
- Limites de tamanho e extensão continuam aplicados no upload.

## Parte 2 — OCR com estrutura real

- `include_blocks=true` e confiança por bloco.
- Páginas, cabeçalho, rodapé, tabelas, ordem de leitura e bounding boxes são preservados.
- O fallback de markdown existe somente quando a API não devolve blocos.
- Nenhuma geometria artificial é usada para inferir relações entre campos.

## Parte 3 — anotação universal

- A Mistral responde sob JSON Schema estrito.
- Pessoas, organizações, campos, eventos e itens do checklist exigem citação literal e página.
- Instituições são separadas de pessoas.
- Tipo genérico `certidao` é proibido; o modelo deve distinguir certidões civis e policiais.

## Parte 4 — classificação documental

- Combina anotação da Mistral com expressões fortes e determinísticas.
- Conflito entre modelo e texto não é ocultado: gera revisão humana.
- Taxonomia jurídica versionada contempla identidade, civil, policial, trabalhista, médica, previdenciária, financeira, mandato, contratos e peças processuais.

## Parte 5 — schema específico

- Depois do tipo, somente os campos pertinentes são promovidos.
- Pessoas citadas são conciliadas com papéis como paciente, trabalhador, outorgante e declarante.
- Regexes específicas complementam campos de BO, certidão policial, CAT, atestado/laudo, CNIS e holerite.
- Campo ou entidade cuja citação não exista no OCR é registrado como recusado.

## Parte 6 — validação e conciliação

- Estados independentes: arquivo legível, tipo confirmado, campos validados, atendimento ao checklist e evidências extraídas.
- Nome do sujeito principal é comparado ao cliente do caso.
- O destino do checklist usa o código `tipo_ocr` ou relação determinística com o nome do item; a indicação livre do modelo não decide sozinha.
- Documento com baixa cobertura, conflito, divergência de pessoa ou destino incerto segue para revisão.

## Parte 7 — evidências e resumo

- Somente fatos com citação localizada em uma página entram como evidência.
- Evidências sensíveis recebem marcação própria.
- O resumo é derivado das evidências aceitas e não volta a consultar o documento sem lastro.
- Enquanto houver revisão pendente, o documento fica em `conferir` e não cumpre automaticamente o checklist.

## Parte 8 — revisão humana

- Endpoint: `POST /api/entregas/{id}/analise/revisao`.
- O profissional confirma ou corrige tipo, itens atendidos, aceitação e observação.
- A decisão atualiza a entrega, conclui a etapa humana e gera o resumo final.
- A interface exibe a linha do tempo e os cinco estados técnicos, sem apresentar “aprovação jurídica” automática.

## Parte 9 — aprendizado e operação

- Correções ficam em `analise_documento_feedback`, sem alterar silenciosamente regras em produção.
- Endpoint `POST /api/entregas/{id}/analise/reprocessar` reaplica classificador, schema e validadores usando o OCR salvo.
- Métricas Prometheus: `forense_document_pipeline_stage_total` e `forense_document_pipeline_stage_duration_seconds`.
- Novas regras só devem ser promovidas após superar o conjunto-ouro e reduzir erro/revisão sem aumentar falsos positivos.

## Critério de conclusão

Um documento só segue direto ao resumo quando o arquivo é legível, o tipo está confirmado, os campos mínimos estão cobertos, o destino do checklist possui sustentação e as evidências têm citação verificável. Qualquer dúvida permanece visível e exige a palavra final do profissional jurídico.
