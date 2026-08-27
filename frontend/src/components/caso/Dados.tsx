"use client";

/* O acervo de precedentes, para consultar e auditar.
 *
 * A recomendação diz "destes N processos parecidos, tantos foram favoráveis".
 * Esta tela responde a pergunta seguinte, que antes não tinha resposta: N
 * processos de onde? A tela tem dois andares:
 *
 *   1. PAINEL — quanto há, de quando, e como se distribui (resultado, origem,
 *      tribunal, tipo, classe) + taxa de recurso e duração observada. É a foto
 *      do que a base enxerga, em números e gráficos.
 *   2. DETALHAMENTO — panorama → lista → trechos do documento, a ordem em que a
 *      dúvida aparece. O último nível mostra os TRECHOS (e todos os metadados
 *      que cada um carrega), porque é o trecho que a busca compara: auditar o
 *      original não diria se ele foi bem fatiado — e é o fatiamento que decide
 *      o que a recomendação enxerga.
 */

import { useCallback, useEffect, useState } from "react";

import { Aviso, Botao, Selo } from "@/components/ui/Basicos";
import {
  CORES_DE_SERIE,
  Figura,
  GraficoDeBarras,
  SemDado,
  type BarraHorizontal,
} from "@/components/ui/graficos";
import {
  ApiError,
  listarDocumentosAcervo,
  obterDocumentoAcervo,
  panoramaAcervo,
  prazosAcervo,
  type DocumentoAcervo,
  type DocumentoDetalhe,
  type PanoramaAcervo,
  type PrazosAcervo,
} from "@/lib/api";

interface Props {
  onVoltar: () => void;
}

const N = (v: number) => v.toLocaleString("pt-BR");
const dia = (s?: string | null) => (s ? s.slice(0, 10) : "");

/** Item de qualquer agrupamento do panorama. `trechos` falta no tipo de fonte. */
type ItemGrupo = { nome: string; documentos: number; trechos?: number };

/* -------------------------------------------------------------- painel -- */

/** Um número grande com rótulo. `tom` critico chama atenção do que está errado. */
function Kpi({
  rotulo,
  valor,
  tom = "normal",
}: {
  rotulo: string;
  valor: string;
  tom?: "normal" | "critico";
}) {
  return (
    <div className="flex flex-col gap-[2px] px-4 py-3 border border-borda-forte rounded-[10px] bg-papel min-w-[132px]">
      <strong
        className={`text-[1.5rem] leading-[1.1] tabular-nums ${
          tom === "critico" ? "text-critico" : "text-tinta"
        }`}
      >
        {valor}
      </strong>
      <span className={`text-[0.82rem] ${tom === "critico" ? "text-critico" : "text-tinta-3"}`}>
        {rotulo}
      </span>
    </div>
  );
}

/** Uma figura de barras a partir de um agrupamento do panorama. */
function FiguraGrupo({
  titulo,
  descricao,
  itens,
  limite = 12,
  colorido = false,
}: {
  titulo: string;
  descricao: string;
  itens: ItemGrupo[];
  /** Quantas barras mostrar — o resto fica na tabela da figura. */
  limite?: number;
  /** Uma cor por categoria (para poucas categorias, como resultado/origem). */
  colorido?: boolean;
}) {
  const top = itens.slice(0, limite);
  if (top.length === 0) {
    return <SemDado titulo={titulo} motivo="Nada indexado nesta dimensão ainda." />;
  }
  const temTrechos = top.some((i) => typeof i.trechos === "number");
  const barras: BarraHorizontal[] = top.map((i, k) => ({
    rotulo: i.nome || "(sem valor)",
    valores: [
      {
        nome: "documentos",
        valor: i.documentos,
        cor: colorido ? CORES_DE_SERIE[k % CORES_DE_SERIE.length] : CORES_DE_SERIE[0],
      },
    ],
    nota: temTrechos
      ? `${N(i.documentos)} documento(s) · ${N(i.trechos ?? 0)} trecho(s)`
      : `${N(i.documentos)} documento(s)`,
  }));
  return (
    <Figura
      titulo={titulo}
      descricao={descricao}
      tabela={{
        colunas: [
          { chave: "nome", rotulo: titulo },
          { chave: "documentos", rotulo: "Documentos" },
          ...(temTrechos ? [{ chave: "trechos", rotulo: "Trechos" }] : []),
        ],
        linhas: top.map((i) => ({
          nome: i.nome || "(sem valor)",
          documentos: i.documentos,
          ...(temTrechos ? { trechos: i.trechos ?? 0 } : {}),
        })),
      }}
    >
      <GraficoDeBarras itens={barras} unidade=" doc." />
    </Figura>
  );
}

/* --------------------------------------------------------- detalhamento -- */

/** Uma contagem por categoria, clicável quando serve de filtro. */
function Grupo({
  titulo,
  itens,
  ativo,
  onEscolher,
}: {
  titulo: string;
  itens: ItemGrupo[];
  ativo?: string;
  onEscolher?: (nome: string) => void;
}) {
  if (itens.length === 0) return null;
  return (
    <section className="[&+&]:mt-[18px] [&+&]:pt-4 [&+&]:border-t [&+&]:border-borda">
      <h3 className="mb-2 mt-0 text-[0.82rem] uppercase tracking-[0.04em] text-tinta-3">
        {titulo} <span className="text-tinta-3 text-[0.82rem]">({itens.length})</span>
      </h3>
      <ul className="list-none m-0 p-0">
        {itens.map((i) => (
          <li key={i.nome}>
            {onEscolher ? (
              <button
                type="button"
                className={`flex justify-between gap-[10px] w-full px-[7px] py-[5px] border-0 rounded-[6px] [font:inherit] text-left cursor-pointer hover:bg-papel-3 ${
                  ativo === i.nome ? "bg-acao-clara font-semibold" : "bg-transparent"
                }`}
                onClick={() => onEscolher(ativo === i.nome ? "" : i.nome)}
              >
                <span className="[overflow-wrap:anywhere]">{i.nome || "(sem valor)"}</span>
                <span className="text-tinta-3 text-[0.82rem] whitespace-nowrap">
                  {N(i.documentos)} doc.
                </span>
              </button>
            ) : (
              <div className="flex justify-between gap-[10px] w-full px-[7px] py-[5px] border-0 rounded-[6px] bg-transparent [font:inherit] text-left">
                <span className="[overflow-wrap:anywhere]">{i.nome || "(sem valor)"}</span>
                <span className="text-tinta-3 text-[0.82rem] whitespace-nowrap">
                  {N(i.documentos)} doc.
                </span>
              </div>
            )}
          </li>
        ))}
      </ul>
    </section>
  );
}

/* Os metadados que cada trecho carrega, na ordem em que se lê um processo.
 *
 * É o que a busca usa para achar "processos semelhantes" e para dizer se foram
 * favoráveis — então é o que precisa estar à vista quando se audita o acervo. */
const ROTULO_META: [string, string][] = [
  ["numero_processo", "Processo"],
  ["orgao_julgador", "Órgão julgador / vara"],
  ["relator", "Relator"],
  ["magistrados", "Magistrados"],
  ["rotulo", "Resultado"],
  ["tipo_documento", "Tipo de documento"],
  ["classe", "Classe"],
  ["assuntos", "Assuntos"],
  ["origem", "Origem"],
  ["data", "Data"],
];

function textoMeta(chave: string, valor: unknown): string {
  if (Array.isArray(valor)) return valor.map((v) => String(v)).join(", ");
  if (chave === "data") return dia(String(valor));
  return String(valor);
}

/** Lista chave→valor dos metadados de um trecho (só o que existe). */
function MetaLista({ metadados }: { metadados: unknown }) {
  if (!metadados || typeof metadados !== "object") return null;
  const m = metadados as Record<string, unknown>;
  const linhas = ROTULO_META.map(([chave, rotulo]) => ({
    rotulo,
    texto: m[chave] === undefined || m[chave] === null ? "" : textoMeta(chave, m[chave]),
  })).filter((l) => l.texto.trim().length > 0);
  if (linhas.length === 0) return null;
  return (
    <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-[3px] m-0 mt-[10px] mb-1 p-[10px] rounded-[7px] bg-papel-2 text-[0.82rem]">
      {linhas.map((l) => (
        <div key={l.rotulo} className="contents">
          <dt className="text-tinta-3 whitespace-nowrap">{l.rotulo}</dt>
          <dd className="m-0 text-tinta [overflow-wrap:anywhere]">{l.texto}</dd>
        </div>
      ))}
    </dl>
  );
}

/* --------------------------------------------------------------- tela -- */

export default function Dados({ onVoltar }: Props) {
  const [panorama, setPanorama] = useState<PanoramaAcervo | null>(null);
  const [prazos, setPrazos] = useState<PrazosAcervo | null>(null);
  const [erro, setErro] = useState<string | null>(null);
  const [carregando, setCarregando] = useState(true);

  const [origem, setOrigem] = useState("");
  const [tribunal, setTribunal] = useState("");
  const [busca, setBusca] = useState("");
  const [docs, setDocs] = useState<DocumentoAcervo[]>([]);
  const [listando, setListando] = useState(false);

  const [aberto, setAberto] = useState<DocumentoDetalhe | null>(null);
  const [abrindo, setAbrindo] = useState(false);

  useEffect(() => {
    void panoramaAcervo()
      .then(setPanorama)
      .catch((e) =>
        setErro(e instanceof ApiError ? e.message : "Não foi possível ler o acervo."),
      )
      .finally(() => setCarregando(false));
    // Prazos moram na mesma base e falham juntos; um erro aqui não derruba o
    // painel inteiro — a seção some e o resto continua.
    void prazosAcervo()
      .then(setPrazos)
      .catch(() => setPrazos(null));
  }, []);

  const listar = useCallback(async () => {
    setListando(true);
    setAberto(null);
    try {
      setDocs((await listarDocumentosAcervo({ origem, tribunal, busca })).itens);
      setErro(null);
    } catch (e) {
      setErro(e instanceof ApiError ? e.message : "Não foi possível listar.");
    } finally {
      setListando(false);
    }
  }, [origem, tribunal, busca]);

  // Escolher origem ou tribunal já lista: são os filtros que vêm de um clique,
  // e obrigar a apertar "buscar" depois de clicar seria um passo sem sentido.
  useEffect(() => {
    if (origem || tribunal) void listar();
  }, [origem, tribunal, listar]);

  async function abrir(id: string) {
    setAbrindo(true);
    try {
      setAberto(await obterDocumentoAcervo(id));
    } catch (e) {
      setErro(e instanceof ApiError ? e.message : "Não foi possível abrir o documento.");
    } finally {
      setAbrindo(false);
    }
  }

  return (
    <div className="max-w-[1280px] mx-auto px-5 pt-6 pb-16">
      <Botao variante="secundario" onClick={onVoltar}>
        ← Voltar para a carteira
      </Botao>

      <header className="mt-5 mb-[18px]">
        <h1 className="mb-[6px] mt-0 text-[1.6rem]">Dados do acervo</h1>
        <p className="m-0 text-tinta-3 max-w-[74ch] leading-[1.55]">
          Tudo que foi alimentado no banco de precedentes, em números e em detalhe. É daqui
          que saem os processos semelhantes citados na recomendação e na análise das
          respostas — o painel mostra como a base se distribui, e a lista abaixo deixa
          conferir, documento a documento, o que exatamente está indexado.
        </p>
      </header>

      {erro && (
        <Aviso tom="critico" titulo="Acervo indisponível">
          {erro}
        </Aviso>
      )}

      {carregando ? (
        <p className="m-0 text-tinta-3">Lendo o acervo…</p>
      ) : panorama ? (
        <>
          {/* ------------------------------------------------------- painel */}
          <div className="flex gap-3 flex-wrap">
            <Kpi rotulo="documentos" valor={N(panorama.fontes)} />
            <Kpi rotulo="trechos indexados" valor={N(panorama.trechos)} />
            <Kpi rotulo="com vetor" valor={N(panorama.vetorizados)} />
            {/* Trecho sem vetor não é encontrável pela busca. Quando houver, é
              * sinal de ingestão que parou no meio — por isso aparece em
              * destaque, e não escondido numa soma. */}
            {panorama.sem_vetor > 0 && (
              <Kpi
                rotulo="sem vetor — fora da busca"
                valor={N(panorama.sem_vetor)}
                tom="critico"
              />
            )}
            {prazos && prazos.processos > 0 && (
              <>
                <Kpi rotulo="processos" valor={N(prazos.processos)} />
                <Kpi rotulo="taxa de recurso" valor={`${prazos.percentual_recurso}%`} />
                {prazos.duracao.mediana_dias != null && (
                  <Kpi
                    rotulo={`duração mediana · n=${N(prazos.duracao.processos_medidos)}`}
                    valor={`${N(prazos.duracao.mediana_dias)} d`}
                  />
                )}
              </>
            )}
          </div>

          {panorama.periodo.de && (
            <p className="mt-3 mb-0 text-tinta-3">
              Decisões de <strong>{dia(panorama.periodo.de)}</strong> a{" "}
              <strong>{dia(panorama.periodo.ate)}</strong>
            </p>
          )}

          {prazos && prazos.processos > 0 && (
            <p className="mt-2 mb-0 max-w-[80ch] text-tinta-3 text-[0.82rem] leading-[1.5]">
              {prazos.aviso}
            </p>
          )}

          <section className="grid grid-cols-2 max-[900px]:grid-cols-1 gap-5 mt-6">
            <FiguraGrupo
              titulo="Resultado"
              descricao="Como os precedentes indexados terminaram — é o que sustenta o 'tantos foram favoráveis'."
              itens={panorama.por_resultado}
              colorido
            />
            <FiguraGrupo
              titulo="Origem"
              descricao="De qual base cada precedente foi ingerido."
              itens={panorama.por_origem}
              colorido
            />
            <div className="col-span-2 max-[900px]:col-span-1">
              <FiguraGrupo
                titulo="Tribunais e varas"
                descricao="Onde os processos correram — as 12 com mais documentos; o resto está na tabela."
                itens={panorama.por_tribunal}
                limite={12}
              />
            </div>
            <FiguraGrupo
              titulo="Tipo de documento"
              descricao="Sentença, acórdão, decisão — o tipo pesa na qualidade do que a busca acha."
              itens={panorama.por_tipo_documento}
            />
            <FiguraGrupo
              titulo="Classe processual"
              descricao="A classe de cada processo indexado."
              itens={panorama.por_classe}
            />
            {panorama.por_tipo_de_fonte.length > 0 && (
              <FiguraGrupo
                titulo="Tipo de fonte"
                descricao="Lei, súmula, jurisprudência ou material interno."
                itens={panorama.por_tipo_de_fonte}
                colorido
              />
            )}
          </section>

          {/* ------------------------------------------------- detalhamento */}
          <h2 className="mt-9 mb-1 text-[1.15rem]">Detalhamento</h2>
          <p className="mt-0 mb-4 text-tinta-3 max-w-[74ch] leading-[1.5]">
            Filtre por origem ou tribunal à esquerda, ou busque por número de processo.
            Abrir um documento mostra os trechos como o buscador os vê — cada um com os
            metadados que carrega.
          </p>

          <div className="grid grid-cols-[300px_minmax(0,1fr)] max-[940px]:grid-cols-1 gap-6 items-start">
            <div className="border border-borda-forte rounded-[10px] p-4 bg-papel max-h-[78vh] overflow-y-auto">
              <Grupo
                titulo="Origem"
                itens={panorama.por_origem}
                ativo={origem}
                onEscolher={setOrigem}
              />
              <Grupo
                titulo="Tribunais e varas"
                itens={panorama.por_tribunal}
                ativo={tribunal}
                onEscolher={setTribunal}
              />
            </div>

            <div className="border border-borda-forte rounded-[10px] p-4 bg-papel">
              <form
                className="flex gap-2 mb-[14px]"
                onSubmit={(e) => {
                  e.preventDefault();
                  void listar();
                }}
              >
                <input
                  className="flex-1 px-[11px] py-[9px] border border-borda-forte rounded-[7px] [font:inherit]"
                  value={busca}
                  onChange={(e) => setBusca(e.target.value)}
                  placeholder="Número do processo ou título"
                />
                <Botao variante="secundario" type="submit" disabled={listando}>
                  {listando ? "Buscando…" : "Buscar"}
                </Botao>
              </form>

              {(origem || tribunal) && (
                <p className="flex items-center gap-2 flex-wrap mb-3 mt-0 text-tinta-3 text-[0.88rem]">
                  Filtrando por{" "}
                  {origem && <Selo tom="info">{origem}</Selo>}
                  {tribunal && <Selo tom="info">{tribunal}</Selo>}
                  <button
                    type="button"
                    className="border-0 bg-transparent text-acao cursor-pointer [font:inherit] underline p-0"
                    onClick={() => {
                      setOrigem("");
                      setTribunal("");
                    }}
                  >
                    limpar
                  </button>
                </p>
              )}

              {aberto ? (
                <div>
                  <button
                    type="button"
                    className="border-0 bg-transparent text-acao cursor-pointer [font:inherit] underline p-0"
                    onClick={() => setAberto(null)}
                  >
                    ← voltar à lista
                  </button>
                  <h3 className="mt-3 mb-1 text-base [overflow-wrap:anywhere]">
                    {aberto.fonte.titulo}
                  </h3>
                  <p className="mt-0 mb-2 text-tinta-3 text-[0.82rem] [overflow-wrap:anywhere]">
                    {[
                      aberto.fonte.tipo,
                      aberto.fonte.identificador,
                      aberto.fonte.publicado_em ? `publicado em ${dia(aberto.fonte.publicado_em)}` : "",
                      `${aberto.total_trechos} trecho(s)`,
                    ]
                      .filter(Boolean)
                      .join(" · ")}
                    {aberto.fonte.url && (
                      <>
                        {" · "}
                        <a href={aberto.fonte.url} target="_blank" rel="noreferrer">
                          documento na origem
                        </a>
                      </>
                    )}
                  </p>
                  {/* Os trechos como o buscador os vê, com os metadados de cada
                    * um. É o nível que responde "por que este processo foi
                    * considerado parecido — e favorável". */}
                  <ol className="list-none m-0 p-0 mt-[14px]">
                    {aberto.trechos.map((t) => (
                      <li key={t.ordem} className="py-[12px] border-t border-borda">
                        <div className="flex gap-[10px] items-center mb-1">
                          <span className="text-tinta-3 text-[0.82rem] whitespace-nowrap">
                            #{t.ordem} · {N(t.caracteres)} car.
                          </span>
                          {!t.vetorizado && (
                            <span className="px-2 py-[1px] rounded-pill bg-critico-claro text-critico text-[0.76rem]">
                              sem vetor
                            </span>
                          )}
                        </div>
                        <p className="m-0 leading-[1.6] whitespace-pre-wrap [overflow-wrap:anywhere]">
                          {t.texto}
                        </p>
                        <MetaLista metadados={t.metadados} />
                      </li>
                    ))}
                  </ol>
                </div>
              ) : docs.length === 0 ? (
                <p className="m-0 text-tinta-3">
                  Escolha uma origem ou um tribunal à esquerda, ou busque por número
                  de processo.
                </p>
              ) : (
                <ul className="list-none m-0 p-0">
                  {docs.map((d) => (
                    <li key={d.id} className="[&+&]:border-t [&+&]:border-borda">
                      <button
                        type="button"
                        className="flex flex-col gap-[3px] w-full px-[7px] py-[9px] border-0 rounded-[6px] bg-transparent [font:inherit] text-left cursor-pointer hover:bg-papel-3"
                        onClick={() => void abrir(d.id)}
                        disabled={abrindo}
                      >
                        <span className="[overflow-wrap:anywhere]">{d.titulo}</span>
                        <span className="text-tinta-3 text-[0.82rem] [overflow-wrap:anywhere]">
                          {[
                            d.processo,
                            d.tribunal || d.origem,
                            d.resultado || "sem resultado",
                            `${N(d.trechos)} trecho(s)`,
                            d.publicado_em ? dia(d.publicado_em) : "",
                          ]
                            .filter(Boolean)
                            .join(" · ")}
                        </span>
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </div>
        </>
      ) : null}
    </div>
  );
}
