# Guia visual do front-end (Acervo)

Este documento descreve o sistema visual do `frontend/`, adotado em substituição
à antiga direção "AUTOS" (fundo quase preto, filetes duplos, carimbos girados,
texto em caixa alta de 9–11px). A troca não foi estética: usuários sem
familiaridade técnica relatavam dificuldade para entender a hierarquia da
tela, identificar a ação principal e distinguir o significado das cores.

## Objetivo e princípios

O sistema foi desenhado para um público misto — advogados, equipe de apoio e,
no portal, o próprio cliente do escritório, muitas vezes leigo e no celular.
Três regras sustentam todas as decisões abaixo:

1. **Hierarquia por peso e espaço, não por linha divisória.** Cartão branco
   com sombra discreta sobre fundo cinza-claro (`--fundo` / `--papel`).
   Divisórias (`--borda`) só separam itens de uma mesma lista.
2. **Uma única cor de ação.** Azul-marinho (`--acao`) é a cor de tudo o que se
   clica como ação principal. Vermelho, âmbar e verde ficam reservados a
   **estado** (problema / conferir / pronto) e nunca aparecem como cor de
   botão comum — isso devolve à cor o seu significado.
3. **Cor nunca sozinha.** Todo estado (selo, aviso, marcador de item) traz
   símbolo + palavra além da cor (✕ problema, ! atenção, ✓ pronto, → próxima
   ação). Quem não distingue vermelho de âmbar continua lendo a tela
   corretamente.

## Onde tudo mora

| Camada | Arquivo | Conteúdo |
|---|---|---|
| Tokens + primitivos globais | `frontend/app/globals.css` | Cores, tipografia, espaçamento, sombra; classes `.botao`, `.campo`, `.cartao`, `.selo`, `.aviso`, `.barraProgresso` |
| Primitivos em React | `frontend/components/Basicos.tsx` | `<Selo>`, `<Aviso>`, `<Barra>`, `<Stat>`, `<ListaMensagens>` — envolvem as classes globais e garantem símbolo+palavra |
| Helpers de leitura | `frontend/lib/formato.ts` | `corDoScore`, `leituraDoScore`, `ESTILO_VEREDITO`, `SELO_TOM` |
| Estilo por tela | `frontend/components/*.module.css` | Layout específico de cada tela — nunca redefine cor, fonte ou botão |

Regra prática: **cor, fonte, botão e campo se editam em `globals.css`.**
Um `*.module.css` de tela só deveria conter grade, espaçamento e composição —
se você está prestes a escrever `background: #...` ou `border-radius: 9px` num
desses arquivos, é sinal de que deveria estar usando um primitivo global.

## Tokens de cor

Definidos em `:root` de `globals.css`. Contraste medido em WCAG 2.1 (fórmula
de luminância relativa), texto ≥ 4,5:1, contorno de controle e símbolo ≥ 3:1.

| Token | Valor | Uso |
|---|---|---|
| `--fundo` | `#f5f7fa` | Fundo da aplicação |
| `--papel` | `#ffffff` | Cartão, painel, modal |
| `--papel-2` | `#f7f9fc` | Área rebaixada (campo, bloco de código) |
| `--papel-3` | `#eff3f8` | Hover de linha/item |
| `--tinta` | `#14202e` | Título e número — 16,5:1 sobre `--papel` |
| `--tinta-2` | `#33465c` | Texto corrido — 9,7:1 |
| `--tinta-3` | `#5a6b80` | Rótulo, metadado — 5,5:1 |
| `--borda` / `--borda-forte` | `#e3e9f0` / `#c8d3e0` | Divisória / contorno de cartão |
| `--borda-campo` | `#7a8b9f` | Contorno de campo e botão secundário — 3,5:1 |
| `--acao` / `--acao-forte` | `#17457a` / `#10345f` | Cor de ação e seu hover — 9,7:1 / 12,5:1 |
| `--critico` | `#b3261e` | Estado "problema" — 6,5:1 |
| `--atencao` | `#8a5300` | Estado "conferir" (texto) — 6,3:1 |
| `--atencao-marca` | `#a96f00` | Estado "conferir" em barra/traço fino — 4,2:1 (o tom de texto reprova como elemento gráfico fino) |
| `--ok` | `#1c6b3e` | Estado "pronto" — 6,5:1 |
| `--foco` | `#1f6feb` | Anel de foco de teclado — nunca reaproveita âmbar |

Cada cor de estado tem par `-claro` (fundo tingido, ~5–8%) e `-borda`
(contorno), usados juntos nos componentes `.selo--*` e `.aviso--*`.

**Ao alterar qualquer valor de cor, remeça o contraste antes de commitar.**
O script usado nesta revisão (fórmula de luminância relativa padrão) está
descrito no fim deste documento para reuso.

### Apelidos de compatibilidade

`globals.css` também define nomes antigos (`--surface`, `--ink`, `--muted`,
`--accent`, `--warn`, `--err`, `--font-display`…) apontando para os tokens
novos. Isso existe só para não quebrar CSS legado que ainda não foi
revisitado — **não use os nomes antigos em código novo.** Se remover um
`*.module.css` inteiro do vocabulário antigo, é seguro também remover as
linhas de apelido que só ele usava (confira com uma busca antes).

## Tipografia

Três famílias, injetadas via `next/font` em `app/layout.tsx` e expostas como
`--fonte-serif` / `--fonte-sans` / `--fonte-mono` no `<html>`:

- **Newsreader** (serifa) — `--fonte-titulo`. Títulos de página e de cartão.
- **Archivo** (sem serifa) — `--fonte-ui`. Todo o resto: corpo, rótulo, botão.
- **IBM Plex Mono** — `--fonte-codigo`. Valores extraídos, código, número
  tabular (com `font-variant-numeric: tabular-nums`).

Escala mínima de 13px (`--t-xs`). O desenho anterior usava rótulos de 9–11px
em caixa alta com `letter-spacing` largo — legível para quem já conhecia a
tela, ilegível para quem via pela primeira vez. Não há mais texto abaixo de
13px em nenhuma tela.

## Primitivos

### Botões (`.botao` + modificador)

```html
<button class="botao botao--primario">Ação principal</button>
<button class="botao botao--secundario">Ação alternativa</button>
<button class="botao botao--discreto">Ação de apoio</button>
<button class="botao botao--perigo">Excluir</button>
<button class="botao botao--texto">Link-como-botão</button>
```

Regra de uma tela: **no máximo um `botao--primario` visível por bloco.** Se
duas ações competem pela cor sólida, nenhuma é de fato principal — foi
exatamente esse problema (botão vermelho de "Criar caso", concorrendo com o
vermelho de erro) que a paleta antiga tinha.

Modificadores de tamanho: `botao--pequeno` (dentro de linha de lista),
`botao--bloco` (100% da largura).

### Campos (`.campo` + modificador)

`.campo`, `.campo--area` (textarea), `.campo--seletor` (select com seta SVG).
Sempre acompanhado de `.rotuloCampo` (rótulo visível — não usar apenas
`placeholder` como rótulo) e, quando útil, `.ajudaCampo`.

### Selos de estado (`<Selo>` / `.selo--*`)

```tsx
<Selo tom="critico" simbolo="✕">Falta enviar</Selo>
<Selo tom="atencao" simbolo="!">3 a conferir</Selo>
<Selo tom="ok" simbolo="✓">Entregue</Selo>
<Selo tom="info">Obrigatório</Selo>
<Selo tom="neutro">2 de 5 opcionais</Selo>
```

`tom` mapeia para `--critico` / `--atencao` / `--ok` / `--acao` / neutro. O
símbolo é passado explicitamente porque o texto em português já muda por
contexto ("Falta enviar" vs. "Cobrar cliente") — a única constante é o par
símbolo+cor por tom.

### Avisos (`<Aviso>` / `.aviso--*`)

Faixa com símbolo, título opcional e corpo — usada para erro de formulário,
veredito de validação, confirmação de sucesso. Substitui o antigo `.banner`
(que só existia no vocabulário do resultado de OCR) e generaliza o padrão
para toda a aplicação.

```tsx
<Aviso tom="critico" titulo="Não foi possível salvar">{erro}</Aviso>
```

### Barra de progresso

`.barraProgresso` / `.barraProgressoValor` (global, cor de ação) para
progresso de ação do sistema. Telas com progresso de **documento** (Checklist,
portal do cliente) usam a variante local em `*.module.css` porque o
preenchimento muda de cor por contexto (ex.: verde no portal do cliente).

## Vocabulário de estado

Um mapeamento único de gravidade → símbolo → cor é reaplicado em toda a
aplicação (Carteira, Checklist, portal do cliente, visor de entrega):

| Gravidade | Símbolo | Cor | Significa |
|---|---|---|---|
| crítico | ✕ | `--critico` | Falta algo obrigatório / falha |
| atenção | ! | `--atencao` | Precisa de decisão humana (conferir, ilegível) |
| pronto | ✓ | `--ok` | Resolvido / validado |
| info/neutro | → / • | `--acao` / `--tinta-2` | Próxima ação sugerida / neutro |

Isso está centralizado em `lib/useCarteira.ts` (`AcaoCaso`, `estagioDaEntrega`)
e `lib/formato.ts` (`ESTILO_VEREDITO`, `SELO_TOM`) — ao adicionar um novo
estado de negócio, mapeie-o para uma dessas quatro gravidades em vez de
inventar uma cor nova.

## Vocabulário de texto

Alguns termos internos foram traduzidos para o vocabulário de quem usa a
tela, não de quem a programou:

| Antes | Agora | Onde |
|---|---|---|
| "modelo pronto" / "carrega no 1º envio" | "Leitura automática pronta" / "Leitura inicia no primeiro envio" | Carteira |
| "COBRAR CLIENTE", "CONFERIR 3" (caixa alta) | "Cobrar o cliente", "Conferir 3 documentos" | Carteira |
| "APROVADO_COM_RESSALVAS" | "Aprovado, mas confira" | Resultado do OCR |
| "ENTREGUE" / "CONFERIR" / "FALTA" | "Recebido" / "Confira" / "Falta enviar" | Checklist |
| JSON / XML como abas nomeadas assim | "Exportar JSON" / "Exportar XML" | Resultado do OCR |

Ao adicionar texto de interface, prefira a frase que se diria em voz alta ao
cliente ou colega, evite jargão do próprio sistema (nomes de tabela, nomes de
variável) e evite caixa alta em blocos de mais de uma palavra.

## Portal do cliente: um degrau acima

`app/portal/[token]/` usa a mesma paleta e os mesmos primitivos, mas com
alvos de toque maiores (mínimo 44px), corpo de texto maior (`--t-md` como
base) e uma única coluna. É a tela mais exposta a quem tem menos prática com
telas — cada decisão de espaçamento ali parte desse pressuposto, não do
espaço disponível na tela.

## Como validar contraste ao alterar uma cor

Fórmula de luminância relativa (WCAG 2.1), usada para toda a paleta acima:

```js
function lin(c) { c /= 255; return c <= 0.03928 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4); }
function lum(hex) {
  const h = hex.replace('#', '');
  const r = parseInt(h.slice(0, 2), 16), g = parseInt(h.slice(2, 4), 16), b = parseInt(h.slice(4, 6), 16);
  return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b);
}
function ratio(a, b) {
  const l1 = lum(a), l2 = lum(b);
  return (Math.max(l1, l2) + 0.05) / (Math.min(l1, l2) + 0.05);
}
// ratio('#14202e', '#ffffff') // -> 16.46
```

Alvo: **≥ 4,5:1** para texto normal, **≥ 3:1** para contorno de controle e
para símbolo/ícone usado como portador de informação (não decorativo).

## O que evitar

- Não reintroduzir cor de estado (`--critico`/`--atencao`/`--ok`) como cor de
  botão de ação comum — isso é o que fazia a tela antiga parecer sempre "em
  alerta".
- Não escrever cor, fonte ou raio de borda direto num `*.module.css` de tela;
  use os tokens e primitivos globais.
- Não usar cor como único portador de significado — todo estado leva símbolo
  e palavra.
- Não usar caixa alta em frases; reservar para rótulos de uma ou duas
  palavras onde já era assim antes (raro, e revisável).
