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

import { Aviso } from "@/components/Basicos";
import {
  ApiError,
  listarDocumentosAcervo,
  obterDocumentoAcervo,
  panoramaAcervo,
  type DocumentoAcervo,
  type DocumentoDetalhe,
  type PanoramaAcervo,
} from "@/lib/api";
import estilos from "./Dados.module.css";

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
    <section className={estilos.grupo}>
      <h3>
        {titulo} <span className={estilos.meta}>({itens.length})</span>
      </h3>
      <ul>
        {itens.map((i) => (
          <li key={i.nome}>
            {onEscolher ? (
              <button
                type="button"
                className={`${estilos.linha} ${ativo === i.nome ? estilos.linhaAtiva : ""}`}
                onClick={() => onEscolher(ativo === i.nome ? "" : i.nome)}
              >
                <span className={estilos.nome}>{i.nome}</span>
                <span className={estilos.meta}>{N(i.documentos)} doc.</span>
              </button>
            ) : (
              <div className={estilos.linha}>
                <span className={estilos.nome}>{i.nome}</span>
                <span className={estilos.meta}>{N(i.documentos)} doc.</span>
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
    <div className={estilos.container}>
      <button type="button" className="botao botao--secundario" onClick={onVoltar}>
        ← Voltar para a carteira
      </button>

      <header className={estilos.cabecalho}>
        <h1>Dados do acervo</h1>
        <p>
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
        <p className={estilos.vazio}>Lendo o acervo…</p>
      ) : panorama ? (
        <>
          <div className={estilos.numeros}>
            <div>
              <strong>{N(panorama.fontes)}</strong>
              <span>documentos</span>
            </div>
            <div>
              <strong>{N(panorama.trechos)}</strong>
              <span>trechos indexados</span>
            </div>
            <div>
              <strong>{N(panorama.vetorizados)}</strong>
              <span>com vetor</span>
            </div>
            {/* Trecho sem vetor não é encontrável pela busca. Quando houver, é
              * sinal de ingestão que parou no meio — por isso aparece em
              * destaque, e não escondido numa soma. */}
            {panorama.sem_vetor > 0 && (
              <div className={estilos.alerta}>
                <strong>{N(panorama.sem_vetor)}</strong>
                <span>sem vetor — não são achados pela busca</span>
              </div>
            )}
          </div>

          {panorama.periodo.de && (
            <p className={estilos.periodo}>
              Decisões de <strong>{panorama.periodo.de.slice(0, 10)}</strong> a{" "}
              <strong>{panorama.periodo.ate?.slice(0, 10)}</strong>
            </p>
          )}

          <div className={estilos.colunas}>
            <div className={estilos.grupos}>
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

            <div className={estilos.painel}>
              <form
                className={estilos.busca}
                onSubmit={(e) => {
                  e.preventDefault();
                  void listar();
                }}
              >
                <input
                  value={busca}
                  onChange={(e) => setBusca(e.target.value)}
                  placeholder="Número do processo ou título"
                />
                <button type="submit" className="botao" disabled={listando}>
                  {listando ? "Buscando…" : "Buscar"}
                </button>
              </form>

              {(origem || tribunal) && (
                <p className={estilos.filtros}>
                  Filtrando por{" "}
                  {origem && <span className={estilos.selo}>{origem}</span>}
                  {tribunal && <span className={estilos.selo}>{tribunal}</span>}
                  <button
                    type="button"
                    className={estilos.limpar}
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
                    className={estilos.limpar}
                    onClick={() => setAberto(null)}
                  >
                    ← voltar à lista
                  </button>
                  <h3 className={estilos.tituloDoc}>{aberto.fonte.titulo}</h3>
                  <p className={estilos.meta}>
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
                  <ol className={estilos.trechos}>
                    {aberto.trechos.map((t) => (
                      <li key={t.ordem}>
                        <div className={estilos.trechoTopo}>
                          <span className={estilos.meta}>
                            #{t.ordem} · {N(t.caracteres)} car.
                          </span>
                          {!t.vetorizado && (
                            <span className={estilos.semVetor}>sem vetor</span>
                          )}
                        </div>
                        <p>{t.texto}</p>
                      </li>
                    ))}
                  </ol>
                </div>
              ) : docs.length === 0 ? (
                <p className={estilos.vazio}>
                  Escolha uma origem ou um tribunal à esquerda, ou busque por número
                  de processo.
                </p>
              ) : (
                <ul className={estilos.docs}>
                  {docs.map((d) => (
                    <li key={d.id}>
                      <button
                        type="button"
                        className={estilos.doc}
                        onClick={() => void abrir(d.id)}
                        disabled={abrindo}
                      >
                        <span className={estilos.docTitulo}>{d.titulo}</span>
                        <span className={estilos.meta}>
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
