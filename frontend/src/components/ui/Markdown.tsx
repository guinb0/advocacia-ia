/**
 * O markdown que a IA escreve — em um lugar só.
 *
 * Nasceu dentro do cartão de pesquisa na web, onde o modelo responde em markdown livre
 * e tudo caía num `<p>` com `whitespace-pre-wrap`: asteriscos e `###` apareciam crus. O
 * chat da petição escreve do mesmo jeito, e uma segunda cópia deste parser divergiria
 * no dia em que uma das duas telas passasse a entender lista aninhada e a outra não.
 *
 * É um subconjunto de propósito (sem HTML, sem tabela) e nada é injetado como HTML —
 * só nós React, então não há risco de script vindo da web.
 */

"use client";

import { createContext, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";

const TEXTO = "text-sm leading-relaxed text-tinta-2 m-0";

export function dominioDe(url: string): string {
  return url.replace(/^https?:\/\/(www\.)?/, "").split(/[/?#]/)[0];
}

/* ---------------------------------------------------------------------------
 * Markdown da resposta da pesquisa.
 *
 * O modelo responde em markdown livre — às vezes um parágrafo, às vezes títulos,
 * listas e citação de súmula. Antes tudo caía num único `<p>` com
 * `whitespace-pre-wrap`: asteriscos e `###` apareciam crus e as listas ficavam
 * presas ao espaçamento de texto corrido. Aqui cada bloco vira o elemento
 * certo. É um subconjunto de propósito (sem HTML, sem tabela) e nada é injetado
 * como HTML — só nós React, então não há risco de script vindo da web.
 * ------------------------------------------------------------------------- */

type BlocoMd =
  | { tipo: "titulo"; nivel: number; texto: string }
  | { tipo: "lista"; ordenada: boolean; itens: { texto: string; nivel: number }[] }
  | { tipo: "citacao"; linhas: string[] }
  | { tipo: "separador" }
  | { tipo: "tabela"; cabecalho: string[]; corpo: string[][]; markdown: string }
  | { tipo: "paragrafo"; linhas: string[] };

const ITEM_MD = /^(\s*)([-*•+]|\d+[.)])\s+(.*)$/;
const TITULO_MD = /^\s*(#{1,6})\s+(.*?)\s*#*\s*$/;
const SEPARADOR_MD = /^\s*([-*_])(\s*\1){2,}\s*$/;
/** Mesma linha separadora que o gerador do .docx aceita (`_RE_SEPARADOR_TABELA`
 *  em `app/peticao_local.py`) e que o editor da peça desenha. */
const SEPARADOR_TABELA_MD = /^\s*\|?\s*:?-{3,}:?\s*(?:\|\s*:?-{3,}:?\s*)+\|?\s*$/;

function celulasMd(linha: string): string[] {
  let limpa = linha.trim();
  if (limpa.startsWith("|")) limpa = limpa.slice(1);
  if (limpa.endsWith("|")) limpa = limpa.slice(0, -1);
  return limpa.split("|").map((celula) => celula.trim());
}

/**
 * Começa uma tabela COMPLETA aqui? Cabeçalho, separadora e ao menos uma linha
 * de dados.
 *
 * A linha de dados é exigida AQUI, e não depois de ler o bloco, por causa do
 * streaming: a resposta do chat é desenhada enquanto chega, e existe um instante
 * em que o modelo já mandou o cabeçalho e a separadora e ainda não mandou a
 * primeira linha. Reconhecer isso como tabela e desistir depois deixava o laço
 * de `blocosDoMarkdown` sem avançar o índice — travava a tela no meio da
 * resposta, e de fora parecia que a IA tinha parado de fazer tabela.
 */
function ehInicioDeTabela(linhas: string[], i: number): boolean {
  const dados = linhas[i + 2] ?? "";
  return (
    (linhas[i] ?? "").includes("|") &&
    SEPARADOR_TABELA_MD.test(linhas[i + 1] ?? "") &&
    celulasMd(linhas[i]).length >= 2 &&
    dados.includes("|") &&
    dados.trim() !== ""
  );
}

function blocosDoMarkdown(texto: string): BlocoMd[] {
  const blocos: BlocoMd[] = [];
  const linhas = texto.replace(/\r\n?/g, "\n").split("\n");
  let i = 0;
  while (i < linhas.length) {
    const linha = linhas[i];
    if (!linha.trim()) {
      i += 1;
      continue;
    }
    const titulo = linha.match(TITULO_MD);
    if (titulo) {
      blocos.push({ tipo: "titulo", nivel: titulo[1].length, texto: titulo[2] });
      i += 1;
      continue;
    }
    if (SEPARADOR_MD.test(linha)) {
      blocos.push({ tipo: "separador" });
      i += 1;
      continue;
    }
    if (/^\s*>/.test(linha)) {
      const citacao: string[] = [];
      while (i < linhas.length && /^\s*>/.test(linhas[i])) {
        citacao.push(linhas[i].replace(/^\s*>\s?/, ""));
        i += 1;
      }
      blocos.push({ tipo: "citacao", linhas: citacao });
      continue;
    }
    /* TABELA. Este parser nasceu "sem tabela, de propósito", e isso deixou de
       servir no dia em que o chat passou a montar cronologias e quadros de
       gastos a pedido do advogado: a resposta vinha com o Markdown cru na tela,
       e quem pedia concluía que não tinha funcionado — quando na verdade o
       .docx já saía com a tabela pronta. */
    if (ehInicioDeTabela(linhas, i)) {
      const inicio = i;
      const cabecalho = celulasMd(linhas[i]);
      const corpo: string[][] = [];
      i += 2;
      while (i < linhas.length && linhas[i].includes("|") && linhas[i].trim()) {
        corpo.push(celulasMd(linhas[i]));
        i += 1;
      }
      // `ehInicioDeTabela` já garantiu a primeira linha de dados, então o índice
      // andou pelo menos três linhas. NÃO pode haver caminho de volta aqui: um
      // ramo que devolva o índice ao ponto de partida trava o laço, porque o
      // parágrafo lá embaixo também se recusa a consumir a linha de uma tabela.
      blocos.push({
        tipo: "tabela",
        cabecalho,
        corpo,
        markdown: linhas.slice(inicio, i).join("\n"),
      });
      continue;
    }
    const primeiro = linha.match(ITEM_MD);
    if (primeiro) {
      const ordenada = /\d/.test(primeiro[2]);
      const itens: { texto: string; nivel: number }[] = [];
      while (i < linhas.length) {
        const atual = linhas[i].match(ITEM_MD);
        if (atual) {
          const recuo = atual[1].replace(/\t/g, "  ").length;
          itens.push({ texto: atual[3], nivel: Math.min(2, Math.floor(recuo / 2)) });
          i += 1;
        } else if (linhas[i].trim() && /^\s{2,}/.test(linhas[i]) && itens.length) {
          // Continuação do item anterior, quebrada em outra linha.
          itens[itens.length - 1].texto += ` ${linhas[i].trim()}`;
          i += 1;
        } else if (!linhas[i].trim() && ITEM_MD.test(linhas[i + 1] ?? "")) {
          i += 1; // Linha em branco entre itens da mesma lista.
        } else {
          break;
        }
      }
      blocos.push({ tipo: "lista", ordenada, itens });
      continue;
    }
    const paragrafo: string[] = [];
    while (
      i < linhas.length &&
      linhas[i].trim() &&
      !TITULO_MD.test(linhas[i]) &&
      !/^\s*>/.test(linhas[i]) &&
      !ITEM_MD.test(linhas[i]) &&
      !SEPARADOR_MD.test(linhas[i]) &&
      !ehInicioDeTabela(linhas, i)
    ) {
      paragrafo.push(linhas[i].trim());
      i += 1;
    }
    blocos.push({ tipo: "paragrafo", linhas: paragrafo });
  }
  return blocos;
}

/**
 * A tabela da resposta, desenhada — e pronta para ir para a peça.
 *
 * "Copiar" leva o MARKDOWN, não o texto visível: é nesse formato que a tabela
 * vive dentro da seção da petição, e é dele que o gerador faz a `w:tbl` nativa
 * do Word. Colar na peça desenha a tabela na hora (ver o `onPaste` do
 * `CampoDoDocumento`), então a tabela entra exatamente no ponto em que o
 * advogado deixou o cursor — que é o "onde eu quiser" do pedido.
 */
function TabelaDaResposta({
  bloco,
}: {
  bloco: { cabecalho: string[]; corpo: string[][]; markdown: string };
}) {
  const [copiado, setCopiado] = useState(false);
  const colunas = Math.max(bloco.cabecalho.length, ...bloco.corpo.map((l) => l.length));
  const completar = (linha: string[]) =>
    [...linha, ...Array(Math.max(0, colunas - linha.length)).fill("")].slice(0, colunas);

  async function copiar() {
    try {
      await navigator.clipboard.writeText(bloco.markdown);
      setCopiado(true);
      setTimeout(() => setCopiado(false), 2000);
    } catch {
      /* Área de transferência negada pelo navegador: o texto continua na tela
         para selecionar à mão, que é melhor do que um erro sem saída. */
    }
  }

  return (
    <div className="grid gap-1">
      {/* `overflow-x`: a coluna da conversa é estreita e uma cronologia de cinco
          colunas não cabe. Rolar na horizontal é melhor que espremer a data em
          duas linhas. */}
      <div className="overflow-x-auto">
        <table className="w-full border-collapse text-xs">
          <thead>
            <tr>
              {completar(bloco.cabecalho).map((celula, j) => (
                <th
                  key={j}
                  className="border border-borda bg-papel-2 px-2 py-1 text-left align-top font-semibold text-tinta"
                >
                  <MdEmLinha texto={celula} />
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {bloco.corpo.map((linha, j) => (
              <tr key={j}>
                {completar(linha).map((celula, k) => (
                  <td key={k} className="border border-borda px-2 py-1 align-top">
                    <MdEmLinha texto={celula} />
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div>
        <button
          type="button"
          className="bg-transparent border-0 p-0 text-xs underline cursor-pointer text-tinta-3 hover:text-tinta"
          onClick={() => void copiar()}
        >
          {copiado ? "Copiada — cole no ponto da peça" : "Copiar tabela"}
        </button>
      </div>
    </div>
  );
}

export function RespostaFormatada({ texto }: { texto: string }) {
  const blocos = blocosDoMarkdown(texto);
  if (!blocos.length) return <p className={TEXTO}>A pesquisa não trouxe texto de resposta.</p>;
  return (
    <div className="grid gap-3 text-sm leading-relaxed text-tinta-2 break-words">
      {blocos.map((bloco, i) => {
        switch (bloco.tipo) {
          case "titulo":
            return bloco.nivel <= 2 ? (
              <h4 key={i} className="m-0 mt-1 font-ui text-base font-semibold text-tinta">
                <MdEmLinha texto={bloco.texto} />
              </h4>
            ) : (
              <h5 key={i} className="m-0 mt-1 font-ui text-sm font-semibold text-tinta">
                <MdEmLinha texto={bloco.texto} />
              </h5>
            );
          case "separador":
            return <hr key={i} className="m-0 border-0 border-t border-borda" />;
          case "tabela":
            return <TabelaDaResposta key={i} bloco={bloco} />;
          case "citacao":
            return (
              <blockquote key={i} className="m-0 border-l-4 border-acao-borda bg-papel-2 px-3 py-2">
                {bloco.linhas.map((l, j) => (
                  <span key={j} className="block">
                    <MdEmLinha texto={l} />
                  </span>
                ))}
              </blockquote>
            );
          case "lista": {
            const Lista = bloco.ordenada ? "ol" : "ul";
            return (
              <Lista
                key={i}
                className={`m-0 grid gap-1 pl-5 marker:text-tinta-3 ${bloco.ordenada ? "list-decimal" : "list-disc"}`}
              >
                {bloco.itens.map((it, j) => (
                  <li key={j} style={it.nivel ? { marginLeft: `${it.nivel * 16}px` } : undefined}>
                    <MdEmLinha texto={it.texto} />
                  </li>
                ))}
              </Lista>
            );
          }
          default:
            return (
              <p key={i} className="m-0">
                {bloco.linhas.map((l, j) => (
                  <span key={j}>
                    {j > 0 && " "}
                    <MdEmLinha texto={l} />
                  </span>
                ))}
              </p>
            );
        }
      })}
    </div>
  );
}

/* ---------------------------------------------------------------------------
 * Documentos citados viram link.
 *
 * O chat da petição cita "a CTPS (IMG_4411.jpg)" e o advogado tinha de sair da
 * conversa e procurar no checklist qual dos arquivos era aquele. Dentro de um
 * `DocumentosCitaveis`, o nome do arquivo — ou o tipo, quando só UM anexo tem aquele
 * tipo — vira um botão que abre o documento. Fora dele (a pesquisa na web do
 * FluxoPeticao), nada muda.
 *
 * Tipo repetido não abre um documento ao acaso: "o contracheque" num caso com três
 * contracheques não diz qual abrir, e abrir o errado é pior do que não abrir. O clique
 * abre uma lista curta com os arquivos daquele tipo, e a escolha abre o preview.
 * ------------------------------------------------------------------------- */

export interface DocumentoCitavelMd {
  id: string;
  arquivo: string;
  tipo: string;
}

interface Citaveis {
  padrao: RegExp;
  /** Mais de um documento por chave = ambíguo: o clique pede a escolha. */
  porChave: Map<string, DocumentoCitavelMd[]>;
  aoAbrir: (documento: DocumentoCitavelMd) => void;
}

const ContextoCitaveis = createContext<Citaveis | null>(null);

const escapar = (texto: string) => texto.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

function montarCitaveis(
  documentos: DocumentoCitavelMd[],
  aoAbrir: Citaveis["aoAbrir"],
): Citaveis | null {
  const porChave = new Map<string, DocumentoCitavelMd[]>();
  const registrar = (chave: string, documento: DocumentoCitavelMd) => {
    const limpa = chave.trim().toLowerCase();
    if (limpa.length < 2) return;
    const lista = porChave.get(limpa);
    if (!lista) porChave.set(limpa, [documento]);
    else if (!lista.some((d) => d.id === documento.id)) lista.push(documento);
  };
  for (const documento of documentos) {
    registrar(documento.arquivo, documento);
    // O modelo às vezes escreve o nome sem a extensão ("IMG_4411"). Curto demais
    // ("doc") casaria com palavra comum.
    const semExtensao = documento.arquivo.replace(/\.[a-z0-9]{2,5}$/i, "");
    if (semExtensao !== documento.arquivo && semExtensao.length >= 6) registrar(semExtensao, documento);
    if (documento.tipo) {
      registrar(documento.tipo, documento);
      // «Carteira de Trabalho (CTPS)»: o modelo escreve só uma das duas formas.
      const sigla = documento.tipo.match(/\(([^)]{2,20})\)/)?.[1];
      const semSigla = documento.tipo.replace(/\s*\([^)]*\)\s*/g, " ").trim();
      if (sigla) registrar(sigla, documento);
      if (semSigla && semSigla !== documento.tipo && semSigla.length >= 3) registrar(semSigla, documento);
    }
  }
  if (!porChave.size) return null;
  const chaves = [...porChave.keys()].sort((a, b) => b.length - a.length).map(escapar);
  return {
    // Fronteira de palavra que entende acento: o `\b` do JS não vê "é" como letra.
    padrao: new RegExp(`(?<![\\p{L}\\p{N}_])(?:${chaves.join("|")})(?![\\p{L}\\p{N}_])`, "giu"),
    porChave,
    aoAbrir,
  };
}

export function DocumentosCitaveis({
  documentos,
  aoAbrir,
  children,
}: {
  documentos: DocumentoCitavelMd[];
  aoAbrir: (documento: DocumentoCitavelMd) => void;
  children: ReactNode;
}) {
  const valor = useMemo(() => montarCitaveis(documentos, aoAbrir), [documentos, aoAbrir]);
  return <ContextoCitaveis.Provider value={valor}>{children}</ContextoCitaveis.Provider>;
}

/** O documento citado, em VERDE: é o sinal de «isto está nos autos e abre aqui». */
const ESTILO_DO_LINK =
  "inline cursor-pointer rounded-campo border-0 bg-ok-claro px-[3px] py-[1px] font-[inherit] text-[length:inherit] font-medium text-ok underline decoration-dotted underline-offset-2 hover:decoration-solid";

function LinkDoDocumento({
  documentos,
  aoAbrir,
  children,
}: {
  documentos: DocumentoCitavelMd[];
  aoAbrir: Citaveis["aoAbrir"];
  children: ReactNode;
}) {
  const [escolhendo, setEscolhendo] = useState(false);
  const raiz = useRef<HTMLSpanElement>(null);
  useEffect(() => {
    if (!escolhendo) return;
    const fora = (evento: MouseEvent) => {
      if (raiz.current && !raiz.current.contains(evento.target as Node)) setEscolhendo(false);
    };
    const esc = (evento: KeyboardEvent) => {
      if (evento.key === "Escape") setEscolhendo(false);
    };
    document.addEventListener("mousedown", fora);
    document.addEventListener("keydown", esc);
    return () => {
      document.removeEventListener("mousedown", fora);
      document.removeEventListener("keydown", esc);
    };
  }, [escolhendo]);

  const unico = documentos.length === 1 ? documentos[0] : null;
  return (
    <span ref={raiz} className="relative inline">
      <button
        type="button"
        onClick={() => (unico ? aoAbrir(unico) : setEscolhendo((aberto) => !aberto))}
        title={
          unico
            ? `Ver ${unico.arquivo}${unico.tipo ? ` (${unico.tipo})` : ""} sem sair da conversa`
            : `${documentos.length} documentos deste tipo — escolha qual ver`
        }
        aria-haspopup={unico ? undefined : "menu"}
        aria-expanded={unico ? undefined : escolhendo}
        className={ESTILO_DO_LINK}
      >
        <IconeDocumento />
        {children}
        {!unico && <span className="ml-[2px] text-[10px]" aria-hidden>▾</span>}
      </button>
      {escolhendo && (
        <span
          role="menu"
          className="absolute left-0 top-full z-20 mt-1 grid min-w-[220px] max-w-[300px] gap-[2px] rounded-campo border border-borda bg-papel p-1 text-left text-xs shadow-lg"
        >
          {documentos.map((documento) => (
            <button
              key={documento.id}
              type="button"
              role="menuitem"
              onClick={() => {
                setEscolhendo(false);
                aoAbrir(documento);
              }}
              className="flex cursor-pointer flex-col items-start rounded-campo border-0 bg-transparent px-2 py-[5px] text-left font-[inherit] text-tinta hover:bg-ok-claro"
            >
              <span className="break-all font-medium text-ok">{documento.arquivo}</span>
              {documento.tipo && <span className="text-tinta-3">{documento.tipo}</span>}
            </button>
          ))}
        </span>
      )}
    </span>
  );
}

function IconeDocumento() {
  return (
    <svg className="mr-[2px] inline-block align-[-2px]" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
      <path d="M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z" />
      <path d="M14 3v6h6" />
    </svg>
  );
}

/** Texto corrido com os documentos citados trocados por link. */
function comDocumentos(texto: string, citaveis: Citaveis | null, base: number): ReactNode[] {
  if (!citaveis) return [texto];
  const partes: ReactNode[] = [];
  let ultimo = 0;
  for (const achado of texto.matchAll(citaveis.padrao)) {
    const documentos = citaveis.porChave.get(achado[0].toLowerCase());
    if (!documentos?.length) continue;
    const inicio = achado.index ?? 0;
    if (inicio > ultimo) partes.push(texto.slice(ultimo, inicio));
    partes.push(
      <LinkDoDocumento key={`doc-${base + inicio}`} documentos={documentos} aoAbrir={citaveis.aoAbrir}>
        {achado[0]}
      </LinkDoDocumento>,
    );
    ultimo = inicio + achado[0].length;
  }
  if (ultimo < texto.length) partes.push(texto.slice(ultimo));
  return partes;
}

/** Em linha: link `[rótulo](url)`, URL solta, `**negrito**`, `*itálico*` e `código`. */
function MdEmLinha({ texto }: { texto: string }) {
  const citaveis = useContext(ContextoCitaveis);
  const partes: ReactNode[] = [];
  const padrao =
    /\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)|\*\*([^*]+)\*\*|__([^_]+)__|`([^`]+)`|(?<![\w*])\*([^*\n]+)\*(?!\*)|(https?:\/\/[^\s<>)\]]+)/g;
  let ultimo = 0;
  for (const achado of texto.matchAll(padrao)) {
    const inicio = achado.index ?? 0;
    if (inicio > ultimo) partes.push(...comDocumentos(texto.slice(ultimo, inicio), citaveis, ultimo));
    const [, rotulo, url, negrito, negrito2, codigo, italico, urlSolta] = achado;
    if (url || urlSolta) {
      const bruta = url || urlSolta;
      const destino = bruta.replace(/[.,;:]+$/, "");
      partes.push(
        <a key={inicio} href={destino} target="_blank" rel="noopener noreferrer" className="text-acao underline break-words">
          {rotulo ? <MdEmLinha texto={rotulo} /> : dominioDe(destino)}
        </a>,
      );
      if (bruta.length > destino.length) partes.push(bruta.slice(destino.length));
    } else if (negrito || negrito2) {
      partes.push(
        <strong key={inicio} className="text-tinta">
          <MdEmLinha texto={negrito || negrito2} />
        </strong>,
      );
    } else if (codigo && citaveis?.porChave.has(codigo.trim().toLowerCase())) {
      // O modelo costuma pôr o nome do arquivo entre crases.
      partes.push(
        <LinkDoDocumento key={inicio} documentos={citaveis.porChave.get(codigo.trim().toLowerCase())!} aoAbrir={citaveis.aoAbrir}>
          <code className="rounded-campo bg-papel-3 px-1 font-codigo text-xs">{codigo}</code>
        </LinkDoDocumento>,
      );
    } else if (codigo) {
      partes.push(
        <code key={inicio} className="rounded-campo bg-papel-3 px-1 font-codigo text-xs text-tinta">
          {codigo}
        </code>,
      );
    } else if (italico) {
      partes.push(<em key={inicio}>{comDocumentos(italico, citaveis, inicio)}</em>);
    }
    ultimo = inicio + achado[0].length;
  }
  if (ultimo < texto.length) partes.push(...comDocumentos(texto.slice(ultimo), citaveis, ultimo));
  return <>{partes}</>;
}
