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

import { Aviso, Selo } from "@/components/Basicos";
import {
  CORES_DE_SERIE,
  Figura,
  GraficoDeBarras,
  GraficoDeLinha,
  SemDado,
} from "@/components/graficos";
import type { TomSelo } from "@/lib/formato";
import { dataHora, duracao, LEITURA_DO_TOM, numero, type Tom } from "@/lib/painel";
import {
  buscarPanorama,
  type CasoDoPanorama,
  type FaixaDoFunil,
  type Panorama as Dados,
} from "@/lib/panorama";
import estilos from "./Panorama.module.css";

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
    <div className={estilos.pagina}>
      <div className={estilos.topo}>
        <button type="button" className="botao botao--secundario botao--pequeno" onClick={onVoltar}>
          ← Voltar para a carteira
        </button>
      </div>

      <header className={estilos.cabecalho}>
        <h1 className={estilos.titulo}>Panorama do escritório</h1>
        <p className={estilos.subtitulo}>
          Todos os casos somados: em que estágio estão, onde o tempo é gasto e o que está
          parado. Tudo medido de instante gravado no banco, com as mesmas contas do painel de
          cada caso — nada aqui é estimado.
        </p>
        {dados && (
          <p className={estilos.linhaFina}>
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
        <p className={estilos.carregando} aria-live="polite">
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

          <div className={estilos.gradeIndicadores}>
            {dados.indicadores.map((indicador) => (
              <div key={indicador.codigo} className={estilos.indicador}>
                <span className={estilos.rotuloIndicador}>{indicador.rotulo}</span>
                <span className={estilos.valorIndicador}>
                  {indicador.valor === null ? "—" : numero(indicador.valor)}
                  {indicador.unidade && indicador.valor !== null && (
                    <span className={estilos.unidadeIndicador}>{indicador.unidade}</span>
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
                <span className={estilos.detalheIndicador}>{indicador.detalhe}</span>
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
          <div className={estilos.duasColunas}>
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
        <div className={estilos.listaFunil}>
          {comCaso.map((faixa) => {
            const marcado = escolhida?.codigo === faixa.codigo;
            return (
              <button
                key={faixa.codigo}
                type="button"
                className={`${estilos.faixaFunil} ${marcado ? estilos.faixaFunilAtiva : ""}`}
                aria-expanded={marcado}
                title={faixa.descricao}
                onClick={() => onAbrirEstagio(marcado ? null : faixa.codigo)}
              >
                <span className={estilos.rotuloFaixa}>
                  <Selo tom={TOM_SELO[faixa.tom]} simbolo={LEITURA_DO_TOM[faixa.tom].simbolo}>
                    {faixa.titulo}
                  </Selo>
                </span>
                <span className={estilos.barraFaixa} aria-hidden>
                  <span
                    className={estilos.preenchimentoFaixa}
                    style={{
                      width: `${total ? (faixa.casos / total) * 100 : 0}%`,
                      background: COR_DO_TOM[faixa.tom],
                    }}
                  />
                </span>
                <span className={estilos.numeroFaixa}>
                  {faixa.casos}
                  <span className={estilos.percentualFaixa}>
                    {faixa.percentual === null ? "" : ` · ${numero(faixa.percentual)}%`}
                  </span>
                </span>
              </button>
            );
          })}

          {escolhida ? (
            <div className={estilos.casosDoEstagio}>
              <p className={estilos.tituloEstagio}>
                {escolhida.titulo} — {escolhida.descricao}
              </p>
              <ul className={estilos.listaCasos}>
                {doEstagio.map((caso) => (
                  <li key={caso.id}>
                    <button
                      type="button"
                      className={estilos.linhaCaso}
                      onClick={() => onAbrirCaso(caso.id)}
                    >
                      <span className={estilos.clienteCaso}>{caso.cliente}</span>
                      <span className={estilos.detalheCaso}>{caso.categoria}</span>
                      <span className={estilos.tempoCaso}>
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
            <p className={estilos.rodapeBloco}>
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
        <ul className={estilos.listaNotas}>
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
        <div className={estilos.rolagem}>
          <table className={estilos.tabela}>
            <thead>
              <tr>
                <th>Tipo de ação</th>
                <th>Casos</th>
                <th>Em andamento</th>
                <th>Instruídos</th>
                <th>Parados</th>
                <th>Ciclo mediano</th>
                <th>Idade dos que correm</th>
              </tr>
            </thead>
            <tbody>
              {categorias.map((categoria) => (
                <tr key={categoria.codigo}>
                  <td>{categoria.nome}</td>
                  <td>{categoria.casos}</td>
                  <td>{categoria.em_andamento}</td>
                  <td>{categoria.instruidos}</td>
                  <td>
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
                      <span className={estilos.semMedida}>sem amostra</span>
                    ) : (
                      `${duracao(categoria.ciclo_mediano_horas)} · ${categoria.ciclo_amostra} casos`
                    )}
                  </td>
                  <td>
                    {categoria.idade_mediana_horas === null ? (
                      <span className={estilos.semMedida}>sem amostra</span>
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
          <ul className={estilos.listaCasos}>
            {parados.itens.map((caso) => (
              <li key={caso.id}>
                <button
                  type="button"
                  className={estilos.linhaCaso}
                  onClick={() => onAbrirCaso(caso.id)}
                >
                  <span className={estilos.clienteCaso}>{caso.cliente}</span>
                  <span className={estilos.detalheCaso}>
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
            <p className={estilos.rodapeBloco}>
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
          <div className={estilos.rolagem}>
            <table className={estilos.tabela}>
              <thead>
                <tr>
                  <th>Quem</th>
                  <th>Entrevistas</th>
                  <th>Casos</th>
                  <th>Lidas pelo agente</th>
                  <th>Fatos gerados</th>
                </tr>
              </thead>
              <tbody>
                {equipe.pessoas.map((pessoa) => (
                  <tr key={pessoa.nome}>
                    <td>
                      {pessoa.informado ? (
                        pessoa.nome
                      ) : (
                        <span className={estilos.semMedida}>não informado</span>
                      )}
                    </td>
                    <td>{pessoa.entrevistas}</td>
                    <td>{pessoa.casos}</td>
                    <td>{pessoa.lidas}</td>
                    <td>{pessoa.fatos_gerados}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {equipe.sem_atribuicao > 0 && (
            <p className={estilos.rodapeBloco}>
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
        <ul className={estilos.listaContagens}>
          <li>
            <span className={estilos.numeroContagem}>{qualidade.entregas}</span>
            recebidos
          </li>
          <li>
            <span className={estilos.numeroContagem}>{qualidade.aproveitadas}</span>
            aproveitados
            {qualidade.percentual_aproveitado !== null && (
              <span className={estilos.notaContagem}>
                {numero(qualidade.percentual_aproveitado)}% do total
              </span>
            )}
          </li>
          <li>
            <span className={estilos.numeroContagem}>{qualidade.a_conferir}</span>
            a conferir
            <span className={estilos.notaContagem}>ilegível ou de outro tipo</span>
          </li>
          <li>
            <span className={estilos.numeroContagem}>{qualidade.com_erro}</span>
            falharam na leitura
          </li>
          <li>
            <span className={estilos.numeroContagem}>
              {qualidade.legibilidade_media === null
                ? "—"
                : `${numero(qualidade.legibilidade_media)}%`}
            </span>
            legibilidade média
            <span className={estilos.notaContagem}>
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
      <dl className={estilos.listaAusencias}>
        {ausencias.map((item) => (
          <div key={item.campo} className={estilos.ausencia}>
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
    <section className={estilos.bloco}>
      <h2 className={estilos.tituloBloco}>{titulo}</h2>
      {explicacao && <p className={estilos.explicacaoBloco}>{explicacao}</p>}
      {children}
    </section>
  );
}
