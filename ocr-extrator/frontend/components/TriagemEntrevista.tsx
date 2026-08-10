"use client";

import { useRef, useState } from "react";

import { triarEntrevista } from "@/lib/api";
import type { Triagem } from "@/lib/types";
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
  const [resultado, setResultado] = useState<Triagem | null>(null);
  const [escolhida, setEscolhida] = useState<string | null>(null);
  const [analisando, setAnalisando] = useState(false);
  const [erro, setErro] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  async function analisar(arquivo?: File) {
    if (!arquivo && !texto.trim()) return;
    setAnalisando(true);
    setErro(null);
    setEscolhida(null);
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
    </div>
  );
}
