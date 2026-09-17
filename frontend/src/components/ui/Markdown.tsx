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

import type { ReactNode } from "react";

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
  | { tipo: "paragrafo"; linhas: string[] };

const ITEM_MD = /^(\s*)([-*•+]|\d+[.)])\s+(.*)$/;
const TITULO_MD = /^\s*(#{1,6})\s+(.*?)\s*#*\s*$/;
const SEPARADOR_MD = /^\s*([-*_])(\s*\1){2,}\s*$/;

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
      !SEPARADOR_MD.test(linhas[i])
    ) {
      paragrafo.push(linhas[i].trim());
      i += 1;
    }
    blocos.push({ tipo: "paragrafo", linhas: paragrafo });
  }
  return blocos;
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

/** Em linha: link `[rótulo](url)`, URL solta, `**negrito**`, `*itálico*` e `código`. */
function MdEmLinha({ texto }: { texto: string }) {
  const partes: ReactNode[] = [];
  const padrao =
    /\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)|\*\*([^*]+)\*\*|__([^_]+)__|`([^`]+)`|(?<![\w*])\*([^*\n]+)\*(?!\*)|(https?:\/\/[^\s<>)\]]+)/g;
  let ultimo = 0;
  for (const achado of texto.matchAll(padrao)) {
    const inicio = achado.index ?? 0;
    if (inicio > ultimo) partes.push(texto.slice(ultimo, inicio));
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
    } else if (codigo) {
      partes.push(
        <code key={inicio} className="rounded-campo bg-papel-3 px-1 font-codigo text-xs text-tinta">
          {codigo}
        </code>,
      );
    } else if (italico) {
      partes.push(<em key={inicio}>{italico}</em>);
    }
    ultimo = inicio + achado[0].length;
  }
  if (ultimo < texto.length) partes.push(texto.slice(ultimo));
  return <>{partes}</>;
}
