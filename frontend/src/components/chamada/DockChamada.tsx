"use client";

import { useState } from "react";

import { useChamada } from "@/lib/ChamadaContexto";
import type { EstadoChamada } from "@/lib/chamadaJitsi";
import Retratos from "@/components/ui/Retratos";

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

/* Verde de "em chamada" e sua auréola: indicador de vida, não um estado do
 * design system (não é `--ok`) — por isso o hex fica fora de `globals.css`. */
const PONTO_ATIVO_ESTILO = { background: "#3fa46a", boxShadow: "0 0 0 3px rgba(63, 164, 106, 0.2)" };

const BOTAO_SECUNDARIO =
  "border-[1.5px] border-borda-campo bg-transparent text-tinta text-[10.5px] font-semibold leading-none " +
  "font-ui tracking-[0.06em] uppercase px-[10px] py-2 cursor-pointer hover:border-tinta hover:bg-tinta hover:text-papel";
const BOTAO_DESLIGAR =
  "border-[1.5px] border-critico bg-transparent text-critico text-[10.5px] font-semibold leading-none " +
  "font-ui tracking-[0.06em] uppercase px-[10px] py-2 cursor-pointer hover:bg-critico hover:text-papel";

export default function DockChamada() {
  const chamada = useChamada();
  const [aberto, setAberto] = useState(true);

  if (!chamada.mostrarDock) return null;

  const ponto =
    chamada.estado === "falando" ? (
      <i className="w-2 h-2 rounded-full flex-none" style={PONTO_ATIVO_ESTILO} />
    ) : chamada.estado === "encerrada" ? (
      <i className="w-2 h-2 rounded-full flex-none bg-tinta-3" />
    ) : (
      <i
        className="w-2 h-2 rounded-full flex-none bg-atencao animate-[pulsar_1.6s_ease-in-out_infinite] motion-reduce:animate-none"
      />
    );

  if (!aberto) {
    return (
      <button
        type="button"
        className="fixed right-5 bottom-5 z-[900] inline-flex items-center gap-2 bg-tinta text-papel border-none px-[14px] py-[10px] text-[10.5px] font-semibold leading-none font-ui tracking-[0.08em] uppercase cursor-pointer shadow-[0_8px_30px_rgba(20,32,46,0.22)]"
        onClick={() => setAberto(true)}
        aria-label="Abrir a chamada"
      >
        {ponto}
        {LEGENDA[chamada.estado]}
      </button>
    );
  }

  return (
    <aside
      className="fixed right-5 bottom-5 z-[900] w-[260px] max-w-[calc(100vw-40px)] bg-papel border border-borda-forte border-t-[3px] px-[14px] pt-3 pb-[14px] shadow-[0_8px_30px_rgba(20,32,46,0.18)]"
      style={{ borderTopColor: "var(--tinta)" }}
      aria-label="Chamada em andamento"
    >
      <div className="flex items-center justify-between gap-[10px] mb-[10px]">
        <span className="inline-flex items-center gap-[7px] text-[10px] font-semibold leading-none font-ui tracking-[0.1em] uppercase text-tinta-3">
          {ponto}
          {LEGENDA[chamada.estado]}
        </span>
        <button
          type="button"
          className="border border-borda-forte bg-transparent text-tinta text-[14px] font-semibold leading-none font-ui w-[22px] h-[22px] cursor-pointer hover:bg-tinta hover:text-papel"
          onClick={() => setAberto(false)}
          aria-label="Recolher"
        >
          –
        </button>
      </div>

      <Retratos participantes={chamada.participantes} tamanho="coluna" />

      {chamada.erro && (
        <p className="mt-2 mb-0 font-normal text-[11.5px] leading-[1.4] font-ui text-critico">
          {chamada.erro}
        </p>
      )}

      <div className="flex flex-wrap gap-2 mt-3">
        {/* A câmera só faz sentido para quem tem uma; o cliente no celular
            costuma ter, o escritório às vezes não. O botão vale para os dois. */}
        <button type="button" className={BOTAO_SECUNDARIO} onClick={() => void chamada.alternarCamera()}>
          {chamada.temCamera ? "Câmera off" : "Câmera"}
        </button>
        <button type="button" className={BOTAO_SECUNDARIO} onClick={chamada.alternarMudo}>
          {chamada.mudo ? "Reativar mic" : "Mudo"}
        </button>
        <button type="button" className={BOTAO_DESLIGAR} onClick={chamada.desligar}>
          Desligar
        </button>
      </div>
    </aside>
  );
}
