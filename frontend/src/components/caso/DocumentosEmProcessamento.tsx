"use client";

import { useState } from "react";

import type { Entrega, ItemSituacao } from "@/lib/types";
import { Botao, Selo, Vazio } from "@/components/ui/Basicos";
import VisorEntrega from "@/components/caso/VisorEntrega";

interface Props {
  entregas: Entrega[];
  itens: ItemSituacao[];
}

function estadoDaAnalise(entrega: Entrega): { texto: string; tom: "info" | "atencao" } {
  if (entrega.analise_status === "REVISAO_NECESSARIA") {
    return { texto: "Aguardando conferência", tom: "atencao" };
  }
  if (entrega.status_proc === "na_fila" || entrega.analise_status === "NA_FILA") {
    return { texto: "Na fila", tom: "info" };
  }
  const etapa = entrega.analise_etapa?.replaceAll("_", " ");
  return { texto: etapa ? `Em ${etapa}` : "Em processamento", tom: "info" };
}

/** Arquivos acompanhados por entrega, inclusive os que ainda não têm item final. */
export default function DocumentosEmProcessamento({ entregas, itens }: Props) {
  const [visor, setVisor] = useState<{ id: string; arquivo: string } | null>(null);
  const porCodigo = new Map(itens.map((item) => [item.codigo, item.nome]));

  if (entregas.length === 0) {
    return <Vazio className="mt-4">Nenhum documento está em processamento agora.</Vazio>;
  }

  return (
    <div className="mt-4 border border-borda-forte rounded-cartao bg-papel shadow-cartao overflow-hidden">
      <p className="m-0 px-5 py-3 border-b border-borda bg-papel-2 text-tinta-2 text-sm leading-[1.5]">
        Acompanhe arquivos em leitura, validação, resumo ou aguardando sua conferência.
      </p>
      <ul className="m-0 p-0 list-none">
        {entregas.map((entrega) => {
          const estado = estadoDaAnalise(entrega);
          const destinos = entrega.itens_atendidos
            .map((codigo) => porCodigo.get(codigo) ?? codigo)
            .join(" · ") || "A identificar";
          return (
            <li key={entrega.id} className="flex items-center gap-3 flex-wrap px-5 py-4 border-b border-borda last:border-b-0">
              <Selo tom={estado.tom} simbolo={estado.tom === "atencao" ? "!" : "◌"}>{estado.texto}</Selo>
              <div className="flex-1 min-w-[220px]">
                <button
                  type="button"
                  className="block p-0 border-none bg-transparent text-acao font-codigo text-xs text-left underline underline-offset-2 cursor-pointer [overflow-wrap:anywhere]"
                  onClick={() => setVisor({ id: entrega.id, arquivo: entrega.arquivo })}
                >
                  {entrega.arquivo}
                </button>
                <span className="block mt-1 text-tinta-3 text-xs">Checklist: {destinos}</span>
              </div>
              <Botao variante="secundario" pequeno onClick={() => setVisor({ id: entrega.id, arquivo: entrega.arquivo })}>
                Acompanhar leitura
              </Botao>
            </li>
          );
        })}
      </ul>
      {visor && <VisorEntrega entregaId={visor.id} arquivo={visor.arquivo} onFechar={() => setVisor(null)} />}
    </div>
  );
}
