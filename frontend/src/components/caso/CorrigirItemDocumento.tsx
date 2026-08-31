"use client";

import { useState } from "react";

import type { ItemSituacao } from "@/lib/types";
import { Botao } from "@/components/ui/Basicos";

interface Props {
  entregaId: string;
  itemAtual: string;
  itens: ItemSituacao[];
  onReatribuir: (entregaId: string, itens: string[]) => Promise<void> | void;
  /** Destaque quando a leitura automática encaminhou o arquivo. */
  destacar?: boolean;
  /** Abre o painel de movimentação de cara — útil na coleta documental. */
  expandidoPorPadrao?: boolean;
  rotulo?: string;
}

/** Move um documento já lido para outro item — ou devolve à triagem. */
export default function CorrigirItemDocumento({
  entregaId,
  itemAtual,
  itens,
  onReatribuir,
  destacar = false,
  expandidoPorPadrao = false,
  rotulo = "Corrigir classificação",
}: Props) {
  const [aberto, setAberto] = useState(destacar || expandidoPorPadrao);
  const [destino, setDestino] = useState("");
  const [salvando, setSalvando] = useState(false);

  if (!aberto) {
    return (
      <Botao
        variante={destacar ? "secundario" : "discreto"}
        pequeno
        onClick={() => setAberto(true)}
        title="Corrigir o tipo identificado automaticamente"
      >
        {rotulo}
      </Botao>
    );
  }

  async function aplicar(novoDestino: string | null) {
    setSalvando(true);
    try {
      await onReatribuir(entregaId, novoDestino ? [novoDestino] : []);
      setAberto(false);
      setDestino("");
    } finally {
      setSalvando(false);
    }
  }

  const opcoes = itens.filter((item) => item.codigo !== itemAtual);

  return (
    <div className="[flex-basis:100%] mt-2 p-3 border border-borda rounded-campo bg-papel">
      <p className="m-0 mb-2 text-tinta-2 text-xs leading-[1.5]">
        A classificação automática pode errar. Escolha o tipo correto: o checklist será
        ajustado, a sugestão original ficará no histórico e esta correção ajudará nas próximas leituras.
      </p>
      <div className="flex gap-2 items-end flex-wrap">
        <label className="flex-1 min-w-[220px] text-xs text-tinta-3">
          Tipo correto do documento
          <select
            className="block w-full min-h-10 mt-1 px-3 border border-borda-campo rounded-campo bg-papel text-tinta text-sm"
            value={destino}
            disabled={salvando}
            onChange={(evento) => setDestino(evento.target.value)}
          >
            <option value="">Escolha o documento…</option>
            {opcoes.map((item) => (
              <option key={item.codigo} value={item.codigo}>
                {item.nome} ({item.codigo})
              </option>
            ))}
          </select>
        </label>
        <Botao
          variante="primario"
          pequeno
          disabled={!destino || salvando}
          onClick={() => void aplicar(destino)}
        >
          {salvando ? "Salvando…" : "Salvar classificação"}
        </Botao>
        <Botao variante="secundario" pequeno disabled={salvando} onClick={() => void aplicar(null)}>
          Devolver à triagem
        </Botao>
        <Botao variante="texto" pequeno disabled={salvando} onClick={() => setAberto(false)}>
          Cancelar
        </Botao>
      </div>
    </div>
  );
}
