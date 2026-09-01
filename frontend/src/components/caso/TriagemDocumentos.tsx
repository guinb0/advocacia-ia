"use client";

import { useState } from "react";

import type { Entrega, ItemSituacao } from "@/lib/types";
import { Aviso, Botao, Selo } from "@/components/ui/Basicos";
import VisorEntrega from "@/components/caso/VisorEntrega";

interface Props {
  entregas: Entrega[];
  itens: ItemSituacao[];
  onAtribuir: (entregaId: string, itens: string[]) => Promise<void> | void;
  onRemover: (entregaId: string) => void;
}

export default function TriagemDocumentos({ entregas, itens, onAtribuir, onRemover }: Props) {
  const [destinos, setDestinos] = useState<Record<string, string>>({});
  const [salvando, setSalvando] = useState<string | null>(null);
  const [visor, setVisor] = useState<{ id: string; arquivo: string } | null>(null);

  if (entregas.length === 0) return null;

  async function atribuir(entrega: Entrega) {
    const destino = destinos[entrega.id];
    if (!destino) return;
    setSalvando(entrega.id);
    try {
      await onAtribuir(entrega.id, [destino]);
    } finally {
      setSalvando(null);
    }
  }

  return (
    <section className="mt-5 border border-atencao-borda rounded-cartao bg-atencao-claro overflow-hidden">
      <div className="px-5 py-4 border-b border-atencao-borda">
        <h2 className="flex gap-2 items-center m-0 text-tinta font-titulo text-lg font-semibold">
          Documentos para identificar <Selo tom="atencao">{entregas.length}</Selo>
        </h2>
        <p className="mt-1 mb-0 text-tinta-2 text-sm leading-[1.55]">
          O arquivo foi preservado, mas a leitura não encontrou um destino seguro. Confira e escolha
          o item correto; não é necessário enviar novamente.
        </p>
      </div>
      <ul className="m-0 p-0 list-none bg-papel">
        {entregas.map((entrega) => {
          const lendo = entrega.status_proc === "na_fila" || entrega.status_proc === "processando";
          return (
            <li key={entrega.id} className="px-5 py-4 border-b border-borda last:border-b-0">
              <div className="flex items-center gap-3 flex-wrap">
                <Selo tom={lendo ? "info" : entrega.status_proc === "erro" ? "critico" : "atencao"}>
                  {lendo ? "Lendo…" : entrega.status_proc === "erro" ? "Falha na leitura" : "Sem destino"}
                </Selo>
                <button
                  type="button"
                  className="flex-1 min-w-[180px] border-none bg-transparent text-acao font-codigo text-xs text-left underline underline-offset-2 cursor-pointer [overflow-wrap:anywhere]"
                  onClick={() => setVisor({ id: entrega.id, arquivo: entrega.arquivo })}
                >
                  {entrega.arquivo}
                </button>
                <Botao variante="secundario" pequeno onClick={() => setVisor({ id: entrega.id, arquivo: entrega.arquivo })}>
                  Abrir documento
                </Botao>
              </div>

              {entrega.alertas?.map((alerta, indice) => (
                <div className="mt-3" key={indice}>
                  <Aviso tom={entrega.status_proc === "erro" ? "critico" : "atencao"}>{alerta}</Aviso>
                </div>
              ))}

              {!lendo && (
                <div className="flex gap-2 items-end mt-3 flex-wrap">
                  <label className="flex-1 min-w-[240px] text-xs text-tinta-3">
                    Item correto do checklist
                    <select
                      className="block w-full min-h-10 mt-1 px-3 border border-borda-campo rounded-campo bg-papel text-tinta text-sm"
                      value={destinos[entrega.id] ?? ""}
                      onChange={(evento) => setDestinos((atual) => ({ ...atual, [entrega.id]: evento.target.value }))}
                    >
                      <option value="">Escolha o documento…</option>
                      {itens.map((item) => (
                        <option key={item.codigo} value={item.codigo}>{item.nome} ({item.codigo})</option>
                      ))}
                    </select>
                  </label>
                  <Botao
                    variante="primario"
                    onClick={() => void atribuir(entrega)}
                    disabled={!destinos[entrega.id] || salvando === entrega.id}
                  >
                    {salvando === entrega.id ? "Atribuindo…" : "Atribuir ao item"}
                  </Botao>
                  <Botao variante="perigo" onClick={() => onRemover(entrega.id)}>Remover</Botao>
                </div>
              )}
            </li>
          );
        })}
      </ul>
      {visor && <VisorEntrega entregaId={visor.id} arquivo={visor.arquivo} onFechar={() => setVisor(null)} />}
    </section>
  );
}
