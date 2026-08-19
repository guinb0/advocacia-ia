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

import { Aviso, Selo } from "@/components/Basicos";
import { CORES_DE_SERIE, Figura, GraficoDeBarras, GraficoDeLinha, SemDado } from "@/components/graficos";
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
import estilos from "./Jurimetria.module.css";

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

function corDoDesfecho(codigo: string): string {
  return COR_DO_DESFECHO[codigo] ?? "var(--tinta-3)";
}

export default function Jurimetria({
  casoId,
  onVoltar,
  onAbrirDossie,
  onAbrirPainel,
}: {
  casoId: string;
  onVoltar: () => void;
  onAbrirDossie: () => void;
  onAbrirPainel: () => void;
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
    <div className={estilos.pagina}>
      <div className={estilos.topo}>
        <div className={estilos.navegacao}>
          <button type="button" className="botao botao--secundario botao--pequeno" onClick={onVoltar}>
            ← Voltar para a carteira
          </button>
          <button type="button" className="botao botao--texto botao--pequeno" onClick={onAbrirDossie}>
            Dossiê do caso →
          </button>
          <button type="button" className="botao botao--texto botao--pequeno" onClick={onAbrirPainel}>
            Painel analítico →
          </button>
        </div>
        <h1 className={estilos.titulo}>Jurisprudência e jurimetria</h1>
        <p className={estilos.subtitulo}>
          Como o foro decidiu casos comparáveis a este, medido sobre decisões já proferidas.
          Não é previsão de resultado.
        </p>
      </div>

      {carregando && <div className={estilos.vazio}>Consultando o acervo…</div>}

      {erro && !carregando && (
        <Aviso tom="critico" titulo="O painel não foi calculado">
          {erro}
          <div className={estilos.acaoDoErro}>
            <button type="button" className="botao botao--secundario botao--pequeno" onClick={() => void carregar()}>
              Tentar de novo
            </button>
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
          <div className={estilos.heroi}>
            <span className={estilos.valorHeroi}>{percentual(dados.appellate.share)}</span>
            <span className={estilos.detalheHeroi}>
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
        <ul className={estilos.ausencias}>
          {dados.absences.map((item) => (
            <li key={item.question}>
              <strong>{item.question}</strong>
              <span>{item.reason}</span>
            </li>
          ))}
        </ul>
      </Secao>

      <p className={estilos.natureza}>{dados.nature}</p>
    </>
  );
}

/** O recorte por extenso: sem ele, todo percentual da tela perde o referente. */
function Recorte({ dados }: { dados: Dados }) {
  const cobertura = dados.coverage;
  return (
    <div className={`cartao ${estilos.recorte}`}>
      <div>
        <span className={estilos.rotuloRecorte}>Recorte medido</span>
        <strong className={estilos.valorRecorte}>{dados.scope.label}</strong>
      </div>
      <div className={estilos.numerosRecorte}>
        <span>
          <strong>{cobertura.processes.toLocaleString("pt-BR")}</strong> processos
        </span>
        {cobertura.first_decision && cobertura.last_decision && (
          <span>
            decisões de {cobertura.first_decision.slice(0, 4)} a {cobertura.last_decision.slice(0, 4)}
          </span>
        )}
        {dados.reference && (
          <span>
            referência: {dados.reference.scope.label} ({dados.reference.coverage.processes.toLocaleString("pt-BR")})
          </span>
        )}
      </div>
      {(dados.scope.notes ?? []).length > 0 && (
        <ul className={estilos.notasRecorte}>
          {(dados.scope.notes ?? []).map((nota) => (
            <li key={nota}>{nota}</li>
          ))}
        </ul>
      )}
    </div>
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

      <ul className={estilos.comparacoes}>
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
    <li className={estilos.comparacao}>
      <div className={estilos.comparacaoTopo}>
        <strong>{rotuloDoDesfecho(linha.label)}</strong>
        <span className={estilos.parcela}>{percentual(linha.share)}</span>
      </div>
      <div className={estilos.comparacaoBase}>
        <span>
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
        <p className={estilos.rodapeFigura}>
          * Ano incompleto — ainda corre, ou o acervo termina no meio dele. A queda no
          último ponto é de calendário, não de entendimento.
        </p>
      )}

      {dados.trend ? (
        <div className={estilos.tendencia}>
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
          <span className={estilos.base}>{dados.trend.comparison.basis}</span>
        </div>
      ) : (
        <p className={estilos.rodapeFigura}>
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
    <ul className={estilos.fatias}>
      {ranking.slices.map((fatia) => {
        const principal = fatia.shares[0];
        const leitura = leituraDaComparacao(principal?.comparacao);
        return (
          <li key={fatia.value} className={estilos.fatia}>
            <div className={estilos.fatiaTopo}>
              <strong>{fatia.value}</strong>
              <span>{fatia.processes} processos</span>
            </div>
            <div className={estilos.barras}>
              {fatia.shares.map((linha) => (
                <span
                  key={linha.label}
                  className={estilos.segmento}
                  style={{ width: `${linha.share * 100}%`, background: corDoDesfecho(linha.label) }}
                  title={`${rotuloDoDesfecho(linha.label)}: ${linha.count} (${percentual(linha.share)})`}
                />
              ))}
            </div>
            <div className={estilos.fatiaBase}>
              {principal && (
                <span>
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
    <section className={estilos.secao}>
      <h2 className={estilos.tituloSecao}>
        <span className={estilos.numeroSecao}>{numero}</span>
        {titulo}
      </h2>
      {explicacao && <p className={estilos.explicacaoSecao}>{explicacao}</p>}
      <div className="cartao">{children}</div>
    </section>
  );
}
