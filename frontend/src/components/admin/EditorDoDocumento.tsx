"use client";

/**
 * O documento da petição, editável como no Word.
 *
 * Era um `<textarea>` por seção: dava para escrever, não para formatar. Quem
 * revisa uma peça precisa grifar um trecho, pôr um título no meio da página,
 * recuar um parágrafo — e fazia isso baixando o .docx, editando no Word e
 * perdendo o vínculo com o caso. Agora a barra e a régua aplicam negrito,
 * itálico, sublinhado, tachado, alinhamento, recuos, caixa, tabulação, quebra
 * de página e TABELA direto na peça.
 *
 * COMO A FORMATAÇÃO SOBREVIVE
 *
 * O estado continua sendo o texto da seção (ver `lib/formatacaoPeticao.ts`):
 * a formatação vira marcação dentro dele. Nada mais mudou de caminho — salvar,
 * revisar por prompt, comparar versões e baixar .docx/PDF seguem lendo texto.
 * O que a barra aplica tem de existir nos TRÊS lugares: na marcação, aqui na
 * tela, e no gerador do .docx (`app/peticao_local.montar_docx`). Um controle
 * que só mexe na tela é pior que controle nenhum — foi por isso que tamanho e
 * cor saíram daqui.
 *
 * POR QUE `contentEditable` E NÃO UMA BIBLIOTECA
 *
 * O que se formata aqui cabe em `document.execCommand` mais alguns ajustes de
 * estilo no bloco do parágrafo e na `<table>`. Trazer um editor inteiro (TipTap
 * e afins) custaria o dobro do peso da tela para ganhar lista numerada, que a
 * peça resolve por outro caminho. `execCommand` está obsoleto no papel e
 * implementado em todos os navegadores — inclusive porque é ele que dá o Ctrl+B
 * de graça.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import {
  AlignCenter,
  AlignJustify,
  AlignLeft,
  AlignRight,
  Bold,
  CaseLower,
  CaseUpper,
  Columns3,
  IndentDecrease,
  IndentIncrease,
  Italic,
  Redo2,
  RemoveFormatting,
  Rows3,
  SeparatorHorizontal,
  Strikethrough,
  Table,
  Underline,
  Undo2,
} from "lucide-react";

import {
  HTML_DA_QUEBRA,
  SEM_PARAGRAFO,
  aplicarFormatoDeParagrafo,
  formatoDeParagrafoDoBloco,
  formatoEfetivoDoBloco,
  htmlDeTabelaNova,
  paraHtml,
  paraTexto,
  temTabelaMarkdown,
  type FormatoDeParagrafo,
} from "@/lib/formatacaoPeticao";

/**
 * A largura útil do papel, em centímetros: A4 (21 cm) menos as margens do
 * modelo do escritório (3,00 cm à esquerda, 1,89 cm à direita) — os mesmos
 * números de `CONFIGURACAO_VISUAL_PADRAO`, em `app/peticao_local.py`.
 *
 * NÃO é enfeite: é o que faz a régua dizer a verdade. A caixa do documento tem
 * exatamente esta largura de texto, em centímetros CSS, então 2 cm na régua são
 * os 2 cm que o Word vai mostrar. Com a caixa em pixels arbitrários, arrastar
 * um recuo para "2 cm" produziria outra coisa no papel.
 *
 * Um escritório que mude as margens no modelo geral desloca a régua — ela
 * continua correta em centímetros, só não bate mais com a borda do papel. Ler a
 * configuração daqui não é possível: `/api/modelos/peticao/visual/configuracao`
 * exige a permissão de manter o modelo, que quem só redige não tem.
 */
export const LARGURA_UTIL_CM = 16.11;

/** O passo de um toque de recuo, em centímetros — o mesmo do Word. */
const PASSO_DE_RECUO_CM = 1.25;

/** Duas casas decimais. Sem isto, arrastar a régua grava `1.2500000003` e o
 *  texto da peça muda a cada arrasto sem nada ter mudado de verdade. */
function duasCasasCm(valor: number): number {
  return Math.round(valor * 100) / 100;
}

export type EstadoDaSelecao = {
  negrito: boolean;
  italico: boolean;
  sublinhado: boolean;
  tachado: boolean;
  /** O formato do parágrafo onde está o cursor — o que a régua mostra. */
  paragrafo: FormatoDeParagrafo;
  /** O cursor está dentro de uma tabela: só então os botões dela aparecem. */
  naTabela: boolean;
};

function comandoPossivel(): boolean {
  return typeof document !== "undefined" && typeof document.execCommand === "function";
}

/** O bloco (parágrafo) que contém um nó, dentro de um campo do documento. */
function blocoDe(raiz: HTMLElement, no: Node | null): HTMLElement | null {
  if (!no || !raiz.contains(no)) return null;
  let atual: Node | null = no;
  while (atual && atual !== raiz) {
    if (atual.parentNode === raiz && atual instanceof HTMLElement) return atual;
    atual = atual.parentNode;
  }
  return null;
}

/** Os parágrafos que a seleção toca. Um clique simples devolve um; uma seleção
 *  que atravessa a peça devolve todos, e é isso que faz recuar três parágrafos
 *  de uma vez funcionar. */
function blocosDaSelecao(raiz: HTMLElement): HTMLElement[] {
  const selecao = document.getSelection();
  if (!selecao || selecao.rangeCount === 0) return [];
  const intervalo = selecao.getRangeAt(0);
  const tocados = Array.from(raiz.children).filter(
    (filho): filho is HTMLElement => filho instanceof HTMLElement && intervalo.intersectsNode(filho),
  );
  if (tocados.length) return tocados;
  const unico = blocoDe(raiz, selecao.anchorNode);
  return unico ? [unico] : [];
}

/** O parágrafo sob o cursor, como ele APARECE — é o que a régua mostra. */
function paragrafoDaSelecao(raiz: HTMLElement): FormatoDeParagrafo {
  const [primeiro] = blocosDaSelecao(raiz);
  return primeiro ? formatoEfetivoDoBloco(primeiro) : { ...SEM_PARAGRAFO };
}

/** Muda o formato de parágrafo de tudo o que a seleção toca.
 *
 * A decisão parte do que está NA TELA (o formato efetivo, somando o que a peça
 * já impõe) e é gravada sobre o que está NAQUELE parágrafo. A diferença
 * importa: somar 1,25 cm a um recuo que a régua mostra como 2 cm tem de dar 3,25
 * cm, e não 1,25 — e os campos que ninguém tocou têm de continuar herdando o
 * padrão da peça em vez de virarem valores fixos na primeira mexida. */
function mudarParagrafo(
  raiz: HTMLElement,
  mudanca: (efetivo: FormatoDeParagrafo) => Partial<FormatoDeParagrafo>,
) {
  for (const bloco of blocosDaSelecao(raiz)) {
    const proprio = formatoDeParagrafoDoBloco(bloco);
    aplicarFormatoDeParagrafo(bloco, {
      ...proprio,
      ...mudanca(formatoEfetivoDoBloco(bloco)),
    });
  }
}

/** Troca a caixa do texto selecionado sem perder a formatação de dentro dele.
 *
 * `insertText` apagaria negrito e itálico do trecho junto com as letras. Mexer
 * nó a nó troca só o caractere, que é o que se pede ao clicar em "MAIÚSCULAS". */
function mudarCaixa(raiz: HTMLElement, transformar: (texto: string) => string) {
  const selecao = document.getSelection();
  if (!selecao || selecao.rangeCount === 0 || selecao.isCollapsed) return;
  const intervalo = selecao.getRangeAt(0);
  const caminhante = document.createTreeWalker(raiz, NodeFilter.SHOW_TEXT);
  const alvos: Text[] = [];
  for (let no = caminhante.nextNode(); no; no = caminhante.nextNode()) {
    if (no instanceof Text && intervalo.intersectsNode(no)) alvos.push(no);
  }
  for (const no of alvos) {
    const inicio = no === intervalo.startContainer ? intervalo.startOffset : 0;
    const fim = no === intervalo.endContainer ? intervalo.endOffset : (no.nodeValue ?? "").length;
    const texto = no.nodeValue ?? "";
    no.nodeValue = texto.slice(0, inicio) + transformar(texto.slice(inicio, fim)) + texto.slice(fim);
  }
}

/* ------------------------------------------------------------------ tabelas
 *
 * A tabela é uma `<table>` de verdade no editor e volta ao texto como Markdown
 * (ver `lib/formatacaoPeticao.ts`), que é o que o gerador do .docx converte em
 * tabela nativa do Word. Aqui ficam só os comandos: criar, e acrescentar ou
 * tirar linha e coluna depois de criada.
 */

/** A célula onde está o cursor, se houver uma. */
function celulaDaSelecao(raiz: HTMLElement): HTMLTableCellElement | null {
  const no = document.getSelection()?.anchorNode ?? null;
  if (!no || !raiz.contains(no)) return null;
  const elemento = no instanceof Element ? no : no.parentElement;
  const celula = elemento?.closest("th,td") ?? null;
  return celula instanceof HTMLTableCellElement ? celula : null;
}

/** Copia uma célula vazia com o mesmo estilo da vizinha — assim a grade não
 *  ganha uma casa sem borda no meio. */
function celulaVazia(modelo: HTMLTableCellElement, marca: "th" | "td"): HTMLTableCellElement {
  const nova = document.createElement(marca);
  nova.setAttribute("style", modelo.getAttribute("style") ?? "");
  nova.innerHTML = "<br>";
  return nova;
}

function mexerNaTabela(raiz: HTMLElement, acao: "linha+" | "linha-" | "coluna+" | "coluna-") {
  const celula = celulaDaSelecao(raiz);
  const tabela = celula?.closest("table");
  if (!celula || !(tabela instanceof HTMLTableElement)) return;
  const linha = celula.parentElement as HTMLTableRowElement | null;
  if (!linha) return;
  const corpo = tabela.tBodies[0];
  if (!corpo) return;

  if (acao === "linha+") {
    const modelo = corpo.rows[corpo.rows.length - 1] ?? linha;
    const nova = corpo.insertRow(linha.parentElement === corpo ? linha.rowIndex : corpo.rows.length);
    for (const celulaModelo of Array.from(modelo.cells)) nova.appendChild(celulaVazia(celulaModelo, "td"));
    return;
  }
  if (acao === "linha-") {
    // O cabeçalho não sai, e o corpo nunca fica vazio: sem nenhuma linha de
    // dados o gerador do .docx desiste da tabela e devolve as barras como texto.
    if (linha.parentElement !== corpo || corpo.rows.length <= 1) return;
    linha.remove();
    return;
  }
  const coluna = celula.cellIndex;
  if (acao === "coluna+") {
    for (const linhaDaTabela of Array.from(tabela.rows)) {
      const vizinha = linhaDaTabela.cells[Math.min(coluna, linhaDaTabela.cells.length - 1)];
      if (!vizinha) continue;
      const marca = vizinha.tagName === "TH" ? "th" : "td";
      linhaDaTabela.insertBefore(celulaVazia(vizinha, marca), linhaDaTabela.cells[coluna + 1] ?? null);
    }
    return;
  }
  // Duas colunas é o mínimo que o gerador reconhece como tabela.
  if (tabela.rows[0] && tabela.rows[0].cells.length <= 2) return;
  for (const linhaDaTabela of Array.from(tabela.rows)) {
    linhaDaTabela.cells[coluna]?.remove();
  }
}

/** Tab dentro da tabela anda de célula em célula, como no Word. Devolve `false`
 *  quando não havia tabela, para o Tab voltar a escrever uma tabulação. */
function andarNaTabela(raiz: HTMLElement, paraTras: boolean): boolean {
  const celula = celulaDaSelecao(raiz);
  const tabela = celula?.closest("table");
  if (!celula || !(tabela instanceof HTMLTableElement)) return false;
  const todas = Array.from(tabela.querySelectorAll<HTMLTableCellElement>("th,td"));
  const atual = todas.indexOf(celula);
  let alvo = todas[atual + (paraTras ? -1 : 1)];
  if (!alvo && !paraTras) {
    // Tab na última célula cria a linha seguinte — é como se preenche uma
    // cronologia sem tirar as mãos do teclado.
    mexerNaTabela(raiz, "linha+");
    alvo = Array.from(tabela.querySelectorAll<HTMLTableCellElement>("th,td")).pop() ?? null!;
  }
  if (!alvo) return false;
  const intervalo = document.createRange();
  intervalo.selectNodeContents(alvo);
  intervalo.collapse(true);
  const selecao = document.getSelection();
  selecao?.removeAllRanges();
  selecao?.addRange(intervalo);
  return true;
}

/** "Primeira Maiúscula", palavra a palavra. */
function primeiraMaiuscula(texto: string): string {
  return texto
    .toLocaleLowerCase("pt-BR")
    .replace(/(^|[\s(“"'\-—])(\p{L})/gu, (_todo, antes: string, letra: string) => antes + letra.toLocaleUpperCase("pt-BR"));
}

const CLASSE_BOTAO_BARRA =
  "inline-flex h-7 min-w-7 items-center justify-center gap-1 rounded-campo border border-borda-campo px-1.5 text-sm transition disabled:cursor-not-allowed disabled:opacity-40";

export function BarraDeFormatacao({
  ativo,
  aoAplicar,
}: {
  ativo: EstadoDaSelecao | null;
  /** Roda a ação sobre o campo em foco e avisa a tela do que mudou. */
  aoAplicar: (acao: (raiz: HTMLElement) => void) => void;
}) {
  const desabilitado = !ativo;
  const classe = (ligado?: boolean) =>
    `${CLASSE_BOTAO_BARRA} ${
      ligado ? "bg-acao text-nav-texto" : "bg-papel text-tinta hover:bg-papel-2"
    }`;

  return (
    /* `sticky`: a barra acompanha quem rola o documento. Sem isto, formatar um
       trecho do fim da peça obrigaria a subir até o topo a cada clique. */
    <div
      className="sticky top-0 z-10 flex flex-wrap items-center gap-1 rounded-campo border border-borda bg-papel px-2 py-1.5"
      role="toolbar"
      aria-label="Formatação do texto"
      /* A barra não pode roubar o cursor: sem isto, clicar em "negrito" tira o
         foco do documento e a seleção que se queria formatar deixa de existir.

         CUIDADO AO ACRESCENTAR CONTROLE AQUI: só BOTÃO funciona. O `<select>`
         nativo abre no `mousedown`, e este cancelamento cancela a abertura da
         lista junto — o menu fica morto ao mouse, sem erro nenhum no console.
         Foi o que matou, em silêncio, os controles de tamanho, de cor e de
         espaço entre parágrafos. Um menu, se voltar a ser preciso, tem de ser um
         painel de botões. */
      onMouseDown={(evento) => evento.preventDefault()}
    >
      {([
        ["undo", Undo2, "Desfazer (Ctrl+Z)"],
        ["redo", Redo2, "Refazer (Ctrl+Y)"],
      ] as const).map(([comando, Icone, rotulo]) => (
        <button
          key={comando}
          type="button"
          className={classe()}
          disabled={desabilitado}
          title={rotulo}
          onClick={() => aoAplicar(() => document.execCommand(comando))}
        >
          <Icone size={14} aria-hidden />
          <span className="sr-only">{rotulo}</span>
        </button>
      ))}

      <span className="mx-1 h-5 w-px bg-borda" aria-hidden />

      {([
        ["bold", Bold, "Negrito (Ctrl+B)", ativo?.negrito],
        ["italic", Italic, "Itálico (Ctrl+I)", ativo?.italico],
        ["underline", Underline, "Sublinhado (Ctrl+U)", ativo?.sublinhado],
        ["strikeThrough", Strikethrough, "Tachado", ativo?.tachado],
      ] as const).map(([comando, Icone, rotulo, ligado]) => (
        <button
          key={comando}
          type="button"
          className={classe(ligado)}
          disabled={desabilitado}
          aria-pressed={ligado ?? false}
          title={rotulo}
          onClick={() => aoAplicar(() => document.execCommand(comando))}
        >
          <Icone size={14} aria-hidden />
          <span className="sr-only">{rotulo}</span>
        </button>
      ))}

      <span className="mx-1 h-5 w-px bg-borda" aria-hidden />

      {([
        ["justifyLeft", AlignLeft, "Alinhar à esquerda"],
        ["justifyCenter", AlignCenter, "Centralizar"],
        ["justifyRight", AlignRight, "Alinhar à direita"],
        ["justifyFull", AlignJustify, "Justificar"],
      ] as const).map(([comando, Icone, rotulo]) => (
        <button
          key={comando}
          type="button"
          className={classe()}
          disabled={desabilitado}
          title={rotulo}
          onClick={() => aoAplicar(() => document.execCommand(comando))}
        >
          <Icone size={14} aria-hidden />
          <span className="sr-only">{rotulo}</span>
        </button>
      ))}

      <span className="mx-1 h-5 w-px bg-borda" aria-hidden />

      {/* Recuo do parágrafo inteiro. Não é `execCommand("indent")`: aquele
          embrulha o parágrafo num `<blockquote>`, que o leitor de formatação
          não entende e que se perderia ao gravar. */}
      <button
        type="button"
        className={classe()}
        disabled={desabilitado}
        title={`Aumentar recuo (${PASSO_DE_RECUO_CM} cm)`}
        onClick={() =>
          aoAplicar((raiz) =>
            mudarParagrafo(raiz, (atual) => ({
              esquerda: (atual.esquerda ?? 0) + PASSO_DE_RECUO_CM,
            })),
          )
        }
      >
        <IndentIncrease size={14} aria-hidden />
        <span className="sr-only">Aumentar recuo</span>
      </button>
      <button
        type="button"
        className={classe()}
        disabled={desabilitado}
        title={`Diminuir recuo (${PASSO_DE_RECUO_CM} cm)`}
        onClick={() =>
          aoAplicar((raiz) =>
            mudarParagrafo(raiz, (atual) => {
              const novo = (atual.esquerda ?? 0) - PASSO_DE_RECUO_CM;
              // Chegando a zero, o campo volta a `null`: a diferença é que zero
              // vence o recuo do modelo do escritório e `null` o respeita.
              return { esquerda: novo > 0.01 ? novo : null };
            }),
          )
        }
      >
        <IndentDecrease size={14} aria-hidden />
        <span className="sr-only">Diminuir recuo</span>
      </button>

      {/* Quebra de página. O jeito de pôr os pedidos numa folha nova sem encher a
          peça de linhas em branco — que se desfazem sozinhas quando o texto
          acima cresce ou a IA reescreve um parágrafo. */}
      <button
        type="button"
        className={classe()}
        disabled={desabilitado}
        title="Inserir quebra de página"
        onClick={() =>
          aoAplicar(() => document.execCommand("insertHTML", false, `${HTML_DA_QUEBRA}<div><br></div>`))
        }
      >
        <SeparatorHorizontal size={14} aria-hidden />
        <span className="sr-only">Inserir quebra de página</span>
      </button>

      {/* Tabela: cronologia, quadro de gastos, relação de documentos. O texto
          leva a tabela em Markdown e o gerador a converte em `w:tbl` nativa —
          ela sai do Word editável, não como imagem nem como texto alinhado a
          tabulação. */}
      <button
        type="button"
        className={classe()}
        disabled={desabilitado}
        title="Inserir tabela (3 colunas × 2 linhas)"
        onClick={() =>
          aoAplicar(() =>
            document.execCommand("insertHTML", false, `${htmlDeTabelaNova(3, 2)}<div><br></div>`),
          )
        }
      >
        <Table size={14} aria-hidden />
        <span className="sr-only">Inserir tabela</span>
      </button>

      {/* Só com o cursor dentro da tabela: quatro botões a mais na barra o tempo
          todo, para quem não está mexendo em tabela nenhuma, é ruído. */}
      {ativo?.naTabela && (
        <>
          {([
            ["linha+", Rows3, "Acrescentar linha"],
            ["linha-", Rows3, "Tirar esta linha"],
            ["coluna+", Columns3, "Acrescentar coluna"],
            ["coluna-", Columns3, "Tirar esta coluna"],
          ] as const).map(([acao, Icone, rotulo]) => (
            <button
              key={acao}
              type="button"
              className={classe()}
              title={rotulo}
              onClick={() => aoAplicar((raiz) => mexerNaTabela(raiz, acao))}
            >
              <Icone size={14} aria-hidden />
              <span className="text-[10px] font-semibold" aria-hidden>
                {acao.endsWith("+") ? "+" : "−"}
              </span>
              <span className="sr-only">{rotulo}</span>
            </button>
          ))}
        </>
      )}

      <span className="mx-1 h-5 w-px bg-borda" aria-hidden />

      <button
        type="button"
        className={classe()}
        disabled={desabilitado}
        title="MAIÚSCULAS"
        onClick={() => aoAplicar((raiz) => mudarCaixa(raiz, (t) => t.toLocaleUpperCase("pt-BR")))}
      >
        <CaseUpper size={14} aria-hidden />
        <span className="sr-only">Maiúsculas</span>
      </button>
      <button
        type="button"
        className={classe()}
        disabled={desabilitado}
        title="minúsculas"
        onClick={() => aoAplicar((raiz) => mudarCaixa(raiz, (t) => t.toLocaleLowerCase("pt-BR")))}
      >
        <CaseLower size={14} aria-hidden />
        <span className="sr-only">Minúsculas</span>
      </button>
      <button
        type="button"
        className={classe()}
        disabled={desabilitado}
        title="Primeira Maiúscula"
        onClick={() => aoAplicar((raiz) => mudarCaixa(raiz, primeiraMaiuscula))}
      >
        <span className="text-xs font-semibold" aria-hidden>
          Aa
        </span>
        <span className="sr-only">Primeira maiúscula</span>
      </button>

      <span className="mx-1 h-5 w-px bg-borda" aria-hidden />

      <button
        type="button"
        className={classe()}
        disabled={desabilitado}
        title="Limpar a formatação do trecho e do parágrafo"
        onClick={() =>
          aoAplicar((raiz) => {
            document.execCommand("removeFormat");
            for (const bloco of blocosDaSelecao(raiz)) {
              aplicarFormatoDeParagrafo(bloco, SEM_PARAGRAFO);
              bloco.style.removeProperty("text-align");
            }
          })
        }
      >
        <RemoveFormatting size={14} aria-hidden />
        <span className="sr-only">Limpar formatação</span>
      </button>
    </div>
  );
}

/** Os marcadores da régua: qual recuo cada um move e em que borda da faixa ele
 *  fica. O da primeira linha vai em cima, como no Word, porque ele anda por
 *  cima do marcador da margem esquerda e os dois não podem se cobrir. */
const MARCADORES = [
  { campo: "primeira", rotulo: "Recuo da primeira linha", topo: true },
  { campo: "esquerda", rotulo: "Recuo à esquerda", topo: false },
  { campo: "direita", rotulo: "Recuo à direita", topo: false },
] as const;

/**
 * A régua do documento: onde estão as margens e os recuos, em centímetros.
 *
 * Os três marcadores são os do Word — primeira linha, esquerda e direita — e
 * arrastar qualquer um deles muda o parágrafo onde está o cursor, não a peça
 * inteira. Sem cursor em lugar nenhum a régua aparece esmaecida: mostrar os
 * marcadores prontos para arrastar sem ter onde aplicar seria mentira.
 *
 * O arrasto gruda em meio centímetro, e `Alt` solta a grade para o ajuste fino
 * — o mesmo atalho do Word, pelo mesmo motivo: sem a grade, nenhum parágrafo
 * fica alinhado com o vizinho.
 */
export function ReguaDeTabulacao({
  ativo,
  aoAplicar,
}: {
  ativo: EstadoDaSelecao | null;
  aoAplicar: (acao: (raiz: HTMLElement) => void) => void;
}) {
  const faixa = useRef<HTMLDivElement>(null);
  const [arrastando, setArrastando] = useState<string | null>(null);
  const paragrafo = ativo?.paragrafo ?? SEM_PARAGRAFO;
  const esquerda = paragrafo.esquerda ?? 0;
  const direita = paragrafo.direita ?? 0;
  const primeira = paragrafo.primeira ?? 0;

  /** Onde cada marcador está, em centímetros medidos da margem esquerda. */
  const posicao = (campo: string): number => {
    if (campo === "esquerda") return esquerda;
    if (campo === "direita") return LARGURA_UTIL_CM - direita;
    return esquerda + primeira;
  };

  useEffect(() => {
    if (!arrastando) return;
    const mover = (evento: PointerEvent) => {
      const caixa = faixa.current?.getBoundingClientRect();
      if (!caixa || caixa.width === 0) return;
      const bruto = ((evento.clientX - caixa.left) / caixa.width) * LARGURA_UTIL_CM;
      const grade = evento.altKey ? 0.05 : 0.5;
      const cm = Math.round(Math.max(0, Math.min(LARGURA_UTIL_CM, bruto)) / grade) * grade;
      aoAplicar((raiz) =>
        mudarParagrafo(raiz, (efetivo) => {
          if (arrastando === "esquerda") {
            // Arrastar a margem esquerda leva a primeira linha junto, como no
            // Word: o que se está movendo é o parágrafo, e o deslocamento da
            // primeira linha é relativo a ele. Em zero o campo volta a `null`,
            // que aqui dá no mesmo — a peça não recua parágrafo à esquerda.
            return { esquerda: cm > 0.01 ? cm : null };
          }
          if (arrastando === "direita") {
            const recuo = LARGURA_UTIL_CM - cm;
            return { direita: recuo > 0.01 ? recuo : null };
          }
          // A primeira linha, ao contrário, é gravada SEMPRE, inclusive o zero:
          // a peça já entra com 1,25 cm de recuo vindo do estilo, e deixar o
          // campo em `null` devolveria justamente esse 1,25 cm que a pessoa
          // acabou de arrastar para fora.
          return { primeira: duasCasasCm(cm - (efetivo.esquerda ?? 0)) };
        }),
      );
    };
    const soltar = () => setArrastando(null);
    window.addEventListener("pointermove", mover);
    window.addEventListener("pointerup", soltar);
    window.addEventListener("pointercancel", soltar);
    return () => {
      window.removeEventListener("pointermove", mover);
      window.removeEventListener("pointerup", soltar);
      window.removeEventListener("pointercancel", soltar);
    };
  }, [arrastando, aoAplicar]);

  /** Teclado no marcador: quem não arrasta com o mouse move de 0,25 em 0,25. */
  const pelaTecla = (campo: string, passo: number) => {
    aoAplicar((raiz) =>
      mudarParagrafo(raiz, (efetivo) => {
        if (campo === "esquerda") {
          const novo = duasCasasCm((efetivo.esquerda ?? 0) + passo);
          return { esquerda: novo > 0.01 ? Math.min(novo, LARGURA_UTIL_CM) : null };
        }
        if (campo === "direita") {
          const novo = duasCasasCm((efetivo.direita ?? 0) - passo);
          return { direita: novo > 0.01 ? Math.min(novo, LARGURA_UTIL_CM) : null };
        }
        return { primeira: duasCasasCm((efetivo.primeira ?? 0) + passo) };
      }),
    );
  };

  const centimetros = Array.from({ length: Math.floor(LARGURA_UTIL_CM) + 1 }, (_, i) => i);

  return (
    <div
      className={`mb-3 select-none ${ativo ? "" : "opacity-45"}`}
      onMouseDown={(evento) => evento.preventDefault()}
    >
      <div
        ref={faixa}
        className="relative h-7 w-full border border-borda bg-papel-2"
        role="group"
        aria-label="Régua do documento, em centímetros"
      >
        {centimetros.map((cm) => (
          <span
            key={cm}
            className="pointer-events-none absolute top-0 flex h-full flex-col justify-between"
            style={{ left: `${(cm / LARGURA_UTIL_CM) * 100}%` }}
          >
            <span className="block h-1.5 w-px bg-tinta-3" aria-hidden />
            {/* O primeiro e o último número não são centrados na marca: metade
                deles cairia fora da régua e o "0" aparecia cortado ao meio. */}
            <span
              className={`block text-[9px] leading-none text-tinta-3 ${
                cm === 0 ? "" : cm === centimetros[centimetros.length - 1] ? "-translate-x-full" : "-translate-x-1/2"
              }`}
              aria-hidden
            >
              {cm}
            </span>
          </span>
        ))}
        {/* Meio centímetro: marca menor, sem número — é a grade a que o arrasto
            gruda, e sem ela ninguém enxerga onde o marcador vai parar. */}
        {centimetros.slice(0, -1).map((cm) => (
          <span
            key={`meio-${cm}`}
            className="pointer-events-none absolute top-0 block h-1 w-px bg-borda-forte"
            style={{ left: `${((cm + 0.5) / LARGURA_UTIL_CM) * 100}%` }}
            aria-hidden
          />
        ))}
        {MARCADORES.map(({ campo, rotulo, topo }) => (
          <button
            key={campo}
            type="button"
            role="slider"
            aria-label={rotulo}
            aria-valuemin={0}
            aria-valuemax={LARGURA_UTIL_CM}
            aria-valuenow={Number(posicao(campo).toFixed(2))}
            aria-valuetext={`${posicao(campo).toFixed(2).replace(".", ",")} cm`}
            disabled={!ativo}
            title={`${rotulo} — ${posicao(campo).toFixed(2).replace(".", ",")} cm`}
            className={`absolute h-3 w-3 -translate-x-1/2 border border-borda-forte bg-acao transition-colors disabled:cursor-not-allowed disabled:opacity-40 ${
              topo ? "top-0.5" : "bottom-0.5"
            } ${arrastando === campo ? "bg-tinta" : "hover:bg-tinta-2"}`}
            style={{
              left: `${(posicao(campo) / LARGURA_UTIL_CM) * 100}%`,
              clipPath: topo ? "polygon(50% 100%, 0 0, 100% 0)" : "polygon(50% 0, 0 100%, 100% 100%)",
              cursor: ativo ? "ew-resize" : undefined,
            }}
            onPointerDown={() => setArrastando(campo)}
            onKeyDown={(evento) => {
              const passo = evento.shiftKey ? 0.05 : 0.25;
              if (evento.key === "ArrowLeft") {
                evento.preventDefault();
                pelaTecla(campo, campo === "direita" ? passo : -passo);
              }
              if (evento.key === "ArrowRight") {
                evento.preventDefault();
                pelaTecla(campo, campo === "direita" ? -passo : passo);
              }
            }}
          />
        ))}
      </div>
      <p className="m-0 mt-1 text-[11px] text-tinta-3">
        {ativo
          ? `Parágrafo: esquerda ${esquerda.toFixed(2).replace(".", ",")} cm · primeira linha ${
              primeira >= 0 ? "" : "−"
            }${Math.abs(primeira).toFixed(2).replace(".", ",")} cm · direita ${direita
              .toFixed(2)
              .replace(".", ",")} cm. Segure Alt para o ajuste fino.`
          : "Clique num parágrafo da peça para usar a régua."}
      </p>
    </div>
  );
}

/**
 * Um título da peça, editável no lugar onde ele aparece.
 *
 * O nome da peça e o título de cada tópico ("DO CONTRATO DE TRABALHO") eram os
 * únicos textos do documento que não davam para tocar: vinham da IA e só a IA
 * podia trocar. Só que o título do tópico VAI para o .docx como parágrafo em
 * negrito — mudá-lo é editar a peça, não a tela.
 *
 * NÃO é um `CampoDoDocumento`. Título não tem negrito, alinhamento próprio nem
 * parágrafo: é uma linha de texto puro, e é assim que ele viaja — `label` da
 * seção ou `title` da peça, sem passar pelas marcações de `formatacaoPeticao`.
 * Por isso também não avisa a barra de formatação: não há o que ela aplique
 * aqui, e deixá-la ativa sobre um título prometeria o que não se cumpre.
 */
export function CampoDeTitulo({
  valor,
  rotulo,
  centralizado = false,
  onEditar,
}: {
  valor: string;
  rotulo: string;
  centralizado?: boolean;
  onEditar: (valor: string) => void;
}) {
  const campo = useRef<HTMLDivElement>(null);
  /** Mesmo motivo do `CampoDoDocumento`: reescrever o nó a cada tecla mataria o
   *  cursor. Só o texto que veio de FORA (revisão, chat) redesenha o campo. */
  const ultimoEmitido = useRef<string | null>(null);

  useEffect(() => {
    const elemento = campo.current;
    if (!elemento || valor === ultimoEmitido.current) return;
    elemento.textContent = valor;
    ultimoEmitido.current = valor;
  }, [valor]);

  const emitir = useCallback(() => {
    const elemento = campo.current;
    if (!elemento) return;
    // Uma linha só: o que o navegador inserir como quebra vira espaço, e o
    // título nunca chega ao .docx partido em dois parágrafos.
    const texto = (elemento.textContent ?? "").replace(/\s+/g, " ").trim();
    ultimoEmitido.current = texto;
    onEditar(texto);
  }, [onEditar]);

  return (
    <div
      ref={campo}
      role="textbox"
      aria-label={rotulo}
      contentEditable
      suppressContentEditableWarning
      onInput={emitir}
      onBlur={emitir}
      /* Enter no título salta para o texto em vez de criar uma segunda linha —
         é o que se espera de um cabeçalho, e evita o parágrafo fantasma que
         `contentEditable` criaria. */
      onKeyDown={(evento) => {
        if (evento.key !== "Enter") return;
        evento.preventDefault();
        evento.currentTarget.blur();
      }}
      onPaste={(evento) => {
        evento.preventDefault();
        const texto = evento.clipboardData.getData("text/plain").replace(/\s+/g, " ").trim();
        document.execCommand("insertText", false, texto);
      }}
      /* `empty:before`: um título apagado vira uma linha invisível e ninguém
         acha onde clicar para escrever de novo. */
      className={`w-full border-0 bg-transparent p-0 text-sm font-bold uppercase tracking-wide text-tinta focus:outline-none focus:bg-papel-2 empty:before:content-[attr(data-vazio)] empty:before:text-tinta-3 empty:before:font-normal empty:before:normal-case ${
        centralizado ? "text-center" : "text-left"
      }`}
      data-vazio={`${rotulo} (sem título)`}
    />
  );
}

/** Uma seção do documento, editável e formatável.
 *
 * A altura acompanha o conteúdo por natureza — é um `div`, não uma caixa com
 * rolagem própria. Caixa que rola dentro de página que também rola era o que
 * tornava a revisão penosa: dois scrolls concorrentes, e a pessoa perdia o
 * lugar entre eles.
 */
export function CampoDoDocumento({
  valor,
  rotulo,
  formato = "corpo",
  onEditar,
  onFoco,
}: {
  valor: string;
  rotulo: string;
  formato?: "corpo" | "fechamento" | "enderecamento";
  onEditar: (valor: string) => void;
  /** Avisa qual campo está sob o cursor, para a barra saber onde aplicar. */
  onFoco?: (campo: HTMLDivElement | null) => void;
}) {
  const campo = useRef<HTMLDivElement>(null);
  /** O último texto que ESTE campo produziu. Serve para distinguir a mudança que
   *  veio de quem digita (o HTML já está certo, mexer nele mataria o cursor) da
   *  que veio de fora — revisão por prompt, chat, desfazer — que precisa
   *  redesenhar o documento inteiro. */
  const ultimoEmitido = useRef<string | null>(null);

  useEffect(() => {
    const elemento = campo.current;
    if (!elemento || valor === ultimoEmitido.current) return;
    elemento.innerHTML = paraHtml(valor);
    ultimoEmitido.current = valor;
  }, [valor]);

  const emitir = useCallback(() => {
    const elemento = campo.current;
    if (!elemento) return;
    const texto = paraTexto(elemento);
    ultimoEmitido.current = texto;
    onEditar(texto);
  }, [onEditar]);

  return (
    <div
      ref={campo}
      role="textbox"
      aria-multiline="true"
      aria-label={rotulo}
      contentEditable
      suppressContentEditableWarning
      onInput={emitir}
      onFocus={() => onFoco?.(campo.current)}
      onBlur={() => {
        // Emitir no blur também: o `execCommand` da barra muda o DOM sem
        // disparar `input` em todos os navegadores, e uma formatação aplicada e
        // não emitida se perderia ao recarregar.
        emitir();
        onFoco?.(null);
      }}
      /* Tab escreve uma tabulação em vez de pular para o próximo campo — mas
         DENTRO de uma tabela ele anda de célula em célula, como no Word, e na
         última célula cria a linha seguinte. Shift+Tab fora da tabela continua
         saindo do documento: quem navega por teclado precisa de uma saída, e o
         recuo do parágrafo está na barra e na régua. */
      onKeyDown={(evento) => {
        if (evento.key !== "Tab") return;
        const raiz = campo.current;
        if (raiz && andarNaTabela(raiz, evento.shiftKey)) {
          evento.preventDefault();
          return;
        }
        if (evento.shiftKey) return;
        evento.preventDefault();
        document.execCommand("insertText", false, "\t");
      }}
      /* Colar de um .docx traz fonte, cor de fundo e tabela da origem: entra só
         o texto, e a formatação é a que se aplica aqui.

         A EXCEÇÃO é a tabela. Quem copia uma cronologia da conversa está colando
         Markdown; entrando como texto puro, ela apareceria como um monte de
         barras até a próxima recarga da tela — o texto gravado até estaria
         certo, mas ninguém confia no que não vê. Desenhada na hora, a tabela
         entra no ponto exato em que o cursor estava. */
      onPaste={(evento) => {
        evento.preventDefault();
        const texto = evento.clipboardData.getData("text/plain");
        if (temTabelaMarkdown(texto)) {
          document.execCommand("insertHTML", false, paraHtml(texto));
          return;
        }
        document.execCommand("insertText", false, texto);
      }}
      /* `break-spaces`: no `pre-wrap` os espaços do fim da linha ficam
         pendurados para fora da caixa em vez de quebrar — era o texto saindo do
         quadro ao segurar a barra de espaço. `tab-size`: a tabulação digitada
         precisa de uma largura, senão o navegador a desenha como um espaço só. */
      className={`w-full border-0 bg-transparent p-0 font-titulo text-tinta focus:outline-none [white-space:break-spaces] [overflow-wrap:anywhere] [tab-size:4] ${
        formato === "fechamento" || formato === "enderecamento"
          ? "text-center"
          : "text-justify [text-indent:1.25cm]"
      }`}
    />
  );
}

/** Acompanha o que está selecionado para a barra e a régua mostrarem o que já
 *  está ligado, e onde os recuos do parágrafo estão. */
export function useSelecaoFormatada(campoAtivo: HTMLDivElement | null): EstadoDaSelecao | null {
  const [estado, setEstado] = useState<EstadoDaSelecao | null>(null);

  useEffect(() => {
    if (!campoAtivo || !comandoPossivel()) {
      setEstado(null);
      return;
    }
    const conferir = () => {
      setEstado({
        negrito: document.queryCommandState("bold"),
        italico: document.queryCommandState("italic"),
        sublinhado: document.queryCommandState("underline"),
        tachado: document.queryCommandState("strikeThrough"),
        paragrafo: paragrafoDaSelecao(campoAtivo),
        naTabela: celulaDaSelecao(campoAtivo) !== null,
      });
    };
    conferir();
    document.addEventListener("selectionchange", conferir);
    // `input` também: arrastar um marcador da régua muda o estilo do parágrafo
    // sem mexer na seleção, então o `selectionchange` não dispara e os
    // marcadores ficariam parados enquanto o texto anda embaixo deles. Quem
    // aplica já avisa por este evento (ver o `aplicar` da tela da petição).
    campoAtivo.addEventListener("input", conferir);
    return () => {
      document.removeEventListener("selectionchange", conferir);
      campoAtivo.removeEventListener("input", conferir);
    };
  }, [campoAtivo]);

  return estado;
}
