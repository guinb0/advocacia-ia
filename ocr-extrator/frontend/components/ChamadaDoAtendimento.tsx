"use client";

import { useEffect } from "react";

import { useChamada } from "@/lib/ChamadaContexto";
import type { EstadoChamada } from "@/lib/chamadaJitsi";
import estilos from "./ChamadaDoAtendimento.module.css";
import Retratos from "./Retratos";

/* A chamada DEPOIS da entrevista, no atendimento.
 *
 * A ligação já sobrevivia à troca de telas — ela vive no `ProvedorChamada`, na
 * raiz — mas seguia o atendente como uma pílula flutuante num canto. Aqui isso
 * não basta: esta é a tela do Google Meu Negócio, e o roteiro do escritório
 * manda, com todas as letras, PERMANECER na videoconferência enquanto o cliente
 * avalia ("eu permanecerei na videoconferência aguardando para confirmar que
 * deu tudo certo"). Uma instrução dessas ao lado de um canto discreto é uma
 * instrução que ninguém segue.
 *
 * Enquanto este painel está montado, o flutuante se recolhe (`registrarPainel`)
 * — a chamada não aparece duas vezes na mesma tela.
 *
 * Sem chamada de pé, não desenha nada: uma caixa vazia dizendo "chamada
 * desligada" ocuparia a tela do atendimento presencial, que é metade dos
 * casos. */

const LEGENDA: Record<EstadoChamada, string> = {
  fora: "chamada desligada",
  aguardando: "esperando o cliente",
  conectando: "conectando…",
  falando: "o cliente está na linha",
  encerrada: "chamada encerrada",
};

export default function ChamadaDoAtendimento() {
  const chamada = useChamada();

  // `registrarPainel` é estável, então roda uma vez. O retorno dele desfaz o
  // registro na saída — é isso que devolve a pílula flutuante ao atendente
  // quando ele sai desta tela.
  useEffect(() => chamada.registrarPainel(), [chamada.registrarPainel]);

  if (chamada.estado === "fora") return null;

  const encerrada = chamada.estado === "encerrada";

  return (
    <section className={estilos.bloco} aria-label="Chamada com o cliente">
      <div className={estilos.topo}>
        <span className={estilos.rotulo}>
          <i
            className={`${estilos.ponto} ${
              chamada.estado === "falando"
                ? estilos.pontoAtivo
                : encerrada
                  ? estilos.pontoOcioso
                  : estilos.pontoEsperando
            }`}
          />
          {LEGENDA[chamada.estado]}
        </span>
        {!encerrada && (
          <span className={estilos.aviso}>
            Não desligue até o cliente concluir a avaliação.
          </span>
        )}
      </div>

      <Retratos participantes={chamada.participantes} tamanho="coluna" />

      {chamada.erro && <p className={estilos.erro}>{chamada.erro}</p>}

      <div className={estilos.acoes}>
        <button
          type="button"
          className={estilos.secundario}
          onClick={() => void chamada.alternarCamera()}
        >
          {chamada.temCamera ? "Câmera off" : "Câmera"}
        </button>
        <button type="button" className={estilos.secundario} onClick={chamada.alternarMudo}>
          {chamada.mudo ? "Reativar mic" : "Mudo"}
        </button>
        {/* Desligar fica discreto de propósito: nesta tela ele é o botão
          * errado quase sempre — a etapa seguinte depende da chamada de pé. */}
        <button type="button" className={estilos.desligar} onClick={chamada.desligar}>
          desligar a chamada
        </button>
      </div>
    </section>
  );
}
