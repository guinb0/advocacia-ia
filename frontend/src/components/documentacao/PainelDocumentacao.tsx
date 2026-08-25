"use client";

import { useCallback, useEffect, useState } from "react";

import { assumirAtendimentoDocumentacao, criarSalaChamada, listarAtendimentosDocumentacao, registrarPresencaDocumentacao } from "@/lib/api";
import type { AtendimentoDocumentacao } from "@/lib/api";
import { useChamada } from "@/lib/ChamadaContexto";
import { useSessao } from "@/lib/auth";

export default function PainelDocumentacao({ onVoltar }: { onVoltar: () => void }) {
  const [itens, setItens] = useState<AtendimentoDocumentacao[]>([]);
  const [ativas, setAtivas] = useState(0);
  const [solicitacoes, setSolicitacoes] = useState(0);
  const [online, setOnline] = useState(0);
  const [erro, setErro] = useState<string | null>(null);
  const [assumindo, setAssumindo] = useState<string | null>(null);
  const chamada = useChamada();
  const sessao = useSessao();

  const carregar = useCallback(() => {
    void listarAtendimentosDocumentacao()
      .then((r) => { setItens(r.atendimentos); setAtivas(r.entrevistas_ativas); setSolicitacoes(r.solicitacoes); setOnline(r.documentadores_online); setErro(null); })
      .catch((e) => setErro(e instanceof Error ? e.message : "Não foi possível atualizar a fila."));
  }, []);

  useEffect(() => {
    const marcar = () => void registrarPresencaDocumentacao().catch(() => undefined);
    marcar();
    carregar();
    const id = window.setInterval(carregar, 5_000);
    const presenca = window.setInterval(marcar, 30_000);
    return () => { window.clearInterval(id); window.clearInterval(presenca); };
  }, [carregar]);

  async function assumir(item: AtendimentoDocumentacao) {
    if (!item.sala) return;
    setAssumindo(item.entrevista_id);
    setErro(null);
    try {
      const reservado = await assumirAtendimentoDocumentacao(item.entrevista_id);
      const { token } = await criarSalaChamada(reservado.sala!);
      await chamada.entrar(reservado.sala!, "advogado", {
        nome: `Documentação · ${sessao.nome || "Atendente"}`,
        camera: false,
      }, token);
      carregar();
    } catch (e) {
      setErro(e instanceof Error ? e.message : "Não foi possível assumir a chamada.");
    } finally {
      setAssumindo(null);
    }
  }

  return (
    <main className="max-w-[1180px] mx-auto px-7 pt-6 pb-16">
      <button type="button" onClick={onVoltar} className="text-xs text-acao bg-transparent border-0 cursor-pointer">← Carteira</button>
      <h1 className="mt-3 mb-1 text-2xl">Departamento de Documentação</h1>
      <p className="mt-0 text-tinta-3">Acompanhe as entrevistas e assuma a mesma chamada quando o entrevistador solicitar.</p>

      <div className="grid grid-cols-3 max-[620px]:grid-cols-1 max-w-[760px] gap-3 my-5">
        <div className="border border-borda bg-papel-2 p-4"><strong className="block text-3xl">{ativas}</strong><span className="text-xs text-tinta-3">entrevistas acontecendo</span></div>
        <div className="border border-acao-borda bg-acao-clara p-4"><strong className="block text-3xl text-acao">{solicitacoes}</strong><span className="text-xs text-tinta-3">pedindo documentação</span></div>
        <div className="border border-borda bg-papel-2 p-4"><strong className="block text-3xl text-ok">{online}</strong><span className="text-xs text-tinta-3">documentadores online</span></div>
      </div>

      {erro && <p className="border-l-4 border-critico bg-critico-claro p-3 text-sm">{erro}</p>}
      <div className="grid gap-3">
        {itens.map((item) => (
          <article key={item.entrevista_id} className={`border p-4 ${item.status === "solicitado" ? "border-acao bg-acao-clara" : "border-borda bg-papel"}`}>
            <div className="flex justify-between gap-4 flex-wrap">
              <div>
                <strong className="block">{item.cliente || "Cliente ainda não identificado"}</strong>
                <span className="text-xs text-tinta-3">Entrevistador: {item.entrevistador_nome}</span>
              </div>
              <span className="text-[10px] uppercase tracking-wider text-tinta-3">
                {item.status === "solicitado" ? "aguardando documentador" : item.status === "assumido" ? `assumido por ${item.documentador_nome}` : "entrevista em andamento"}
              </span>
            </div>
            {item.status === "solicitado" && (
              <button type="button" onClick={() => void assumir(item)} disabled={assumindo !== null}
                className="mt-3 border border-acao bg-acao text-papel px-4 py-2 text-xs font-bold uppercase tracking-wider cursor-pointer disabled:opacity-50">
                {assumindo === item.entrevista_id ? "Entrando na chamada…" : "Assumir chamada"}
              </button>
            )}
          </article>
        ))}
        {itens.length === 0 && <p className="border border-dashed border-borda p-8 text-center text-tinta-3">Nenhuma entrevista ativa agora.</p>}
      </div>
    </main>
  );
}
