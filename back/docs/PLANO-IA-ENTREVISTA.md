# Plano futuro — interpretação estruturada da entrevista

> Documento de proposta. **Não está implementado e não altera o fluxo atual.**
> A escuta, o Whisper e o preenchimento que já funcionam permanecem como estão.

## Objetivo

Evoluir a interpretação feita pelo DeepSeek sem trocar de modelo, concentrando o
ganho em três pontos: instruções mais rigorosas, estado incremental da entrevista
e uma saída estruturada com evidência e confiança.

O resultado esperado é reduzir preenchimentos por suposição, conservar o que o
cliente realmente disse e tornar cada conclusão auditável pela equipe jurídica.

## Princípios que não podem ser violados

- Nunca inventar ou completar informação ausente.
- Nunca transformar hipótese ou inferência em fato.
- Preservar literalmente nomes, datas, valores, empresas, endereços e termos
  ambíguos; dúvida de transcrição deve ser marcada, não corrigida silenciosamente.
- Interpretar respostas curtas a partir da pergunta imediatamente anterior.
- Não escolher arbitrariamente entre versões contraditórias.
- Informação ausente continua `null` e produz uma pergunta objetiva de retorno.
- Toda conclusão importante deve apontar para uma evidência da transcrição.
- A transcrição original nunca é substituída por texto normalizado ou por dados
  extraídos.

## Três camadas de informação

```text
TRANSCRIÇÃO ORIGINAL
"eu tava carregando umas caixa..."
        ↓
TRANSCRIÇÃO NORMALIZADA
"Eu estava carregando umas caixas..."
        ↓
DADOS EXTRAÍDOS
atividade = "Carregamento de caixas"
```

As três camadas devem ser armazenadas separadamente. A normalização pode corrigir
pontuação, capitalização e erro inequívoco, mas jamais apagar ou reescrever a
fonte. Isso permite revisar e reprocessar uma interpretação no futuro.

## Estado incremental

O DeepSeek não deve recriar o caso inteiro a cada fala. Para cada novo trecho, a
aplicação enviará:

1. pergunta atual;
2. resposta ou trecho recém-confirmado;
3. estado estruturado existente;
4. campos ainda ausentes.

O modelo devolverá apenas mudanças:

```json
{
  "updates": {
    "trabalho.cargo": {
      "valor": "Auxiliar de estoque",
      "confianca": "alta",
      "origem": "explicita",
      "evidencia": "Eu era auxiliar de estoque."
    }
  },
  "remover_faltantes": ["trabalho.cargo"],
  "adicionar_faltantes": [],
  "ambiguidades": [],
  "contradicoes": []
}
```

Essa abordagem reduz custo, evita que campos estáveis sejam reescritos e permite
registrar cada alteração com sua proveniência.

## Confiança e origem

Cada atualização deve informar:

| Campo | Valores | Regra |
|---|---|---|
| `confianca` | `alta`, `media`, `baixa` | baixa nunca autoriza adivinhação |
| `origem` | `explicita`, `contextual`, `inferida` | inferida não preenche fato automaticamente |
| `evidencia` | trecho literal | deve existir na transcrição original |

- **Alta:** declaração direta e inequívoca.
- **Média:** resposta curta cujo significado vem da pergunta anterior.
- **Baixa:** possível erro do reconhecimento ou mais de uma interpretação.

Atualização de confiança baixa ou origem inferida deve virar pendência de
conferência, não preenchimento automático.

## Datas, números e dados sensíveis

- “Foi em março” não vira `01/03` nem recebe ano presumido.
- “Foi dia 15 de março de 2024” pode virar `2024-03-15`.
- Nome próprio, CPF, RG, valores e endereços não são corrigidos por aproximação.
- Versões diferentes permanecem registradas até o advogado escolher ou confirmar.

## Contradições e ambiguidades

Uma contradição deve guardar as duas versões e suas evidências:

```json
{
  "campo": "trabalho.data_admissao",
  "versoes": [
    {"valor": "2021", "evidencia": "Comecei na empresa em 2021."},
    {"valor": "2022", "evidencia": "Eu entrei lá em 2022."}
  ],
  "pergunta_sugerida": "O ingresso ocorreu em 2021 ou 2022?"
}
```

O sistema não deve sobrescrever a primeira versão nem escolher a mais recente
automaticamente.

## Prompt pretendido

O prompt de sistema deve exigir fidelidade absoluta, JSON estrito e obediência ao
schema. Antes de responder, o modelo deve verificar internamente se cada dado tem
suporte, se alguma data ou quantidade foi completada e se existem contradições,
ausências ou baixa confiança.

O prompt não substitui validação em código. A aplicação deve rejeitar:

- campo que não existe no schema;
- evidência vazia ou incompatível com a transcrição;
- valor fechado fora das opções permitidas;
- atualização inferida apresentada como fato;
- alteração de campo protegido ou digitado manualmente;
- JSON inválido ou resposta fora do formato.

## Implementação em fases

### Fase 1 — contrato e medição

- Definir o schema versionado de estado e de atualizações.
- Criar casos de teste com entrevistas reais anonimizadas.
- Medir precisão atual para estabelecer uma linha de base.
- Não alterar a interface nem o preenchimento existente.

### Fase 2 — execução paralela, sem efeito na tela

- Rodar o novo extrator em modo sombra.
- Guardar resultado novo ao lado do resultado atual.
- Comparar preenchimentos, recusas, contradições e custo.
- Nenhuma resposta do modo sombra altera o caso.

### Fase 3 — revisão assistida

- Mostrar confiança, evidência, ambiguidades e contradições ao advogado.
- Exigir confirmação para baixa confiança e inferências.
- Manter botão para abrir a fala original.

### Fase 4 — ativação controlada

- Ativar por escritório ou por tipo de roteiro.
- Manter retorno imediato ao comportamento atual.
- Monitorar erro, latência, custo e quantidade de correções humanas.

## Critérios para substituir o fluxo atual

- Não perder respostas que o fluxo atual captura.
- Reduzir preenchimento indevido por pergunta lida ou suposição.
- Evidência presente em 100% dos campos relevantes.
- Nenhuma data, valor ou nome criado por inferência.
- Contradições preservadas, nunca sobrescritas silenciosamente.
- Latência compatível com a conversa.
- Teste de regressão completo aprovado e validação humana em amostra real.

## Relação com a diarização futura

A diarização com `pyannote.audio` é outra etapa e permanece pós-entrevista. Ela
poderá enriquecer a transcrição com `Advogado:` e `Cliente:`, mas não é requisito
para testar o estado incremental. Na chamada Jitsi, a faixa remota já separa o
cliente; na entrevista presencial, a diarização será mais útil.

## Decisão atual

Não implementar antes da demonstração. O sistema atual está estável e deve ser
preservado. O primeiro trabalho posterior será a Fase 1, seguida obrigatoriamente
do modo sombra; não haverá troca direta do fluxo em produção.
