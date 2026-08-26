# Prazos e tempo de processo — o que dá para dizer hoje, e o que falta

## O que está no ar

`GET /api/dados/prazos` devolve, medido no acervo em 19/08/2026:

| | |
|---|---|
| Processos no acervo | 1.745 |
| Com sinal de segunda instância | 248 — **14,2%** |
| Duração mediana (1º ao último evento) | 519 dias |
| Percentil 90 | 1.019 dias |
| Processos que entraram na conta de duração | **352 de 1.745** |

A taxa de recurso é sólida: sai de contar processos distintos com peça de segunda
instância (origem `tst`/`dejt`, acórdão ou decisão monocrática) sobre o total.

## Por que a duração NÃO é "tempo médio de etapa"

Foi isso que o escritório pediu, e o acervo não sustenta. Medir uma etapa exige
dois eventos datados do **mesmo** processo:

    1.745  processos
      352  têm mais de uma data distinta   (20%)
      336  têm mais de um tipo de documento (19%)

Quatro em cada cinco processos têm **um único documento** — quase sempre a
sentença, sem a distribuição nem o acórdão.

E o viés não é neutro, que é o que torna isso perigoso: processo com vários
documentos registrados é justamente o que **recorreu**, ou seja, o mais longo.
Calcular a média sobre esses 20% e chamá-la de "tempo do processo" infla o
número, e o atendente diria ao cliente um prazo maior que o real.

Há ainda um problema anterior: o acervo não tem **etapa** como campo. Seria
preciso inferi-la do `tipo_documento` (Distribuição → Sentença → Acórdão), e essa
sequência só existe em parte dos casos.

Por isso a tela mostra a duração sempre com o **tamanho da amostra ao lado** e
com o aviso de que é referência, não prazo prometido.

## O que falta para virar medição de verdade

Ingerir as **movimentações processuais** — é o dado que falta, não o cálculo.
Dois caminhos, e eles não competem:

1. **DJEN e a Tabela Processual Unificada.** O `djen` já traz `Distribuição`
   (126 processos) e `Notificação` (180). A `Tabela Processual Unificada de
   Movimentos com Acréscimos da Justiça do Trabalho.xls`, na raiz do projeto, é
   o vocabulário oficial que dá nome à etapa de cada movimento. Com os dois, a
   sequência de etapas deixa de ser inferida do tipo de documento.

2. **ADVBOX.** `GET /api/advbox/processos/{id}/movimentacoes` já está
   implementado (`app/advbox.py`) e traz o histórico dos processos **deste**
   escritório. É a fonte com melhor qualidade para prazo — são os casos da
   banca, não do TRT8 inteiro. Depende de a API estar ativada (custo mensal).

Feito isso, `dados.prazos()` passa a agrupar por etapa e por classe processual,
e a estimativa por tipo de caso passa a ser defensável.

## Regra que não deve ser afrouxada

Prazo exibido ao cliente não pode ser "mais ou menos". Enquanto a amostra for de
20% e enviesada para os processos longos, o número vai à tela **com a amostra
visível e rotulado como observado, nunca como previsto**.
