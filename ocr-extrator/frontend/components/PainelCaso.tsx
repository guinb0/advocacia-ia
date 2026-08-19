"use client";

/**
 * Painel analítico do caso — a terceira aba, ao lado do checklist e do dossiê.
 *
 * As três telas do caso respondem perguntas diferentes, e é por isso que são três:
 *
 *   checklist → "o que ainda falta chegar?"
 *   dossiê    → "o que este caso já é?"
 *   painel    → "como este caso se comportou no tempo, e onde ele está travando?"
 *
 * Tudo o que aparece aqui vem de instante gravado no banco. O sistema não guarda
 * prioridade, prazo, SLA contratado nem responsável formal: em vez de deduzir esses
 * campos, a seção 4 mostra a **referência histórica** (mediana dos casos anteriores da
 * mesma categoria, com o tamanho da amostra) e a seção final lista, por escrito, o que o
 * sistema não sabe. Ausência declarada é informação; ausência preenchida por estimativa
 * vira compromisso na cabeça de quem lê.
 *
 * Nove seções, na ordem em que se lê um caso: resumo, indicadores, evolução, prazos,
 * tempo por etapa, comparação, ocorrências, riscos e histórico.
 */

import { useCallback, useEffect, useMemo, useState } from "react";

import { Aviso, Selo } from "@/components/Basicos";
import {
  CORES_DE_SERIE,
  Faisca,
  Figura,
  GraficoDeBarras,
  GraficoDeColunas,
  GraficoDeLinha,
  MapaDeCalor,
  Medidor,
  Radar,
  Rosca,
  SemDado,
} from "@/components/graficos";
import type { TomSelo } from "@/lib/formato";
import {
  buscarPainel,
  dataCurta,
  dataHora,
  duracao,
  filtrarPorPeriodo,
  LEITURA_DO_TOM,
  mapaDeAtividade,
  numero,
  PERIODOS,
  porTipo,
  ESTADO_DO_FATO,
  origemLegivel,
  valorDoFato,
  ROTULO_DA_PENDENCIA,
  rotuloLegivel,
  ROTULO_DO_TIPO,
  serieDiaria,
  type EtapaDoDossie,
  type EventoDoCaso,
  type FatoDoCaso,
  type Painel,
  type Periodo,
  type Tom,
} from "@/lib/painel";
import estilos from "./PainelCaso.module.css";

/* Vocabulário de estado: símbolo + palavra + cor, nesta ordem (GUIA-VISUAL). */
const ESTADO_ETAPA: Record<
  EtapaDoDossie["estado"],
  { simbolo: string; palavra: string; tom: TomSelo }
> = {
  pronto: { simbolo: "✓", palavra: "Pronto", tom: "ok" },
  andamento: { simbolo: "→", palavra: "Em andamento", tom: "info" },
  atencao: { simbolo: "!", palavra: "Conferir", tom: "atencao" },
  pendente: { simbolo: "•", palavra: "Falta fazer", tom: "neutro" },
  indisponivel: { simbolo: "✕", palavra: "Sem resposta", tom: "critico" },
};

const COR_DO_TOM: Record<Tom, string> = {
  ok: "var(--ok)",
  atencao: "var(--atencao-marca)",
  critico: "var(--critico)",
  info: "var(--acao)",
  neutro: "var(--tinta-3)",
};

const FUNDO_DO_TOM: Record<Tom, string> = {
  ok: "var(--ok-claro)",
  atencao: "var(--atencao-claro)",
  critico: "var(--critico-claro)",
  info: "var(--acao-clara)",
  neutro: "var(--papel-2)",
};

const BORDA_DO_TOM: Record<Tom, string> = {
  ok: "var(--ok-borda)",
  atencao: "var(--atencao-borda)",
  critico: "var(--critico-borda)",
  info: "var(--acao-borda)",
  neutro: "var(--borda-forte)",
};

const TOM_SELO: Record<Tom, TomSelo> = {
  ok: "ok",
  atencao: "atencao",
  critico: "critico",
  info: "info",
  neutro: "neutro",
};

function Secao({
  numero: indice,
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
        <span className={estilos.numeroSecao} aria-hidden>
          {indice}
        </span>
        {titulo}
      </h2>
      {explicacao && <p className={estilos.explicacaoSecao}>{explicacao}</p>}
      {children}
    </section>
  );
}

function Campo({
  rotulo,
  valor,
  ausente,
}: {
  rotulo: string;
  valor: React.ReactNode;
  /** Motivo pelo qual o campo não existe. Preenchido, ele substitui o valor. */
  ausente?: string;
}) {
  return (
    <div className={estilos.campo}>
      <span className={estilos.rotuloCampo}>{rotulo}</span>
      {ausente ? (
        <span className={estilos.valorAusente} title={ausente}>
          não registrado
        </span>
      ) : (
        <span className={estilos.valorCampo}>{valor}</span>
      )}
    </div>
  );
}

function CartaoIndicador({
  rotulo,
  valor,
  unidade,
  detalhe,
  tom,
  comparacao,
  faisca,
}: {
  rotulo: string;
  valor: number | null;
  unidade: string;
  detalhe: string;
  tom: Tom;
  comparacao?: { rotulo: string; valor: number; desvio_percentual: number | null } | null;
  faisca?: number[];
}) {
  const leitura = LEITURA_DO_TOM[tom];
  return (
    <div className={estilos.indicador}>
      <span className={estilos.rotuloIndicador}>{rotulo}</span>
      <span className={estilos.valorIndicador}>
        {valor === null ? "—" : numero(valor)}
        {unidade && valor !== null && <span className={estilos.unidadeIndicador}>{unidade}</span>}
      </span>
      {/* A cor do número nunca informa sozinha: quando o tom significa alguma coisa,
       * o selo escreve a palavra ao lado. */}
      {tom !== "neutro" && (
        <span>
          <Selo tom={TOM_SELO[tom]} simbolo={leitura.simbolo}>
            {leitura.palavra}
          </Selo>
        </span>
      )}
      <span className={estilos.detalheIndicador}>{detalhe}</span>
      {comparacao && (
        <span className={estilos.comparacaoIndicador}>
          <span aria-hidden>
            {comparacao.desvio_percentual === null
              ? "≈"
              : comparacao.desvio_percentual > 0
                ? "▲"
                : "▼"}
          </span>
          {comparacao.rotulo}: {numero(comparacao.valor)}
          {comparacao.desvio_percentual !== null &&
            ` (${comparacao.desvio_percentual > 0 ? "+" : ""}${comparacao.desvio_percentual}%)`}
        </span>
      )}
      {faisca && faisca.length > 2 && <Faisca valores={faisca} />}
    </div>
  );
}

export default function PainelCaso({
  casoId,
  onVoltar,
  onAbrirChecklist,
  onAbrirDossie,
  onAbrirJurimetria,
}: {
  casoId: string;
  onVoltar: () => void;
  onAbrirChecklist: () => void;
  onAbrirDossie: () => void;
  onAbrirJurimetria?: () => void;
}) {
  const [dados, setDados] = useState<Painel | null>(null);
  const [carregando, setCarregando] = useState(true);
  const [erro, setErro] = useState<string | null>(null);
  const [periodo, setPeriodo] = useState<Periodo>(30);
  const [tiposVisiveis, setTiposVisiveis] = useState<string[]>([]);
  const [eventosMostrados, setEventosMostrados] = useState(25);

  const carregar = useCallback(async () => {
    setCarregando(true);
    try {
      setDados(await buscarPainel(casoId));
      setErro(null);
    } catch (e) {
      setErro(e instanceof Error ? e.message : "Não foi possível montar o painel.");
    } finally {
      setCarregando(false);
    }
  }, [casoId]);

  useEffect(() => {
    void carregar();
  }, [carregar]);

  const eventosDoPeriodo = useMemo(
    () => (dados ? filtrarPorPeriodo(dados.eventos, periodo) : []),
    [dados, periodo],
  );

  const eventosFiltrados = useMemo(
    () =>
      tiposVisiveis.length === 0
        ? eventosDoPeriodo
        : eventosDoPeriodo.filter((evento) => tiposVisiveis.includes(evento.tipo)),
    [eventosDoPeriodo, tiposVisiveis],
  );

  const serie = useMemo(
    () => (dados ? serieDiaria(eventosFiltrados, periodo, dados.caso.aberto_em) : []),
    [dados, eventosFiltrados, periodo],
  );

  const distribuicaoPorTipo = useMemo(() => porTipo(eventosFiltrados), [eventosFiltrados]);
  const mapa = useMemo(() => mapaDeAtividade(eventosFiltrados), [eventosFiltrados]);

  if (carregando && !dados) {
    return (
      <div className={estilos.pagina}>
        <div className={estilos.navegacao}>
          <button type="button" className="botao botao--secundario botao--pequeno" onClick={onVoltar}>
            ← Voltar para a carteira
          </button>
        </div>
        <div className={estilos.grade3}>
          <div className={estilos.esqueleto} />
          <div className={estilos.esqueleto} />
          <div className={estilos.esqueleto} />
        </div>
        <div className={estilos.carregando}>
          Montando o painel: histórico do caso, casos anteriores da categoria e agente
          jurídico.
        </div>
      </div>
    );
  }

  if (erro || !dados) {
    return (
      <div className={estilos.pagina}>
        <div className={estilos.navegacao}>
          <button type="button" className="botao botao--secundario botao--pequeno" onClick={onVoltar}>
            ← Voltar para a carteira
          </button>
        </div>
        <Aviso tom="critico" titulo="Não foi possível montar o painel">
          {erro}
        </Aviso>
      </div>
    );
  }

  const { caso, resumo, indicadores, saude, comparacao_historica: comparacao } = dados;
  const progresso = resumo.progresso;
  const referencia = comparacao.referencia;
  const ciclo = comparacao.linhas.find((linha) => linha.codigo === "ciclo");
  const responsavel = resumo.responsaveis[resumo.responsaveis.length - 1];
  const ausencia = (campo: string) => dados.ausencias.find((a) => a.campo === campo)?.motivo;

  const etapasIniciadas = dados.etapas_medidas.filter((etapa) => etapa.iniciada);
  const comparaveis = comparacao.linhas.filter((linha) => linha.realizado_horas !== null);

  return (
    <div className={`${estilos.pagina} ${carregando ? estilos.recarregando : ""}`}>
      {/* ------------------------------------------------------------ topo */}
      <header className={estilos.topo}>
        <div className={estilos.navegacao}>
          <button type="button" className="botao botao--secundario botao--pequeno" onClick={onVoltar}>
            ← Voltar para a carteira
          </button>
          <button type="button" className="botao botao--texto botao--pequeno" onClick={onAbrirChecklist}>
            Checklist de documentos
          </button>
          <button type="button" className="botao botao--texto botao--pequeno" onClick={onAbrirDossie}>
            Dossiê do caso
          </button>
          <button type="button" className="botao botao--secundario botao--pequeno" disabled>
            Painel analítico
          </button>
          {onAbrirJurimetria && (
            <button
              type="button"
              className="botao botao--texto botao--pequeno"
              onClick={onAbrirJurimetria}
            >
              Jurisprudência e jurimetria →
            </button>
          )}
        </div>

        <div className={estilos.identificacao}>
          <div>
            <h1 className={estilos.titulo}>{caso.cliente}</h1>
            <div className={estilos.subtitulo}>
              <span>{caso.categoria}</span>
              <span aria-hidden>·</span>
              <span className={estilos.identificador}>{caso.id.slice(0, 8)}</span>
              {caso.caso_ref_agente && (
                <>
                  <span aria-hidden>·</span>
                  <span className={estilos.identificador}>{caso.caso_ref_agente}</span>
                </>
              )}
              {resumo.etapa_atual && (
                <Selo
                  tom={ESTADO_ETAPA[resumo.etapa_atual.estado].tom}
                  simbolo={ESTADO_ETAPA[resumo.etapa_atual.estado].simbolo}
                >
                  {resumo.etapa_atual.titulo}
                </Selo>
              )}
            </div>
          </div>
          <button type="button" className="botao botao--secundario botao--pequeno" onClick={() => void carregar()}>
            Atualizar
          </button>
        </div>

        {/* Um filtro só, acima de tudo o que ele governa — nunca dentro de um cartão. */}
        <div className={estilos.filtros}>
          <span className={estilos.rotuloFiltro}>Período</span>
          {PERIODOS.map((opcao) => (
            <button
              key={opcao.valor}
              type="button"
              className={`${estilos.filtro} ${periodo === opcao.valor ? estilos.filtroAtivo : ""}`}
              aria-pressed={periodo === opcao.valor}
              onClick={() => setPeriodo(opcao.valor)}
            >
              {opcao.rotulo}
            </button>
          ))}
          <span className={estilos.rotuloFiltro} style={{ marginLeft: 12 }}>
            Tipo
          </span>
          {["documento", "entrevista", "contrato", "agente"].map((tipo) => (
            <button
              key={tipo}
              type="button"
              className={`${estilos.filtro} ${tiposVisiveis.includes(tipo) ? estilos.filtroAtivo : ""}`}
              aria-pressed={tiposVisiveis.includes(tipo)}
              onClick={() =>
                setTiposVisiveis((atual) =>
                  atual.includes(tipo) ? atual.filter((t) => t !== tipo) : [...atual, tipo],
                )
              }
            >
              {ROTULO_DO_TIPO[tipo]}
            </button>
          ))}
          <span className={estilos.aviso}>
            {eventosFiltrados.length} de {dados.eventos.length} movimentações · painel gerado em{" "}
            {dataHora(dados.gerado_em)}
          </span>
        </div>

        {!dados.agente.disponivel && (
          <Aviso tom="atencao" titulo="Parte do painel depende do agente jurídico">
            {dados.agente.motivo ??
              "O agente não respondeu. Fatos, pendências e petição aparecem como sem medida — não como zero."}
          </Aviso>
        )}
      </header>

      {/* ------------------------------------------------- 1. resumo do caso */}
      <Secao
        numero={1}
        titulo="Resumo do caso"
        explicacao="O cadastro do caso e o estado de hoje. Campos que o sistema não guarda aparecem marcados, com o motivo no tooltip."
      >
        <div className={estilos.cartao}>
          <div className={estilos.fichaResumo}>
            <Campo rotulo="Cliente" valor={caso.cliente} />
            <Campo rotulo="Categoria (produto)" valor={caso.categoria} ausente={undefined} />
            <Campo rotulo="Etapa atual" valor={resumo.etapa_atual?.titulo ?? "—"} />
            <Campo
              rotulo="Quem conduziu"
              valor={responsavel?.informado ? responsavel.nome : "—"}
              ausente={responsavel?.informado ? undefined : ausencia("Responsável pelo caso")}
            />
            <Campo rotulo="Prioridade" valor="—" ausente={ausencia("Prioridade")} />
            <Campo rotulo="Prazo / SLA" valor="—" ausente={ausencia("Prazo e SLA contratado")} />
            <Campo rotulo="Aberto em" valor={dataHora(caso.aberto_em)} />
            <Campo rotulo="Última movimentação" valor={dataHora(resumo.ultima_movimentacao)} />
            <Campo rotulo="Tempo em aberto" valor={duracao(resumo.tempo_em_aberto_horas)} />
            <Campo
              rotulo="Documentos obrigatórios"
              valor={`${progresso.obrigatorios_entregues ?? 0} de ${progresso.obrigatorios_total ?? 0}`}
            />
            <Campo rotulo="Ocorrências abertas" valor={String(dados.ocorrencias.abertas)} />
            <Campo
              rotulo="Pendências do playbook"
              valor={dados.pendencias.disponivel ? String(dados.pendencias.abertas) : "—"}
              ausente={dados.pendencias.disponivel ? undefined : dados.pendencias.motivo ?? undefined}
            />
            <Campo rotulo="Portal do cliente" valor={caso.portal_ativo ? "ativo" : "não criado"} />
            <Campo rotulo="Valor da causa" valor="—" ausente={ausencia("Valor da causa")} />
          </div>

          {caso.observacao && <div className={estilos.observacao}>{caso.observacao}</div>}
        </div>

        <div className={estilos.cartao}>
          <Figura
            titulo="Linha do processo"
            descricao="As etapas do caso na ordem em que o escritório trabalha, cada uma com o motivo do estado."
            tabela={{
              colunas: [
                { chave: "etapa", rotulo: "Etapa" },
                { chave: "estado", rotulo: "Estado" },
                { chave: "detalhe", rotulo: "Detalhe" },
              ],
              linhas: resumo.etapas.map((etapa) => ({
                etapa: etapa.titulo,
                estado: ESTADO_ETAPA[etapa.estado].palavra,
                detalhe: etapa.detalhe,
              })),
            }}
          >
            <div className={estilos.trilha}>
              {resumo.etapas.length === 0 ? (
                <SemDado titulo="Sem linha do processo" motivo="O dossiê não devolveu etapas para este caso." />
              ) : (
                resumo.etapas.map((etapa) => {
                  const visual = ESTADO_ETAPA[etapa.estado];
                  const tom: Tom =
                    etapa.estado === "pronto"
                      ? "ok"
                      : etapa.estado === "atencao"
                        ? "atencao"
                        : etapa.estado === "indisponivel"
                          ? "critico"
                          : etapa.estado === "andamento"
                            ? "info"
                            : "neutro";
                  return (
                    <div key={etapa.codigo} className={estilos.etapaTrilha}>
                      <span
                        className={estilos.marcaEtapa}
                        style={{
                          color: COR_DO_TOM[tom],
                          background: FUNDO_DO_TOM[tom],
                          borderColor: BORDA_DO_TOM[tom],
                        }}
                        aria-hidden
                      >
                        {visual.simbolo}
                      </span>
                      <div>
                        <div className={estilos.tituloEtapa}>{etapa.titulo}</div>
                        <div className={estilos.detalheEtapa}>{etapa.detalhe}</div>
                      </div>
                      <span className={estilos.duracaoEtapa}>{visual.palavra}</span>
                    </div>
                  );
                })
              )}
            </div>
          </Figura>
        </div>

        {/* Os fatos são a matéria-prima da petição: o painel mostrava só a contagem,
          * e contagem esconde a distinção que decide o que precisa de prova. */}
        <div className={estilos.cartao}>
          <Figura
            titulo={
              dados.fatos.disponivel
                ? `Fatos apurados no caso (${dados.fatos.vigentes} vigentes de ${dados.fatos.total})`
                : "Fatos apurados no caso"
            }
            descricao="Cada fato traz o valor, o estado e o documento de onde saiu. Não muda com o filtro de período: fato é estado do caso, não movimentação."
            tabela={{
              colunas: [
                { chave: "fato", rotulo: "Fato" },
                { chave: "valor", rotulo: "Valor" },
                { chave: "estado", rotulo: "Estado" },
                { chave: "confianca", rotulo: "Confiança" },
                { chave: "origem", rotulo: "Origem" },
              ],
              linhas: dados.fatos.itens.map((fato) => ({
                fato: rotuloLegivel(fato.tipo),
                valor: valorDoFato(fato.valor),
                estado: ESTADO_DO_FATO[fato.status]?.palavra ?? fato.status,
                confianca: fato.confianca === null ? "—" : `${Math.round(fato.confianca * 100)}%`,
                origem: fato.origens.map(origemLegivel).join(" | ") || "sem origem",
              })),
            }}
          >
            {!dados.fatos.disponivel ? (
              <SemDado titulo="Sem resposta do agente jurídico" motivo={dados.fatos.motivo ?? undefined} />
            ) : dados.fatos.itens.length === 0 ? (
              <SemDado
                titulo="Nenhum fato apurado ainda"
                motivo="Os fatos nascem da leitura dos documentos e da entrevista pelo agente. Rode a análise para produzi-los."
              />
            ) : (
              <div className={estilos.blocoFatos}>
                <div className={estilos.resumoFatos}>
                  {dados.fatos.por_status.map((linha) => {
                    const leitura = ESTADO_DO_FATO[linha.status];
                    return (
                      <span
                        key={linha.status}
                        className={estilos.chipFato}
                        title={leitura?.explicacao ?? linha.status}
                        style={{
                          borderColor: BORDA_DO_TOM[leitura?.tom ?? "neutro"],
                          background: FUNDO_DO_TOM[leitura?.tom ?? "neutro"],
                        }}
                      >
                        <strong>{linha.quantidade}</strong>{" "}
                        {leitura?.palavra ?? linha.status.toLowerCase()}
                      </span>
                    );
                  })}
                  {dados.fatos.apenas_relatados > 0 && (
                    <span
                      className={estilos.chipFato}
                      title="Fatos em estado relatado que não têm nenhum documento como fonte. É a fila de prova a produzir."
                      style={{ borderColor: BORDA_DO_TOM.atencao, background: FUNDO_DO_TOM.atencao }}
                    >
                      <strong>{dados.fatos.apenas_relatados}</strong> sem documento que comprove
                    </span>
                  )}
                  {dados.fatos.sem_origem > 0 && (
                    <span
                      className={estilos.chipFato}
                      title="Fato sem nenhuma fonte registrada — confira antes de usar."
                      style={{ borderColor: BORDA_DO_TOM.critico, background: FUNDO_DO_TOM.critico }}
                    >
                      <strong>{dados.fatos.sem_origem}</strong> sem origem
                    </span>
                  )}
                </div>

                <div className={estilos.rolagem}>
                  <table className={estilos.tabela}>
                    <thead>
                      <tr>
                        <th>Fato</th>
                        <th>Valor</th>
                        <th>Estado</th>
                        <th>Confiança</th>
                        <th>De onde saiu</th>
                      </tr>
                    </thead>
                    <tbody>
                      {dados.fatos.itens.map((fato) => (
                        <LinhaDoFato key={fato.id} fato={fato} />
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )}
          </Figura>
        </div>
      </Secao>

      {/* --------------------------------------------- 2. indicadores gerais */}
      <Secao
        numero={2}
        titulo="Indicadores principais"
        explicacao="Cada número traz o que ele é e de onde saiu. Indicador que depende do agente aparece vazio, e não zerado, quando ele não responde."
      >
        <div className={estilos.gradeIndicadores}>
          <div className={`${estilos.indicador} ${estilos.heroi}`}>
            <span className={estilos.rotuloIndicador}>Saúde do caso</span>
            <span className={estilos.valorHeroi}>
              {saude.pontuacao === null ? "—" : saude.pontuacao}
            </span>
            <span>
              <Selo tom={TOM_SELO[saude.tom]} simbolo={LEITURA_DO_TOM[saude.tom].simbolo}>
                {saude.faixa}
              </Selo>
            </span>
            <span className={estilos.detalheIndicador} title={saude.base}>
              {saude.base} Peso medido: {saude.peso_medido} de 100.
            </span>
            <div className={estilos.componentesSaude}>
              {saude.componentes.map((componente) => (
                <div key={componente.codigo} className={estilos.componente} title={componente.base}>
                  <span>
                    {componente.rotulo} <span style={{ color: "var(--tinta-3)" }}>({componente.peso}%)</span>
                  </span>
                  <span style={{ fontVariantNumeric: "tabular-nums", fontWeight: 600 }}>
                    {componente.valor === null ? "sem dado" : Math.round(componente.valor)}
                  </span>
                  <span className={estilos.barraComponente}>
                    <span
                      className={estilos.preenchimentoComponente}
                      style={{
                        width: `${componente.valor ?? 0}%`,
                        background:
                          componente.valor === null
                            ? "var(--borda-forte)"
                            : componente.valor >= 75
                              ? "var(--ok)"
                              : componente.valor >= 50
                                ? "var(--atencao-marca)"
                                : "var(--critico)",
                      }}
                    />
                  </span>
                </div>
              ))}
            </div>
          </div>

          {indicadores.map((indicador) => (
            <CartaoIndicador
              key={indicador.codigo}
              rotulo={indicador.rotulo}
              valor={indicador.valor}
              unidade={indicador.unidade}
              detalhe={indicador.detalhe}
              tom={indicador.tom}
              comparacao={indicador.comparacao}
              faisca={
                indicador.codigo === "movimentacoes"
                  ? serie.map((ponto) => ponto.movimentacoes)
                  : undefined
              }
            />
          ))}
        </div>
      </Secao>

      {/* ------------------------------------------------ 3. evolução no tempo */}
      <Secao
        numero={3}
        titulo="Evolução temporal"
        explicacao="Como o caso andou dentro do período escolhido. Dia sem movimentação aparece na série — sem ele, três documentos em três semanas pareceriam um ritmo constante."
      >
        <div className={estilos.grade2}>
          <div className={estilos.cartao}>
            <Figura
              titulo="Documentos recebidos, acumulado"
              descricao="Curva do que já chegou. Um degrau é um lote; um platô é espera."
              tabela={{
                colunas: [
                  { chave: "dia", rotulo: "Dia" },
                  { chave: "documentos", rotulo: "No dia" },
                  { chave: "acumulado", rotulo: "Acumulado" },
                ],
                linhas: serie.map((ponto) => ({
                  dia: dataCurta(ponto.dia),
                  documentos: ponto.documentos,
                  acumulado: ponto.documentosAcumulados,
                })),
              }}
            >
              {serie.length < 2 ? (
                <SemDado
                  titulo="Período curto demais para uma curva"
                  motivo="Escolha um período maior ou espere a próxima movimentação: com um único dia não há evolução a desenhar."
                />
              ) : (
                <GraficoDeLinha
                  rotulos={serie.map((ponto) => dataCurta(ponto.dia))}
                  series={[
                    {
                      nome: "Documentos acumulados",
                      cor: CORES_DE_SERIE[0],
                      valores: serie.map((ponto) => ponto.documentosAcumulados),
                      unidade: "doc.",
                    },
                  ]}
                />
              )}
            </Figura>
          </div>

          <div className={estilos.cartao}>
            <Figura
              titulo="Movimentações por dia"
              descricao="Todo evento com instante gravado: documento, entrevista, contrato e trabalho do agente."
              tabela={{
                colunas: [
                  { chave: "dia", rotulo: "Dia" },
                  { chave: "movimentacoes", rotulo: "Movimentações" },
                ],
                linhas: serie.map((ponto) => ({
                  dia: dataCurta(ponto.dia),
                  movimentacoes: ponto.movimentacoes,
                })),
              }}
            >
              {serie.length === 0 ? (
                <SemDado
                  titulo="Nenhuma movimentação no período"
                  motivo={`O caso teve ${dados.eventos.length} movimentação(ões) no total. Experimente "Todo o caso".`}
                />
              ) : (
                <GraficoDeColunas
                  rotulos={serie.map((ponto) => dataCurta(ponto.dia))}
                  valores={serie.map((ponto) => ponto.movimentacoes)}
                  unidade="movimentações"
                />
              )}
            </Figura>
          </div>

          <div className={estilos.cartao}>
            <Figura
              titulo="Mapa de atividade"
              descricao="Quando o caso se mexe, por dia da semana e faixa de três horas. Documento que chega de madrugada é o cliente; o resto é o escritório."
              tabela={{
                colunas: [
                  { chave: "dia", rotulo: "Dia" },
                  { chave: "faixa", rotulo: "Faixa" },
                  { chave: "quantidade", rotulo: "Movimentações" },
                ],
                linhas: mapa
                  .filter((celula) => celula.quantidade > 0)
                  .map((celula) => ({
                    dia: ["dom", "seg", "ter", "qua", "qui", "sex", "sáb"][celula.diaDaSemana],
                    faixa: `${celula.hora}h–${celula.hora + 3}h`,
                    quantidade: celula.quantidade,
                  })),
              }}
            >
              {eventosFiltrados.length === 0 ? (
                <SemDado titulo="Sem atividade no período" />
              ) : (
                <MapaDeCalor celulas={mapa} />
              )}
            </Figura>
          </div>

          <div className={estilos.cartao}>
            <Figura
              titulo="Distribuição das movimentações"
              descricao="De onde veio o trabalho no período."
              tabela={{
                colunas: [
                  { chave: "tipo", rotulo: "Origem" },
                  { chave: "quantidade", rotulo: "Movimentações" },
                ],
                linhas: distribuicaoPorTipo.map((item) => ({
                  tipo: ROTULO_DO_TIPO[item.tipo] ?? item.tipo,
                  quantidade: item.quantidade,
                })),
              }}
            >
              {distribuicaoPorTipo.length === 0 ? (
                <SemDado titulo="Sem movimentações no período" />
              ) : (
                <Rosca
                  total={eventosFiltrados.length}
                  rotuloDoCentro="movimentações"
                  fatias={distribuicaoPorTipo.slice(0, 4).map((item, indice) => ({
                    rotulo: ROTULO_DO_TIPO[item.tipo] ?? item.tipo,
                    valor: item.quantidade,
                    cor: CORES_DE_SERIE[indice % CORES_DE_SERIE.length],
                  }))}
                />
              )}
            </Figura>
          </div>
        </div>
      </Secao>

      {/* ----------------------------------------------- 4. prazos e atrasos */}
      <Secao
        numero={4}
        titulo="Prazos, referência e atrasos"
        explicacao="Não há SLA contratado no sistema. A referência abaixo é a mediana dos casos anteriores da mesma categoria — medida, não arbitrada — e vem com o tamanho da amostra."
      >
        <div className={estilos.gradeLarga}>
          <div className={estilos.cartao}>
            <Figura
              titulo="Consumo do tempo de referência"
              descricao={
                referencia.suficiente
                  ? `Mediana de ${referencia.amostra} caso(s) anteriores em ${caso.categoria}.`
                  : "Sem base histórica suficiente para comparar."
              }
            >
              {!ciclo || ciclo.previsto_horas === null || !ciclo.previsto_horas ? (
                <SemDado
                  titulo="Sem referência de tempo para esta categoria"
                  motivo={
                    referencia.motivo ??
                    "Os casos anteriores desta categoria não concluíram o ciclo, então não há mediana a comparar."
                  }
                />
              ) : (
                <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
                  <div>
                    <div className={estilos.valorIndicador}>
                      {Math.round(
                        ((ciclo.realizado_horas ?? 0) / (ciclo.previsto_horas || 1)) * 100,
                      )}
                      <span className={estilos.unidadeIndicador}>% da referência</span>
                    </div>
                    <div className={estilos.detalheIndicador}>
                      {duracao(ciclo.realizado_horas)} decorridos contra {duracao(ciclo.previsto_horas)}{" "}
                      de mediana.
                    </div>
                  </div>
                  <Medidor
                    valor={Math.min(
                      100,
                      ((ciclo.realizado_horas ?? 0) / (ciclo.previsto_horas || 1)) * 100,
                    )}
                    cor={
                      (ciclo.desvio_horas ?? 0) > 0 ? "var(--atencao-marca)" : "var(--ok)"
                    }
                    esquerda="0"
                    direita={`mediana ${duracao(ciclo.previsto_horas)}`}
                    marca={{ posicao: 1, titulo: "mediana da categoria" }}
                  />
                  <div className={estilos.detalheIndicador}>
                    {ciclo.desvio_horas === null
                      ? "Sem desvio calculável."
                      : ciclo.desvio_horas > 0
                        ? `${duracao(ciclo.desvio_horas)} além da mediana${
                            ciclo.desvio_percentual !== null ? ` (+${ciclo.desvio_percentual}%)` : ""
                          }.`
                        : `${duracao(Math.abs(ciclo.desvio_horas))} abaixo da mediana.`}
                  </div>
                </div>
              )}
            </Figura>
          </div>

          <div className={estilos.cartao}>
            <Figura titulo="Sem movimentação" descricao="Distância entre hoje e o último evento gravado.">
              <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
                <div>
                  <div className={estilos.valorIndicador}>
                    {numero(resumo.dias_sem_movimentacao)}
                    <span className={estilos.unidadeIndicador}>dias</span>
                  </div>
                  <div className={estilos.detalheIndicador}>
                    Última movimentação em {dataHora(resumo.ultima_movimentacao)}.
                  </div>
                </div>
                <Medidor
                  valor={Math.min(
                    resumo.limiar_parado_dias * 2,
                    resumo.dias_sem_movimentacao ?? 0,
                  )}
                  maximo={resumo.limiar_parado_dias * 2}
                  cor={
                    (resumo.dias_sem_movimentacao ?? 0) >= resumo.limiar_parado_dias
                      ? "var(--atencao-marca)"
                      : "var(--ok)"
                  }
                  esquerda="hoje"
                  direita={`limiar ${resumo.limiar_parado_dias} dias`}
                  marca={{ posicao: 0.5, titulo: `limiar de ${resumo.limiar_parado_dias} dias` }}
                />
                <div className={estilos.detalheIndicador}>
                  O limiar de {resumo.limiar_parado_dias} dias é do painel, não do contrato: serve
                  para marcar o caso como parado, e está escrito aqui para não passar por prazo.
                </div>
              </div>
            </Figura>
          </div>
        </div>
      </Secao>

      {/* ---------------------------------------------- 5. tempo por etapa */}
      <Secao
        numero={5}
        titulo="Tempo por etapa"
        explicacao="Duração medida entre dois instantes gravados. Etapa ainda em curso conta até agora e vem marcada; etapa que nunca começou não aparece como zero."
      >
        <div className={estilos.grade2}>
          <div className={estilos.cartao}>
            <Figura
              titulo="Duração de cada etapa"
              descricao="Em horas, do primeiro ao último instante registrado da etapa."
              tabela={{
                colunas: [
                  { chave: "etapa", rotulo: "Etapa" },
                  { chave: "duracao", rotulo: "Duração" },
                  { chave: "inicio", rotulo: "Início" },
                  { chave: "fim", rotulo: "Fim" },
                ],
                linhas: dados.etapas_medidas.map((etapa) => ({
                  etapa: etapa.titulo,
                  duracao: etapa.iniciada ? duracao(etapa.horas) : "não iniciada",
                  inicio: dataHora(etapa.inicio),
                  fim: etapa.em_curso ? "em curso" : dataHora(etapa.fim),
                })),
              }}
            >
              {etapasIniciadas.length === 0 ? (
                <SemDado
                  titulo="Nenhuma etapa iniciada"
                  motivo="O caso foi aberto e ainda não recebeu documento, entrevista ou contrato."
                />
              ) : (
                <GraficoDeBarras
                  unidade=" h"
                  itens={etapasIniciadas.map((etapa) => ({
                    rotulo: etapa.titulo + (etapa.em_curso ? " (em curso)" : ""),
                    valores: [
                      { nome: "Realizado", valor: etapa.horas, cor: CORES_DE_SERIE[0] },
                    ],
                    nota: etapa.descricao,
                  }))}
                />
              )}
            </Figura>
          </div>

          <div className={estilos.cartao}>
            <Figura
              titulo="Distribuição do tempo"
              descricao="Quanto do tempo medido cada etapa consumiu. O ciclo total fica de fora: ele contém as outras."
              tabela={{
                colunas: [
                  { chave: "etapa", rotulo: "Etapa" },
                  { chave: "horas", rotulo: "Horas" },
                  { chave: "percentual", rotulo: "%" },
                ],
                linhas: dados.distribuicao_do_tempo.map((item) => ({
                  etapa: item.titulo,
                  horas: numero(item.horas),
                  percentual: item.percentual === null ? "—" : `${item.percentual}%`,
                })),
              }}
            >
              {dados.distribuicao_do_tempo.length === 0 ? (
                <SemDado
                  titulo="Sem etapa concluída para fatiar"
                  motivo="A distribuição só existe quando ao menos uma etapa tem início e fim medidos."
                />
              ) : (
                <Rosca
                  total={Math.round(
                    dados.distribuicao_do_tempo.reduce((soma, item) => soma + item.horas, 0),
                  )}
                  rotuloDoCentro="horas medidas"
                  fatias={dados.distribuicao_do_tempo.slice(0, 4).map((item, indice) => ({
                    rotulo: item.titulo,
                    valor: Math.round(item.horas),
                    cor: CORES_DE_SERIE[indice % CORES_DE_SERIE.length],
                  }))}
                />
              )}
            </Figura>
          </div>
        </div>
      </Secao>

      {/* ------------------------------------------- 6. comparação histórica */}
      <Secao
        numero={6}
        titulo="Comparação histórica"
        explicacao={`Este caso contra os anteriores da mesma categoria. ${
          referencia.suficiente
            ? `Amostra: ${referencia.amostra} caso(s).`
            : referencia.motivo ?? ""
        }`}
      >
        <div className={estilos.cartao}>
          <Figura
            titulo="Previsto x realizado, por etapa"
            descricao="“Previsto” é a mediana da categoria; etapa cuja amostra própria é pequena fica sem barra de referência, com o motivo no tooltip."
            legenda={[
              { rotulo: "Realizado neste caso", cor: CORES_DE_SERIE[0] },
              { rotulo: "Mediana da categoria", cor: CORES_DE_SERIE[1] },
            ]}
            tabela={{
              colunas: [
                { chave: "etapa", rotulo: "Etapa" },
                { chave: "realizado", rotulo: "Realizado" },
                { chave: "previsto", rotulo: "Mediana" },
                { chave: "amostra", rotulo: "Amostra" },
                { chave: "desvio", rotulo: "Desvio" },
              ],
              linhas: comparacao.linhas.map((linha) => ({
                etapa: linha.titulo,
                realizado: duracao(linha.realizado_horas),
                previsto: linha.previsto_horas === null ? "—" : duracao(linha.previsto_horas),
                amostra: linha.amostra,
                desvio:
                  linha.desvio_horas === null
                    ? "—"
                    : `${linha.desvio_horas > 0 ? "+" : ""}${duracao(Math.abs(linha.desvio_horas))}${
                        linha.desvio_percentual !== null ? ` (${linha.desvio_percentual}%)` : ""
                      }`,
              })),
            }}
          >
            {comparaveis.length === 0 ? (
              <SemDado
                titulo="Nada a comparar ainda"
                motivo={referencia.motivo ?? "Este caso ainda não concluiu nenhuma etapa medível."}
              />
            ) : (
              <GraficoDeBarras
                unidade=" h"
                alturaDaLinha={42}
                itens={comparaveis.map((linha) => ({
                  rotulo: linha.titulo,
                  valores: [
                    { nome: "Realizado", valor: linha.realizado_horas, cor: CORES_DE_SERIE[0] },
                    { nome: "Mediana da categoria", valor: linha.previsto_horas, cor: CORES_DE_SERIE[1] },
                  ],
                  nota:
                    linha.motivo ??
                    `Amostra de ${linha.amostra} caso(s) anteriores${
                      linha.desvio_percentual !== null
                        ? `; desvio de ${linha.desvio_percentual}%`
                        : ""
                    }.`,
                }))}
              />
            )}
          </Figura>
        </div>
      </Secao>

      {/* ----------------------------------------------------- 7. ocorrências */}
      <Secao
        numero={7}
        titulo="Ocorrências e pendências"
        explicacao="Tudo que já deu errado no caso, com estado de aberto ou resolvido — documento ilegível que depois foi substituído continua no histórico, porque custou tempo."
      >
        <div className={estilos.grade2}>
          <div className={estilos.cartao}>
            <Figura
              titulo={`Ocorrências (${dados.ocorrencias.abertas} aberta(s), ${dados.ocorrencias.resolvidas} resolvida(s))`}
              descricao="Arquivo trocado, foto ilegível, falha de leitura, contradição entre fatos e erro de sincronização."
            >
              {dados.ocorrencias.itens.length === 0 ? (
                <SemDado
                  titulo="Nenhuma ocorrência registrada"
                  motivo="Nenhum documento voltou para conferência e nenhuma leitura falhou neste caso."
                />
              ) : (
                <div className={estilos.rolagem}>
                  <table className={estilos.tabela}>
                    <thead>
                      <tr>
                        <th>Quando</th>
                        <th>O quê</th>
                        <th>Origem</th>
                        <th>Estado</th>
                      </tr>
                    </thead>
                    <tbody>
                      {dados.ocorrencias.itens.map((ocorrencia, indice) => (
                        <tr key={indice}>
                          <td>{ocorrencia.quando ? dataHora(ocorrencia.quando) : "—"}</td>
                          <td>
                            <div className={estilos.celulaPrincipal}>{ocorrencia.titulo}</div>
                            <div className={estilos.detalheIndicador}>{ocorrencia.detalhe}</div>
                          </td>
                          <td>{ROTULO_DO_TIPO[ocorrencia.tipo] ?? ocorrencia.tipo}</td>
                          <td>
                            <Selo
                              tom={ocorrencia.estado === "aberta" ? TOM_SELO[ocorrencia.gravidade] : "ok"}
                              simbolo={ocorrencia.estado === "aberta" ? "!" : "✓"}
                            >
                              {ocorrencia.estado}
                            </Selo>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </Figura>
          </div>

          <div className={estilos.cartao}>
            <Figura
              titulo={
                dados.pendencias.disponivel
                  ? `Pendências do playbook (${dados.pendencias.abertas} em aberto)`
                  : "Pendências do playbook"
              }
              descricao="A lista é do agente jurídico, derivada do playbook da classificação — não é uma releitura do checklist."
            >
              {!dados.pendencias.disponivel ? (
                <SemDado titulo="Sem resposta do agente jurídico" motivo={dados.pendencias.motivo ?? undefined} />
              ) : dados.pendencias.itens.length === 0 ? (
                <SemDado
                  titulo="Nenhuma pendência listada"
                  motivo="O agente ainda não classificou o caso, ou o playbook não exige nada além do que já existe."
                />
              ) : (
                <div className={estilos.rolagem}>
                  <table className={estilos.tabela}>
                    <thead>
                      <tr>
                        <th>Item</th>
                        <th>Tipo</th>
                        <th>Severidade</th>
                        <th>Estado</th>
                      </tr>
                    </thead>
                    <tbody>
                      {dados.pendencias.itens.map((pendencia) => (
                        <tr key={pendencia.codigo}>
                          <td>
                            <div className={estilos.celulaPrincipal}>{rotuloLegivel(pendencia.rotulo)}</div>
                            {pendencia.pergunta && (
                              <div className={estilos.detalheIndicador}>{pendencia.pergunta}</div>
                            )}
                          </td>
                          <td>{ROTULO_DA_PENDENCIA[pendencia.tipo] ?? pendencia.tipo}</td>
                          <td>
                            {pendencia.severidade === "BLOCKING" ? (
                              <Selo tom="critico" simbolo="✕">
                                bloqueante
                              </Selo>
                            ) : (
                              <Selo tom="info" simbolo="→">
                                recomendada
                              </Selo>
                            )}
                          </td>
                          <td>
                            {pendencia.estado === "OPEN" ? (
                              <Selo tom="atencao" simbolo="!">
                                em aberto
                              </Selo>
                            ) : (
                              <Selo tom="ok" simbolo="✓">
                                atendida
                              </Selo>
                            )}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </Figura>
          </div>
        </div>
      </Secao>

      {/* ------------------------------------------------ 8. riscos e insights */}
      <Secao
        numero={8}
        titulo="Riscos e insights"
        explicacao="Cada frase é gerada a partir de um número que está nesta tela, e carrega embaixo a conta que a produziu. Sem dado, sem frase."
      >
        <div className={estilos.gradeLarga}>
          <div className={estilos.cartao}>
            {dados.insights.length === 0 ? (
              <SemDado
                titulo="Nenhum insight a apontar"
                motivo="O caso ainda não acumulou histórico suficiente para produzir uma leitura com base numérica."
              />
            ) : (
              <div className={estilos.listaInsights}>
                {dados.insights.map((insight, indice) => (
                  <div
                    key={indice}
                    className={estilos.insight}
                    style={{ borderColor: BORDA_DO_TOM[insight.tom], background: FUNDO_DO_TOM[insight.tom] }}
                  >
                    <span
                      className={estilos.insightSimbolo}
                      style={{
                        color: COR_DO_TOM[insight.tom],
                        borderColor: BORDA_DO_TOM[insight.tom],
                        background: "var(--papel)",
                      }}
                      aria-hidden
                    >
                      {LEITURA_DO_TOM[insight.tom].simbolo}
                    </span>
                    <div>
                      <div className={estilos.insightTexto}>{insight.texto}</div>
                      <div className={estilos.insightBase}>{insight.base}</div>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>

          <div className={estilos.cartao}>
            <Figura
              titulo="Radar de desempenho"
              descricao="Cinco eixos de 0 a 100. Eixo sem dado fica sem vértice e diz por quê — vazio não é nota baixa."
              tabela={{
                colunas: [
                  { chave: "eixo", rotulo: "Eixo" },
                  { chave: "nota", rotulo: "Nota" },
                  { chave: "base", rotulo: "Como foi medido" },
                ],
                linhas: dados.radar.map((eixo) => ({
                  eixo: eixo.eixo,
                  nota: eixo.valor === null ? "sem dado" : Math.round(eixo.valor),
                  base: eixo.base,
                })),
              }}
            >
              <Radar eixos={dados.radar} />
            </Figura>
          </div>
        </div>
      </Secao>

      {/* --------------------------------------------------- 9. histórico */}
      <Secao
        numero={9}
        titulo="Histórico completo"
        explicacao="Todo evento com instante gravado, dos dois lados: Acervo (caso, portal, documentos, entrevista, contrato) e agente jurídico (fatos, classificação, pesquisa, estratégia, petição)."
      >
        <div className={estilos.cartao}>
          <Figura
            titulo={`${eventosFiltrados.length} movimentação(ões) no período`}
            descricao="Ordem cronológica. Evento sem instante gravado não é reconstruído aqui — ele apareceria fora de lugar na linha."
            tabela={{
              colunas: [
                { chave: "quando", rotulo: "Quando" },
                { chave: "evento", rotulo: "Evento" },
                { chave: "detalhe", rotulo: "Detalhe" },
              ],
              linhas: eventosFiltrados.map((evento) => ({
                quando: dataHora(evento.quando),
                evento: evento.titulo,
                detalhe: evento.detalhe,
              })),
            }}
          >
            {eventosFiltrados.length === 0 ? (
              <SemDado
                titulo="Nenhuma movimentação no período selecionado"
                motivo={`O caso tem ${dados.eventos.length} movimentação(ões) no total.`}
              />
            ) : (
              <>
                <div className={estilos.linhaDoTempo}>
                  <span className={estilos.eventoFio} aria-hidden />
                  {[...eventosFiltrados]
                    .reverse()
                    .slice(0, eventosMostrados)
                    .map((evento, indice) => (
                      <LinhaDoEvento key={`${evento.quando}-${indice}`} evento={evento} />
                    ))}
                </div>
                {eventosFiltrados.length > eventosMostrados && (
                  <button
                    type="button"
                    className={`botao botao--secundario botao--pequeno ${estilos.maisEventos}`}
                    onClick={() => setEventosMostrados((atual) => atual + 50)}
                  >
                    Mostrar mais ({eventosFiltrados.length - eventosMostrados} restantes)
                  </button>
                )}
              </>
            )}
          </Figura>
        </div>

        <div className={estilos.cartao}>
          <Figura
            titulo="Quem conduziu"
            descricao="O entrevistador registrado em cada entrevista. Não é dono do caso: o sistema não atribui responsável."
          >
            {resumo.responsaveis.length === 0 ? (
              <SemDado
                titulo="Nenhuma entrevista anexada"
                motivo="Sem entrevista, não há registro de quem conduziu o atendimento."
              />
            ) : (
              <div className={estilos.rolagem}>
                <table className={estilos.tabela}>
                  <thead>
                    <tr>
                      <th>Quem</th>
                      <th>Desde</th>
                      <th>Arquivo</th>
                      <th>Fatos gerados</th>
                    </tr>
                  </thead>
                  <tbody>
                    {resumo.responsaveis.map((pessoa, indice) => (
                      <tr key={indice}>
                        <td className={estilos.celulaPrincipal}>{pessoa.nome}</td>
                        <td>{dataHora(pessoa.desde)}</td>
                        <td>{pessoa.arquivo}</td>
                        <td>{pessoa.lida ? pessoa.fatos_gerados : "não lida"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Figura>
        </div>

        <div className={estilos.cartao}>
          <Figura
            titulo="O que este painel não sabe"
            descricao="Campos que um painel de BI costuma trazer e que este sistema não registra. Estão aqui para que a ausência seja lida como ausência."
          >
            <div className={estilos.ausencias}>
              {dados.ausencias.map((item) => (
                <div key={item.campo} className={estilos.ausencia}>
                  <div className={estilos.ausenciaCampo}>{item.campo}</div>
                  <div className={estilos.ausenciaMotivo}>{item.motivo}</div>
                </div>
              ))}
            </div>
          </Figura>
        </div>
      </Secao>
    </div>
  );
}

function LinhaDoFato({ fato }: { fato: FatoDoCaso }) {
  const leitura = ESTADO_DO_FATO[fato.status];
  const tom: Tom = leitura?.tom ?? "neutro";
  return (
    <tr className={fato.vigente ? undefined : estilos.linhaDescartada}>
      <td className={estilos.celulaPrincipal}>{rotuloLegivel(fato.tipo)}</td>
      <td>{valorDoFato(fato.valor)}</td>
      <td>
        <span title={leitura?.explicacao}>
          <Selo tom={TOM_SELO[tom]} simbolo={leitura?.simbolo ?? "•"}>
            {leitura?.palavra ?? fato.status}
          </Selo>
        </span>
      </td>
      <td style={{ fontVariantNumeric: "tabular-nums" }}>
        {fato.confianca === null ? "—" : `${Math.round(fato.confianca * 100)}%`}
      </td>
      <td>
        {fato.origens.length === 0 ? (
          <span style={{ color: "var(--critico)" }}>sem origem registrada</span>
        ) : (
          <div className={estilos.origens}>
            {fato.origens.map((origem, indice) => (
              <span key={indice} className={estilos.origem}>
                {origemLegivel(origem)}
              </span>
            ))}
          </div>
        )}
      </td>
    </tr>
  );
}

function LinhaDoEvento({ evento }: { evento: EventoDoCaso }) {
  return (
    <div className={estilos.eventoLinha}>
      <span className={estilos.eventoData}>{dataHora(evento.quando)}</span>
      <span
        className={estilos.eventoMarca}
        style={{ color: COR_DO_TOM[evento.tom], borderColor: BORDA_DO_TOM[evento.tom] }}
        title={`${ROTULO_DO_TIPO[evento.tipo] ?? evento.tipo} · ${LEITURA_DO_TOM[evento.tom].palavra}`}
      >
        {LEITURA_DO_TOM[evento.tom].simbolo}
      </span>
      <div>
        <div className={estilos.eventoTitulo}>{evento.titulo}</div>
        <div className={estilos.eventoDetalhe}>{evento.detalhe}</div>
      </div>
    </div>
  );
}
