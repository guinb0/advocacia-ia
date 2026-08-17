"use client";

import { useEffect, useRef, useState } from "react";

import { analisarEstrategia, triarEntrevista } from "@/lib/api";
import type { Estrategia, Triagem } from "@/lib/types";
import AudioDaEntrevista from "./AudioDaEntrevista";
import AvaliacaoGoogle from "./AvaliacaoGoogle";
import { Aviso, Selo } from "./Basicos";
import EntrevistaComChamada from "./EntrevistaComChamada";
import RelatorioEntrevista from "./RelatorioEntrevista";
import PainelContrato from "./PainelContrato";
import estilos from "./TriagemEntrevista.module.css";

/* Lê a entrevista e sugere a categoria — mas quem escolhe é o advogado.
 *
 * A sugestão nunca é aplicada sozinha: categoria errada é checklist errado, e o
 * escritório passaria a cobrar do cliente documentos que a ação não usa e a
 * ignorar os que ela exige. Por isso cada opção mostra o trecho do relato que a
 * sustentou, e a lista inteira fica clicável, não só a primeira. */
export default function TriagemEntrevista({
  onEscolher,
  onAtendimento,
}: {
  /** Aplica a categoria (e o nome do cliente, se a entrevista trouxer). */
  onEscolher: (categoria: string, cliente?: string) => void;
  /** Em que ponto o atendimento está. A tela ao redor usa isto para tirar do
   *  caminho o que não é deste cliente (a lista de casos antigos) e para saber
   *  quando pode mostrar a chamada — durante a entrevista ela já está na
   *  coluna da direita, e desenhá-la duas vezes decodificaria o mesmo vídeo em
   *  dois lugares. */
  onAtendimento?: (fase: "nenhum" | "entrevista" | "pos-entrevista") => void;
}) {
  const [texto, setTexto] = useState("");
  const [mostrarRoteiro, setMostrarRoteiro] = useState(false);
  /* A qualificação fica guardada depois que a entrevista fecha: é ela que
   * preenche o contrato, e o relato corrido já não a tem em campos separados. */
  const [qualificacao, setQualificacao] = useState<Record<string, string | string[]> | null>(
    null,
  );
  /* O áudio sobrevive à tela em que foi gravado — pelo mesmo motivo da
   * qualificação. Sem guardar o id aqui, o arquivo continuaria no disco e
   * ninguém teria como pedi-lo: o nome dele é um uuid. */
  const [audioEntrevista, setAudioEntrevista] = useState("");
  /* A etapa do Google Meu Negócio, marcada pelo atendente. Fica AQUI e não na
   * caixa dela: voltar ao roteiro desmonta a caixa, e a marcação sumiria junto
   * — dando a etapa por pendente depois de ela ter sido cumprida. */
  const [avaliacaoConcluida, setAvaliacaoConcluida] = useState(false);
  const [resultado, setResultado] = useState<Triagem | null>(null);
  const [escolhida, setEscolhida] = useState<string | null>(null);
  const [analisando, setAnalisando] = useState(false);
  const [analisandoEstrategia, setAnalisandoEstrategia] = useState(false);
  const [estrategia, setEstrategia] = useState<Estrategia | null>(null);
  const [erroEstrategia, setErroEstrategia] = useState<string | null>(null);
  const [erro, setErro] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  /* Avisa a tela de fora em que ponto este atendimento está.
   *
   * O pós-entrevista (avaliação, relatório, contrato) é a MESMA sessão da
   * entrevista, com o cliente ainda na linha — por isso ele também conta como
   * atendimento em curso, e não como "voltou para a tela de casos". */
  const fase = mostrarRoteiro
    ? "entrevista"
    : qualificacao !== null
      ? "pos-entrevista"
      : "nenhum";
  const avisar = useRef(onAtendimento);
  avisar.current = onAtendimento;
  useEffect(() => {
    avisar.current?.(fase);
  }, [fase]);

  async function analisar(arquivo?: File) {
    if (!arquivo && !texto.trim()) return;
    const relato = arquivo ? await arquivo.text() : texto;
    setAnalisando(true);
    setAnalisandoEstrategia(true);
    setErro(null);
    setErroEstrategia(null);
    setEstrategia(null);
    setEscolhida(null);
    void analisarEstrategia(relato)
      .then(setEstrategia)
      .catch((e: unknown) =>
        setErroEstrategia(
          e instanceof Error ? e.message : "Não foi possível consultar os processos semelhantes.",
        ),
      )
      .finally(() => setAnalisandoEstrategia(false));
    try {
      const r = await triarEntrevista(texto, arquivo);
      setResultado(r);
      // Confiante aplica direto; ambíguo espera o clique.
      if (r.confiante && r.sugestoes[0]) {
        setEscolhida(r.sugestoes[0].codigo);
        onEscolher(r.sugestoes[0].codigo, r.dados.cliente);
      } else if (r.dados.cliente) {
        onEscolher("", r.dados.cliente);
      }
    } catch (e) {
      setErro(e instanceof Error ? e.message : "Não foi possível analisar a entrevista.");
      setResultado(null);
    } finally {
      setAnalisando(false);
    }
  }

  return (
    <div className={estilos.bloco}>
      {mostrarRoteiro ? (
        <EntrevistaComChamada
          onConcluir={(respostas, relato, entrevistaId) => {
            setTexto(relato);
            setQualificacao(respostas);
            setAudioEntrevista(entrevistaId);
            setMostrarRoteiro(false);
          }}
          onFechar={() => setMostrarRoteiro(false)}
        />
      ) : (
        <button
          type="button"
          className="botao botao--secundario"
          onClick={() => setMostrarRoteiro(true)}
          style={{ marginBottom: 14 }}
        >
          {qualificacao ? "Voltar ao roteiro" : "Conduzir entrevista guiada"}
        </button>
      )}

      {/* O áudio do que acabou de ser conduzido, antes do contrato: quem sai da
        * entrevista costuma querer conferir uma fala antes de seguir. */}
      {!mostrarRoteiro && audioEntrevista && (
        <AudioDaEntrevista entrevistaId={audioEntrevista} />
      )}

      {/* Logo após concluir, o entrevistador entrega ao cliente o convite para
        * avaliar o escritório — antes de seguir para os documentos internos, e
        * com o cliente AINDA na chamada, como o roteiro manda. */}
      {qualificacao && !mostrarRoteiro && (
        <AvaliacaoGoogle
          concluida={avaliacaoConcluida}
          onConcluir={setAvaliacaoConcluida}
        />
      )}

      {/* O relatório analisado, logo depois da entrevista: é a entrega que a
        * saudação do roteiro promete à equipe jurídica. */}
      {qualificacao && !mostrarRoteiro && (
        <RelatorioEntrevista respostas={qualificacao} relato={texto} />
      )}

      {/* Entrevista, contrato, documentos — nesta ordem, que é a do escritório. */}
      {qualificacao && !mostrarRoteiro && <PainelContrato respostas={qualificacao} />}

      <span className={estilos.rotulo}>Sugerir o tipo de ação pela entrevista</span>
      <p className={estilos.texto}>
        Opcional. Cole o relato da entrevista (ou envie um arquivo de texto) e o sistema sugere o
        tipo de ação, mostrando o trecho que levou até ela. A escolha final é sempre sua.
      </p>

      <label className="rotuloCampo" htmlFor="relato-entrevista">
        Relato da entrevista
      </label>
      <textarea
        id="relato-entrevista"
        className={`campo campo--area ${estilos.campo}`}
        value={texto}
        onChange={(e) => setTexto(e.target.value)}
        placeholder={
          "Ex.: O cliente é carteiro dos Correios há 8 anos. Durante a entrega foi abordado por dois homens armados…"
        }
      />

      <div className={estilos.acoes}>
        <button
          type="button"
          className="botao botao--secundario"
          onClick={() => void analisar()}
          disabled={analisando || !texto.trim()}
        >
          {analisando ? "Analisando…" : "Analisar o relato"}
        </button>

        <button
          type="button"
          className="botao botao--discreto botao--pequeno"
          onClick={() => inputRef.current?.click()}
          disabled={analisando}
        >
          Enviar um arquivo .txt
        </button>

        <input
          ref={inputRef}
          type="file"
          accept=".txt,.md,text/plain"
          hidden
          onChange={(e) => {
            const f = e.target.files?.[0];
            if (f) void analisar(f);
            e.target.value = "";
          }}
        />

        {texto.trim() && <span className={estilos.contador}>{texto.trim().length} caracteres</span>}
      </div>

      {erro && (
        <div style={{ marginTop: 12 }}>
          <Aviso tom="critico" titulo="Não foi possível analisar">
            {erro}
          </Aviso>
        </div>
      )}

      {resultado && (
        <div className={estilos.resultado}>
          <Aviso
            tom={resultado.confiante ? "ok" : "atencao"}
            titulo={
              resultado.confiante
                ? "Sugestão com boa margem de acerto"
                : "Sugestão incerta — confira antes de aceitar"
            }
          >
            {resultado.motivo}
            {resultado.concorrentes && (
              <span className={estilos.nota}>
                O relato traz um quadro crônico e um acidente ao mesmo tempo. Pode ser mais de uma
                ação — vale abrir os dois casos.
              </span>
            )}
            {resultado.metodo === "pistas" && (
              <span className={estilos.nota}>
                A classificação saiu de termos encontrados no texto, sem a leitura por
                inteligência artificial, e por isso erra mais.
              </span>
            )}
          </Aviso>

          {resultado.sugestoes.length === 0 ? (
            <p className={estilos.vazio}>
              Nenhuma sugestão. Escolha o tipo de ação no campo abaixo.
            </p>
          ) : (
            <ul className={estilos.lista}>
              {resultado.sugestoes.map((s, i) => (
                <li key={s.codigo}>
                  <button
                    type="button"
                    className={`${estilos.opcao} ${escolhida === s.codigo ? estilos.escolhida : ""}`}
                    onClick={() => {
                      setEscolhida(s.codigo);
                      onEscolher(s.codigo, resultado.dados.cliente);
                    }}
                    aria-pressed={escolhida === s.codigo}
                  >
                    <span className={estilos.posicao}>{i + 1}º</span>
                    <span className={estilos.miolo}>
                      <span className={estilos.nome}>
                        {s.nome}
                        {escolhida === s.codigo && (
                          <Selo tom="ok" simbolo="✓">
                            escolhida
                          </Selo>
                        )}
                      </span>
                      {s.evidencias.slice(0, 2).map((ev, k) => (
                        <span key={k} className={estilos.evidencia}>
                          {ev}
                        </span>
                      ))}
                    </span>
                    <span className={estilos.pontos}>
                      {s.pontos} {s.pontos === 1 ? "ponto" : "pontos"}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      {(analisandoEstrategia || estrategia || erroEstrategia) && (
        <section className={estilos.insights} aria-live="polite">
          <div className={estilos.insightsCabecalho}>
            <span className={estilos.rotulo}>O que dizem processos semelhantes</span>
            {analisandoEstrategia && (
              <span className={estilos.carregando}>Buscando semelhantes…</span>
            )}
          </div>

          {erroEstrategia && !analisandoEstrategia && (
            <p className={estilos.avisoInsights}>{erroEstrategia}</p>
          )}

          {estrategia && (
            <>
              <p className={estilos.resumoInsights}>{estrategia.resumo}</p>

              <div className={estilos.metricas}>
                <div>
                  <strong>{estrategia.estatisticas.processos_analisados}</strong>
                  <span>processos semelhantes</span>
                </div>
                <div>
                  <strong>{estrategia.estatisticas.desfechos_merito.percentual}%</strong>
                  <span>procedente ou parcial entre casos julgados no mérito</span>
                </div>
              </div>

              {estrategia.estatisticas.resultados.length > 0 && (
                <div className={estilos.faixaDados}>
                  <h4>Desfechos na amostra</h4>
                  <p>{estrategia.estatisticas.resultados.map((i) => `${i.nome}: ${i.quantidade} (${i.percentual}%)`).join(" · ")}</p>
                </div>
              )}

              {estrategia.estatisticas.varas.length > 0 && (
                <div className={estilos.faixaDados}>
                  <h4>Varas mais presentes</h4>
                  <p>{estrategia.estatisticas.varas.slice(0, 4).map((i) => `${i.nome} (${i.quantidade})`).join(" · ")}</p>
                </div>
              )}

              {estrategia.estatisticas.magistrados.length > 0 && (
                <div className={estilos.faixaDados}>
                  <h4>Magistrados identificados nos documentos</h4>
                  <p>{estrategia.estatisticas.magistrados.slice(0, 4).map((i) => `${i.nome} (${i.quantidade})`).join(" · ")}</p>
                </div>
              )}

              <div className={estilos.colunasInsights}>
                <div>
                  <h4>Próximas ações sugeridas</h4>
                  <ul>{estrategia.acoes.map((item, i) => <li key={i}><strong>{item.acao} {item.forca && `· força ${item.forca}`}</strong><span>{item.porque} {item.aplicabilidade && ` Aplicável porque: ${item.aplicabilidade}`} {item.contrapontos && ` Contraponto: ${item.contrapontos}`} {item.precedentes.join(", ")}</span></li>)}</ul>
                </div>
                <div>
                  <h4>Riscos e pontos a confirmar</h4>
                  <ul>
                    {estrategia.riscos.map((item, i) => <li key={`r-${i}`}><strong>{item.risco} {item.forca && `· força ${item.forca}`}</strong><span>{item.aplicabilidade && `Aplicável porque: ${item.aplicabilidade}. `}{item.contrapontos && `Contraponto: ${item.contrapontos}. `}{item.precedentes.join(", ")}</span></li>)}
                    {estrategia.lacunas.map((item, i) => <li key={`l-${i}`}>{item}</li>)}
                  </ul>
                </div>
              </div>

              {!!estrategia.divergencias?.length && (
                <div className={estilos.faixaDados}>
                  <h4>Divergências entre os processos</h4>
                  <p>{estrategia.divergencias.map((d) => `${d.ponto} (favoráveis: ${d.precedentes_favoraveis.join(", ") || "—"}; contrários: ${d.precedentes_contrarios.join(", ") || "—"})`).join(" · ")}</p>
                </div>
              )}

              {!!estrategia.perguntas_criticas?.length && (
                <div className={estilos.faixaDados}>
                  <h4>Perguntas críticas para a entrevista</h4>
                  <p>{estrategia.perguntas_criticas.join(" · ")}</p>
                </div>
              )}

              <details className={estilos.precedentes}>
                <summary>Ver processos usados como referência</summary>
                <ul>{estrategia.precedentes.map((p) => <li key={p.indice}><strong>{p.indice}</strong> {p.processo || "processo não informado"} · {p.resultado || "sem desfecho"}{p.vara ? ` · ${p.vara}` : ""}</li>)}</ul>
              </details>
              <p className={estilos.notaEstatistica}>{estrategia.estatisticas.aviso} Similaridade mediana: {estrategia.estatisticas.similaridade_amostra.mediana}.</p>
            </>
          )}
        </section>
      )}
    </div>
  );
}
