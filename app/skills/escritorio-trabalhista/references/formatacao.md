# Formatação e Padronização da Peça Jurídica

Regras obrigatórias de formatação, aplicadas **depois** que o conteúdo da petição estiver pronto e revisado conforme `references/regras_redacao.md`. Formatação nunca autoriza alterar conteúdo — só apresentação, organização e legibilidade.

## 1. Cabeçalho e logo

- Inserir o logo do escritório (`assets/logo.jpg`) no cabeçalho, repetido em todas as páginas quando compatível com o modelo.
- Tamanho proporcional, sem distorcer, recortar ou modificar a identidade visual do logo.
- **Nunca criar, inventar ou substituir o logo** caso o arquivo oficial não esteja disponível — nesse caso, informar expressamente que o logo não pôde ser inserido, em vez de usar outro.
- Usar sempre a imagem real do arquivo (ex. `ImageRun` em scripts docx-js) — nunca recriar o logo como texto estilizado.
- Dados de assinatura (nome e OAB do advogado, conforme o foro do caso): ver `references/dados_advogado.md`.

## 2. Padrão ABNT (quando compatível com a natureza da peça)

- Papel A4.
- Fonte única em toda a peça: Arial ou Times New Roman.
- Corpo do texto: tamanho 12. Citações longas e notas de rodapé: tamanho 10.
- Alinhamento justificado.
- Espaçamento entre linhas: 1,3 no corpo do texto (ver bloco `estilo` abaixo).
- Recuo de primeira linha: 1,25 cm (salvo se a estrutura jurídica exigir padrão diferente).
- Margens: superior 3 cm, esquerda 3 cm, inferior 2 cm, direita 2 cm.
- Hierarquia visual uniforme entre títulos e subtítulos.
- Evitar excesso de negrito, sublinhado, cores ou elementos decorativos — negrito reservado a prazos, riscos e alertas de pendência, como já definido no `SKILL.md`.
- Padrão uniforme de fonte, tamanho, espaçamento e alinhamento do início ao fim.

## 2.1 Estilos (lidos pelo gerador de documento — é AQUI que a aparência se define)

O gerador não conhece aparência de peça alguma: ele só sabe desenhar parágrafo, título,
citação em bloco, bloco nomeado, tabela, imagem, cabeçalho, rodapé e paginação. Cada
valor abaixo é lido deste bloco; o que não estiver aqui NÃO é inventado (sai como piso
técnico genérico e fica registrado no diagnóstico da geração). Formato: `elemento.propriedade: valor`.
Propriedades: `fonte`, `tamanho_pt`, `cor` (hex), `negrito`, `italico`, `caixa_alta` (sim/não),
`alinhamento` (esquerda/centro/direita/justificado), `espacamento_linha`, `antes_pt`, `depois_pt`,
`recuo_esquerdo_cm`, `recuo_direito_cm`, `recuo_primeira_linha_cm`, `borda_cor`, `preenchimento`,
`manter_com_proxima` (sim/não). Elemento que não define uma propriedade herda do `corpo`.

```estilo
pagina.fonte: Arial
pagina.margem_superior_cm: 3
pagina.margem_esquerda_cm: 3
pagina.margem_inferior_cm: 2
pagina.margem_direita_cm: 2
corpo.tamanho_pt: 12
corpo.alinhamento: justificado
corpo.espacamento_linha: 1.3
corpo.antes_pt: 0
corpo.depois_pt: 6
corpo.recuo_primeira_linha_cm: 1.25
titulo1.negrito: sim
titulo1.alinhamento: esquerda
titulo1.recuo_primeira_linha_cm: 0
titulo1.manter_com_proxima: sim
titulo2.negrito: sim
titulo2.alinhamento: esquerda
titulo2.recuo_primeira_linha_cm: 0
titulo2.manter_com_proxima: sim
titulo3.negrito: sim
titulo3.italico: sim
titulo3.alinhamento: esquerda
titulo3.recuo_primeira_linha_cm: 0
titulo3.manter_com_proxima: sim
blockquote.tamanho_pt: 10
blockquote.italico: sim
blockquote.alinhamento: justificado
blockquote.espacamento_linha: 1
blockquote.recuo_esquerdo_cm: 4
blockquote.recuo_primeira_linha_cm: 0
enderecamento.negrito: sim
enderecamento.caixa_alta: sim
enderecamento.alinhamento: centro
enderecamento.recuo_primeira_linha_cm: 0
titulo_acao.negrito: sim
titulo_acao.caixa_alta: sim
titulo_acao.alinhamento: centro
titulo_acao.recuo_primeira_linha_cm: 0
objeto.tamanho_pt: 10
objeto.alinhamento: justificado
objeto.espacamento_linha: 1
objeto.recuo_esquerdo_cm: 8
objeto.recuo_primeira_linha_cm: 0
fechamento.alinhamento: centro
fechamento.recuo_primeira_linha_cm: 0
cabecalho.logo_altura_cm: 2.25
rodape.formato: Página {pagina} de {total}
rodape.alinhamento: direita
rodape.tamanho_pt: 9
rodape.tamanho_numero_pt: 12
```

### Marcação que o redator usa no texto (o gerador converte cada uma no estilo acima)

- `# texto`, `## texto`, `### texto` → `titulo1`, `titulo2`, `titulo3` (capítulo, subcapítulo, item). Título SEM `#` sai como parágrafo de corpo.
- `> texto` → `blockquote` (transcrição de dispositivo legal, ementa ou trecho de documento). Nunca use `>` para outra coisa.
- `::: nome` … `:::` → bloco no estilo `nome`, para qualquer nome definido acima. Usos: `::: enderecamento` (Ao Juízo…), `::: titulo_acao` (nome da ação), `::: objeto` (caixa de objeto logo abaixo do endereçamento, quando o modelo do assunto pedir), `::: fechamento` (Nestes termos…, local/data, advogado e OAB). Só use nomes que existam no bloco `estilo`.
- `**texto**` negrito; tabela em Markdown quando o modelo pedir.

## 3. Formatação jurídica própria da peça

- Endereçamento corretamente destacado.
- Identificação clara das partes.
- Número do processo, quando existente.
- Título da peça em destaque.
- Organização lógica dos tópicos, com numeração padronizada de capítulos e subcapítulos.
- Pedidos com destaque adequado (lista alfabética, como no modelo).
- Dispositivos legais transcritos de forma organizada (recuo/itálico, como no modelo).
- Jurisprudência destacada e identificada (ver item 5).
- Referências a documentos/anexos organizadas de forma coerente com os nomes dos arquivos do checklist.
- Fechamento com local, data e identificação do advogado.

## 4. Cabeçalho, rodapé e paginação

- Cabeçalho institucional com o logo, padronizado em todas as páginas.
- Rodapé apenas se fizer parte do padrão do escritório ou for necessário.
- Paginação contínua, preferencialmente "Página X de Y" quando tecnicamente possível.
- Paginação nunca pode cobrir texto, assinatura, logo ou qualquer outro elemento.
- Cabeçalho e rodapé discretos e profissionais.

## 5. Apresentação de jurisprudência

Cada jurisprudência citada deve trazer, quando disponíveis: tribunal, órgão julgador, número do processo, relator, data do julgamento, data de publicação, e a ementa/trecho efetivamente usado — apresentados de forma organizada e legível (ex. bloco destacado, como no modelo).

**Proibido inventar** jurisprudência, número de processo, relator, tribunal, data ou tese — regra que já vale desde a redação (`regras_redacao.md`) e se mantém na formatação: a etapa de formatação nunca deve "completar" um dado de jurisprudência que estava incompleto por conta própria.

## 6. Legislação e fundamentação

- Usar legislação vigente; não usar dispositivo revogado como se estivesse em vigor.
- Não inventar artigo, parágrafo, inciso ou lei.
- Não criar fundamento jurídico inexistente.
- Dúvida sobre vigência ou aplicação de norma: sinalizar antes de incorporar à peça.

## 7. Preservação do conteúdo durante a formatação

A formatação **não autoriza** alterar o conteúdo jurídico. É proibido, só por causa da formatação: resumir a peça, diminuir conteúdo, retirar fato, excluir argumento, alterar pedido, valor, data, nome, ou documento mencionado, ou criar fato/prova/fundamento/jurisprudência.

A formatação melhora apresentação, organização, legibilidade e profissionalismo — nunca a essência do conteúdo.

## 8. Registro de alterações feitas durante a formatação

Se, ao formatar, for necessário fazer qualquer alteração além de ajuste puramente formal (ex. corrigir uma citação incompleta, reorganizar um parágrafo mal encaixado), informe:

1. que a alteração foi feita;
2. exatamente o que foi alterado;
3. o motivo;
4. se é alteração de **formatação** ou de **conteúdo jurídico** (são coisas diferentes e não podem se confundir).

Ao final, apresente uma seção **"ALTERAÇÕES REALIZADAS"**, separando: Formatação | Organização | Correções gramaticais | Ajustes jurídicos | Inclusões | Exclusões. Isso complementa (não substitui) o relatório de "Alterações e Acréscimos" da Etapa 2, que trata do conteúdo jurídico em si.

## 9. Conferência final antes de entregar

- [ ] Logo inserido corretamente no cabeçalho
- [ ] Formato A4
- [ ] Margens padronizadas (3/3/2/2 cm)
- [ ] Fonte uniforme (Arial ou Times New Roman)
- [ ] Tamanho da fonte adequado (12 corpo, 10 citação/nota)
- [ ] Espaçamento padronizado (bloco `estilo`)
- [ ] Texto justificado
- [ ] Parágrafos uniformes (recuo 1,25 cm)
- [ ] Títulos e subtítulos padronizados
- [ ] Paginação correta e contínua
- [ ] Cabeçalho e rodapé alinhados, sem cobrir conteúdo
- [ ] Nenhum texto cortado
- [ ] Nenhuma página em branco indevida
- [ ] Nenhum título isolado no fim da página (órfão)
- [ ] Jurisprudências devidamente identificadas
- [ ] Legislação conferida
- [ ] Nomes e dados das partes conferidos
- [ ] Datas conferidas
- [ ] Valores conferidos
- [ ] Pedidos preservados integralmente
- [ ] Nenhuma informação inventada
- [ ] Nenhum conteúdo original removido sem autorização
- [ ] Documento final visualmente profissional e pronto para revisão/protocolo

## Regra principal

**Não inventar. Não alterar. Não resumir. Não diminuir.** A peça é só melhorada, organizada, corrigida e formatada — o conteúdo fornecido é preservado integralmente. Qualquer informação nova, fundamento jurídico novo, jurisprudência nova ou alteração relevante é sempre informada expressamente, nunca apresentada como se já fizesse parte do material original.
