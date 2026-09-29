"use client";

import { useEffect, useState } from "react";

/* O OCR roda inteiro dentro de um POST: o backend não reporta andamento, e ~95%
 * do tempo está numa única chamada opaca à API de OCR. Então não há percentual
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

  /* O relógio corre nos DOIS estados. Antes ele parava na fila, e o resultado
   * era uma barra congelada em 18% sem contador nenhum: uma espera de segundos e
   * uma de horas — com o leitor de documentos fora do ar — desenhavam a mesma
   * tela. O tempo decorrido é o único sinal honesto que esta barra tem; escondê-lo
   * justo quando a espera é anormal é escondê-lo quando ele importa. */
  useEffect(() => {
    setSegundos(0);
    const inicio = performance.now();
    const id = setInterval(() => setSegundos((performance.now() - inicio) / 1000), 200);
    return () => clearInterval(id);
  }, [naFila]);

  const estimativa = modeloPronto ? SEGUNDOS_QUENTE : SEGUNDOS_FRIO;
  const pct = naFila ? 18 : (1 - Math.exp(-segundos / (estimativa / 2))) * TETO;
  /* Na fila a paciência é outra: esperar a vez atrás de outro documento é normal,
   * e o alerta do servidor (`casos._esperando_ha_muito`) é quem diz que passou do
   * ponto. Aqui basta parar de fingir tranquilidade depois de um minuto. */
  const demorando = naFila ? segundos > 60 : segundos > estimativa * 1.6;

  return (
    <div className="flex flex-col gap-[6px] mt-[10px] mr-0 mb-1 ml-9 max-w-[460px]" role="status" aria-live="polite">
      <div
        className="h-2 rounded-pill bg-papel-3 overflow-hidden"
        role="progressbar"
        aria-valuemin={0}
        aria-valuemax={100}
        // Sem valor: é estimativa, e anunciar "47%" a um leitor de tela seria
        // afirmar um progresso que não medimos.
        aria-valuetext={
          naFila
            ? `Documento aguardando na fila de leitura há ${Math.round(segundos)} segundos`
            : `Lendo o documento há ${Math.round(segundos)} segundos`
        }
      >
        <i
          className="block h-full rounded-pill bg-acao transition-[width] duration-200 ease-linear"
          style={{ width: `${pct.toFixed(1)}%` }}
        />
      </div>

      <div className="flex justify-between gap-3 text-tinta-2 text-xs">
        <span className={demorando ? "text-atencao font-semibold" : undefined}>
          {naFila
            ? demorando
              ? "A fila não está andando — o sistema tenta de novo sozinho"
              : "Na fila — o sistema lê um documento por vez"
            : demorando
              ? "Está demorando mais que o normal, mas continua lendo…"
              : modeloPronto
                ? "Lendo o documento…"
                : "Preparando a leitura e lendo (a primeira demora mais)…"}
        </span>
        <span className="text-tinta-3 font-codigo tabular-nums">{segundos.toFixed(0)}s</span>
      </div>
    </div>
  );
}
