# Diagnóstico — automação ZapSign por navegador (Playwright): corrigido

Investigado e corrigido em 09/09/2026, contra a conta real do escritório
(`dr.gustavolara@gmail.com`), em dev. Módulo:
[app/assinatura_navegador.py](../app/assinatura_navegador.py).

**Status: corrigido e validado.** `enviar_para_assinatura()` completa as 4
etapas do assistente e devolve um link de assinatura real
(`https://app.zapsign.com.br/verificar/<token>`), pronto pra ir por WhatsApp.

## Onde travava

**Etapa 2 → 3 do assistente**: "Adicionar signatários" → "Posicionar
assinaturas". A etapa 1 (upload do PDF) sempre funcionou. Na etapa 2, o nome
do signatário era digitado certo, mas o clique em "CONTINUAR" não avançava a
tela — a automação seguia tentando as etapas seguintes sem nunca sair dali, e
terminava sem achar link de assinatura.

## Causa raiz encontrada

**Não era JS quebrado do ZapSign nem seletor desatualizado.** Era um bug na
nossa própria função `_clicar()`:

1. **Elemento fantasma.** Depois de avançar de uma etapa, o ZapSign deixa no
   DOM um botão "Continuar" da etapa anterior — mesmo texto, mesmo
   `data-cy="continuarBtn"`, mas **invisível/fora de posição** (confirmado:
   `bounding_box` bem fora do painel principal, `elementFromPoint` no centro
   dele devolvia uma `<div>` vazia). `pagina.locator(...).first` obedece
   **ordem no DOM**, não posição na tela — quando o fantasma vinha primeiro, o
   clique "funcionava" (sem lançar erro) e a etapa não avançava, porque caiu
   no elemento errado.
2. **Corrida de tempo.** Mesmo filtrando só o elemento visível, uma tentativa
   só às vezes chegava cedo demais — o Angular do assistente leva uma fração
   de segundo pra estabilizar depois do clique anterior.

`.first.click()` com timeout único e sem checar visibilidade **escondia** os
dois problemas: parecia funcionar quando a sorte de timing colaborava (é
provavelmente por isso que a calibração original — citada no docstring do
módulo — deu certo uma vez e nunca mais foi revisitada), e travava direto
quando não colaborava.

## O que foi descartado no caminho (registrado porque custou tempo real)

- **Detecção de headless/bot**: reproduzido igual com Chromium headed
  (janela real). Não era isso.
- **Erros de JS do próprio ZapSign** (`your_user_id is not defined`,
  `Cannot read properties of undefined (reading 'value')`): apareciam no
  console, mas bloquear os scripts de terceiros que os causavam (Hotjar, GTM,
  LaunchDarkly) não resolveu o travamento — eram barulho, não a causa.
- **Falta de "confirmar" o nome do signatário** (Enter, clicar fora pra
  perder o foco): não mudava o resultado.
- **Conta com problema/sem permissão**: descartada — conta ativa, uso normal
  (528+ documentos reais na lista).

## A correção

Reescrevi `_clicar()` em `app/assinatura_navegador.py`:
- Filtra candidatos por **`elemento.is_visible()` real**, elemento a
  elemento — não por `.first` numa lista ordenada por DOM, nem por
  pseudo-seletor `:visible` (que teve o mesmo problema numa das tentativas).
- **Repete a busca em ciclos curtos** (a cada 700ms, dentro do orçamento de
  `espera` que a função já recebia) em vez de uma tentativa só — dá tempo do
  Angular estabilizar entre etapas.

Sem mudar a assinatura da função nem quem a chama — `_enviar_um()` e o resto
do módulo continuam iguais.

## Validação — rodada completa, com o fix aplicado

`enviar_para_assinatura()` chamado de ponta a ponta (PDF sintético, sem dado
de cliente real, e-mail de teste `teste-automacao-zapsign@example.com`):

```
ok: True
link: https://api.whatsapp.com/send?text=Cliente, segue link para assinatura
      eletrônica do documento...%0ahttps://app.zapsign.com.br/verificar/ac5dc209-...
erro: (vazio)
url_final: https://app.zapsign.com.br/conta/documentos/novo
```

As 4 etapas completaram (upload → signatário → posicionar → enviar),
screenshots em `_zapsign_debug/01` a `05` confirmam cada uma visualmente.

**Ficou um documento de teste na conta real do ZapSign** — nome
`TESTE-FIX-AUTOMACAO-NAO-E-CONTRATO.pdf`, destinatário
`teste-automacao-zapsign@example.com` (e-mail que não existe, não incomoda
ninguém). Fácil de achar e apagar pela lista de documentos, se quiser
limpar — não apaguei porque mexer na lista de documentos da conta real não
era parte do que foi pedido.

## Sobre o WhatsApp

Não cheguei a testar o envio de verdade pela Evolution — confirmado
previamente que a instância está desconectada, e o pedido original era só
"testar se a automação funciona" até esse ponto. O link que a automação
devolve já vem pronto no formato que o `app/whatsapp.py`/Evolution esperam
mandar (é o mesmo link usado em `https://api.whatsapp.com/send?text=...`, que
é a própria página do ZapSign montando o texto — o sistema usa só o link
`/verificar/...` de dentro dele).

## Próximo passo, se quiser ir além

Quando a instância do WhatsApp for religada, vale um teste de ponta a ponta
de verdade: gerar o link (já validado) → `app/whatsapp.py` mandar pro
cliente. Essa parte não foi tocada nem testada agora.
