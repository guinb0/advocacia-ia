"use client";

/* O acervo de precedentes, para consultar e auditar.
 *
 * A recomendação diz "destes N processos parecidos, tantos foram favoráveis".
 * Esta tela responde a pergunta seguinte, que antes não tinha resposta: N
 * processos de onde? Panorama → lista → trechos do documento, que é a ordem em
 * que a dúvida aparece.
 *
 * O último nível mostra os TRECHOS, e não o documento original, porque é o
 * trecho que a busca compara. Auditar o original não diria se ele foi bem
 * fatiado — e é o fatiamento que decide o que a recomendação enxerga.
 */

import { useCallback, useEffect, useState } from "react";

import { Aviso, Botao } from "@/components/ui/Basicos";
import {
  ApiError,
  listarDocumentosAcervo,
  obterDocumentoAcervo,
  panoramaAcervo,
  type DocumentoAcervo,
  type DocumentoDetalhe,
  type PanoramaAcervo,
} from "@/lib/api";

interface Props {
  onVoltar: () => void;
}

const N = (v: number) => v.toLocaleString("pt-BR");

/** Uma contagem por categoria, clicável quando serve de filtro. */
function Grupo({
  titulo,
  itens,
  ativo,
  onEscolher,
}: {
  titulo: string;
  itens: { nome: string; trechos: number; documentos: number }[];
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
                <span className="[overflow-wrap:anywhere]">{i.nome}</span>
                <span className="text-tinta-3 text-[0.82rem] whitespace-nowrap">{N(i.documentos)} doc.</span>
              </button>
            ) : (
              <div className="flex justify-between gap-[10px] w-full px-[7px] py-[5px] border-0 rounded-[6px] bg-transparent [font:inherit] text-left">
                <span className="[overflow-wrap:anywhere]">{i.nome}</span>
                <span className="text-tinta-3 text-[0.82rem] whitespace-nowrap">{N(i.documentos)} doc.</span>
              </div>
            )}
          </li>
        ))}
      </ul>
    </section>
  );
}

export default function Dados({ onVoltar }: Props) {
  const [panorama, setPanorama] = useState<PanoramaAcervo | null>(null);
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
        <p className="m-0 text-tinta-3 max-w-[70ch] leading-[1.55]">
          Tudo que foi alimentado no banco de precedentes. É daqui que saem os
          processos semelhantes citados na recomendação e na análise das respostas —
          clique para conferir o que exatamente está indexado.
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
          <div className="flex gap-[26px] flex-wrap py-[14px] border-t border-b border-borda-forte">
            <div className="flex flex-col">
              <strong className="text-[1.5rem] leading-[1.1]">{N(panorama.fontes)}</strong>
              <span className="text-tinta-3 text-[0.84rem]">documentos</span>
            </div>
            <div className="flex flex-col">
              <strong className="text-[1.5rem] leading-[1.1]">{N(panorama.trechos)}</strong>
              <span className="text-tinta-3 text-[0.84rem]">trechos indexados</span>
            </div>
            <div className="flex flex-col">
              <strong className="text-[1.5rem] leading-[1.1]">{N(panorama.vetorizados)}</strong>
              <span className="text-tinta-3 text-[0.84rem]">com vetor</span>
            </div>
            {/* Trecho sem vetor não é encontrável pela busca. Quando houver, é
              * sinal de ingestão que parou no meio — por isso aparece em
              * destaque, e não escondido numa soma. */}
            {panorama.sem_vetor > 0 && (
              <div className="flex flex-col">
                <strong className="text-[1.5rem] leading-[1.1] text-critico">{N(panorama.sem_vetor)}</strong>
                <span className="text-[0.84rem] text-critico">sem vetor — não são achados pela busca</span>
              </div>
            )}
          </div>

          {panorama.periodo.de && (
            <p className="mt-3 mb-0 text-tinta-3">
              Decisões de <strong>{panorama.periodo.de.slice(0, 10)}</strong> a{" "}
              <strong>{panorama.periodo.ate?.slice(0, 10)}</strong>
            </p>
          )}

          <div className="grid grid-cols-[300px_minmax(0,1fr)] max-[940px]:grid-cols-1 gap-6 items-start mt-5">
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
              <Grupo titulo="Resultado" itens={panorama.por_resultado} />
              <Grupo titulo="Tipo de documento" itens={panorama.por_tipo_documento} />
              <Grupo titulo="Classe" itens={panorama.por_classe} />
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
                {/* Só o botão base, sem variante — assim como no CSS original
                  * (mantido idêntico na migração, provável descuido de origem). */}
                <button
                  type="submit"
                  className="inline-flex items-center justify-center gap-2 min-h-10 px-4 py-[9px] border border-transparent rounded-campo bg-transparent font-ui text-sm font-semibold text-tinta-2 cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed"
                  disabled={listando}
                >
                  {listando ? "Buscando…" : "Buscar"}
                </button>
              </form>

              {(origem || tribunal) && (
                <p className="flex items-center gap-2 flex-wrap mb-3 mt-0 text-tinta-3 text-[0.88rem]">
                  Filtrando por{" "}
                  {origem && (
                    <span className="px-[9px] py-[2px] rounded-pill bg-acao-clara text-acao text-[0.82rem]">
                      {origem}
                    </span>
                  )}
                  {tribunal && (
                    <span className="px-[9px] py-[2px] rounded-pill bg-acao-clara text-acao text-[0.82rem]">
                      {tribunal}
                    </span>
                  )}
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
                  <h3 className="mt-3 mb-1 text-base [overflow-wrap:anywhere]">{aberto.fonte.titulo}</h3>
                  <p className="text-tinta-3 text-[0.82rem] whitespace-nowrap">
                    {aberto.fonte.identificador} · {aberto.total_trechos} trecho(s)
                    {aberto.fonte.url && (
                      <>
                        {" · "}
                        <a href={aberto.fonte.url} target="_blank" rel="noreferrer">
                          documento na origem
                        </a>
                      </>
                    )}
                  </p>
                  {/* Os trechos como o buscador os vê. É o nível que responde
                    * "por que este processo foi considerado parecido". */}
                  <ol className="list-none m-0 p-0 mt-[14px]">
                    {aberto.trechos.map((t) => (
                      <li key={t.ordem} className="py-[10px] border-t border-borda">
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
                        <p className="m-0 leading-[1.6] whitespace-pre-wrap [overflow-wrap:anywhere]">{t.texto}</p>
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
                        <span className="text-tinta-3 text-[0.82rem] whitespace-nowrap">
                          {d.tribunal || d.origem} · {d.resultado || "sem resultado"} ·{" "}
                          {N(d.trechos)} trecho(s)
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
