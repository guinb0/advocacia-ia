"use client";

/**
 * Panorama do escritório — o painel analítico de **todos** os casos, em módulo próprio.
 *
 * As telas analíticas do sistema respondem perguntas diferentes, e é por isso que são
 * telas diferentes:
 *
 *   carteira  → "o que eu faço agora?"
 *   painel    → "como ESTE caso se comportou no tempo?"
 *   panorama  → "como o escritório está indo?"
 *
 * O panorama mora fora da carteira porque quem o lê não vai trabalhar um caso: vai
 * decidir onde o escritório está travando. Ficar no topo da fila obrigaria o gestor a
 * atravessar a mesa do dia, e obrigaria quem só quer trabalhar a atravessar a análise.
 *
 * Duas regras herdadas do painel do caso valem aqui inteiras:
 *
 * - **número sem amostra não vira gráfico.** Onde o backend manda `null` com motivo, a
 *   tela escreve o motivo — nunca desenha zero, que se lê como "não aconteceu";
 * - **o que o sistema não guarda é dito.** A última seção lista as ausências declaradas,
 *   porque seção vazia sem motivo é lida como ausência de fato.
 *
 * Clicar num estágio do funil abre a lista de casos dele, aqui mesmo: a contagem e a
 * lista saem do mesmo payload, então elas não podem discordar.
 */

import { useEffect, useMemo, useState } from "react";

/* O que era seletor descendente ou variante de estado no CSS Module vira
 * constante aqui: o Tailwind não tem descendente, e repetir a mesma cadeia de
 * classes em cada célula é justamente o que faz duas linhas divergirem. */
const CELULA_TH =
  "px-[10px] py-[7px] border-b border-borda-forte text-tinta-3 text-xs font-semibold " +
  "tracking-[0.03em] text-left uppercase whitespace-nowrap";
const CELULA_TD =
  "px-[10px] py-2 border-b border-borda text-tinta-2 align-middle group-last:border-b-0";
/* A faixa é botão porque abre a lista de casos do estágio. O contorno só aparece
 * no hover e quando aberta — seis molduras permanentes competiriam com a barra,
 * que é o que se lê primeiro. Abaixo de 720px a barra ocupa a linha inteira. */
const FAIXA_FUNIL =
  "grid grid-cols-[minmax(150px,210px)_1fr_minmax(78px,auto)] max-[720px]:grid-cols-[1fr_auto] " +
  "max-[720px]:gap-y-[6px] items-center gap-3 w-full px-[10px] py-2 border border-transparent " +
  "rounded-campo bg-transparent cursor-pointer text-left transition-colors hover:bg-papel-3";
const FAIXA_FUNIL_ATIVA = "border-acao-borda bg-acao-clara hover:bg-acao-clara";
const LINHA_CASO =
  "grid grid-cols-[minmax(140px,1fr)_minmax(160px,2fr)_auto] max-[720px]:grid-cols-[1fr_auto] " +
  "max-[720px]:gap-y-[6px] items-center gap-3 w-full px-[10px] py-[9px] border border-transparent " +
  "rounded-campo bg-transparent cursor-pointer text-left transition-colors hover:bg-papel-3";


import { Aviso, Botao, Selo } from "@/components/ui/Basicos";
import {
  CORES_DE_SERIE,
  Figura,
  GraficoDeBarras,
  GraficoDeLinha,
  SemDado,
} from "@/components/ui/graficos";
import type { TomSelo } from "@/lib/formato";
import { dataHora, duracao, LEITURA_DO_TOM, numero, type Tom } from "@/lib/painel";
import {
  buscarPanorama,
  type CasoDoPanorama,
  type FaixaDoFunil,
  type Panorama as Dados,
} from "@/lib/panorama";

const TOM_SELO: Record<Tom, TomSelo> = {
  ok: "ok",
  atencao: "atencao",
  critico: "critico",
  info: "info",
  neutro: "neutro",
};

const COR_DO_TOM: Record<Tom, string> = {
  ok: "var(--ok)",
  atencao: "var(--atencao-marca)",
  critico: "var(--critico)",
  info: "var(--acao)",
  neutro: "var(--tinta-3)",
};

interface Props {
  onVoltar: () => void;
  onAbrirCaso: (casoId: string) => void;
}

export default function Panorama({ onVoltar, onAbrirCaso }: Props) {
  const [dados, setDados] = useState<Dados | null>(null);
  const [carregando, setCarregando] = useState(true);
  const [erro, setErro] = useState<string | null>(null);
  const [estagio, setEstagio] = useState<string | null>(null);

  useEffect(() => {
    let vivo = true;
    setCarregando(true);
    buscarPanorama()
      .then((resposta) => {
        if (vivo) {
          setDados(resposta);
          setErro(null);
        }
      })
      .catch((falha: Error) => vivo && setErro(falha.message))
      .finally(() => vivo && setCarregando(false));
    return () => {
      vivo = false;
    };
  }, []);

  return (
    <div className="max-w-[1180px] mx-auto px-7 pt-6 pb-16 max-[720px]:px-[14px] max-[720px]:pt-4 max-[720px]:pb-12 flex flex-col gap-6">
      <div className="flex">
        <Botao variante="secundario" pequeno onClick={onVoltar}>
          ← Voltar para a carteira
        </Botao>
      </div>

      <header className="flex flex-col gap-[6px]">
        <h1 className="m-0 text-tinta font-titulo text-xl font-bold tracking-[-0.01em]">Panorama do escritório</h1>
        <p className="m-0 max-w-[82ch] text-tinta-2 text-base leading-[1.55]">
          Todos os casos somados: em que estágio estão, onde o tempo é gasto e o que está
          parado. Tudo medido de instante gravado no banco, com as mesmas contas do painel de
          cada caso — nada aqui é estimado.
        </p>
        {dados && (
          <p className="m-0 text-tinta-3 text-sm">
            {dados.cobertura.casos_medidos}{" "}
            {dados.cobertura.casos_medidos === 1 ? "caso medido" : "casos medidos"} · apurado
            em {dataHora(dados.gerado_em)}
          </p>
        )}
      </header>

      {erro && (
        <Aviso tom="critico" titulo="O panorama não pôde ser calculado">
          {erro}
        </Aviso>
      )}

      {carregando && !dados && (
        <p className="m-0 text-tinta-3 text-sm" aria-live="polite">
          Somando os casos…
        </p>
      )}

      {dados && (
        <>
          {dados.cobertura.motivo && (
            <Aviso tom="atencao" titulo="Nem todos os casos entraram na conta">
              {dados.cobertura.motivo}
            </Aviso>
          )}

          <div className="grid grid-cols-[repeat(auto-fit,minmax(168px,1fr))] gap-[10px]">
            {dados.indicadores.map((indicador) => (
              <div key={indicador.codigo} className="flex flex-col gap-1 px-[14px] py-3 border border-borda rounded-campo bg-papel-2">
                <span className="text-tinta-3 text-xs font-semibold tracking-[0.04em] uppercase">{indicador.rotulo}</span>
                <span className="text-tinta font-titulo text-xl font-bold leading-[1.1]">
                  {indicador.valor === null ? "—" : numero(indicador.valor)}
                  {indicador.unidade && indicador.valor !== null && (
                    <span className="ml-[5px] text-tinta-3 font-ui text-sm font-semibold">{indicador.unidade}</span>
                  )}
                </span>
                {/* A cor nunca informa sozinha: quando o tom significa alguma coisa, o
                  * selo escreve a palavra ao lado (GUIA-VISUAL). */}
                {indicador.tom !== "neutro" && (
                  <span>
                    <Selo
                      tom={TOM_SELO[indicador.tom]}
                      simbolo={LEITURA_DO_TOM[indicador.tom].simbolo}
                    >
                      {LEITURA_DO_TOM[indicador.tom].palavra}
                    </Selo>
                  </span>
                )}
                <span className="text-tinta-3 text-xs leading-[1.45]">{indicador.detalhe}</span>
              </div>
            ))}
          </div>

          <Funil
            faixas={dados.funil}
            /* `?? []` porque um backend de uma versão anterior serve o painel sem a
             * lista: melhor o estágio abrir vazio do que a tela inteira quebrar em
             * cima de um `undefined.filter`. */
            casos={dados.casos ?? []}
            total={dados.cobertura.casos_medidos}
            aberto={estagio}
            onAbrirEstagio={setEstagio}
            onAbrirCaso={onAbrirCaso}
          />
          <OndeOTempoVai tempo={dados.tempo} />
          <Movimento movimento={dados.movimento} />
          <Categorias categorias={dados.categorias} />
          <Parados parados={dados.parados} onAbrirCaso={onAbrirCaso} />
          <div className="grid grid-cols-[repeat(auto-fit,minmax(min(100%,320px),1fr))] gap-[22px]">
            <Equipe equipe={dados.equipe} />
            <Qualidade qualidade={dados.qualidade} />
          </div>
          <Ausencias ausencias={dados.ausencias} />
        </>
      )}
    </div>
  );
}

/* ------------------------------------------------------------------- funil */

function Funil({
  faixas,
  casos,
  total,
  aberto,
  onAbrirEstagio,
  onAbrirCaso,
}: {
  faixas: FaixaDoFunil[];
  casos: CasoDoPanorama[];
  total: number;
  aberto: string | null;
  onAbrirEstagio: (codigo: string | null) => void;
  onAbrirCaso: (casoId: string) => void;
}) {
  const comCaso = faixas.filter((faixa) => faixa.casos > 0);
  const escolhida = comCaso.find((faixa) => faixa.codigo === aberto) ?? null;
  const doEstagio = useMemo(
    () => (escolhida ? casos.filter((caso) => caso.estagio === escolhida.codigo) : []),
    [casos, escolhida],
  );

  return (
    <Bloco
      titulo="Onde os casos estão"
      explicacao={
        "Cada caso conta uma vez só, no estágio em que está travado. O estágio sai do que o " +
        "Acervo grava — a linha do processo do dossiê tem etapas a mais, que dependem do agente."
      }
    >
      {comCaso.length === 0 ? (
        <SemDado titulo="Nenhum caso medido" motivo="Não há caso cadastrado no Acervo." />
      ) : (
        <div className="flex flex-col gap-[6px]">
          {comCaso.map((faixa) => {
            const marcado = escolhida?.codigo === faixa.codigo;
            return (
              <button
                key={faixa.codigo}
                type="button"
                className={`${FAIXA_FUNIL} ${marcado ? FAIXA_FUNIL_ATIVA : ""}`}
                aria-expanded={marcado}
                title={faixa.descricao}
                onClick={() => onAbrirEstagio(marcado ? null : faixa.codigo)}
              >
                <span className="flex min-w-0">
                  <Selo tom={TOM_SELO[faixa.tom]} simbolo={LEITURA_DO_TOM[faixa.tom].simbolo}>
                    {faixa.titulo}
                  </Selo>
                </span>
                <span className="block h-[10px] rounded-pill bg-papel-3 overflow-hidden max-[720px]:col-span-full" aria-hidden>
                  <span
                    className="block h-full rounded-pill"
                    style={{
                      width: `${total ? (faixa.casos / total) * 100 : 0}%`,
                      background: COR_DO_TOM[faixa.tom],
                    }}
                  />
                </span>
                <span className="text-tinta font-titulo text-md font-bold text-right whitespace-nowrap">
                  {faixa.casos}
                  <span className="text-tinta-3 font-ui text-xs font-semibold">
                    {faixa.percentual === null ? "" : ` · ${numero(faixa.percentual)}%`}
                  </span>
                </span>
              </button>
            );
          })}

          {escolhida ? (
            <div className="mt-1 mb-[2px] ml-[10px] px-[14px] py-3 border-l-2 border-acao-borda rounded-r-campo bg-papel-2">
              <p className="mt-0 mb-2 text-tinta-3 text-sm leading-[1.5]">
                {escolhida.titulo} — {escolhida.descricao}
              </p>
              <ul className="flex flex-col gap-[2px] m-0 p-0 list-none">
                {doEstagio.map((caso) => (
                  <li key={caso.id}>
                    <button
                      type="button"
                      className={LINHA_CASO}
                      onClick={() => onAbrirCaso(caso.id)}
                    >
                      <span className="text-tinta text-base font-semibold">{caso.cliente}</span>
                      <span className="text-tinta-3 text-sm max-[720px]:col-span-full">{caso.categoria}</span>
                      <span className="text-tinta-3 text-xs whitespace-nowrap">
                        {caso.dias_sem_movimentacao === null
                          ? "sem movimentação registrada"
                          : `parado há ${numero(caso.dias_sem_movimentacao)} dias`}
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
            </div>
          ) : (
            <p className="mt-[2px] mb-0 text-tinta-3 text-xs">
              Clique num estágio para ver quais casos estão nele.
            </p>
          )}
        </div>
      )}
    </Bloco>
  );
}

/* ------------------------------------------------------------------- tempo */

function OndeOTempoVai({ tempo }: { tempo: Dados["tempo"] }) {
  const comHoras = tempo.etapas.filter((etapa) => etapa.horas_totais > 0);
  const correndo = tempo.etapas.filter((etapa) => etapa.em_curso > 0);

  return (
    <Bloco titulo="Onde o tempo é gasto" explicacao={tempo.base}>
      {comHoras.length === 0 ? (
        <SemDado
          titulo="Nenhuma etapa concluída ainda"
          motivo="Sem etapa fechada não há tempo a distribuir — o que está em curso aparece abaixo."
        />
      ) : (
        <Figura
          titulo="Horas acumuladas por etapa"
          descricao="Soma de todas as vezes que a etapa foi concluída, em todos os casos."
          tabela={{
            colunas: [
              { chave: "etapa", rotulo: "Etapa" },
              { chave: "total", rotulo: "Acumulado" },
              { chave: "parte", rotulo: "Parte do tempo" },
              { chave: "mediana", rotulo: "Mediana" },
              { chave: "amostra", rotulo: "Casos medidos" },
            ],
            linhas: tempo.etapas.map((etapa) => ({
              etapa: etapa.titulo,
              total: duracao(etapa.horas_totais),
              parte: etapa.percentual === null ? "—" : `${numero(etapa.percentual)}%`,
              mediana: etapa.mediana_horas === null ? "—" : duracao(etapa.mediana_horas),
              amostra: etapa.amostra,
            })),
          }}
        >
          <GraficoDeBarras
            itens={comHoras.map((etapa) => ({
              rotulo: etapa.titulo,
              valores: [{ nome: "acumulado", valor: etapa.horas_totais, cor: CORES_DE_SERIE[0] }],
              nota:
                etapa.mediana_horas === null
                  ? (etapa.motivo ?? undefined)
                  : `Mediana de ${duracao(etapa.mediana_horas)} em ${etapa.amostra} casos.`,
            }))}
            unidade=" h"
          />
        </Figura>
      )}

      {correndo.length > 0 && (
        <ul className="m-0 pl-[18px] text-tinta-2 text-sm leading-[1.55]">
          {correndo.map((etapa) => (
            <li key={etapa.codigo}>
              <strong>{etapa.titulo}</strong>: {etapa.em_curso}{" "}
              {etapa.em_curso === 1 ? "caso ainda corre" : "casos ainda correm"} nesta etapa
              {etapa.mais_antigo_horas !== null && (
                <> — o mais antigo há {duracao(etapa.mais_antigo_horas)}</>
              )}
              . Esse tempo não entra na soma acima.
            </li>
          ))}
        </ul>
      )}
    </Bloco>
  );
}

/* --------------------------------------------------------------- movimento */

function Movimento({ movimento }: { movimento: Dados["movimento"] }) {
  const meses = movimento.meses;
  const vazio = meses.every(
    (mes) => mes.abertos === 0 && mes.entrevistas === 0 && mes.contratos_assinados === 0,
  );

  return (
    <Bloco titulo="Movimento dos últimos doze meses" explicacao={movimento.base}>
      {vazio ? (
        <SemDado
          titulo="Nenhum marco no período"
          motivo="Nenhum caso foi aberto, entrevistado ou contratado nos últimos doze meses."
        />
      ) : (
        <Figura
          titulo="Casos abertos, entrevistas e contratos"
          descricao={`O último mês (${meses[meses.length - 1].rotulo}) ainda está correndo.`}
          legenda={[
            { rotulo: "Casos abertos", cor: CORES_DE_SERIE[0], forma: "linha" },
            { rotulo: "Entrevistas", cor: CORES_DE_SERIE[1], forma: "linha" },
            { rotulo: "Contratos assinados", cor: CORES_DE_SERIE[2], forma: "linha" },
          ]}
          tabela={{
            colunas: [
              { chave: "mes", rotulo: "Mês" },
              { chave: "abertos", rotulo: "Abertos" },
              { chave: "entrevistas", rotulo: "Entrevistas" },
              { chave: "contratos", rotulo: "Contratos" },
            ],
            linhas: meses.map((mes) => ({
              mes: mes.parcial ? `${mes.rotulo} (parcial)` : mes.rotulo,
              abertos: mes.abertos,
              entrevistas: mes.entrevistas,
              contratos: mes.contratos_assinados,
            })),
          }}
        >
          <GraficoDeLinha
            rotulos={meses.map((mes) => mes.rotulo)}
            series={[
              {
                nome: "Casos abertos",
                cor: CORES_DE_SERIE[0],
                valores: meses.map((mes) => mes.abertos),
                unidade: "casos",
              },
              {
                nome: "Entrevistas",
                cor: CORES_DE_SERIE[1],
                valores: meses.map((mes) => mes.entrevistas),
                unidade: "entrevistas",
              },
              {
                nome: "Contratos assinados",
                cor: CORES_DE_SERIE[2],
                valores: meses.map((mes) => mes.contratos_assinados),
                unidade: "contratos",
              },
            ]}
          />
        </Figura>
      )}
    </Bloco>
  );
}

/* -------------------------------------------------------------- categorias */

function Categorias({ categorias }: { categorias: Dados["categorias"] }) {
  return (
    <Bloco
      titulo="Por tipo de ação"
      explicacao={
        "Ciclo e idade são medidas diferentes: o ciclo é dos casos que chegaram ao contrato " +
        "assinado; a idade é de quanto os que ainda correm já levaram. Somá-las faria a " +
        "mediana cair a cada caso novo aberto."
      }
    >
      {categorias.length === 0 ? (
        <SemDado titulo="Nenhuma categoria" motivo="Não há caso cadastrado no Acervo." />
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full border-collapse text-sm">
            <thead>
              <tr>
                <th className={CELULA_TH}>Tipo de ação</th>
                <th className={CELULA_TH}>Casos</th>
                <th className={CELULA_TH}>Em andamento</th>
                <th className={CELULA_TH}>Instruídos</th>
                <th className={CELULA_TH}>Parados</th>
                <th className={CELULA_TH}>Ciclo mediano</th>
                <th className={CELULA_TH}>Idade dos que correm</th>
              </tr>
            </thead>
            <tbody>
              {categorias.map((categoria) => (
                <tr key={categoria.codigo} className="group">
                  <td className={CELULA_TD}>{categoria.nome}</td>
                  <td className={CELULA_TD}>{categoria.casos}</td>
                  <td className={CELULA_TD}>{categoria.em_andamento}</td>
                  <td className={CELULA_TD}>{categoria.instruidos}</td>
                  <td className={CELULA_TD}>
                    {categoria.parados > 0 ? (
                      <Selo tom="critico" simbolo="✕">
                        {categoria.parados}
                      </Selo>
                    ) : (
                      "—"
                    )}
                  </td>
                  <td title={categoria.motivo ?? undefined}>
                    {categoria.ciclo_mediano_horas === null ? (
                      <span className="text-tinta-3 text-xs italic">sem amostra</span>
                    ) : (
                      `${duracao(categoria.ciclo_mediano_horas)} · ${categoria.ciclo_amostra} casos`
                    )}
                  </td>
                  <td className={CELULA_TD}>
                    {categoria.idade_mediana_horas === null ? (
                      <span className="text-tinta-3 text-xs italic">sem amostra</span>
                    ) : (
                      `${duracao(categoria.idade_mediana_horas)} · ${categoria.idade_amostra} casos`
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Bloco>
  );
}

/* ----------------------------------------------------------------- parados */

function Parados({
  parados,
  onAbrirCaso,
}: {
  parados: Dados["parados"];
  onAbrirCaso: (casoId: string) => void;
}) {
  return (
    <Bloco
      titulo="Parados há mais tempo"
      explicacao={
        `Casos sem nenhuma movimentação registrada há ${parados.limiar_dias} dias ou mais. ` +
        "Não é prazo — o sistema não guarda nenhum; é o limiar do indicador de ritmo. Caso " +
        "instruído não entra aqui: não há o que movimentar nele."
      }
    >
      {parados.itens.length === 0 ? (
        <SemDado
          titulo="Nenhum caso parado"
          motivo={`Todos os casos tiveram alguma movimentação nos últimos ${parados.limiar_dias} dias.`}
        />
      ) : (
        <>
          <ul className="flex flex-col gap-[2px] m-0 p-0 list-none">
            {parados.itens.map((caso) => (
              <li key={caso.id}>
                <button
                  type="button"
                  className={LINHA_CASO}
                  onClick={() => onAbrirCaso(caso.id)}
                >
                  <span className="text-tinta text-base font-semibold">{caso.cliente}</span>
                  <span className="text-tinta-3 text-sm max-[720px]:col-span-full">
                    {caso.categoria} · {caso.estagio_titulo}
                  </span>
                  <Selo tom={TOM_SELO[caso.tom]} simbolo={LEITURA_DO_TOM[caso.tom].simbolo}>
                    {numero(caso.dias)} dias
                  </Selo>
                </button>
              </li>
            ))}
          </ul>
          {parados.total > parados.mostrando && (
            <p className="mt-[2px] mb-0 text-tinta-3 text-xs">
              Mostrando os {parados.mostrando} mais antigos de {parados.total} parados. Os
              demais estão na fila da carteira.
            </p>
          )}
        </>
      )}
    </Bloco>
  );
}

/* ------------------------------------------------------------------ equipe */

function Equipe({ equipe }: { equipe: Dados["equipe"] }) {
  return (
    <Bloco
      titulo="Entrevistas por quem conduziu"
      explicacao={
        "Não é ranking de desempenho: quem entrevista mais pode estar atendendo os casos mais " +
        "simples, e o sistema não guarda nada que permita afirmar o contrário."
      }
    >
      {equipe.pessoas.length === 0 ? (
        <SemDado titulo="Nenhuma entrevista" motivo="Nenhuma entrevista foi anexada a um caso." />
      ) : (
        <>
          <div className="overflow-x-auto">
            <table className="w-full border-collapse text-sm">
              <thead>
                <tr>
                  <th className={CELULA_TH}>Quem</th>
                  <th className={CELULA_TH}>Entrevistas</th>
                  <th className={CELULA_TH}>Casos</th>
                  <th className={CELULA_TH}>Lidas pelo agente</th>
                  <th className={CELULA_TH}>Fatos gerados</th>
                </tr>
              </thead>
              <tbody>
                {equipe.pessoas.map((pessoa) => (
                  <tr key={pessoa.nome} className="group">
                    <td className={CELULA_TD}>
                      {pessoa.informado ? (
                        pessoa.nome
                      ) : (
                        <span className="text-tinta-3 text-xs italic">não informado</span>
                      )}
                    </td>
                    <td className={CELULA_TD}>{pessoa.entrevistas}</td>
                    <td className={CELULA_TD}>{pessoa.casos}</td>
                    <td className={CELULA_TD}>{pessoa.lidas}</td>
                    <td className={CELULA_TD}>{pessoa.fatos_gerados}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {equipe.sem_atribuicao > 0 && (
            <p className="mt-[2px] mb-0 text-tinta-3 text-xs">
              {equipe.sem_atribuicao} de {equipe.total_entrevistas} entrevistas foram gravadas
              sem o nome de quem conduziu — elas continuam contadas, agrupadas como não
              informado.
            </p>
          )}
        </>
      )}
    </Bloco>
  );
}

/* --------------------------------------------------------------- qualidade */

function Qualidade({ qualidade }: { qualidade: Dados["qualidade"] }) {
  return (
    <Bloco titulo="Documentos recebidos" explicacao={qualidade.base}>
      {qualidade.entregas === 0 ? (
        <SemDado titulo="Nenhum documento" motivo="Nenhum arquivo foi enviado a um caso ainda." />
      ) : (
        <ul className="flex flex-col gap-2 m-0 p-0 list-none text-tinta-2 text-sm [&>li]:flex [&>li]:items-baseline [&>li]:gap-2 [&>li]:flex-wrap">
          <li>
            <span className="min-w-[56px] text-tinta font-titulo text-md font-bold">{qualidade.entregas}</span>
            recebidos
          </li>
          <li>
            <span className="min-w-[56px] text-tinta font-titulo text-md font-bold">{qualidade.aproveitadas}</span>
            aproveitados
            {qualidade.percentual_aproveitado !== null && (
              <span className="text-tinta-3 text-xs">
                {numero(qualidade.percentual_aproveitado)}% do total
              </span>
            )}
          </li>
          <li>
            <span className="min-w-[56px] text-tinta font-titulo text-md font-bold">{qualidade.a_conferir}</span>
            a conferir
            <span className="text-tinta-3 text-xs">ilegível ou de outro tipo</span>
          </li>
          <li>
            <span className="min-w-[56px] text-tinta font-titulo text-md font-bold">{qualidade.com_erro}</span>
            falharam na leitura
          </li>
          <li>
            <span className="min-w-[56px] text-tinta font-titulo text-md font-bold">
              {qualidade.legibilidade_media === null
                ? "—"
                : `${numero(qualidade.legibilidade_media)}%`}
            </span>
            legibilidade média
            <span className="text-tinta-3 text-xs">
              {qualidade.legibilidade_amostra > 0
                ? `medida em ${qualidade.legibilidade_amostra} arquivos com nota`
                : "nenhum arquivo tem nota de legibilidade"}
            </span>
          </li>
        </ul>
      )}
    </Bloco>
  );
}

/* --------------------------------------------------------------- ausências */

function Ausencias({ ausencias }: { ausencias: Dados["ausencias"] }) {
  return (
    <Bloco
      titulo="O que este painel não sabe"
      explicacao={
        "Está escrito porque a alternativa é pior: seção vazia sem motivo é lida como zero, e " +
        "um prazo deduzido de mediana vira compromisso na cabeça de quem lê."
      }
    >
      <dl className="grid grid-cols-[repeat(auto-fit,minmax(280px,1fr))] gap-[10px] m-0">
        {ausencias.map((item) => (
          <div key={item.campo} className="px-3 py-[10px] border border-dashed border-borda-forte rounded-campo bg-papel-2 [&>dt]:text-tinta [&>dt]:text-sm [&>dt]:font-bold [&>dd]:mt-[3px] [&>dd]:mb-0 [&>dd]:ml-0 [&>dd]:text-tinta-3 [&>dd]:text-xs [&>dd]:leading-[1.5]">
            <dt>{item.campo}</dt>
            <dd>{item.motivo}</dd>
          </div>
        ))}
      </dl>
    </Bloco>
  );
}

/* ------------------------------------------------------------------ bloco */

function Bloco({
  titulo,
  explicacao,
  children,
}: {
  titulo: string;
  explicacao?: string;
  children: React.ReactNode;
}) {
  return (
    <section className="flex flex-col gap-[10px]">
      <h2 className="m-0 text-tinta font-titulo text-md font-bold">{titulo}</h2>
      {explicacao && <p className="m-0 max-w-[78ch] text-tinta-3 text-sm leading-[1.5]">{explicacao}</p>}
      {children}
    </section>
  );
}
