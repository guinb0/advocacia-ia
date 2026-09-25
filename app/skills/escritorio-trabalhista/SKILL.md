---
name: "escritorio-trabalhista"
description: 'Gera o pacote completo de qualquer Reclamação Trabalhista: assalto a carteiro/empregado, verbas rescisórias/rescisão indireta, horas extras, doença ocupacional/acidente de trabalho, equiparação salarial/acúmulo de função, assédio moral, reconhecimento de vínculo/terceirização ilícita, estabilidades (gestante, acidentária, sindical, cipeiro), adicional de insalubridade/periculosidade, reversão de justa causa/dispensa discriminatória, FGTS/diferenças salariais, e qualquer outra ação trabalhista. Analisa o caso, pesquisa como a Vara/TRT decide, redige a petição completa (todas as teses, jurisprudência certa, nunca resumida), só libera a pasta de protocolo com a petição 100% completa, prepara dados de cálculo (PJe-Calc), valida o cálculo e monta a pasta final com logo do escritório. Use quando vier documentação trabalhista e pedirem análise, petição ou protocolo — mesmo sem citar essas palavras, pois a skill identifica sozinha.'
---

# Escritório Trabalhista — Reclamações Trabalhistas (Todos os Assuntos)

Skill única para qualquer ação trabalhista. Fluxo em etapas, **sempre nesta ordem, parando entre elas para aguardar validação/dados da advogada quando indicado**:

1. **Análise do caso** — a partir da documentação recebida.
2. **Pesquisa jurisdicional e jurimetria** — antes de escrever qualquer linha da petição.
3. **Redação da petição** — completa, estrutura fixa, sem resumir.
4. **Formatação da peça** — padrão visual/ABNT do escritório.
5. **Dados para o cálculo** — tabela de dados + PJe-Calc, e aguardar o cálculo da advogada.
6. **Validação do cálculo recebido** — inserir valor da causa, apontar correções.
7. **Montagem da pasta final para protocolo.**

Se faltar dado essencial (qualificação, datas, valores, período contratual, jornada, remuneração), **peça expressamente** o que falta antes de avançar — não invente dado de qualificação, valor, data, período ou fato.

**Regra de ouro desta skill: nunca entregar petição resumida ou enxuta. A petição final deve ser completa, de excelência, usando todas as teses, fundamentos e precedentes cabíveis ao caso concreto, com a legislação e jurisprudência mais atualizadas — nunca cortada para economizar espaço.** Vale para todos os assuntos, inclusive assalto a carteiro.

---

## Etapa 1 — Análise do caso

Ao receber a documentação de um cliente, antes de qualquer outra coisa:

### 1.1 Identificar o assunto e a tese

A partir dos documentos e do relato recebidos, identifique qual conjunto de referência usar:

| Assunto | Situação típica | Referência a usar |
|---|---|---|
| **Assalto a carteiro/empregado em serviço** | Assalto sofrido por carteiro dos Correios, motoboy, entregador, vigilante ou empregado em atividade de risco similar, durante o serviço | `references/assalto_carteiro/modelo_peticao.md` + regras específicas próprias |
| Verbas rescisórias em aberto / Rescisão indireta | Verbas não pagas ou pagas a menor na rescisão; falta grave do empregador (art. 483, CLT) | `references/verbas_rescisorias.md` |
| Horas extras e reflexos | Jornada extra não paga, cartão de ponto inválido/uniforme, intervalo suprimido, horas in itinere | `references/horas_extras.md` |
| Doença ocupacional / Acidente de trabalho (geral) | LER/DORT, perda auditiva, acidente com máquina, intoxicação, acidente de trajeto — qualquer acidente/doença ocupacional que não seja assalto | `references/doenca_ocupacional_acidente_trabalho.md` |
| Equiparação salarial / Acúmulo ou desvio de função | Mesma função que paradigma com salário diferente; exercício de atribuições de outro cargo sem correspondente aumento | `references/equiparacao_salarial_acumulo_funcao.md` |
| Assédio moral / Dano moral trabalhista | Conduta abusiva reiterada, exposição vexatória, revista íntima, atraso reiterado de salário | `references/assedio_moral_dano_moral_trabalhista.md` |
| Reconhecimento de vínculo empregatício / Terceirização ilícita | "Pejotização", falso autônomo, terceirização fraudulenta de atividade-fim, subordinação a tomador | `references/vinculo_terceirizacao.md` |
| Estabilidades provisórias | Gestante, acidentária, dirigente sindical, cipeiro, pré-aposentadoria | `references/estabilidades.md` |
| Adicional de insalubridade / periculosidade (avulso) | Exposição a agente insalubre/perigoso não paga ou paga a menor, sem relação direta com acidente já ocorrido | `references/adicional_insalubridade_periculosidade.md` |
| Reversão de justa causa / Dispensa discriminatória | Dispensa por justa causa contestada; dispensa por doença estigmatizante, gravidez, orientação sexual, idade, deficiência | `references/justa_causa_dispensa_discriminatoria.md` |
| FGTS não recolhido / Diferenças salariais por norma coletiva | FGTS em atraso ou não recolhido; piso, reajuste ou vantagem de CCT/ACT não aplicada; PLR não paga | `references/fgts_diferencas_salariais.md` |
| **Qualquer outro tipo de ação trabalhista** (adicional noturno avulso, dano existencial, jornada exaustiva, greve, sindicato, intervalo interjornada etc.) | Direito trabalhista que não se encaixa nos assuntos acima | `references/outros_assuntos.md` — **nunca recuse o caso por falta de modelo pronto** |

Se houver mais de uma leitura possível, ou mais de um pedido cabível ao mesmo tempo (comum em trabalhista: um caso pode reunir horas extras + verbas rescisórias + dano moral na mesma reclamação), **combine as referências pertinentes na mesma petição**, sempre seguindo `estrutura_peca.md` para a ordem geral. Pergunte à advogada quando houver dúvida sobre incluir ou não uma tese adicional.

**Se o caso for de um assunto trabalhista que não está nessa tabela**, a skill **continua se aplicando integralmente**: todas as demais etapas (análise, pesquisa jurisdicional, estrutura da peça, citação jurídica, cálculo, montagem da pasta) seguem exatamente as mesmas regras genéricas (`references/estrutura_peca.md`, `citacoes_juridicas.md`, `regras_redacao.md`, `regras_complementares.md`, `formatacao.md`, `padrao_documentos_protocolo.md`, `outros_assuntos.md`). Informe à advogada que está usando as regras gerais da skill e redija a fundamentação com base na legislação e jurisprudência aplicáveis ao caso, pesquisadas e verificadas normalmente — nunca recusar o caso só por não haver um arquivo de assunto dedicado.

### 1.2 Conferir o checklist de documentos do assunto

Confira os arquivos recebidos contra o checklist do assunto identificado (para assalto a carteiro, ver `references/assalto_carteiro/checklist_especifico.md`; para os demais assuntos, o checklist decorre dos "Documentos decisivos" listados em cada arquivo de referência, mais os documentos pessoais/de qualificação padrão). Apresente sempre: ✅ Presente (nome do arquivo) | ❌ Faltando | ⚠️ Presente com pendência.

**Leia o conteúdo de cada documento (não apenas o nome do arquivo)** e cruze as informações entre eles, reportando qualquer divergência factual, de data ou de valor.

### 1.3 Análise detalhada do caso — pontos fortes e fracos

Depois do checklist, apresente sempre uma análise própria, separada, com esta estrutura:

**a) Pontos fortes do caso** — o que já está bem comprovado (ex. cartão de ponto claramente divergente do contracheque, CAT/BO já emitidos, testemunha identificada, contracheque com valor incontroverso).

**b) Pontos fracos do caso** — o que é frágil, contraditório, ou pode ser contestado pela reclamada/juízo (ex. cartão de ponto uniforme sem variação, ausência de testemunha, documento ilegível, divergência entre CTPS e contracheque).

**c) Se a documentação é suficiente para o protocolo** — resposta direta (sim/não/com ressalvas), separando o que é imprescindível (impede o protocolo se faltar) do que é apenas recomendável (ex. prova testemunhal a produzir em audiência).

**d) O que ajudaria a fortalecer o caso** — documento, informação ou providência que, se obtida antes do protocolo, melhoraria a tese (ex. laudo/exame atualizado, cartão de ponto de período faltante, testemunha adicional).

---

## Etapa 2 — Pesquisa jurisdicional e jurimetria

Antes de redigir qualquer linha, siga `references/pesquisa_jurisdicional_e_jurimetria.md`: identificar a Vara do Trabalho/TRT competente, pesquisar como aquele TRT decide o tipo de ação, e apontar o documento decisivo para a tese identificada.

---

## Etapa 3 — Redação da petição

Use o modelo do assunto identificado (Etapa 1.1) como estrutura e tom fixos, seguindo sempre `references/estrutura_peca.md` para a ordem dos capítulos e `references/citacoes_juridicas.md` para a forma de citar. Leia e siga à risca `references/regras_redacao.md` (e, no caso de assalto a carteiro, também `references/assalto_carteiro/regras_redacao_especifica.md`) e `references/regras_complementares.md` — preservação de conteúdo, anti-invenção, cálculo, valor da causa e limpeza da versão final.

Ao final do rascunho, apresente o **relatório de alterações e acréscimos** exigido em `regras_redacao.md` — como relatório interno para a advogada (fora da peça; no sistema, em `analise.observacoes`), nunca como seção do documento.

---

## Etapa 4 — Formatar a peça

Aplique `references/formatacao.md` à risca: logo do escritório, padrão ABNT, formatação própria de peça jurídica, paginação contínua. Formatação nunca altera conteúdo — qualquer alteração além do puramente visual é informada expressamente, separando formatação de conteúdo jurídico.

Gere a petição em `.docx`, com o logo do escritório (`assets/logo.jpg`) no cabeçalho de todas as páginas. Consulte a skill `docx` para a mecânica de geração do arquivo.

---

## Etapa 5 — Dados para o cálculo

Siga `references/dados_para_calculo.md`: reunir período contratual, jornada, remuneração e verbas pleiteadas, gerar a tabela de dados e **aguardar o retorno da advogada** com o cálculo antes de prosseguir. Quando o cálculo for feito no PJe-Calc Cidadão, usar a skill `calculo-trabalhista-pjecalc` como referência de parâmetros e passo a passo.

---

## Etapa 6 — Validação do cálculo recebido

Siga `references/validacao_calculo.md`: conferir consistência do cálculo recebido, inserir o valor da causa na linha final da petição (sem capítulo próprio, conforme `estrutura_peca.md`), e sinalizar qualquer inconsistência à advogada antes de montar a pasta final.

---

## Etapa 6.5 — Conferência de completude antes do protocolo (obrigatória, para todos os assuntos)

**A pasta final só é considerada pronta para protocolo depois que a petição estiver com todas as informações preenchidas — nunca antes.** Antes de avançar para a Etapa 7, confira item a item:

- [ ] Nenhum `[INFORMAÇÃO A CONFIRMAR]` ou `[PREENCHER]` restante no corpo da petição.
- [ ] Nenhum comentário interno, placeholder de trabalho ou anotação destinada só à advogada (ver `regras_complementares.md`, item 4).
- [ ] Qualificação completa de todas as partes (nome, RG, CPF, endereço, CNPJ da reclamada).
- [ ] Todos os fatos narrados com data, e todas as verbas/pedidos com valor ou memória de cálculo.
- [ ] Valor da causa inserido, validado pela Etapa 6.
- [ ] Toda jurisprudência citada com tribunal, órgão julgador, número do processo (ou súmula/tema), relator e data — nunca "jurisprudência a confirmar" na versão final.
- [ ] Todos os documentos citados no corpo da petição efetivamente presentes na pasta (Etapa 7).

**Se qualquer item acima não estiver resolvido, a petição e a pasta permanecem em rascunho** — liste exatamente o que falta em uma seção "PENDÊNCIAS PARA CONFERÊNCIA" (fora do corpo da peça) e **não gere a pasta final de protocolo** até a advogada confirmar ou completar o que falta. Isso vale para todos os assuntos desta skill, com atenção redobrada no assalto a carteiro, por ser o modelo mais detalhado e mais sensível a lacunas (nexo causal, responsabilidade objetiva, quantificação do dano).

---

## Etapa 7 — Montagem da pasta final para protocolo

Siga integralmente `references/padrao_documentos_protocolo.md`: nome da pasta, nomenclatura `Doc N. Nome Do Documento.pdf` (Title Case, siglas em caixa alta), ordem dos documentos, e checklist para protocolo em PDF com campos marcáveis.

Se os documentos vierem bagunçados, digitalizados torto ou fora de padrão, aplique a mesma lógica de tratamento de imagem/PDF da skill `analise-e-organizacao-documental` (recorte, orientação, legibilidade) antes de nomear e juntar.

Ao final, entregue a pasta com `present_files` e feche com um resumo objetivo: o que foi gerado, o que ficou pendente do checklist e qualquer jurisprudência nova adicionada além do modelo, para a advogada validar antes do protocolo.

---

## Regras que não se flexibilizam

- Nunca invente dado de qualificação (CPF, RG, endereço, valores, datas, jornada, salário) — pergunte o que faltar.
- Nunca invente jurisprudência, súmula, OJ, tema ou número de processo — se não tiver certeza, diga e sugira verificação.
- Nunca omita item obrigatório do checklist do assunto, presente ou faltando.
- A petição sempre trata expressamente da prescrição (bienal/quinquenal), mesmo que só para afastá-la.
- Pedidos subsidiários/alternativos só entram mediante confirmação prévia com a advogada.
- Nomenclatura de documentos sempre em "Title Case" (cada palavra maiúscula, siglas em caixa alta total) com "Doc n." na frente, conforme `references/padrao_documentos_protocolo.md`.
- O checklist para protocolo é sempre entregue em PDF com campos marcáveis.
- Nunca recusar um caso trabalhista por falta de modelo pronto — usar `references/outros_assuntos.md`.
- **A pasta de protocolo (Etapa 7) só é gerada depois que a petição estiver 100% completa** — sem `[INFORMAÇÃO A CONFIRMAR]`, sem placeholder, sem jurisprudência pendente de confirmação (ver Etapa 6.5). Isso vale para todo assunto, com atenção redobrada no assalto a carteiro.
- Todo arquivo final leva o logotipo do escritório.

## Arquivos da skill

- `SKILL.md` — este arquivo, orquestrador do fluxo em 7 etapas.
- `references/estrutura_peca.md` — ordem obrigatória da petição.
- `references/citacoes_juridicas.md` — forma correta de citar dispositivos, súmulas, OJs, temas e acórdãos.
- `references/pesquisa_jurisdicional_e_jurimetria.md` — identificar Vara/TRT competente e pesquisar jurisprudência local.
- `references/dados_para_calculo.md` / `references/validacao_calculo.md` — fluxo de cálculo.
- `references/padrao_documentos_protocolo.md` — nomenclatura, ordem e checklist da pasta final.
- `references/regras_redacao.md`, `references/regras_complementares.md`, `references/formatacao.md` — regras gerais de conteúdo e formatação.
- `references/dados_advogado.md` — logo institucional e inscrições OAB de Gustavo Lara de Melo, e qual usar conforme o foro do caso.
- `references/outros_assuntos.md` — metodologia para qualquer ação trabalhista sem modelo específico.
- `references/verbas_rescisorias.md`, `references/horas_extras.md`, `references/doenca_ocupacional_acidente_trabalho.md`, `references/equiparacao_salarial_acumulo_funcao.md`, `references/assedio_moral_dano_moral_trabalhista.md`, `references/vinculo_terceirizacao.md`, `references/estabilidades.md`, `references/adicional_insalubridade_periculosidade.md`, `references/justa_causa_dispensa_discriminatoria.md`, `references/fgts_diferencas_salariais.md` — assuntos genéricos com subteses, checklist e sugestões de reforço desenvolvidos.
- `references/assalto_carteiro/` — modelo completo e real de petição de assalto a carteiro/empregado em serviço, com regras e checklist próprios.
- `assets/logo.jpg` — logo do escritório.
