"use client";

/**
 * Relatório de follow-up: clientes com documento obrigatório pendente, com nome,
 * telefone, o que falta e o alerta de quando é preciso LIGAR (o WhatsApp
 * automático não está resolvendo). Retrato operacional para o atendimento —
 * não é ranking de cliente. Ver `carteira.relatorio_follow_up`.
 */

import { useCallback, useEffect, useState } from "react";

import { relatorioFollowUp, type RelatorioFollowUp } from "@/lib/api";
import { Aviso, Botao, Cartao, Selo, Vazio } from "@/components/ui/Basicos";

export default function FollowUp() {
  const [dados, setDados] = useState<RelatorioFollowUp | null>(null);
  const [carregando, setCarregando] = useState(true);
  const [erro, setErro] = useState<string | null>(null);
  const [soLigar, setSoLigar] = useState(false);

  const recarregar = useCallback(async () => {
    setCarregando(true);
    setErro(null);
    try {
      setDados(await relatorioFollowUp());
    } catch (e) {
      setErro(e instanceof Error ? e.message : "Não foi possível carregar o relatório.");
    } finally {
      setCarregando(false);
    }
  }, []);

  useEffect(() => {
    void recarregar();
  }, [recarregar]);

  const lista = (dados?.clientes ?? []).filter((c) => !soLigar || c.precisa_ligar);

  return (
    <Cartao
      titulo="Follow-up de documentos pendentes"
      subtitulo="Clientes com documento obrigatório em falta. O alerta de ligação aparece quando o follow-up por WhatsApp não está resolvendo."
    >
      {dados && (
        <div className="mb-4 flex flex-wrap items-center gap-3">
          <Indicador rotulo="Com pendência" valor={String(dados.total)} />
          <Indicador rotulo="Precisam de ligação" valor={String(dados.precisam_ligar)} destaque />
          <label className="ml-auto flex items-center gap-2 text-xs text-tinta-3 cursor-pointer">
            <input type="checkbox" checked={soLigar} onChange={(e) => setSoLigar(e.target.checked)} />
            só quem precisa ligar
          </label>
          <Botao variante="texto" pequeno onClick={() => void recarregar()}>Atualizar</Botao>
        </div>
      )}

      {dados?.regra && (
        <p className="mb-3 mt-0 text-[11px] leading-[1.5] text-tinta-3">
          <strong className="text-tinta-2">Quando liga:</strong> {dados.regra} {dados.aviso}
        </p>
      )}

      {erro ? (
        <Aviso tom="critico" titulo="Erro">{erro}</Aviso>
      ) : carregando && !dados ? (
        <Vazio>Carregando o relatório…</Vazio>
      ) : lista.length === 0 ? (
        <Vazio>Nenhum cliente com pendência {soLigar ? "que precise de ligação" : ""} agora.</Vazio>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full border-collapse text-sm">
            <thead>
              <tr className="border-b border-borda text-left text-[11px] uppercase tracking-wide text-tinta-3">
                <th className="py-2 pr-3 font-semibold">Cliente</th>
                <th className="py-2 pr-3 font-semibold">Telefone</th>
                <th className="py-2 pr-3 font-semibold">Documentos faltantes</th>
                <th className="py-2 pr-3 font-semibold">Parado</th>
                <th className="py-2 pr-3 font-semibold">Ligação</th>
              </tr>
            </thead>
            <tbody>
              {lista.map((c) => (
                <tr
                  key={c.caso_id}
                  className={`border-b border-borda align-top ${c.precisa_ligar ? "bg-atencao-claro" : ""}`}
                >
                  <td className="py-2 pr-3 text-tinta">{c.cliente || "—"}</td>
                  <td className="py-2 pr-3 tabular-nums text-tinta-2">
                    {c.telefone || <span className="text-critico">sem telefone</span>}
                  </td>
                  <td className="py-2 pr-3 text-tinta-2 [overflow-wrap:anywhere]">
                    <span className="text-tinta-3">{c.faltantes_total}: </span>
                    {c.documentos_faltantes.slice(0, 6).join(", ")}
                    {c.documentos_faltantes.length > 6 ? "…" : ""}
                  </td>
                  <td className="py-2 pr-3 tabular-nums text-tinta-3">{c.dias_parado}d</td>
                  <td className="py-2 pr-3">
                    {c.precisa_ligar ? (
                      <span className="grid gap-1">
                        <Selo tom="critico" simbolo="!">LIGAR</Selo>
                        <span className="text-[11px] leading-[1.4] text-tinta-3">{c.motivo_ligacao}</span>
                      </span>
                    ) : (
                      <Selo tom={c.follow_up_ativo ? "ok" : "neutro"}>
                        {c.follow_up_ativo ? "follow-up ativo" : "no prazo"}
                      </Selo>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Cartao>
  );
}

function Indicador({ rotulo, valor, destaque }: { rotulo: string; valor: string; destaque?: boolean }) {
  return (
    <div className={`rounded-campo border p-3 ${destaque ? "border-atencao bg-atencao-claro" : "border-borda-forte bg-papel"}`}>
      <strong className="block text-[1.4rem] leading-none tabular-nums text-tinta">{valor}</strong>
      <span className="text-xs text-tinta-3">{rotulo}</span>
    </div>
  );
}
