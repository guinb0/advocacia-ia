# Pipeline de Petição V2

## Objetivo

Produzir sempre uma minuta salvável e rastreável. Qualidade jurídica decide
`READY` ou `NEEDS_REVIEW`; nunca decide se uma minuta pode ser gravada.

## Fluxo único

```text
INGESTÃO/FACT_MATRIX → ISSUE_MATRIX → LEGAL_SUPPORT → PETITION_PLAN
→ CHAPTER_WRITING → REVIEW_AND_REPAIR → FINAL_RENDER
```

Cada etapa recebe o artefato anterior e devolve apenas o seu próprio artefato.
Não há pós-processamento jurídico, regex de valores ou segundo construtor de
pedidos.

| Etapa | Decide | Não decide |
| --- | --- | --- |
| FACT_MATRIX | fatos, fonte, certeza e eventos | tese, pedido, cálculo |
| ISSUE_MATRIX | teses candidatas e sua classificação | valores e redação |
| LEGAL_SUPPORT | proposições e autoridades que as sustentam | fatos do caso |
| PETITION_PLAN | capítulos, pedidos e cálculos únicos | prosa |
| CHAPTER_WRITING | prosa autorizada por contrato | fato, pedido, valor, autoridade |
| REVIEW_AND_REPAIR | finding e reparo exclusivamente de prosa | ledger jurídico |
| FINAL_RENDER | DOCX/PDF e texto determinístico de pedidos/valores | Direito |

## Fonte canônica

`CaseStateV2` é o único estado jurídico. Após `PETITION_PLAN_FINALIZED`, os
campos `facts`, `issues`, `authorities`, `requests`, `calculations`, `tables`
e `metadata` são imutáveis. `prose_sections` é separado de `internal_trace`.

## Estados de entrega

- `DRAFT`: geração parcial ou revisão ainda não executada.
- `NEEDS_REVIEW`: minuta completa, com finding jurídico pendente.
- `READY`: sem finding crítico e ledger consistente.
- `BLOCKED`: somente indisponibilidade técnica que impeça inclusive criar a
  minuta mínima.

`protocolable` só é verdadeiro em `READY`. `can_save` é verdadeiro em todos
os estados acima, exceto falha técnica total.

## Migração

1. `peticao_v2.py` é a nova entrada isolada, habilitada por
   `PETITION_PIPELINE_V2=1`.
2. A V1 fica acessível apenas com a flag desligada enquanto a migração é
   acompanhada; ela não é fallback automático da V2.
3. Quando os três golden cases forem estáveis, a V1 pode ser removida sem
   alterar o contrato HTTP da tela.
