"use client";

import { useEffect } from "react";

import { useChamada } from "@/lib/ChamadaContexto";
import type { EstadoChamada } from "@/lib/chamadaJitsi";
import Retratos from "@/components/ui/Retratos";

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

const PONTO_ATIVO_ESTILO = { background: "#3fa46a", boxShadow: "0 0 0 3px rgba(63, 164, 106, 0.2)" };

export default function ChamadaDoAtendimento() {
  const chamada = useChamada();

  // `registrarPainel` é estável, então roda uma vez. O retorno dele desfaz o
  // registro na saída — é isso que devolve a pílula flutuante ao atendente
  // quando ele sai desta tela.
  useEffect(() => chamada.registrarPainel(), [chamada.registrarPainel]);

  if (chamada.estado === "fora") return null;

  const encerrada = chamada.estado === "encerrada";

  return (
    <section
      className="my-[18px] border border-borda-forte border-t-[3px] px-[15px] pt-[13px] pb-[15px] bg-papel"
      style={{ borderTopColor: "var(--tinta)" }}
      aria-label="Chamada com o cliente"
    >
      <div className="flex items-baseline justify-between flex-wrap gap-2 mb-[11px]">
        <span className="inline-flex items-center gap-[7px] text-[10px] font-semibold leading-none font-ui tracking-[0.1em] uppercase text-tinta-3">
          {chamada.estado === "falando" ? (
            <i className="w-2 h-2 rounded-full flex-none" style={PONTO_ATIVO_ESTILO} />
          ) : encerrada ? (
            <i className="w-2 h-2 rounded-full flex-none bg-tinta-3" />
          ) : (
            <i className="w-2 h-2 rounded-full flex-none bg-atencao animate-[pulsar_1.6s_ease-in-out_infinite] motion-reduce:animate-none" />
          )}
          {LEGENDA[chamada.estado]}
        </span>
        {/* O recado que justifica a chamada estar aqui. Em âmbar e não em
            vermelho: não é erro, é a ordem do roteiro — desligar agora custa
            a avaliação. */}
        {!encerrada && (
          <span className="font-semibold text-[11px] leading-[1.4] font-ui text-atencao">
            Não desligue até o cliente concluir a avaliação.
          </span>
        )}
      </div>

      <Retratos participantes={chamada.participantes} tamanho="coluna" />

      {chamada.erro && (
        <p className="mt-[9px] mb-0 font-normal text-[11.5px] leading-[1.45] font-ui text-critico">
          {chamada.erro}
        </p>
      )}

      <div className="flex items-center flex-wrap gap-[9px] mt-3">
        {/* `.secundario` original usava `var(--border-campo)`, uma variável que
         * nunca existiu em globals.css (nem atual nem apelido) e sem fallback
         * — o botão nunca teve borda visível, apesar do comentário original
         * dizer "mesma linguagem do painel flutuante" (DockChamada, que TEM
         * borda). Provável bug — mantido igual (paridade visual), sinalizado
         * aqui em vez de corrigido em silêncio. */}
        <button
          type="button"
          className="bg-transparent text-tinta text-[10.5px] font-semibold leading-none font-ui tracking-[0.06em] uppercase px-[11px] py-2 cursor-pointer hover:bg-tinta hover:text-papel"
          onClick={() => void chamada.alternarCamera()}
        >
          {chamada.temCamera ? "Câmera off" : "Câmera"}
        </button>
        <button
          type="button"
          className="bg-transparent text-tinta text-[10.5px] font-semibold leading-none font-ui tracking-[0.06em] uppercase px-[11px] py-2 cursor-pointer hover:bg-tinta hover:text-papel"
          onClick={chamada.alternarMudo}
        >
          {chamada.mudo ? "Reativar mic" : "Mudo"}
        </button>
        {/* Desligar fica discreto de propósito: nesta tela ele é o botão
          * errado quase sempre — a etapa seguinte depende da chamada de pé. */}
        <button
          type="button"
          className="border-none bg-transparent p-0 ml-auto text-tinta-3 font-normal text-[11px] leading-none font-ui underline underline-offset-[3px] cursor-pointer hover:text-critico"
          onClick={chamada.desligar}
        >
          desligar a chamada
        </button>
      </div>
    </section>
  );
}
