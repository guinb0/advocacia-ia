/**
 * A ponte entre o que se vê no editor e o que fica gravado na seção.
 *
 * A petição é TEXTO — é assim que ela atravessa versão, histórico, comparação
 * antes × depois, revisão por prompt e chat. A formatação que o advogado aplica
 * na tela viaja dentro desse mesmo texto, como marcações, e só o gerador do
 * .docx (`app/peticao_local.py`) sabe o que elas significam:
 *
 *   **negrito**                        (já existia, vindo da IA)
 *   [[i]]…[[/i]]   [[u]]…[[/u]]        itálico, sublinhado
 *   [[alin=centro]] no início da linha esquerda | centro | direita | justificado
 *
 * `[[tam=14]]` e `[[cor=#c00000]]` continuam sendo LIDOS, nunca escritos: a
 * barra não oferece mais tamanho nem cor, mas peças gravadas antes disso têm
 * essas marcações no texto e, sem interpretá-las, elas apareceriam cruas na
 * tela do advogado.
 *
 * As duas funções aqui precisam ser inversas uma da outra: o que o editor
 * escreve tem de voltar igual ao ser reaberto, senão editar duas vezes deforma
 * a peça.
 */

export type Alinhamento = "esquerda" | "centro" | "direita" | "justificado";

const ALINHAMENTO_CSS: Record<Alinhamento, string> = {
  esquerda: "left",
  centro: "center",
  direita: "right",
  justificado: "justify",
};

const CSS_ALINHAMENTO: Record<string, Alinhamento> = {
  left: "esquerda",
  center: "centro",
  right: "direita",
  justify: "justificado",
  start: "esquerda",
  end: "direita",
};

const TAMANHO_MIN_PT = 6;
const TAMANHO_MAX_PT = 72;

const RE_MARCACAO = /\*\*|\[\[(\/?)(i|u|tam|cor)(?:=([^\]\s]*))?\]\]/g;
const RE_ALINHAMENTO = /^\s*\[\[alin=(esquerda|centro|direita|justificado)\]\]/;
const RE_COR = /^#?[0-9a-fA-F]{6}$/;

type Formato = {
  negrito: boolean;
  italico: boolean;
  sublinhado: boolean;
  tamanho: number | null;
  cor: string | null;
};

const SEM_FORMATO: Formato = {
  negrito: false,
  italico: false,
  sublinhado: false,
  tamanho: null,
  cor: null,
};

function mesmoFormato(a: Formato, b: Formato): boolean {
  return (
    a.negrito === b.negrito &&
    a.italico === b.italico &&
    a.sublinhado === b.sublinhado &&
    a.tamanho === b.tamanho &&
    a.cor === b.cor
  );
}

function escaparHtml(texto: string): string {
  return texto
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

/** Quebra uma linha (já sem o `[[alin]]`) nos trechos e seus formatos. */
function trechosDaLinha(linha: string): { texto: string; formato: Formato }[] {
  const marcas = [...linha.matchAll(RE_MARCACAO)];
  // `**` sem par é texto solto, não abertura de negrito: tratá-lo como abertura
  // deixaria o resto da linha em negrito até o fim. O gerador do .docx faz o
  // mesmo — o marcador ímpar simplesmente some.
  const negritos = marcas.filter((m) => m[0] === "**");
  const semPar = negritos.length % 2 ? negritos[negritos.length - 1] : null;

  let negrito = false;
  let italico = false;
  let sublinhado = false;
  const tamanhos: number[] = [];
  const cores: string[] = [];
  const saida: { texto: string; formato: Formato }[] = [];

  const emitir = (texto: string) => {
    if (!texto) return;
    const formato: Formato = {
      negrito,
      italico,
      sublinhado,
      tamanho: tamanhos.length ? tamanhos[tamanhos.length - 1] : null,
      cor: cores.length ? cores[cores.length - 1] : null,
    };
    const ultimo = saida[saida.length - 1];
    if (ultimo && mesmoFormato(ultimo.formato, formato)) ultimo.texto += texto;
    else saida.push({ texto, formato });
  };

  let posicao = 0;
  for (const marca of marcas) {
    emitir(linha.slice(posicao, marca.index));
    posicao = marca.index + marca[0].length;
    if (marca[0] === "**") {
      if (marca !== semPar) negrito = !negrito;
      continue;
    }
    const fechando = marca[1] === "/";
    const nome = marca[2];
    const valor = marca[3];
    if (nome === "i") italico = !fechando;
    else if (nome === "u") sublinhado = !fechando;
    else if (nome === "tam") {
      if (fechando) tamanhos.pop();
      else {
        const numero = Number(valor);
        if (Number.isFinite(numero) && numero > 0) {
          tamanhos.push(Math.max(TAMANHO_MIN_PT, Math.min(TAMANHO_MAX_PT, numero)));
        }
      }
    } else if (nome === "cor") {
      if (fechando) cores.pop();
      else if (valor && RE_COR.test(valor)) cores.push(`#${valor.replace("#", "").toUpperCase()}`);
    }
  }
  emitir(linha.slice(posicao));
  return saida;
}

/** O texto da seção como HTML para o editor: uma `<div>` por linha. */
export function paraHtml(texto: string): string {
  return (texto || "")
    .split("\n")
    .map((linhaBruta) => {
      const achado = RE_ALINHAMENTO.exec(linhaBruta);
      const linha = achado ? linhaBruta.slice(achado[0].length) : linhaBruta;
      const estilo = achado ? ` style="text-align:${ALINHAMENTO_CSS[achado[1] as Alinhamento]}"` : "";
      const trechos = trechosDaLinha(linha);
      // `<br>` para a linha vazia não sumir: `<div></div>` tem altura zero e o
      // parágrafo em branco entre blocos desapareceria da tela.
      if (!trechos.length) return `<div${estilo}><br></div>`;
      const corpo = trechos
        .map(({ texto: pedaco, formato }) => {
          const estilos: string[] = [];
          if (formato.tamanho) estilos.push(`font-size:${formato.tamanho}pt`);
          if (formato.cor) estilos.push(`color:${formato.cor}`);
          let html = escaparHtml(pedaco);
          if (formato.sublinhado) html = `<u>${html}</u>`;
          if (formato.italico) html = `<i>${html}</i>`;
          if (formato.negrito) html = `<b>${html}</b>`;
          return estilos.length ? `<span style="${estilos.join(";")}">${html}</span>` : html;
        })
        .join("");
      return `<div${estilo}>${corpo}</div>`;
    })
    .join("");
}

/** O texto sem nenhuma marcação, para onde se LÊ a peça em vez de editá-la —
 *  a comparação entre versões, por exemplo. Sem isto, um trecho formatado
 *  apareceria ali como `[[i]]assim[[/i]]`, e uma mudança só de formatação
 *  contaria como palavra alterada na revisão da IA. */
export function semMarcacao(texto: string): string {
  return (texto || "")
    .split("\n")
    .map((linha) => {
      const achado = RE_ALINHAMENTO.exec(linha);
      const resto = achado ? linha.slice(achado[0].length) : linha;
      return trechosDaLinha(resto)
        .map(({ texto: pedaco }) => pedaco)
        .join("");
    })
    .join("\n");
}

function corParaHex(cor: string): string | null {
  const rgb = /^rgba?\((\d+),\s*(\d+),\s*(\d+)/.exec(cor);
  if (rgb) {
    const hex = [rgb[1], rgb[2], rgb[3]]
      .map((n) => Number(n).toString(16).padStart(2, "0"))
      .join("");
    return `#${hex.toUpperCase()}`;
  }
  if (/^#[0-9a-fA-F]{6}$/.test(cor)) return cor.toUpperCase();
  if (/^#[0-9a-fA-F]{3}$/.test(cor)) {
    return `#${cor.slice(1).split("").map((c) => c + c).join("").toUpperCase()}`;
  }
  return null;
}

/** O formato de um nó de texto, olhando os ancestrais até o bloco da linha. */
function formatoDoNo(no: Node, limite: Element): Formato {
  const formato: Formato = { ...SEM_FORMATO };
  let atual: Node | null = no.parentElement;
  while (atual && atual !== limite.parentElement) {
    if (atual instanceof HTMLElement) {
      const tag = atual.tagName;
      if (tag === "B" || tag === "STRONG") formato.negrito = true;
      if (tag === "I" || tag === "EM") formato.italico = true;
      if (tag === "U") formato.sublinhado = true;
      const estilo = atual.style;
      // O navegador escreve o negrito ora como `<b>`, ora como `font-weight`,
      // conforme o `styleWithCSS`; ler os dois evita perder a formatação.
      if (estilo.fontWeight === "bold" || Number(estilo.fontWeight) >= 600) formato.negrito = true;
      if (estilo.fontStyle === "italic") formato.italico = true;
      if (estilo.textDecorationLine?.includes("underline") || estilo.textDecoration?.includes("underline")) {
        formato.sublinhado = true;
      }
      if (formato.cor === null && estilo.color) formato.cor = corParaHex(estilo.color);
      if (formato.tamanho === null && estilo.fontSize) {
        const pt = /^([\d.]+)pt$/.exec(estilo.fontSize);
        const px = /^([\d.]+)px$/.exec(estilo.fontSize);
        const valor = pt ? Number(pt[1]) : px ? Number(px[1]) * 0.75 : NaN;
        if (Number.isFinite(valor)) {
          formato.tamanho = Math.round(Math.max(TAMANHO_MIN_PT, Math.min(TAMANHO_MAX_PT, valor)) * 10) / 10;
        }
      }
    }
    if (atual === limite) break;
    atual = atual.parentElement;
  }
  return formato;
}

function marcar(texto: string, formato: Formato): string {
  let saida = texto;
  if (formato.negrito) saida = `**${saida}**`;
  if (formato.italico) saida = `[[i]]${saida}[[/i]]`;
  if (formato.sublinhado) saida = `[[u]]${saida}[[/u]]`;
  if (formato.tamanho) saida = `[[tam=${formato.tamanho}]]${saida}[[/tam]]`;
  if (formato.cor) saida = `[[cor=${formato.cor}]]${saida}[[/cor]]`;
  return saida;
}

/** Uma linha do editor de volta a texto com marcações. */
function linhaParaTexto(bloco: Element): string {
  const trechos: { texto: string; formato: Formato }[] = [];
  const caminhante = document.createTreeWalker(bloco, NodeFilter.SHOW_TEXT);
  for (let no = caminhante.nextNode(); no; no = caminhante.nextNode()) {
    const texto = no.nodeValue ?? "";
    if (!texto) continue;
    const formato = formatoDoNo(no, bloco);
    const ultimo = trechos[trechos.length - 1];
    if (ultimo && mesmoFormato(ultimo.formato, formato)) ultimo.texto += texto;
    else trechos.push({ texto, formato });
  }
  const corpo = trechos
    // Espaço em branco não carrega formatação visível e, marcado, encheria o
    // texto de `[[i]] [[/i]]` que a IA teria de copiar sem motivo.
    .map(({ texto, formato }) => (texto.trim() ? marcar(texto, formato) : texto))
    .join("");
  const alinhamento =
    bloco instanceof HTMLElement ? CSS_ALINHAMENTO[bloco.style.textAlign] : undefined;
  // ` `: o navegador põe espaço-duro ao digitar espaços seguidos. No texto
  // gravado ele viraria um caractere invisível diferente, que o Word mostra mas
  // ninguém consegue procurar nem apagar.
  const limpo = corpo.replace(/ /g, " ");
  return alinhamento && limpo.trim() ? `[[alin=${alinhamento}]]${limpo}` : limpo;
}

/** O conteúdo do editor de volta ao texto da seção. */
export function paraTexto(raiz: HTMLElement): string {
  const linhas: string[] = [];
  let soltos: Node[] = [];

  const descarregarSoltos = () => {
    if (!soltos.length) return;
    // Texto digitado direto na raiz (acontece quando o editor está vazio) não
    // tem bloco: monta-se um temporário só para ler, sem tocar no documento.
    const caixa = document.createElement("div");
    for (const no of soltos) caixa.appendChild(no.cloneNode(true));
    linhas.push(linhaParaTexto(caixa));
    soltos = [];
  };

  for (const no of Array.from(raiz.childNodes)) {
    if (no instanceof HTMLElement && no.tagName === "BR") {
      descarregarSoltos();
      linhas.push("");
      continue;
    }
    if (no instanceof HTMLElement && ["DIV", "P", "LI", "BLOCKQUOTE", "H1", "H2", "H3"].includes(no.tagName)) {
      descarregarSoltos();
      linhas.push(linhaParaTexto(no));
      continue;
    }
    soltos.push(no);
  }
  descarregarSoltos();
  return linhas.join("\n");
}
