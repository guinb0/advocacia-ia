# Conferência da petição contra os autos

A petição gerada passa por uma conferência determinística (`app/conferencia_peticao.py`)
**antes de ser salva**. O que ela afirma e os documentos do caso não sustentam vira achado
na tela — e, na geração, uma rodada de correção automática.

## Por que existe

Teste com caso-gabarito (18/09/2026): documentos fictícios com números plantados, entrevista
com contradições deliberadas, geração real pelo DeepSeek. Os números de documento do cliente
(CPF, RG, CTPS, PIS, NB, CAT, datas) saíram **todos corretos** — mas a peça:

- citou "declaração de hipossuficiência anexa (Documento 09)" — o caso tinha 8 anexos e nenhuma declaração;
- criou R$ 6.440,00 de "despesas médicas", sem despesa nenhuma, para a soma fechar em R$ 150.000,00;
- deixou horas extras, acúmulo e pensão "a apurar em liquidação" (art. 840, § 1º, da CLT);
- escreveu "DA MULTA DO ART. 477 — não se aplica" dentro da inicial do cliente;
- citou a Súmula 6 do TST (equiparação salarial) para acúmulo de função.

O contrato de redação já proibia tudo isso. A única conferência pós-geração
(`peticao_aprendizado.avaliar_documento`) media **tamanho de seção**.

## O que é conferido

| Código | Retém? | Regra |
|---|---|---|
| `DOCUMENTO_INEXISTENTE` | sim | "Documento NN" fora da numeração do bloco DOCUMENTOS |
| `ANEXO_INEXISTENTE` | sim | "X anexo/juntado/acostado" sem anexo que seja X (tipo, nome, campos ou texto; com sinônimos) |
| `NUMERO_SEM_ORIGEM` | sim | número de 5+ dígitos fora de documentos, entrevista, cadastro e material (norma e R$ não contam) |
| `DATA_SEM_ORIGEM` | sim | data fora dos autos que não deriva de uma data dos autos (mesmo dia e mês, até 5 anos) |
| `PEDIDO_SEM_VALOR` | sim | pedido de pagamento sem R$ na própria linha (honorários, juros, gratuidade, reintegração ficam de fora) |
| `VALOR_SEM_CRITERIO` | sim | valor sem conta escrita (× ou =, ou nº de meses com o valor mensal); dano moral é arbitrado e fica de fora |
| `VALOR_DA_CAUSA_INCOERENTE` | sim | valor da causa ≠ soma dos valores anunciados nos pedidos (±1%) |
| `TOPICO_CONTRA_O_CLIENTE` | sim | tópico que conclui "não se aplica / não há atraso / não se formula pedido" e não pede nada |
| `CITACAO_NAO_VERIFICADA` | não | súmula/OJ/tema ausente do material do acervo — **carimbada na peça** `[CONFERIR: …]` |

## Onde roda

- **Geração** (`gerar`): conferência → se houver violação que retém, UMA revisão via
  `_revisar_secoes_via_llm` com a lista exata e os únicos documentos existentes → nova
  conferência. O que sobrar retém a peça (`blocking_findings`, selo "Retida na revisão").
  A correção só troca o conteúdo das seções devolvidas; a estrutura das 8 seções fica.
- **Revisão por prompt/chat**: confere e carimba, sem correção automática (o pedido foi do advogado).
- **Aceite de revisão e edição manual**: reconfere; o achado some quando o advogado corrige.
- `trace.conferencia` registra violações iniciais, se houve rodada e o que restou.

## Insumos da geração

`trace.insumos` diz se vieram orientação do escritório, julgados, legislação e peças-modelo.
Faltando qualquer um, a peça ganha o aviso "Gerada SEM …" em *O que faltava quando a peça foi
gerada*. Sem julgados nem legislação, o prompt recebe o bloco "NENHUMA FONTE DO ACERVO FOI
RECUPERADA" e a instrução de não citar súmula por número.

## Resultado no caso-gabarito (mesmo caso, acervo fora do ar)

| | Antes | Depois |
|---|---|---|
| Documento/anexo inventado | "declaração anexa (Documento 09)" | `[PENDENTE: juntar declaração…]` |
| Súmula de memória | 378 e 6 (a 6 errada) | nenhuma; `[PESQUISAR PRECEDENTE…]` |
| Valores | 3 pedidos sem valor; R$ 6.440 para fechar a soma | todos com conta (ex.: 2 h × 22 dias × 22 meses × R$ 10,82 × 1,5) |
| Estabilidade | 12 meses + reintegração de período vencido | 9 meses, da dispensa ao fim, sem reintegração |
| Tópico contra o cliente | "multa do 477 — não se aplica" | ausente |

**O modelo tenta burlar a regra.** Na rodada de correção ele escreveu a conta dentro do
`[PENDENTE: …]`, pôs "R$ 0,00" em gratuidade e citação, e trocou "multa não se aplica" por
PEDIR a multa sem base. Cada brecha virou regra e teste (seções 3 e 5 do teste). Regra que
tem saída de emergência vira a saída que o modelo usa.

## Limites conhecidos

- **Súmula contra o texto oficial**: o acervo não tem catálogo de súmulas/OJs (só `lei`,
  `jurisprudencia`, `interno`). Até existir, a citação sem fonte sai carimbada — não barrada.
- **Relato citado como documento** ("trava quebrada (Documento 04)") e **erro jurídico de
  mérito** (12 meses de estabilidade em vez do período restante) não são detectáveis por regra;
  o prompt trata, a conferência não.
- **Pedido sem base** (multa do art. 477 com homologação no prazo) e **premissa arbitrária**
  (pensão "× 12 meses") passam: a conta existe, o mérito é que está errado.
- A variação entre gerações é grande (pedido de intervalo aparece numa e some na outra).
- A rodada de correção custa uma chamada a mais: a geração passou de ~85 s para ~145–180 s.

Testes: `tests/test_conferencia_peticao.py` (trechos reais da geração defeituosa).
