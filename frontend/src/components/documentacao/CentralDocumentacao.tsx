"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { assumirAtendimentoDocumentacao, criarSalaChamada, listarAtendimentosDocumentacao, registrarPresencaDocumentacao } from "@/lib/api";
import type { AtendimentoDocumentacao } from "@/lib/api";
import { useChamada } from "@/lib/ChamadaContexto";
import { useSessao } from "@/lib/auth";

interface Props { onVoltar: () => void; onAbrirDocumentos: (casoId: string) => void; }

export default function CentralDocumentacao({ onVoltar, onAbrirDocumentos }: Props) {
  const [fila, setFila] = useState<AtendimentoDocumentacao[]>([]);
  const [metricas, setMetricas] = useState({ ativas: 0, solicitacoes: 0, online: 0 });
  const [alerta, setAlerta] = useState<AtendimentoDocumentacao | null>(null);
  const [erro, setErro] = useState<string | null>(null);
  const [assumindo, setAssumindo] = useState<string | null>(null);
  const [permissao, setPermissao] = useState<NotificationPermission | "indisponivel">(
    typeof window !== "undefined" && "Notification" in window ? Notification.permission : "indisponivel",
  );
  const vistas = useRef(new Set<string>());
  const chamada = useChamada();
  const sessao = useSessao();

  const avisar = useCallback((item: AtendimentoDocumentacao) => {
    setAlerta(item);
    document.title = `🔔 ${item.cliente || "Cliente"} precisa da Documentação`;
    try {
      const audio = new AudioContext(); const som = audio.createOscillator(); const volume = audio.createGain();
      som.frequency.value = 880; volume.gain.setValueAtTime(0.12, audio.currentTime);
      volume.gain.exponentialRampToValueAtTime(0.001, audio.currentTime + 0.45);
      som.connect(volume).connect(audio.destination); som.start(); som.stop(audio.currentTime + 0.45);
    } catch { /* O alerta visual continua quando o navegador bloqueia o som. */ }
    if ("Notification" in window && Notification.permission === "granted") {
      const aviso = new Notification("Documentação solicitada", {
        body: `${item.entrevistador_nome} pediu sua presença para atender ${item.cliente || "o cliente"}.`,
        tag: `documentacao-${item.entrevista_id}`, requireInteraction: true,
      });
      aviso.onclick = () => { window.focus(); aviso.close(); };
    }
  }, []);

  const carregar = useCallback(() => {
    void listarAtendimentosDocumentacao().then((r) => {
      setFila(r.atendimentos);
      setMetricas({ ativas: r.entrevistas_ativas, solicitacoes: r.solicitacoes, online: r.documentadores_online });
      setErro(null);
      for (const item of r.atendimentos) {
        if (item.status !== "solicitado" || vistas.current.has(item.entrevista_id)) continue;
        vistas.current.add(item.entrevista_id); avisar(item);
      }
    }).catch((e) => setErro(e instanceof Error ? e.message : "Não foi possível atualizar a fila."));
  }, [avisar]);

  useEffect(() => {
    const marcar = () => void registrarPresencaDocumentacao().catch(() => undefined);
    marcar(); carregar();
    const atualizacao = window.setInterval(carregar, 5_000);
    const presenca = window.setInterval(marcar, 30_000);
    return () => { window.clearInterval(atualizacao); window.clearInterval(presenca); };
  }, [carregar]);

  async function assumir(item: AtendimentoDocumentacao) {
    if (!item.sala) return;
    setAssumindo(item.entrevista_id); setErro(null);
    try {
      const reservado = await assumirAtendimentoDocumentacao(item.entrevista_id);
      const { token } = await criarSalaChamada(reservado.sala!);
      await chamada.entrar(reservado.sala!, "advogado", { nome: `Documentação · ${sessao.nome || "Atendente"}`, camera: false }, token);
      if (!reservado.caso_id) throw new Error("O atendimento ainda não possui um caso vinculado.");
      setAlerta(null); document.title = "Acervo"; onAbrirDocumentos(reservado.caso_id);
    } catch (e) { setErro(e instanceof Error ? e.message : "Não foi possível assumir a chamada."); }
    finally { setAssumindo(null); }
  }

  async function ativarNotificacoes() {
    if ("Notification" in window) setPermissao(await Notification.requestPermission());
  }

  return (
    <main className="max-w-[1180px] mx-auto px-7 pt-6 pb-16">
      <button type="button" onClick={onVoltar} className="text-xs text-acao bg-transparent border-0 cursor-pointer">← Carteira</button>
      <header className="mt-3 flex items-start justify-between gap-5 flex-wrap border-b border-borda-forte pb-5">
        <div><span className="text-[10px] font-semibold tracking-[0.14em] uppercase text-tinta-3">Central de atendimento</span><h1 className="mt-2 mb-1 text-3xl">Departamento de Documentação</h1><p className="mt-0 max-w-[68ch] text-tinta-3">Acompanhe as entrevistas, receba a convocação e entre na chamada com os documentos do cliente à mão.</p></div>
        {permissao !== "granted" && permissao !== "indisponivel" && <button type="button" onClick={() => void ativarNotificacoes()} className="border border-acao bg-acao text-papel px-4 py-3 text-xs font-bold uppercase tracking-wider cursor-pointer">Ativar notificações</button>}
      </header>

      {alerta && <section className="my-5 border-2 border-acao bg-acao-clara p-5 shadow-cartao" role="alert" aria-live="assertive"><div className="flex justify-between gap-4 items-start flex-wrap"><div><span className="text-[10px] font-bold tracking-[0.14em] uppercase text-acao">🔔 Presença solicitada agora</span><h2 className="mt-2 mb-1 text-xl">{alerta.cliente || "Cliente ainda não identificado"}</h2><p className="m-0 text-sm text-tinta-2">{alerta.entrevistador_nome} está aguardando você na chamada.</p></div><button type="button" onClick={() => void assumir(alerta)} disabled={assumindo !== null} className="border border-acao bg-acao text-papel px-5 py-3 text-xs font-bold uppercase tracking-wider cursor-pointer disabled:opacity-50">{assumindo === alerta.entrevista_id ? "Entrando…" : "Entrar e abrir documentos"}</button></div></section>}

      <div className="grid grid-cols-3 max-[620px]:grid-cols-1 max-w-[820px] gap-3 my-5"><div className="border border-borda bg-papel-2 p-4"><strong className="block text-3xl">{metricas.ativas}</strong><span className="text-xs text-tinta-3">entrevistas acontecendo</span></div><div className="border border-acao-borda bg-acao-clara p-4"><strong className="block text-3xl text-acao">{metricas.solicitacoes}</strong><span className="text-xs text-tinta-3">aguardando Documentação</span></div><div className="border border-borda bg-papel-2 p-4"><strong className="block text-3xl text-ok">{metricas.online}</strong><span className="text-xs text-tinta-3">documentadores online</span></div></div>
      {erro && <p className="border-l-4 border-critico bg-critico-claro p-3 text-sm">{erro}</p>}
      <div className="flex items-baseline justify-between gap-3 mt-7 mb-3"><h2 className="m-0 text-lg">Fila de atendimentos</h2><span className="text-xs text-tinta-3">Atualização a cada 5 segundos</span></div>
      <div className="grid gap-3">
        {fila.map((item) => <article key={item.entrevista_id} className={`border-l-4 border-y border-r p-5 ${item.status === "solicitado" ? "border-acao bg-acao-clara" : "border-borda bg-papel"}`}><div className="flex justify-between gap-4 flex-wrap"><div><strong className="block text-base">{item.cliente || "Cliente ainda não identificado"}</strong><span className="block mt-1 text-xs text-tinta-3">Entrevistador: {item.entrevistador_nome}</span></div><span className="text-[10px] uppercase tracking-wider text-tinta-3">{item.status === "solicitado" ? "aguardando você" : item.status === "assumido" ? `assumido por ${item.documentador_nome}` : "entrevista em andamento"}</span></div>{item.status === "solicitado" && <button type="button" onClick={() => void assumir(item)} disabled={assumindo !== null} className="mt-3 border border-acao bg-acao text-papel px-4 py-2 text-xs font-bold uppercase tracking-wider cursor-pointer disabled:opacity-50">{assumindo === item.entrevista_id ? "Entrando na chamada…" : "Entrar e abrir documentos"}</button>}</article>)}
        {fila.length === 0 && <p className="border border-dashed border-borda p-10 text-center text-tinta-3">Nenhuma entrevista ativa agora. Você será avisado quando precisarem da Documentação.</p>}
      </div>
    </main>
  );
}
