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
 *   [[s]]…[[/s]]                       tachado
 *   uma tabulação literal (\t)         parada de tabulação dentro da linha
 *   [[alin=centro]]                    no início da linha
 *   [[par=esq:2;pri:-1.25;dir:0]]      no início da linha: os recuos
 *   [[pagina]]                         sozinho na linha: quebra de página
 *
 * `[[tam=14]]` e `[[cor=#c00000]]` continuam sendo LIDOS, nunca escritos: a
 * barra não oferece mais tamanho nem cor, mas peças gravadas antes disso têm
 * essas marcações no texto e, sem interpretá-las, elas apareceriam cruas na
 * tela do advogado.
 *
 * POR QUE `[[par]]` É SEPARADO DE `[[alin]]`
 *
 * `[[alin]]` já existia dos dois lados da ponte — tela e gerador do .docx — e
 * há peças gravadas com ele. Dobrar o significado de um marcador em uso obriga
 * a mudar os dois leitores no mesmo instante, sob pena de uma peça antiga abrir
 * errada. O marcador novo carrega só o que é novo, e os dois convivem.
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

/** Os limites dos recuos, em centímetros. O recuo da primeira linha aceita
 *  negativo: é o "deslocamento" do Word, com a primeira linha saindo à esquerda
 *  do resto do parágrafo — a forma de escrever "a) …" com o texto alinhado. */
export const RECUO_MAX_CM = 10;
export const RECUO_PRIMEIRA_MIN_CM = -5;

const RE_MARCACAO = /\*\*|\[\[(\/?)(i|u|s|tam|cor)(?:=([^\]\s]*))?\]\]/g;
const RE_ALINHAMENTO = /^\s*\[\[alin=(esquerda|centro|direita|justificado)\]\]/;
const RE_PARAGRAFO = /^\s*\[\[par=([^\]]*)\]\]/;
const RE_COR = /^#?[0-9a-fA-F]{6}$/;

/** Quebra de página: a linha inteira é o marcador, e nada mais cabe nela. */
const RE_QUEBRA = /^\s*\[\[pagina\]\]\s*$/;
export const MARCA_DE_QUEBRA = "[[pagina]]";

/** A quebra desenhada na prévia.
 *
 * `contenteditable="false"`: quebra não é texto e não se digita dentro dela —
 * sem isto o cursor entra no bloco e o que se escrever ali some ao gravar.
 * Estilo embutido, e não classe: este HTML nasce de uma string em tempo de
 * execução, que o gerador de CSS não varre. */
export const HTML_DA_QUEBRA =
  '<div data-quebra="1" contenteditable="false" style="margin:12pt 0;border-top:1px dashed currentColor;' +
  'opacity:.45;text-align:center;font-size:9pt;text-indent:0;user-select:none">Quebra de página</div>';

type Formato = {
  negrito: boolean;
  italico: boolean;
  sublinhado: boolean;
  tachado: boolean;
  tamanho: number | null;
  cor: string | null;
};

const SEM_FORMATO: Formato = {
  negrito: false,
  italico: false,
  sublinhado: false,
  tachado: false,
  tamanho: null,
  cor: null,
};

/** O que se ajusta num parágrafo inteiro. `null` em qualquer campo significa
 *  "o padrão da peça" — e é diferente de zero: zero é uma escolha, e vale
 *  contra o padrão configurado no modelo do escritório. */
export type FormatoDeParagrafo = {
  esquerda: number | null;
  primeira: number | null;
  direita: number | null;
};

export const SEM_PARAGRAFO: FormatoDeParagrafo = {
  esquerda: null,
  primeira: null,
  direita: null,
};

/** As chaves do marcador `[[par=…]]`, na ordem em que são escritas. */
const CAMPOS_DE_PARAGRAFO = [
  ["esq", "esquerda"],
  ["pri", "primeira"],
  ["dir", "direita"],
] as const;

function numeroOuNulo(texto: string | undefined): number | null {
  if (texto === undefined || texto.trim() === "") return null;
  const valor = Number(texto);
  return Number.isFinite(valor) ? valor : null;
}

function limitar(valor: number, minimo: number, maximo: number): number {
  return Math.max(minimo, Math.min(maximo, valor));
}

/** Arredonda para duas casas: sem isto, arrastar a régua grava `1.2500000003`
 *  e o texto da peça muda a cada arrasto sem nada ter mudado de verdade. */
function duasCasas(valor: number): number {
  return Math.round(valor * 100) / 100;
}

function normalizarParagrafo(bruto: FormatoDeParagrafo): FormatoDeParagrafo {
  return {
    esquerda: bruto.esquerda === null ? null : duasCasas(limitar(bruto.esquerda, 0, RECUO_MAX_CM)),
    primeira:
      bruto.primeira === null
        ? null
        : duasCasas(limitar(bruto.primeira, RECUO_PRIMEIRA_MIN_CM, RECUO_MAX_CM)),
    direita: bruto.direita === null ? null : duasCasas(limitar(bruto.direita, 0, RECUO_MAX_CM)),
  };
}

function lerParagrafo(corpo: string): FormatoDeParagrafo {
  const valores = new Map<string, string>();
  for (const par of corpo.split(";")) {
    const [chave, valor] = par.split(":");
    if (chave && valor !== undefined) valores.set(chave.trim(), valor.trim());
  }
  const bruto = { ...SEM_PARAGRAFO };
  for (const [chave, campo] of CAMPOS_DE_PARAGRAFO) {
    bruto[campo] = numeroOuNulo(valores.get(chave));
  }
  return normalizarParagrafo(bruto);
}

function escreverParagrafo(formato: FormatoDeParagrafo): string {
  const partes = CAMPOS_DE_PARAGRAFO.filter(([, campo]) => formato[campo] !== null).map(
    ([chave, campo]) => `${chave}:${formato[campo]}`,
  );
  return partes.length ? `[[par=${partes.join(";")}]]` : "";
}

/** Tira do início da linha os marcadores que valem para o parágrafo inteiro.
 *
 * Aceita-os em qualquer ordem e em qualquer quantidade: o que o editor escreve
 * é sempre `[[alin]]` e depois `[[par]]`, mas um texto vindo do chat ou de uma
 * revisão da IA pode chegar na outra ordem, e a linha não pode abrir com o
 * marcador aparecendo cru. */
function separarMarcadoresDeLinha(linha: string): {
  alinhamento: Alinhamento | null;
  paragrafo: FormatoDeParagrafo;
  resto: string;
} {
  let resto = linha;
  let alinhamento: Alinhamento | null = null;
  let paragrafo = { ...SEM_PARAGRAFO };
  for (;;) {
    const alin = RE_ALINHAMENTO.exec(resto);
    if (alin) {
      alinhamento = alin[1] as Alinhamento;
      resto = resto.slice(alin[0].length);
      continue;
    }
    const par = RE_PARAGRAFO.exec(resto);
    if (par) {
      paragrafo = lerParagrafo(par[1]);
      resto = resto.slice(par[0].length);
      continue;
    }
    break;
  }
  return { alinhamento, paragrafo, resto };
}

function estilosDoParagrafo(
  alinhamento: Alinhamento | null,
  paragrafo: FormatoDeParagrafo,
): string {
  const estilos: string[] = [];
  if (alinhamento) estilos.push(`text-align:${ALINHAMENTO_CSS[alinhamento]}`);
  if (paragrafo.esquerda !== null) estilos.push(`margin-left:${paragrafo.esquerda}cm`);
  if (paragrafo.direita !== null) estilos.push(`margin-right:${paragrafo.direita}cm`);
  if (paragrafo.primeira !== null) estilos.push(`text-indent:${paragrafo.primeira}cm`);
  return estilos.length ? ` style="${estilos.join(";")}"` : "";
}

function escaparHtml(texto: string): string {
  return texto
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function mesmoFormato(a: Formato, b: Formato): boolean {
  return (
    a.negrito === b.negrito &&
    a.italico === b.italico &&
    a.sublinhado === b.sublinhado &&
    a.tachado === b.tachado &&
    a.tamanho === b.tamanho &&
    a.cor === b.cor
  );
}

/** Quebra uma linha (já sem os marcadores de parágrafo) nos trechos e formatos. */
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
  let tachado = false;
  const tamanhos: number[] = [];
  const cores: string[] = [];
  const saida: { texto: string; formato: Formato }[] = [];

  const emitir = (texto: string) => {
    if (!texto) return;
    const formato: Formato = {
      negrito,
      italico,
      sublinhado,
      tachado,
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
    else if (nome === "s") tachado = !fechando;
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
      if (RE_QUEBRA.test(linhaBruta)) return HTML_DA_QUEBRA;
      const { alinhamento, paragrafo, resto } = separarMarcadoresDeLinha(linhaBruta);
      const estilo = estilosDoParagrafo(alinhamento, paragrafo);
      const trechos = trechosDaLinha(resto);
      // `<br>` para a linha vazia não sumir: `<div></div>` tem altura zero e o
      // parágrafo em branco entre blocos desapareceria da tela.
      if (!trechos.length) return `<div${estilo}><br></div>`;
      const corpo = trechos
        .map(({ texto: pedaco, formato }) => {
          const estilos: string[] = [];
          if (formato.tamanho) estilos.push(`font-size:${formato.tamanho}pt`);
          if (formato.cor) estilos.push(`color:${formato.cor}`);
          let html = escaparHtml(pedaco);
          if (formato.tachado) html = `<s>${html}</s>`;
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
    .map((linha) =>
      RE_QUEBRA.test(linha)
        ? ""
        : trechosDaLinha(separarMarcadoresDeLinha(linha).resto)
            .map(({ texto: pedaco }) => pedaco)
            .join(""),
    )
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
      if (tag === "S" || tag === "STRIKE" || tag === "DEL") formato.tachado = true;
      const estilo = atual.style;
      // O navegador escreve o negrito ora como `<b>`, ora como `font-weight`,
      // conforme o `styleWithCSS`; ler os dois evita perder a formatação.
      if (estilo.fontWeight === "bold" || Number(estilo.fontWeight) >= 600) formato.negrito = true;
      if (estilo.fontStyle === "italic") formato.italico = true;
      // Sublinhado e tachado moram na MESMA propriedade quando o navegador
      // escreve por CSS (`text-decoration: underline line-through`): ler uma e
      // ignorar a outra apagava o tachado ao gravar.
      const decoracao = `${estilo.textDecorationLine || ""} ${estilo.textDecoration || ""}`;
      if (decoracao.includes("underline")) formato.sublinhado = true;
      if (decoracao.includes("line-through")) formato.tachado = true;
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
  if (formato.tachado) saida = `[[s]]${saida}[[/s]]`;
  if (formato.tamanho) saida = `[[tam=${formato.tamanho}]]${saida}[[/tam]]`;
  if (formato.cor) saida = `[[cor=${formato.cor}]]${saida}[[/cor]]`;
  return saida;
}

/** Lê em centímetros uma medida escrita no estilo do bloco. O navegador devolve
 *  a unidade como ela foi escrita — e é sempre este módulo que a escreve —, mas
 *  um texto colado pode trazer `px`, e cair para zero seria pior que converter. */
function paraCentimetros(medida: string): number | null {
  const achado = /^(-?[\d.]+)(cm|mm|in|pt|px)$/.exec(medida.trim());
  if (!achado) return null;
  const valor = Number(achado[1]);
  if (!Number.isFinite(valor)) return null;
  const emCm: Record<string, number> = { cm: 1, mm: 0.1, in: 2.54, pt: 2.54 / 72, px: 2.54 / 96 };
  return duasCasas(valor * emCm[achado[2]]);
}

/** O formato de parágrafo de um bloco do editor. */
export function formatoDeParagrafoDoBloco(bloco: Element): FormatoDeParagrafo {
  if (!(bloco instanceof HTMLElement)) return { ...SEM_PARAGRAFO };
  const estilo = bloco.style;
  return normalizarParagrafo({
    esquerda: estilo.marginLeft ? paraCentimetros(estilo.marginLeft) : null,
    primeira: estilo.textIndent ? paraCentimetros(estilo.textIndent) : null,
    direita: estilo.marginRight ? paraCentimetros(estilo.marginRight) : null,
  });
}

/**
 * O formato de parágrafo COMO ELE APARECE, somando o que a peça já impunha.
 *
 * `formatoDeParagrafoDoBloco` lê o que está escrito NAQUELE parágrafo, que é o
 * que precisa voltar ao texto; este lê o que a pessoa enxerga. Os dois são
 * diferentes e os dois são necessários: o corpo da peça já entra com 1,25 cm de
 * recuo de primeira linha vindo do estilo. A régua alimentada
 * pelo primeiro mostraria zero embaixo de um texto visivelmente recuado — e
 * arrastar o marcador daria um salto.
 */
export function formatoEfetivoDoBloco(bloco: Element): FormatoDeParagrafo {
  if (!(bloco instanceof HTMLElement) || typeof window === "undefined") {
    return { ...SEM_PARAGRAFO };
  }
  const calculado = window.getComputedStyle(bloco);
  const cm = (valor: string): number => {
    const px = Number.parseFloat(valor);
    return Number.isFinite(px) ? duasCasas((px * 2.54) / 96) : 0;
  };
  return {
    esquerda: cm(calculado.marginLeft),
    primeira: cm(calculado.textIndent),
    direita: cm(calculado.marginRight),
  };
}

/** Grava no bloco o formato de parágrafo. Campo `null` volta ao padrão da peça
 *  — removendo a propriedade, e não escrevendo zero: um zero explícito venceria
 *  o recuo configurado no modelo do escritório. */
export function aplicarFormatoDeParagrafo(bloco: HTMLElement, formato: FormatoDeParagrafo) {
  const limpo = normalizarParagrafo(formato);
  const escrever = (propriedade: string, valor: string | null) => {
    if (valor === null) bloco.style.removeProperty(propriedade);
    else bloco.style.setProperty(propriedade, valor);
  };
  escrever("margin-left", limpo.esquerda === null ? null : `${limpo.esquerda}cm`);
  escrever("margin-right", limpo.direita === null ? null : `${limpo.direita}cm`);
  escrever("text-indent", limpo.primeira === null ? null : `${limpo.primeira}cm`);
}

/** Uma linha do editor de volta a texto com marcações. */
function linhaParaTexto(bloco: Element): string {
  // A quebra de página não tem texto NENHUM — o rótulo que aparece na prévia é
  // desenho. Sem esta saída, o leitor comum a devolveria como linha vazia e a
  // quebra sumiria no primeiro salvamento.
  if (bloco instanceof HTMLElement && bloco.dataset.quebra === "1") return MARCA_DE_QUEBRA;
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
  const paragrafo = escreverParagrafo(formatoDeParagrafoDoBloco(bloco));
  // `&nbsp;`: o navegador põe espaço-duro ao digitar espaços seguidos. No texto
  // gravado ele viraria um caractere invisível diferente, que o Word mostra mas
  // ninguém consegue procurar nem apagar. A TABULAÇÃO, ao contrário, fica: ela
  // é uma parada de tabulação pedida, e o gerador do .docx a converte em `w:tab`.
  const limpo = corpo.replace(/ /g, " ");
  if (!limpo.trim()) return limpo;
  return `${alinhamento ? `[[alin=${alinhamento}]]` : ""}${paragrafo}${limpo}`;
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
