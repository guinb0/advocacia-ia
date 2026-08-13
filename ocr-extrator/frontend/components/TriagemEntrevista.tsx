"use client";

import { useRef, useState } from "react";

import { analisarEstrategia, triarEntrevista } from "@/lib/api";
import type { Estrategia, Triagem } from "@/lib/types";
import EntrevistaComChamada from "./EntrevistaComChamada";
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
}: {
  /** Aplica a categoria (e o nome do cliente, se a entrevista trouxer). */
  onEscolher: (categoria: string, cliente?: string) => void;
}) {
  const [texto, setTexto] = useState("");
  const [mostrarRoteiro, setMostrarRoteiro] = useState(false);
  /* A qualificação fica guardada depois que a entrevista fecha: é ela que
   * preenche o contrato, e o relato corrido já não a tem em campos separados. */
  const [qualificacao, setQualificacao] = useState<Record<string, string | string[]> | null>(
    null,
  );
  const [resultado, setResultado] = useState<Triagem | null>(null);
  const [escolhida, setEscolhida] = useState<string | null>(null);
  const [analisando, setAnalisando] = useState(false);
  const [analisandoEstrategia, setAnalisandoEstrategia] = useState(false);
  const [estrategia, setEstrategia] = useState<Estrategia | null>(null);
  const [erroEstrategia, setErroEstrategia] = useState<string | null>(null);
  const [erro, setErro] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

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
          onConcluir={(respostas, relato) => {
            setTexto(relato);
            setQualificacao(respostas);
            setMostrarRoteiro(false);
          }}
          onFechar={() => setMostrarRoteiro(false)}
        />
      ) : (
        <button
          type="button"
          className={estilos.arquivo}
          onClick={() => setMostrarRoteiro(true)}
          style={{ marginBottom: 14 }}
        >
          {qualificacao ? "Voltar ao roteiro" : "Conduzir entrevista guiada"}
        </button>
      )}

      {/* Entrevista, contrato, documentos — nesta ordem, que é a do escritório. */}
      {qualificacao && !mostrarRoteiro && <PainelContrato respostas={qualificacao} />}

      <span className={estilos.rotulo}>TRIAGEM PELA ENTREVISTA</span>
      <p className={estilos.texto}>
        Cole o relato da entrevista ou envie um <code>.txt</code>. O sistema sugere a
        categoria e mostra o que no texto levou a ela — a escolha final é sua.
      </p>

      <textarea
        className={estilos.campo}
        value={texto}
        onChange={(e) => setTexto(e.target.value)}
        placeholder={
          "Ex.: O cliente é carteiro dos Correios há 8 anos. Durante a entrega foi abordado por dois homens armados…"
        }
        aria-label="Texto da entrevista"
      />

      <div className={estilos.acoes}>
        <button
          type="button"
          className={estilos.botao}
          onClick={() => void analisar()}
          disabled={analisando || !texto.trim()}
        >
          {analisando ? "Analisando…" : "Analisar entrevista"}
        </button>

        <button
          type="button"
          className={estilos.arquivo}
          onClick={() => inputRef.current?.click()}
          disabled={analisando}
        >
          Enviar .txt
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

      {erro && <div className={estilos.erro}>{erro}</div>}

      {resultado && (
        <div className={estilos.resultado}>
          <div
            className={`${estilos.veredito} ${resultado.confiante ? estilos.confiante : estilos.conferir}`}
          >
            {resultado.motivo}
            {resultado.concorrentes && (
              <span className={estilos.metodo}>
                Atenção: há um quadro crônico e um acidente no mesmo relato. Pode ser
                mais de uma ação — vale abrir os dois casos.
              </span>
            )}
            {resultado.metodo === "pistas" && (
              <span className={estilos.metodo}>
                Classificado por termos locais — o modelo de leitura não respondeu.
              </span>
            )}
          </div>

          {resultado.sugestoes.length === 0 ? (
            <p className={estilos.vazio}>
              Escolha a categoria manualmente no campo abaixo.
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
                  >
                    <span className={estilos.posicao}>{i + 1}º</span>
                    <span className={estilos.miolo}>
                      <span className={estilos.nome}>{s.nome}</span>
                      {s.evidencias.slice(0, 2).map((ev, k) => (
                        <span key={k} className={estilos.evidencia}>
                          {ev}
                        </span>
                      ))}
                    </span>
                    <span className={estilos.pontos}>{s.pontos} pts</span>
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
            <span className={estilos.rotulo}>INSIGHTS DOS PROCESSOS</span>
            {analisandoEstrategia && <span className={estilos.carregando}>Buscando semelhantes…</span>}
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
                  <strong>{estrategia.estatisticas.desfechos_favoraveis_amplos.percentual}%</strong>
                  <span>procedente, parcial ou acordo na amostra</span>
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
                  <ul>{estrategia.acoes.map((item, i) => <li key={i}><strong>{item.acao}</strong><span>{item.porque} {item.precedentes.join(", ")}</span></li>)}</ul>
                </div>
                <div>
                  <h4>Riscos e pontos a confirmar</h4>
                  <ul>
                    {estrategia.riscos.map((item, i) => <li key={`r-${i}`}>{item.risco} {item.precedentes.join(", ")}</li>)}
                    {estrategia.lacunas.map((item, i) => <li key={`l-${i}`}>{item}</li>)}
                  </ul>
                </div>
              </div>

              <details className={estilos.precedentes}>
                <summary>Ver processos usados como referência</summary>
                <ul>{estrategia.precedentes.map((p) => <li key={p.indice}><strong>{p.indice}</strong> {p.processo || "processo não informado"} · {p.resultado || "sem desfecho"}{p.vara ? ` · ${p.vara}` : ""}</li>)}</ul>
              </details>
              <p className={estilos.notaEstatistica}>{estrategia.estatisticas.aviso}</p>
            </>
          )}
        </section>
      )}
    </div>
  );
}
