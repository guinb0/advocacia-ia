"use client";

/**
 * Primitivos de gráfico em SVG — sem biblioteca e sem dependência nova.
 *
 * Todos seguem as mesmas regras, que valem para o painel inteiro:
 *
 * - **nenhum gráfico é a única forma de ler o número.** Cada figura tem o par em
 *   tabela, acessível pelo botão "Tabela"; o tooltip acrescenta, nunca guarda;
 * - **estado vazio é conteúdo.** Série sem dado desenha a moldura com o motivo escrito
 *   ("o agente não respondeu", "só 2 casos anteriores") em vez de um eixo vazio, que se
 *   parece com zero;
 * - **um eixo só.** Duas medidas de escalas diferentes viram dois gráficos. Eixo duplo
 *   inventa correlação que o dado não tem;
 * - **marca fina, grade recessiva.** Linha de 2px, coluna com teto de 24px, grade em fio
 *   sólido de 1px um passo acima do fundo, respiro no lugar de moldura.
 */

import { useId, useLayoutEffect, useRef, useState, type ReactNode } from "react";

export const CORES_DE_SERIE = [
  "var(--serie-1)",
  "var(--serie-2)",
  "var(--serie-3)",
  "var(--serie-4)",
] as const;

/** Rampa sequencial de um matiz só — a única usada para magnitude contínua. */
export const RAMPA = [
  "var(--rampa-0)",
  "var(--rampa-1)",
  "var(--rampa-2)",
  "var(--rampa-3)",
  "var(--rampa-4)",
  "var(--rampa-5)",
] as const;

/* As cores de série NÃO são as cores de estado do sistema. `--ok`, `--atencao` e
 * `--critico` continuam significando pronto/conferir/problema em toda a aplicação;
 * se uma delas pintasse "série 2" de um gráfico, a cor deixaria de informar.
 *
 * A paleta abaixo foi validada para daltonismo contra o fundo branco do cartão
 * (deutan/protan/tritan, ΔE ≥ 8 entre vizinhas; pior par aqua↔laranja 9,2). Por
 * isso vive aqui como propriedades CSS custom no `<figure>` raiz — não em
 * `globals.css` — e não como classes Tailwind: nada mais no app deve poder
 * "pintar de --serie-2" por engano. */
const TOKENS_GRAFICO = {
  "--serie-1": "#2a78d6",
  "--serie-2": "#eb6834",
  "--serie-3": "#1baf7a",
  "--serie-4": "#4a3aa7",
  "--rampa-0": "#eef4fc",
  "--rampa-1": "#cde2fb",
  "--rampa-2": "#9ec5f4",
  "--rampa-3": "#5598e7",
  "--rampa-4": "#2a78d6",
  "--rampa-5": "#1c5cab",
  "--grade": "var(--borda)",
  "--eixo": "var(--borda-forte)",
  "--rotulo": "var(--tinta-3)",
} as React.CSSProperties;

const CLASSE_SVG = "block overflow-visible";
const CLASSE_AREA = "relative w-full min-w-0 overflow-x-auto";
const CLASSE_ROTULO_EIXO = "font-ui text-[11px] fill-[var(--rotulo)] tabular-nums";
const CLASSE_ROTULO_DIRETO = "font-ui text-[11px] font-semibold fill-tinta-2";
const CLASSE_LINHA_GRADE = "stroke-[var(--grade)] [stroke-width:1]";
const CLASSE_LINHA_EIXO = "stroke-[var(--eixo)] [stroke-width:1]";
const CLASSE_ALVO = "fill-transparent cursor-crosshair";
const CLASSE_TOOLTIP_TITULO = "font-semibold text-tinta mb-1";
const CLASSE_TOOLTIP_LINHA = "flex items-center justify-between gap-3";
const CLASSE_TOOLTIP_VALOR = "tabular-nums font-semibold text-tinta";
const CLASSE_TOOLTIP_ROTULO = "inline-flex items-center gap-[6px]";
const CLASSE_MARCA_LEGENDA = "w-3 h-3 rounded-[3px] flex-none";
const CLASSE_MARCA_LEGENDA_LINHA = "w-[14px] h-[2px] rounded-[2px] flex-none";
const CLASSE_ITEM_LEGENDA = "inline-flex items-center gap-[6px]";
const CLASSE_LEGENDA = "flex flex-wrap gap-x-4 gap-y-[6px] text-xs text-tinta-2";

/** Mede a largura disponível para o SVG desenhar em pixels reais.
 *
 * Sem isto restariam duas saídas ruins: `viewBox` esticado (que deforma o texto junto
 * com o desenho) ou largura fixa (que estoura o cartão no celular). */
function useLargura(): [React.RefObject<HTMLDivElement | null>, number] {
  const referencia = useRef<HTMLDivElement | null>(null);
  const [largura, setLargura] = useState(640);

  useLayoutEffect(() => {
    const elemento = referencia.current;
    if (!elemento) return;
    const medir = () => setLargura(Math.max(240, elemento.clientWidth));
    medir();
    const observador = new ResizeObserver(medir);
    observador.observe(elemento);
    return () => observador.disconnect();
  }, []);

  return [referencia, largura];
}

// ------------------------------------------------------------------- moldura

export interface ColunaDaTabela {
  chave: string;
  rotulo: string;
}

export function Figura({
  titulo,
  descricao,
  legenda,
  acoes,
  tabela,
  children,
}: {
  titulo: string;
  descricao?: string;
  legenda?: { rotulo: string; cor: string; forma?: "bloco" | "linha" }[];
  acoes?: ReactNode;
  /** O par em tabela. Toda figura tem um — é o que sobra quando a cor falha. */
  tabela?: { colunas: ColunaDaTabela[]; linhas: Record<string, string | number>[] };
  children: ReactNode;
}) {
  const [mostrandoTabela, setMostrandoTabela] = useState(false);
  const id = useId();

  return (
    <figure className="relative flex flex-col gap-[10px] min-w-0" style={TOKENS_GRAFICO}>
      <div className="flex items-baseline justify-between gap-3 flex-wrap">
        <div>
          <figcaption className="font-ui text-sm font-semibold text-tinta tracking-[0.01em]">
            {titulo}
          </figcaption>
          {descricao && <div className="text-xs text-tinta-3 max-w-[62ch]">{descricao}</div>}
        </div>
        <div className="flex gap-2 items-center">
          {acoes}
          {tabela && tabela.linhas.length > 0 && (
            <button
              type="button"
              className="border border-borda-campo bg-papel text-tinta-2 rounded-campo px-[9px] py-[3px] text-xs font-ui cursor-pointer transition-[background-color] duration-[120ms] ease-[ease] hover:bg-papel-3 focus-visible:outline-2 focus-visible:outline-foco focus-visible:outline-offset-2"
              aria-expanded={mostrandoTabela}
              aria-controls={id}
              onClick={() => setMostrandoTabela((atual) => !atual)}
            >
              {mostrandoTabela ? "Gráfico" : "Tabela"}
            </button>
          )}
        </div>
      </div>

      {legenda && legenda.length > 1 && (
        <div className={CLASSE_LEGENDA}>
          {legenda.map((item) => (
            <span key={item.rotulo} className={CLASSE_ITEM_LEGENDA}>
              <span
                className={item.forma === "linha" ? CLASSE_MARCA_LEGENDA_LINHA : CLASSE_MARCA_LEGENDA}
                style={{ background: item.cor }}
                aria-hidden
              />
              {item.rotulo}
            </span>
          ))}
        </div>
      )}

      {mostrandoTabela && tabela ? (
        <div className="max-h-[320px] overflow-auto" id={id}>
          <table className="w-full border-collapse text-xs">
            <thead>
              <tr>
                {tabela.colunas.map((coluna, indice) => (
                  <th
                    key={coluna.chave}
                    className={`text-left px-2 py-[6px] border-b border-borda text-tinta-3 font-semibold ${
                      indice !== 0 ? "text-right tabular-nums" : ""
                    }`}
                  >
                    {coluna.rotulo}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {tabela.linhas.map((linha, indice) => (
                <tr key={indice}>
                  {tabela.colunas.map((coluna, indiceColuna) => (
                    <td
                      key={coluna.chave}
                      className={`text-left px-2 py-[6px] border-b border-borda text-tinta-2 ${
                        indiceColuna !== 0 ? "text-right tabular-nums" : ""
                      }`}
                    >
                      {linha[coluna.chave] ?? "—"}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        children
      )}
    </figure>
  );
}

/** Estado vazio com o motivo — "não há dado" e "não consegui ler" são coisas diferentes. */
export function SemDado({ titulo, motivo }: { titulo: string; motivo?: string }) {
  return (
    <div className="border border-dashed border-borda-forte rounded-campo bg-papel-2 px-4 py-5 text-center text-tinta-3 text-sm flex flex-col gap-1 items-center">
      <span className="text-lg text-tinta-3" aria-hidden>
        ▨
      </span>
      <div>{titulo}</div>
      {motivo && <div className="text-xs max-w-[52ch]">{motivo}</div>}
    </div>
  );
}

function Tooltip({
  x,
  y,
  largura,
  children,
}: {
  x: number;
  y: number;
  largura: number;
  children: ReactNode;
}) {
  // Perto da borda direita o balão vira para a esquerda; senão ele é cortado pelo
  // cartão justamente nos últimos pontos, que são os mais consultados.
  const paraEsquerda = x > largura * 0.6;
  return (
    <div
      className="absolute z-[5] pointer-events-none bg-papel border border-borda-forte rounded-campo shadow-cartao-forte px-[10px] py-2 text-xs text-tinta-2 min-w-[140px] max-w-[260px]"
      style={{
        left: paraEsquerda ? undefined : x + 14,
        right: paraEsquerda ? largura - x + 14 : undefined,
        top: Math.max(0, y - 12),
      }}
      role="status"
    >
      {children}
    </div>
  );
}

// --------------------------------------------------------------------- eixos

function ticks(maximo: number, quantidade = 4): number[] {
  if (maximo <= 0) return [0];
  const bruto = maximo / quantidade;
  const magnitude = 10 ** Math.floor(Math.log10(bruto));
  const passo = [1, 2, 2.5, 5, 10].map((m) => m * magnitude).find((p) => p >= bruto) ?? magnitude * 10;
  const valores: number[] = [];
  for (let valor = 0; valor <= maximo + passo * 0.001; valor += passo) valores.push(valor);
  return valores;
}

function formatar(valor: number): string {
  if (Math.abs(valor) >= 1000) return valor.toLocaleString("pt-BR", { maximumFractionDigits: 0 });
  return valor.toLocaleString("pt-BR", { maximumFractionDigits: 1 });
}

// ---------------------------------------------------------------- linha/área

export interface SerieDeLinha {
  nome: string;
  cor: string;
  valores: number[];
  /** Sufixo do valor no tooltip ("documentos", "%"). */
  unidade?: string;
}

/**
 * Linha (ou área, quando é uma série só) com mira e tooltip por coluna.
 *
 * A mira acompanha a coluna inteira em vez de exigir acerto no ponto: um ponto de 8px
 * é alvo pequeno demais para o mouse e impossível no toque.
 */
export function GraficoDeLinha({
  rotulos,
  series,
  altura = 200,
  rotuloDoValor,
}: {
  rotulos: string[];
  series: SerieDeLinha[];
  altura?: number;
  rotuloDoValor?: (valor: number) => string;
}) {
  const [caixa, largura] = useLargura();
  const [ativo, setAtivo] = useState<number | null>(null);

  const margem = { topo: 14, direita: 52, base: 26, esquerda: 44 };
  const plotoLargura = Math.max(40, largura - margem.esquerda - margem.direita);
  const plotoAltura = altura - margem.topo - margem.base;

  const maximo = Math.max(1, ...series.flatMap((s) => s.valores));
  const marcas = ticks(maximo);
  const teto = Math.max(maximo, marcas[marcas.length - 1] ?? maximo);

  const x = (indice: number) =>
    margem.esquerda +
    (rotulos.length <= 1 ? plotoLargura / 2 : (indice / (rotulos.length - 1)) * plotoLargura);
  const y = (valor: number) => margem.topo + plotoAltura - (valor / teto) * plotoAltura;

  // Um rótulo a cada N colunas: eixo com trinta datas coladas não se lê.
  const passoRotulo = Math.max(1, Math.ceil(rotulos.length / Math.max(2, Math.floor(largura / 90))));

  return (
    <div className={CLASSE_AREA} ref={caixa}>
      <svg
        className={CLASSE_SVG}
        width={largura}
        height={altura}
        role="img"
        aria-label={`Gráfico de linha: ${series.map((s) => s.nome).join(", ")}`}
        onMouseLeave={() => setAtivo(null)}
      >
        {marcas.map((marca) => (
          <g key={marca}>
            <line
              className={CLASSE_LINHA_GRADE}
              x1={margem.esquerda}
              x2={margem.esquerda + plotoLargura}
              y1={y(marca)}
              y2={y(marca)}
            />
            <text className={CLASSE_ROTULO_EIXO} x={margem.esquerda - 8} y={y(marca) + 4} textAnchor="end">
              {formatar(marca)}
            </text>
          </g>
        ))}

        <line
          className={CLASSE_LINHA_EIXO}
          x1={margem.esquerda}
          x2={margem.esquerda + plotoLargura}
          y1={margem.topo + plotoAltura}
          y2={margem.topo + plotoAltura}
        />

        {rotulos.map((rotulo, indice) =>
          indice % passoRotulo === 0 || indice === rotulos.length - 1 ? (
            <text
              key={rotulo + indice}
              className={CLASSE_ROTULO_EIXO}
              x={x(indice)}
              y={altura - 8}
              textAnchor="middle"
            >
              {rotulo}
            </text>
          ) : null,
        )}

        {series.map((serie, indiceSerie) => {
          const caminho = serie.valores
            .map((valor, indice) => `${indice === 0 ? "M" : "L"}${x(indice)},${y(valor)}`)
            .join(" ");
          const areaCaminho =
            series.length === 1
              ? `${caminho} L${x(serie.valores.length - 1)},${margem.topo + plotoAltura} L${x(0)},${
                  margem.topo + plotoAltura
                } Z`
              : null;
          return (
            <g key={serie.nome}>
              {areaCaminho && <path d={areaCaminho} fill={serie.cor} opacity={0.1} />}
              <path
                d={caminho}
                fill="none"
                stroke={serie.cor}
                strokeWidth={2}
                strokeLinejoin="round"
                strokeLinecap="round"
              />
              {/* Ponto final marcado e rotulado: é o valor de hoje, o mais consultado. */}
              {serie.valores.length > 0 && (
                <>
                  <circle
                    cx={x(serie.valores.length - 1)}
                    cy={y(serie.valores[serie.valores.length - 1])}
                    r={4}
                    fill={serie.cor}
                    stroke="var(--papel)"
                    strokeWidth={2}
                  />
                  <text
                    className={CLASSE_ROTULO_DIRETO}
                    x={x(serie.valores.length - 1) + 8}
                    y={y(serie.valores[serie.valores.length - 1]) + 4 + indiceSerie * 12}
                  >
                    {(rotuloDoValor ?? formatar)(serie.valores[serie.valores.length - 1])}
                  </text>
                </>
              )}
            </g>
          );
        })}

        {ativo !== null && (
          <g>
            <line
              className={CLASSE_LINHA_EIXO}
              x1={x(ativo)}
              x2={x(ativo)}
              y1={margem.topo}
              y2={margem.topo + plotoAltura}
            />
            {series.map((serie) => (
              <circle
                key={serie.nome}
                cx={x(ativo)}
                cy={y(serie.valores[ativo] ?? 0)}
                r={4}
                fill={serie.cor}
                stroke="var(--papel)"
                strokeWidth={2}
              />
            ))}
          </g>
        )}

        {rotulos.map((rotulo, indice) => (
          <rect
            key={`alvo-${indice}`}
            className={CLASSE_ALVO}
            x={x(indice) - plotoLargura / Math.max(1, rotulos.length) / 2}
            y={margem.topo}
            width={Math.max(12, plotoLargura / Math.max(1, rotulos.length))}
            height={plotoAltura}
            onMouseEnter={() => setAtivo(indice)}
            onFocus={() => setAtivo(indice)}
            tabIndex={-1}
          />
        ))}
      </svg>

      {ativo !== null && (
        <Tooltip x={x(ativo)} y={margem.topo} largura={largura}>
          <div className={CLASSE_TOOLTIP_TITULO}>{rotulos[ativo]}</div>
          {series.map((serie) => (
            <div key={serie.nome} className={CLASSE_TOOLTIP_LINHA}>
              <span className={CLASSE_TOOLTIP_ROTULO}>
                <span className={CLASSE_MARCA_LEGENDA_LINHA} style={{ background: serie.cor }} aria-hidden />
                {serie.nome}
              </span>
              <span className={CLASSE_TOOLTIP_VALOR}>
                {formatar(serie.valores[ativo] ?? 0)}
                {serie.unidade ? ` ${serie.unidade}` : ""}
              </span>
            </div>
          ))}
        </Tooltip>
      )}
    </div>
  );
}

// -------------------------------------------------------------------- colunas

export function GraficoDeColunas({
  rotulos,
  valores,
  cor = CORES_DE_SERIE[0],
  altura = 170,
  unidade,
}: {
  rotulos: string[];
  valores: number[];
  cor?: string;
  altura?: number;
  unidade?: string;
}) {
  const [caixa, largura] = useLargura();
  const [ativo, setAtivo] = useState<number | null>(null);

  const margem = { topo: 14, direita: 12, base: 26, esquerda: 40 };
  const plotoLargura = Math.max(40, largura - margem.esquerda - margem.direita);
  const plotoAltura = altura - margem.topo - margem.base;
  const maximo = Math.max(1, ...valores);
  const marcas = ticks(maximo);
  const teto = Math.max(maximo, marcas[marcas.length - 1] ?? maximo);

  const faixa = plotoLargura / Math.max(1, valores.length);
  // Teto de 24px na marca e 2px de respiro entre vizinhas — o branco é que separa.
  const espessura = Math.max(3, Math.min(24, faixa - 2));
  const y = (valor: number) => margem.topo + plotoAltura - (valor / teto) * plotoAltura;
  const passoRotulo = Math.max(1, Math.ceil(rotulos.length / Math.max(2, Math.floor(largura / 80))));

  return (
    <div className={CLASSE_AREA} ref={caixa}>
      <svg
        className={CLASSE_SVG}
        width={largura}
        height={altura}
        role="img"
        aria-label="Gráfico de colunas"
        onMouseLeave={() => setAtivo(null)}
      >
        {marcas.map((marca) => (
          <g key={marca}>
            <line
              className={CLASSE_LINHA_GRADE}
              x1={margem.esquerda}
              x2={margem.esquerda + plotoLargura}
              y1={y(marca)}
              y2={y(marca)}
            />
            <text className={CLASSE_ROTULO_EIXO} x={margem.esquerda - 8} y={y(marca) + 4} textAnchor="end">
              {formatar(marca)}
            </text>
          </g>
        ))}

        {valores.map((valor, indice) => {
          const centro = margem.esquerda + faixa * indice + faixa / 2;
          const altoDaColuna = plotoAltura - (valor / teto) * plotoAltura;
          return (
            <g key={indice}>
              {valor > 0 && (
                <rect
                  x={centro - espessura / 2}
                  y={margem.topo + altoDaColuna}
                  width={espessura}
                  height={Math.max(2, (valor / teto) * plotoAltura)}
                  rx={Math.min(4, espessura / 2)}
                  fill={cor}
                  opacity={ativo === null || ativo === indice ? 1 : 0.55}
                />
              )}
              <rect
                className={CLASSE_ALVO}
                x={margem.esquerda + faixa * indice}
                y={margem.topo}
                width={faixa}
                height={plotoAltura}
                onMouseEnter={() => setAtivo(indice)}
              />
            </g>
          );
        })}

        <line
          className={CLASSE_LINHA_EIXO}
          x1={margem.esquerda}
          x2={margem.esquerda + plotoLargura}
          y1={margem.topo + plotoAltura}
          y2={margem.topo + plotoAltura}
        />

        {rotulos.map((rotulo, indice) =>
          indice % passoRotulo === 0 || indice === rotulos.length - 1 ? (
            <text
              key={rotulo + indice}
              className={CLASSE_ROTULO_EIXO}
              x={margem.esquerda + faixa * indice + faixa / 2}
              y={altura - 8}
              textAnchor="middle"
            >
              {rotulo}
            </text>
          ) : null,
        )}
      </svg>

      {ativo !== null && (
        <Tooltip
          x={margem.esquerda + faixa * ativo + faixa / 2}
          y={margem.topo}
          largura={largura}
        >
          <div className={CLASSE_TOOLTIP_TITULO}>{rotulos[ativo]}</div>
          <div className={CLASSE_TOOLTIP_LINHA}>
            <span className={CLASSE_TOOLTIP_ROTULO}>
              <span className={CLASSE_MARCA_LEGENDA} style={{ background: cor }} aria-hidden />
              {unidade ?? "eventos"}
            </span>
            <span className={CLASSE_TOOLTIP_VALOR}>{formatar(valores[ativo] ?? 0)}</span>
          </div>
        </Tooltip>
      )}
    </div>
  );
}

// -------------------------------------------------------------------- barras

export interface BarraHorizontal {
  rotulo: string;
  valores: { nome: string; valor: number | null; cor: string }[];
  /** Frase mostrada no tooltip: de onde saiu o número, ou por que ele não existe. */
  nota?: string;
}

/**
 * Barras horizontais, uma ou duas por linha (previsto x realizado).
 *
 * O rótulo do valor fica na ponta de fora da barra, nunca dentro: dentro ele some
 * quando a barra é curta, e cortar texto é pior que não rotular.
 */
export function GraficoDeBarras({
  itens,
  unidade = "",
  alturaDaLinha = 34,
}: {
  itens: BarraHorizontal[];
  unidade?: string;
  alturaDaLinha?: number;
}) {
  const [caixa, largura] = useLargura();
  const [ativo, setAtivo] = useState<number | null>(null);

  const rotuloLargura = Math.min(240, Math.max(120, largura * 0.3));
  const valorLargura = 58;
  const plotoLargura = Math.max(40, largura - rotuloLargura - valorLargura - 8);
  const maximo = Math.max(
    1,
    ...itens.flatMap((item) => item.valores.map((v) => v.valor ?? 0)),
  );
  const altura = itens.length * alturaDaLinha + 8;

  return (
    <div className={CLASSE_AREA} ref={caixa}>
      <svg
        className={CLASSE_SVG}
        width={largura}
        height={altura}
        role="img"
        aria-label="Gráfico de barras"
        onMouseLeave={() => setAtivo(null)}
      >
        {itens.map((item, indice) => {
          const topo = indice * alturaDaLinha + 4;
          const quantas = item.valores.length;
          const espessura = Math.max(5, Math.min(14, (alturaDaLinha - 14) / quantas - 2));
          return (
            <g key={item.rotulo}>
              <text
                className={CLASSE_ROTULO_EIXO}
                x={0}
                y={topo + alturaDaLinha / 2 + 4}
                style={{ fill: "var(--tinta-2)" }}
              >
                {item.rotulo.length > 34 ? `${item.rotulo.slice(0, 33)}…` : item.rotulo}
              </text>

              {item.valores.map((serie, indiceSerie) => {
                const y =
                  topo +
                  alturaDaLinha / 2 -
                  (quantas * (espessura + 2)) / 2 +
                  indiceSerie * (espessura + 2);
                if (serie.valor === null) {
                  // Trilho vazado no lugar da barra: mostra que a série existe e está sem
                  // valor, sem escrever texto que colidiria com o rótulo do valor ao lado.
                  // Quem quer o motivo tem o tooltip da linha e a tabela.
                  return (
                    <g key={serie.nome}>
                      <rect
                        x={rotuloLargura}
                        y={y + espessura / 2 - 1}
                        width={plotoLargura}
                        height={2}
                        fill="var(--borda)"
                      />
                    </g>
                  );
                }
                const comprimento = Math.max(2, (serie.valor / maximo) * plotoLargura);
                return (
                  <rect
                    key={serie.nome}
                    x={rotuloLargura}
                    y={y}
                    width={comprimento}
                    height={espessura}
                    rx={Math.min(4, espessura / 2)}
                    fill={serie.cor}
                    opacity={ativo === null || ativo === indice ? 1 : 0.55}
                  />
                );
              })}

              <text
                className={CLASSE_ROTULO_DIRETO}
                x={largura - 2}
                y={topo + alturaDaLinha / 2 + 4}
                textAnchor="end"
              >
                {item.valores[0].valor === null ? "—" : `${formatar(item.valores[0].valor)}${unidade}`}
              </text>

              <rect
                className={CLASSE_ALVO}
                x={0}
                y={topo}
                width={largura}
                height={alturaDaLinha}
                onMouseEnter={() => setAtivo(indice)}
              />
            </g>
          );
        })}
      </svg>

      {ativo !== null && (
        <Tooltip x={rotuloLargura + 40} y={ativo * alturaDaLinha} largura={largura}>
          <div className={CLASSE_TOOLTIP_TITULO}>{itens[ativo].rotulo}</div>
          {itens[ativo].valores.map((serie) => (
            <div key={serie.nome} className={CLASSE_TOOLTIP_LINHA}>
              <span className={CLASSE_TOOLTIP_ROTULO}>
                <span className={CLASSE_MARCA_LEGENDA} style={{ background: serie.cor }} aria-hidden />
                {serie.nome}
              </span>
              <span className={CLASSE_TOOLTIP_VALOR}>
                {serie.valor === null ? "—" : `${formatar(serie.valor)}${unidade}`}
              </span>
            </div>
          ))}
          {itens[ativo].nota && <div className="mt-[6px] pt-[6px] border-t border-borda text-tinta-3">{itens[ativo].nota}</div>}
        </Tooltip>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------- rosca

export function Rosca({
  fatias,
  total,
  rotuloDoCentro,
  tamanho = 168,
}: {
  fatias: { rotulo: string; valor: number; cor: string }[];
  total: number;
  rotuloDoCentro: string;
  tamanho?: number;
}) {
  const [ativo, setAtivo] = useState<number | null>(null);
  const raio = tamanho / 2;
  const espessura = 26;
  const centro = raio;
  const circunferencia = 2 * Math.PI * (raio - espessura / 2);

  let acumulado = 0;
  return (
    <div className={CLASSE_AREA} style={{ display: "flex", gap: 20, alignItems: "center", flexWrap: "wrap" }}>
      <svg
        className={CLASSE_SVG}
        width={tamanho}
        height={tamanho}
        role="img"
        aria-label="Distribuição em rosca"
        onMouseLeave={() => setAtivo(null)}
      >
        <circle
          cx={centro}
          cy={centro}
          r={raio - espessura / 2}
          fill="none"
          stroke="var(--papel-3)"
          strokeWidth={espessura}
        />
        {fatias.map((fatia, indice) => {
          const fracao = total > 0 ? fatia.valor / total : 0;
          const comprimento = fracao * circunferencia;
          // 2px de respiro entre fatias: o branco separa, sem contorno desenhado.
          const traco = Math.max(0, comprimento - 2);
          const deslocamento = acumulado * circunferencia;
          acumulado += fracao;
          return (
            <circle
              key={fatia.rotulo}
              cx={centro}
              cy={centro}
              r={raio - espessura / 2}
              fill="none"
              stroke={fatia.cor}
              strokeWidth={espessura}
              strokeDasharray={`${traco} ${circunferencia - traco}`}
              strokeDashoffset={-deslocamento}
              transform={`rotate(-90 ${centro} ${centro})`}
              opacity={ativo === null || ativo === indice ? 1 : 0.5}
              onMouseEnter={() => setAtivo(indice)}
              style={{ cursor: "pointer" }}
            />
          );
        })}
        <text
          x={centro}
          y={centro - 2}
          textAnchor="middle"
          style={{ fontSize: 22, fontWeight: 700, fill: "var(--tinta)", fontFamily: "var(--fonte-ui)" }}
        >
          {formatar(total)}
        </text>
        <text x={centro} y={centro + 16} textAnchor="middle" className={CLASSE_ROTULO_EIXO}>
          {rotuloDoCentro}
        </text>
      </svg>

      <div className={CLASSE_LEGENDA} style={{ flexDirection: "column", gap: 8 }}>
        {fatias.map((fatia, indice) => (
          <span
            key={fatia.rotulo}
            className={CLASSE_ITEM_LEGENDA}
            onMouseEnter={() => setAtivo(indice)}
            onMouseLeave={() => setAtivo(null)}
          >
            <span className={CLASSE_MARCA_LEGENDA} style={{ background: fatia.cor }} aria-hidden />
            {fatia.rotulo}
            <strong style={{ color: "var(--tinta)", fontVariantNumeric: "tabular-nums" }}>
              {formatar(fatia.valor)}
            </strong>
            <span style={{ color: "var(--tinta-3)" }}>
              ({total > 0 ? Math.round((fatia.valor / total) * 100) : 0}%)
            </span>
          </span>
        ))}
      </div>
    </div>
  );
}

// -------------------------------------------------------------------- medidor

/** Barra de consumo com trilho no mesmo matiz — o estado se lê na barra inteira. */
export function Medidor({
  valor,
  maximo = 100,
  cor,
  esquerda,
  direita,
  marca,
}: {
  valor: number;
  maximo?: number;
  cor: string;
  esquerda: string;
  direita: string;
  /** Posição de uma referência (a mediana da categoria, por exemplo), de 0 a 1. */
  marca?: { posicao: number; titulo: string } | null;
}) {
  const fracao = Math.max(0, Math.min(1, maximo > 0 ? valor / maximo : 0));
  return (
    <div className="flex flex-col gap-[6px]">
      <div className="relative h-[10px] rounded-pill bg-[var(--rampa-1)] overflow-hidden">
        <div
          className="absolute top-0 bottom-0 left-0 rounded-pill transition-[width] duration-[120ms] ease-[ease]"
          style={{ width: `${fracao * 100}%`, background: cor }}
        />
        {marca && (
          <div
            className="absolute -top-[3px] -bottom-[3px] w-[2px] bg-tinta-2"
            style={{ left: `${Math.max(0, Math.min(1, marca.posicao)) * 100}%` }}
            title={marca.titulo}
          />
        )}
      </div>
      <div className="flex justify-between text-xs text-tinta-3 tabular-nums">
        <span>{esquerda}</span>
        <span>{direita}</span>
      </div>
    </div>
  );
}

// -------------------------------------------------------------- mapa de calor

const DIAS_DA_SEMANA = ["dom", "seg", "ter", "qua", "qui", "sex", "sáb"];

export function MapaDeCalor({
  celulas,
}: {
  celulas: { diaDaSemana: number; hora: number; quantidade: number }[];
}) {
  const [caixa, largura] = useLargura();
  const [ativa, setAtiva] = useState<number | null>(null);

  const colunas = 8; // faixas de 3 horas
  const margemEsquerda = 34;
  const margemTopo = 18;
  const lado = Math.max(14, Math.min(30, (largura - margemEsquerda - 8) / colunas - 3));
  const maximo = Math.max(1, ...celulas.map((c) => c.quantidade));

  const nivel = (quantidade: number) => {
    if (quantidade === 0) return RAMPA[0];
    const passo = Math.ceil((quantidade / maximo) * (RAMPA.length - 1));
    return RAMPA[Math.max(1, Math.min(RAMPA.length - 1, passo))];
  };

  const altura = margemTopo + 7 * (lado + 3);

  return (
    <div className={CLASSE_AREA} ref={caixa}>
      <svg
        className={CLASSE_SVG}
        width={Math.max(largura, margemEsquerda + colunas * (lado + 3))}
        height={altura}
        role="img"
        aria-label="Mapa de atividade por dia da semana e faixa de horário"
        onMouseLeave={() => setAtiva(null)}
      >
        {Array.from({ length: colunas }, (_, coluna) => (
          <text
            key={coluna}
            className={CLASSE_ROTULO_EIXO}
            x={margemEsquerda + coluna * (lado + 3) + lado / 2}
            y={12}
            textAnchor="middle"
          >
            {coluna * 3}h
          </text>
        ))}
        {DIAS_DA_SEMANA.map((dia, linha) => (
          <text
            key={dia}
            className={CLASSE_ROTULO_EIXO}
            x={margemEsquerda - 6}
            y={margemTopo + linha * (lado + 3) + lado / 2 + 4}
            textAnchor="end"
          >
            {dia}
          </text>
        ))}
        {celulas.map((celula, indice) => (
          <rect
            key={indice}
            x={margemEsquerda + (celula.hora / 3) * (lado + 3)}
            y={margemTopo + celula.diaDaSemana * (lado + 3)}
            width={lado}
            height={lado}
            rx={3}
            fill={nivel(celula.quantidade)}
            stroke={ativa === indice ? "var(--tinta-2)" : "transparent"}
            strokeWidth={1}
            onMouseEnter={() => setAtiva(indice)}
          />
        ))}
      </svg>

      <div className="inline-flex items-center gap-[6px] text-xs text-tinta-3" style={{ marginTop: 6 }}>
        <span>menos</span>
        <span className="inline-flex gap-[2px]">
          {RAMPA.map((cor) => (
            <span key={cor} className="w-[14px] h-[10px] rounded-[2px]" style={{ background: cor }} />
          ))}
        </span>
        <span>mais ({maximo} no pico)</span>
      </div>

      {ativa !== null && (
        <Tooltip
          x={margemEsquerda + (celulas[ativa].hora / 3) * (lado + 3) + lado}
          y={margemTopo + celulas[ativa].diaDaSemana * (lado + 3)}
          largura={largura}
        >
          <div className={CLASSE_TOOLTIP_TITULO}>
            {DIAS_DA_SEMANA[celulas[ativa].diaDaSemana]}, {celulas[ativa].hora}h–
            {celulas[ativa].hora + 3}h
          </div>
          <div className={CLASSE_TOOLTIP_LINHA}>
            <span>movimentações</span>
            <span className={CLASSE_TOOLTIP_VALOR}>{celulas[ativa].quantidade}</span>
          </div>
        </Tooltip>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------- radar

export function Radar({
  eixos,
  cor = CORES_DE_SERIE[0],
  altura = 260,
}: {
  eixos: { eixo: string; valor: number | null; base: string }[];
  cor?: string;
  altura?: number;
}) {
  const [caixa, largura] = useLargura();
  const [ativo, setAtivo] = useState<number | null>(null);

  const centroX = largura / 2;
  const centroY = altura / 2;
  // O texto do eixo ocupa espaço fora do polígono; sem reservá-lo, "Qualidade da
  // leitura (sem dado)" sai cortado pela borda do cartão.
  const raio = Math.max(48, Math.min(centroY - 40, centroX - 110));
  const quantidade = eixos.length;

  const ponto = (indice: number, fracao: number) => {
    const angulo = (Math.PI * 2 * indice) / quantidade - Math.PI / 2;
    return [centroX + Math.cos(angulo) * raio * fracao, centroY + Math.sin(angulo) * raio * fracao];
  };

  // O polígono passa SÓ pelos eixos medidos. Fechá-lo em cima do zero de um eixo sem
  // dado desenharia "nota zero" onde não há medida nenhuma — o erro que o painel
  // inteiro existe para não cometer.
  const medidos = eixos
    .map((eixo, indice) => ({ ...eixo, indice }))
    .filter((eixo) => eixo.valor !== null);
  const caminho = medidos
    .map((eixo, ordem) => {
      const [x, y] = ponto(eixo.indice, (eixo.valor as number) / 100);
      return `${ordem === 0 ? "M" : "L"}${x},${y}`;
    })
    .join(" ");

  return (
    <div className={CLASSE_AREA} ref={caixa}>
      <svg
        className={CLASSE_SVG}
        width={largura}
        height={altura}
        role="img"
        aria-label="Radar de desempenho do caso"
        onMouseLeave={() => setAtivo(null)}
      >
        {[0.25, 0.5, 0.75, 1].map((anel) => (
          <polygon
            key={anel}
            points={eixos.map((_, indice) => ponto(indice, anel).join(",")).join(" ")}
            fill="none"
            className={CLASSE_LINHA_GRADE}
          />
        ))}
        {eixos.map((eixo, indice) => {
          const [x, y] = ponto(indice, 1);
          return (
            <line key={eixo.eixo} x1={centroX} y1={centroY} x2={x} y2={y} className={CLASSE_LINHA_GRADE} />
          );
        })}

        {medidos.length >= 3 && (
          <path d={`${caminho} Z`} fill={cor} fillOpacity={0.12} stroke={cor} strokeWidth={2} />
        )}

        {eixos.map((eixo, indice) => {
          const [x, y] = ponto(indice, (eixo.valor ?? 0) / 100);
          const [rx, ry] = ponto(indice, 1.16);
          const ancora = rx > centroX + 6 ? "start" : rx < centroX - 6 ? "end" : "middle";
          return (
            <g key={eixo.eixo} onMouseEnter={() => setAtivo(indice)}>
              {eixo.valor !== null && (
                <circle cx={x} cy={y} r={4} fill={cor} stroke="var(--papel)" strokeWidth={2} />
              )}
              <text className={CLASSE_ROTULO_EIXO} x={rx} y={ry} textAnchor={ancora}>
                {eixo.eixo}
              </text>
              {/* Valor na linha de baixo: cabe em cartão estreito e mantém a palavra
                * "sem dado" legível, em vez de espremê-la ao lado do nome. */}
              <text
                className={CLASSE_ROTULO_EIXO}
                x={rx}
                y={ry + 13}
                textAnchor={ancora}
                style={{
                  fill: eixo.valor === null ? "var(--tinta-3)" : "var(--tinta)",
                  fontWeight: eixo.valor === null ? 400 : 600,
                }}
              >
                {eixo.valor === null ? "sem dado" : Math.round(eixo.valor)}
              </text>
              <circle cx={rx} cy={ry} r={16} fill="transparent" onMouseEnter={() => setAtivo(indice)} />
            </g>
          );
        })}
      </svg>

      {ativo !== null && (
        <Tooltip x={centroX} y={0} largura={largura}>
          <div className={CLASSE_TOOLTIP_TITULO}>{eixos[ativo].eixo}</div>
          <div className={CLASSE_TOOLTIP_LINHA}>
            <span>nota</span>
            <span className={CLASSE_TOOLTIP_VALOR}>
              {eixos[ativo].valor === null ? "sem dado" : Math.round(eixos[ativo].valor as number)}
            </span>
          </div>
          <div className="mt-[6px] pt-[6px] border-t border-borda text-tinta-3">{eixos[ativo].base}</div>
        </Tooltip>
      )}
    </div>
  );
}

/** Sparkline de 1px de peso visual — acompanha um número, nunca substitui o gráfico. */
export function Faisca({
  valores,
  cor = CORES_DE_SERIE[0],
  largura = 90,
  altura = 24,
}: {
  valores: number[];
  cor?: string;
  largura?: number;
  altura?: number;
}) {
  if (valores.length < 2) return null;
  const maximo = Math.max(1, ...valores);
  const passo = largura / (valores.length - 1);
  const caminho = valores
    .map((valor, indice) => `${indice === 0 ? "M" : "L"}${indice * passo},${altura - (valor / maximo) * altura}`)
    .join(" ");
  return (
    <svg width={largura} height={altura} className={CLASSE_SVG} aria-hidden>
      <path d={caminho} fill="none" stroke={cor} strokeWidth={2} strokeLinejoin="round" />
    </svg>
  );
}
