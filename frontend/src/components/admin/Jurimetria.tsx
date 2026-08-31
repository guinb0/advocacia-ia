"use client";

/**
 * Jurisprudência & Jurimetria — a quarta tela do caso.
 *
 * As quatro respondem perguntas diferentes, e é por isso que são quatro:
 *
 *   checklist  → "o que ainda falta chegar?"
 *   dossiê     → "o que este caso já é?"
 *   painel     → "como este caso se comportou no tempo?"
 *   jurimetria → "o que esperar do mérito, e com que fundamento?"
 *
 * Esta é a única que olha para fora do escritório: os números vêm do acervo de
 * jurisprudência, não dos casos do escritório. Isso muda a régua de honestidade e é o que
 * organiza a tela inteira:
 *
 * - **nenhum percentual aparece sozinho.** Ao lado de cada um vão a amostra ("em 79
 *   processos"), a margem de erro e o recorte que o produziu. Um número solto vira "61% de
 *   chance de ganhar" na conversa com o cliente, e essa frase não se sustenta;
 * - **diferença que a amostra não sustenta é dita, não escondida.** Sai marcada como
 *   "dentro da margem", com a conta no tooltip. Omitir faria quem viu 8 pontos ontem achar
 *   que o sistema mudou de ideia; exibir como achado faria ruído virar tendência;
 * - **o que o acervo não sabe fecha a tela.** A última seção lista, por escrito, as
 *   perguntas que este painel não responde — valor de condenação, taxa de reforma, pedido
 *   deferido. Ausência declarada é informação; ausência omitida é lida como "não houve".
 *
 * Nada aqui é previsão. Todo bloco carrega a frase de natureza que o backend envia, e ela
 * é repetida de propósito: um bloco copiado para uma apresentação viaja sem o topo da tela.
 */

import { useCallback, useEffect, useState } from "react";

import { Aviso, Botao, Cartao, Selo } from "@/components/ui/Basicos";
import { CORES_DE_SERIE, Figura, GraficoDeBarras, GraficoDeLinha, SemDado } from "@/components/ui/graficos";
import {
  buscarJurimetria,
  leituraDaComparacao,
  percentual,
  pontos,
  rotuloDoDesfecho,
  type Jurimetria as Dados,
  type Proporcao,
  type Ranking,
} from "@/lib/jurimetria";

/* Cor por desfecho, fixa: a mesma fatia precisa ter a mesma cor no gráfico de rosca, na
 * série anual e em cada ranking. Cor que muda de significado entre seções é pior que
 * nenhuma cor. Acompanhada sempre de palavra — cor nunca carrega sentido sozinha. */
const COR_DO_DESFECHO: Record<string, string> = {
  PROCEDENTE: "var(--ok)",
  PARCIAL: CORES_DE_SERIE[0],
  IMPROCEDENTE: "var(--critico)",
  ACORDO: CORES_DE_SERIE[2],
  EXTINTO: "var(--tinta-3)",
  INDEFINIDO: "var(--tinta-3)",
};

const JURIMETRIA_SHELL = "flex w-full min-w-0 max-w-full flex-col gap-5";
const CARTAO_SECAO = "min-w-0 max-w-full overflow-hidden";

function corDoDesfecho(codigo: string): string {
  return COR_DO_DESFECHO[codigo] ?? "var(--tinta-3)";
}

export default function Jurimetria({
  casoId,
  onVoltar,
}: {
  casoId: string;
  onVoltar: () => void;
  onAbrirDossie?: () => void;
  onAbrirPainel?: () => void;
}) {
  const [dados, setDados] = useState<Dados | null>(null);
  const [erro, setErro] = useState<string | null>(null);
  const [carregando, setCarregando] = useState(true);

  const carregar = useCallback(async () => {
    setCarregando(true);
    setErro(null);
    try {
      setDados(await buscarJurimetria(casoId));
    } catch (falha) {
      // A mensagem do backend distingue "sem pesquisa ainda" de "o acervo não respondeu",
      // e essas duas levam o advogado a ações opostas. Por isso ela é exibida crua.
      setErro(falha instanceof Error ? falha.message : "Falha ao consultar o acervo.");
      setDados(null);
    } finally {
      setCarregando(false);
    }
  }, [casoId]);

  useEffect(() => {
    void carregar();
  }, [carregar]);

  return (
    <div className={JURIMETRIA_SHELL}>
      <header className="overflow-hidden rounded-cartao border border-borda-forte bg-papel shadow-cartao">
        <div className="flex min-w-0 flex-col gap-3 border-b border-borda bg-papel-2 px-4 py-4 sm:px-5 lg:flex-row lg:items-end lg:justify-between">
          <div className="min-w-0">
            <Botao variante="texto" pequeno onClick={onVoltar}>
              ← Carteira
            </Botao>
            <span className="mt-3 block text-[11px] font-bold uppercase tracking-[0.12em] text-tinta-3">
              Acervo jurisprudencial
            </span>
            <h1 className="mt-1 truncate font-titulo text-xl leading-[1.15] text-tinta">
              Jurisprudência e jurimetria
            </h1>
            <p className="mt-2 max-w-[76ch] text-sm leading-[1.55] text-tinta-2">
              Como o foro decidiu casos comparáveis a este, medido sobre decisões já
              proferidas. Não é previsão de resultado.
            </p>
          </div>
          <Botao variante="secundario" pequeno onClick={() => void carregar()}>
            Atualizar
          </Botao>
        </div>
      </header>

      {carregando && (
        <div className="rounded-cartao border border-borda bg-papel px-5 py-10 text-center text-tinta-3 shadow-cartao">
          Consultando o acervo…
        </div>
      )}

      {erro && !carregando && (
        <Aviso tom="critico" titulo="O painel não foi calculado">
          {erro}
          <div className="mt-[10px]">
            <Botao variante="secundario" pequeno onClick={() => void carregar()}>
              Tentar de novo
            </Botao>
          </div>
        </Aviso>
      )}

      {dados && !carregando && <Painel dados={dados} />}
    </div>
  );
}

function Painel({ dados }: { dados: Dados }) {
  const referencia = dados.reference;

  return (
    <>
      <Recorte dados={dados} />

      {!dados.reliable && (
        <Aviso tom="atencao" titulo="Amostra pequena demais para leitura">
          O recorte tem {dados.coverage.processes} processo(s), abaixo do mínimo de{" "}
          {dados.minimum_sample}. Os números abaixo valem como contagem, não como tendência.
        </Aviso>
      )}

      {dados.notes.map((nota) => (
        <Aviso key={nota} tom="info">
          {nota}
        </Aviso>
      ))}

      <Secao
        numero={1}
        titulo="Como esses casos terminaram"
        explicacao={
          referencia
            ? `Cada desfecho comparado com o mesmo recorte sem a vara — ${referencia.coverage.processes} processos.`
            : "Distribuição do recorte. Sem referência: este já é o acervo completo."
        }
      >
        <Desfechos linhas={dados.outcomes} />
      </Secao>

      <Secao
        numero={2}
        titulo="Isso está mudando?"
        explicacao="Desfechos por ano da decisão. Ano incompleto sai marcado, e a tendência só é afirmada quando a amostra a sustenta."
      >
        <Serie dados={dados} />
      </Secao>

      {dados.rankings.map((ranking, indice) => (
        <Secao
          key={ranking.dimension}
          numero={3 + indice}
          titulo={`Por ${ranking.label}`}
          explicacao={`Ordenado por volume, nunca por taxa de êxito. ${
            ranking.counts_processes_once
              ? ""
              : "Um processo pode entrar em mais de uma fatia — a coluna não fecha com o total."
          }`}
        >
          <RankingBlocos ranking={ranking} />
        </Secao>
      ))}

      {dados.appellate && (
        <Secao
          numero={3 + dados.rankings.length}
          titulo="Chegaram a instância superior"
          explicacao={dados.appellate.meaning}
        >
          <div className="flex flex-col gap-1">
            <span className="text-[34px] tabular-nums text-tinta leading-none">
              {percentual(dados.appellate.share)}
            </span>
            <span className="text-tinta-3 text-sm">
              {dados.appellate.count} de {dados.appellate.total} processos do recorte
              {" · "}margem de {percentual(dados.appellate.margin)}
            </span>
          </div>
        </Secao>
      )}

      <Secao
        numero={4 + dados.rankings.length}
        titulo="O que este painel não responde"
        explicacao="Perguntas frequentes que o acervo não sustenta. Estão aqui porque a ausência de um gráfico é lida como ausência do fato."
      >
        <ul className="list-none m-0 p-0 flex flex-col gap-3">
          {dados.absences.map((item) => (
            <li key={item.question} className="flex flex-col gap-[2px]">
              <strong className="text-tinta text-sm">{item.question}</strong>
              <span className="text-tinta-2 text-sm">{item.reason}</span>
            </li>
          ))}
        </ul>
      </Secao>

      <p className="text-tinta-3 text-xs max-w-[82ch] m-0">{dados.nature}</p>
    </>
  );
}

/** O recorte por extenso: sem ele, todo percentual da tela perde o referente. */
function Recorte({ dados }: { dados: Dados }) {
  const cobertura = dados.coverage;
  return (
    <Cartao className="flex min-w-0 max-w-full flex-col gap-[10px] overflow-hidden">
      <div className="min-w-0">
        <span className="block text-xs uppercase tracking-[0.04em] text-tinta-3">Recorte medido</span>
        <strong className="block truncate text-md text-tinta" title={dados.scope.label}>{dados.scope.label}</strong>
      </div>
      <div className="flex min-w-0 flex-wrap gap-x-[18px] gap-y-2 text-sm text-tinta-2">
        <span>
          <strong>{cobertura.processes.toLocaleString("pt-BR")}</strong> processos
        </span>
        {cobertura.first_decision && cobertura.last_decision && (
          <span className="min-w-0 max-w-full truncate" title={`decisões de ${cobertura.first_decision.slice(0, 4)} a ${cobertura.last_decision.slice(0, 4)}`}>
            decisões de {cobertura.first_decision.slice(0, 4)} a {cobertura.last_decision.slice(0, 4)}
          </span>
        )}
        {dados.reference && (
          <span className="min-w-0 max-w-full truncate" title={`referência: ${dados.reference.scope.label} (${dados.reference.coverage.processes.toLocaleString("pt-BR")})`}>
            referência: {dados.reference.scope.label} ({dados.reference.coverage.processes.toLocaleString("pt-BR")})
          </span>
        )}
      </div>
      {(dados.scope.notes ?? []).length > 0 && (
        <ul className="m-0 flex min-w-0 flex-col gap-1 pl-[18px] text-sm text-tinta-2">
          {(dados.scope.notes ?? []).map((nota) => (
            <li key={nota} className="[overflow-wrap:anywhere]">{nota}</li>
          ))}
        </ul>
      )}
    </Cartao>
  );
}

function Desfechos({ linhas }: { linhas: Proporcao[] }) {
  if (linhas.length === 0) {
    return <SemDado titulo="Nenhum processo com desfecho no recorte" />;
  }

  return (
    <>
      <Figura
        titulo="Desfechos do recorte"
        descricao="Um voto por processo, não por documento."
        tabela={{
          colunas: [
            { chave: "desfecho", rotulo: "Desfecho" },
            { chave: "processos", rotulo: "Processos" },
            { chave: "parcela", rotulo: "Parcela" },
            { chave: "diferenca", rotulo: "vs. referência" },
          ],
          linhas: linhas.map((linha) => ({
            desfecho: rotuloDoDesfecho(linha.label),
            processos: linha.count,
            parcela: percentual(linha.share),
            diferenca: linha.comparacao
              ? `${pontos(linha.comparacao.difference_points)}${
                  linha.comparacao.meaningful ? "" : " (dentro da margem)"
                }`
              : "—",
          })),
        }}
      >
        <GraficoDeBarras
          itens={linhas.map((linha) => ({
            rotulo: rotuloDoDesfecho(linha.label),
            valores: [
              {
                nome: "processos",
                valor: Math.round(linha.share * 1000) / 10,
                cor: corDoDesfecho(linha.label),
              },
            ],
            nota: `${linha.count} de ${linha.total} processos · margem de ${percentual(linha.margin)}`,
          }))}
          unidade="%"
        />
      </Figura>

      <ul className="list-none mt-4 mb-0 p-0 flex flex-col gap-[10px]">
        {linhas.map((linha) => (
          <LinhaDeComparacao key={linha.label} linha={linha} />
        ))}
      </ul>
    </>
  );
}

/** Um desfecho com tudo o que ele precisa carregar: parcela, amostra e ressalva. */
function LinhaDeComparacao({ linha }: { linha: Proporcao }) {
  const leitura = leituraDaComparacao(linha.comparacao);

  return (
    <li className="flex min-w-0 flex-col gap-1 rounded-[8px] border border-borda bg-papel-2 px-3 py-[10px]">
      <div className="flex min-w-0 items-baseline justify-between gap-3">
        <strong className="min-w-0 truncate" title={rotuloDoDesfecho(linha.label)}>{rotuloDoDesfecho(linha.label)}</strong>
        <span className="text-lg tabular-nums text-tinta">{percentual(linha.share)}</span>
      </div>
      <div className="flex min-w-0 flex-wrap items-center justify-between gap-3 text-xs text-tinta-3">
        <span className="min-w-0 truncate">
          {linha.count} de {linha.total} processos · margem de {percentual(linha.margin)}
        </span>
        {leitura && linha.comparacao && (
          /* O `title` traz a conta: nota sem fórmula visível é chute com aparência de
           * medida, e é essa frase que sustenta a diferença numa reunião. */
          <span title={linha.comparacao.basis}>
            <Selo tom={leitura.tom} simbolo={leitura.simbolo}>
              {pontos(linha.comparacao.difference_points)} · {leitura.palavra}
            </Selo>
          </span>
        )}
      </div>
    </li>
  );
}

function Serie({ dados }: { dados: Dados }) {
  const pontosDoAno = dados.timeline;
  if (pontosDoAno.length === 0) {
    return <SemDado titulo="Sem decisões datadas no recorte" />;
  }

  /* Uma linha por desfecho, com a parcela do ano. Volume absoluto por ano diria mais
   * sobre a ingestão do acervo do que sobre o entendimento do foro. */
  const desfechos = Array.from(
    new Set(pontosDoAno.flatMap((ponto) => ponto.shares.map((item) => item.label))),
  );

  return (
    <>
      <Figura
        titulo="Parcela de cada desfecho por ano"
        descricao="Ano da decisão. Anos incompletos aparecem na tabela marcados."
        legenda={desfechos.map((codigo) => ({
          rotulo: rotuloDoDesfecho(codigo),
          cor: corDoDesfecho(codigo),
          forma: "linha" as const,
        }))}
        tabela={{
          colunas: [
            { chave: "ano", rotulo: "Ano" },
            { chave: "processos", rotulo: "Processos" },
            ...desfechos.map((codigo) => ({ chave: codigo, rotulo: rotuloDoDesfecho(codigo) })),
          ],
          linhas: pontosDoAno.map((ponto) => ({
            ano: ponto.partial ? `${ponto.year} (incompleto)` : String(ponto.year),
            processos: ponto.processes,
            ...Object.fromEntries(
              desfechos.map((codigo) => [
                codigo,
                percentual(ponto.shares.find((item) => item.label === codigo)?.share ?? 0),
              ]),
            ),
          })),
        }}
      >
        <GraficoDeLinha
          rotulos={pontosDoAno.map((ponto) => (ponto.partial ? `${ponto.year}*` : String(ponto.year)))}
          series={desfechos.map((codigo) => ({
            nome: rotuloDoDesfecho(codigo),
            cor: corDoDesfecho(codigo),
            unidade: "%",
            valores: pontosDoAno.map(
              (ponto) =>
                Math.round((ponto.shares.find((item) => item.label === codigo)?.share ?? 0) * 1000) / 10,
            ),
          }))}
          rotuloDoValor={(valor) => `${valor}%`}
        />
      </Figura>

      {pontosDoAno.some((ponto) => ponto.partial) && (
        <p className="mt-[10px] mb-0 text-tinta-3 text-xs max-w-[82ch]">
          * Ano incompleto — ainda corre, ou o acervo termina no meio dele. A queda no
          último ponto é de calendário, não de entendimento.
        </p>
      )}

      {dados.trend ? (
        <div className="mt-[14px] flex items-center gap-3 flex-wrap text-tinta-2 text-sm">
          <Selo
            tom={dados.trend.direction === "estável" ? "neutro" : "info"}
            simbolo={dados.trend.direction === "alta" ? "▲" : dados.trend.direction === "queda" ? "▼" : "≈"}
          >
            {rotuloDoDesfecho(dados.trend.label)}: {dados.trend.direction}
          </Selo>
          <span>
            {dados.trend.first_year} a {dados.trend.last_year} ·{" "}
            {pontos(dados.trend.comparison.difference_points)}
          </span>
          <span className="text-tinta-3 text-xs [flex-basis:100%]">{dados.trend.comparison.basis}</span>
        </div>
      ) : (
        <p className="mt-[10px] mb-0 text-tinta-3 text-xs max-w-[82ch]">
          Sem dois anos completos no recorte, não há série para afirmar tendência.
        </p>
      )}
    </>
  );
}

function RankingBlocos({ ranking }: { ranking: Ranking }) {
  if (ranking.slices.length === 0) {
    return <SemDado titulo="Nenhuma fatia com processos neste eixo" />;
  }

  return (
    <ul className="m-0 flex min-w-0 list-none flex-col gap-[14px] p-0">
      {ranking.slices.map((fatia) => {
        const principal = fatia.shares[0];
        const leitura = leituraDaComparacao(principal?.comparacao);
        return (
          <li key={fatia.value} className="flex min-w-0 flex-col gap-[6px]">
            <div className="flex min-w-0 items-baseline justify-between gap-3 text-sm text-tinta [&_span]:tabular-nums [&_span]:text-tinta-3">
              <strong className="min-w-0 truncate" title={fatia.value}>{fatia.value}</strong>
              <span>{fatia.processes} processos</span>
            </div>
            <div className="flex h-[14px] rounded-[4px] overflow-hidden bg-papel-2 border border-borda">
              {fatia.shares.map((linha) => (
                <span
                  key={linha.label}
                  className="h-full"
                  style={{ width: `${linha.share * 100}%`, background: corDoDesfecho(linha.label) }}
                  title={`${rotuloDoDesfecho(linha.label)}: ${linha.count} (${percentual(linha.share)})`}
                />
              ))}
            </div>
            <div className="flex min-w-0 flex-wrap items-center justify-between gap-3 text-xs text-tinta-3">
              {principal && (
                <span className="min-w-0 truncate">
                  {rotuloDoDesfecho(principal.label)} {percentual(principal.share)}
                </span>
              )}
              {fatia.small_sample ? (
                <Selo tom="atencao" simbolo="!">
                  amostra pequena
                </Selo>
              ) : (
                leitura &&
                principal?.comparacao && (
                  <span title={principal.comparacao.basis}>
                    <Selo tom={leitura.tom} simbolo={leitura.simbolo}>
                      {pontos(principal.comparacao.difference_points)} · {leitura.palavra}
                    </Selo>
                  </span>
                )
              )}
            </div>
          </li>
        );
      })}
    </ul>
  );
}

function Secao({
  numero,
  titulo,
  explicacao,
  children,
}: {
  numero: number;
  titulo: string;
  explicacao?: string;
  children: React.ReactNode;
}) {
  return (
    <section className="flex min-w-0 max-w-full flex-col gap-[10px]">
      <h2 className="m-0 flex min-w-0 items-center gap-[10px] font-titulo text-lg text-tinta">
        <span className="inline-flex h-[26px] w-[26px] shrink-0 items-center justify-center rounded-full border border-borda-forte bg-papel-2 text-xs text-tinta-2">
          {numero}
        </span>
        <span className="min-w-0 truncate" title={titulo}>{titulo}</span>
      </h2>
      {explicacao && <p className="m-0 max-w-[82ch] text-sm text-tinta-2">{explicacao}</p>}
      <Cartao className={CARTAO_SECAO}>{children}</Cartao>
    </section>
  );
}
