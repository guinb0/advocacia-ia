"use client";

import { useEffect, useState } from "react";

import estilos from "./ProgressoOcr.module.css";

/* A fila informa quando o job começou e terminou, mas ~95% do tempo fica numa
 * única chamada opaca ao PaddleOCR. Não há percentual interno verdadeiro.
 *
 * O que esta barra mostra de real é o tempo decorrido. O preenchimento é uma
 * estimativa que se aproxima de 92% de forma assintótica: desacelera conforme
 * passa da média e nunca chega a 100% antes de a resposta chegar, para não
 * afirmar que terminou quando não terminou. Ao passar de 1,6× a estimativa, o
 * texto assume que está demorando mais que o normal.
 *
 * Estimativas medidas nesta máquina com a CNH PDF usada no benchmark:
 *   modelo quente ~46s · aquecimento inicial ~29s, feito antes de consumir a fila
 */

const SEGUNDOS_QUENTE = 47;
const SEGUNDOS_FRIO = 76;
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
    setSegundos(0);
    if (naFila) return;
    const inicio = performance.now();
    const id = setInterval(() => setSegundos((performance.now() - inicio) / 1000), 200);
    return () => clearInterval(id);
  }, [naFila]);

  const estimativa = modeloPronto ? SEGUNDOS_QUENTE : SEGUNDOS_FRIO;
  const pct = naFila ? 18 : (1 - Math.exp(-segundos / (estimativa / 2))) * TETO;
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
        aria-valuetext={
          naFila
            ? "Documento aguardando na fila de leitura"
            : `Lendo o documento há ${Math.round(segundos)} segundos`
        }
      >
        <i className={estilos.preenchimento} style={{ width: `${pct.toFixed(1)}%` }} />
      </div>

      <div className={estilos.legenda}>
        <span className={demorando ? estilos.demorando : undefined}>
          {naFila
            ? "Na fila — o arquivo está seguro e será o próximo disponível"
            : demorando
              ? "Está demorando mais que o normal, mas continua lendo…"
              : modeloPronto
                ? "Lendo o documento…"
                : "Preparando a leitura e lendo (a primeira demora mais)…"}
        </span>
        {!naFila && <span className={estilos.tempo}>{segundos.toFixed(0)}s</span>}
      </div>
    </div>
  );
}
