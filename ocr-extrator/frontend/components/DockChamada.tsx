"use client";

import { useState } from "react";

import { useChamada } from "@/lib/ChamadaContexto";
import type { EstadoChamada } from "@/lib/chamadaJitsi";
import Retratos from "./Retratos";
import estilos from "./DockChamada.module.css";

/* O painel flutuante da chamada — o que faz a ligação SEGUIR o usuário.
 *
 * Aparece num canto quando há chamada de pé e nenhuma tela já a mostra por
 * inteiro (`mostrarDock`). É o que sustenta "a chamada permanece": ao sair da
 * entrevista para o checklist, ou ao trocar de tela, a conversa não cai — ela
 * encolhe para cá e continua, com os controles à mão.
 *
 * Fica na raiz do app (`app/layout.tsx`), então vale para o escritório e para o
 * cliente. Recolhido, é uma pílula; aberto, traz os retratos e os controles. */

const LEGENDA: Record<EstadoChamada, string> = {
  fora: "fora da chamada",
  aguardando: "esperando o outro lado",
  conectando: "conectando…",
  falando: "em chamada",
  encerrada: "chamada encerrada",
};

export default function DockChamada() {
  const chamada = useChamada();
  const [aberto, setAberto] = useState(true);

  if (!chamada.mostrarDock) return null;

  const pontoAtivo =
    chamada.estado === "falando"
      ? estilos.pontoAtivo
      : chamada.estado === "encerrada"
        ? estilos.pontoOcioso
        : estilos.pontoEsperando;

  if (!aberto) {
    return (
      <button
        type="button"
        className={estilos.pilula}
        onClick={() => setAberto(true)}
        aria-label="Abrir a chamada"
      >
        <i className={`${estilos.ponto} ${pontoAtivo}`} />
        {LEGENDA[chamada.estado]}
      </button>
    );
  }

  return (
    <aside className={estilos.dock} aria-label="Chamada em andamento">
      <div className={estilos.topo}>
        <span className={estilos.rotulo}>
          <i className={`${estilos.ponto} ${pontoAtivo}`} />
          {LEGENDA[chamada.estado]}
        </span>
        <button
          type="button"
          className={estilos.recolher}
          onClick={() => setAberto(false)}
          aria-label="Recolher"
        >
          –
        </button>
      </div>

      <Retratos participantes={chamada.participantes} tamanho="coluna" />

      {chamada.erro && <p className={estilos.erro}>{chamada.erro}</p>}

      <div className={estilos.acoes}>
        {/* A câmera só faz sentido para quem tem uma; o cliente no celular
            costuma ter, o escritório às vezes não. O botão vale para os dois. */}
        <button
          type="button"
          className={estilos.secundario}
          onClick={() => void chamada.alternarCamera()}
        >
          {chamada.temCamera ? "Câmera off" : "Câmera"}
        </button>
        <button
          type="button"
          className={estilos.secundario}
          onClick={chamada.alternarMudo}
        >
          {chamada.mudo ? "Reativar mic" : "Mudo"}
        </button>
        <button type="button" className={estilos.desligar} onClick={chamada.desligar}>
          Desligar
        </button>
      </div>
    </aside>
  );
}
