"use client";

import { useEffect, useState } from "react";

import estilos from "./ProgressoOcr.module.css";

/* O OCR roda inteiro dentro de um POST: o backend não reporta andamento, e ~95%
 * do tempo está numa única chamada opaca ao PaddleOCR. Então não há percentual
 * verdadeiro a exibir.
 *
 * O que esta barra mostra de real é o tempo decorrido. O preenchimento é uma
 * estimativa que se aproxima de 92% de forma assintótica: desacelera conforme
 * passa da média e nunca chega a 100% antes de a resposta chegar, para não
 * afirmar que terminou quando não terminou. Ao passar de 1,6× a estimativa, o
 * texto assume que está demorando mais que o normal.
 *
 * Estimativas medidas nesta máquina (CNH de 3000x4000):
 *   modelo quente ~10-14s · primeira leitura do processo ~25s (carrega o modelo)
 */

const SEGUNDOS_QUENTE = 13;
const SEGUNDOS_FRIO = 26;
const TETO = 92;

interface Props {
  /** O modelo já está carregado? Se não, a primeira leitura paga a carga. */
  modeloPronto?: boolean;
  /** Uploads são serializados numa thread só; avisa quem está esperando a vez. */
  naFila?: boolean;
}

export default function ProgressoOcr({ modeloPronto = true, naFila = false }: Props) {
  const [segundos, setSegundos] = useState(0);

  useEffect(() => {
    const inicio = performance.now();
    const id = setInterval(() => setSegundos((performance.now() - inicio) / 1000), 200);
    return () => clearInterval(id);
  }, []);

  const estimativa = modeloPronto ? SEGUNDOS_QUENTE : SEGUNDOS_FRIO;
  const pct = (1 - Math.exp(-segundos / (estimativa / 2))) * TETO;
  const demorando = segundos > estimativa * 1.6;

  return (
    <div className={estilos.bloco} role="status" aria-live="polite">
      <div
        className={estilos.barra}
        role="progressbar"
        aria-valuemin={0}
        aria-valuemax={100}
        // Sem valor: é estimativa, e anunciar "47%" a um leitor de tela seria
        // afirmar um progresso que não medimos.
        aria-valuetext={`Lendo o documento há ${Math.round(segundos)} segundos`}
      >
        <i className={estilos.preenchimento} style={{ width: `${pct.toFixed(1)}%` }} />
      </div>

      <div className={estilos.legenda}>
        <span className={demorando ? estilos.demorando : undefined}>
          {naFila
            ? "Na fila — o OCR lê um documento por vez"
            : demorando
              ? "Demorando mais que o normal…"
              : modeloPronto
                ? "Lendo o documento…"
                : "Carregando o modelo e lendo…"}
        </span>
        <span className={estilos.tempo}>{segundos.toFixed(0)}s</span>
      </div>
    </div>
  );
}
