"use client";

import { useCallback, useEffect, useState } from "react";
import type { ReactNode } from "react";
import { Headphones, Radio, UsersRound } from "lucide-react";

import {
  assumirAtendimentoDocumentacao,
  criarSalaChamada,
  listarAtendimentosDocumentacao,
  registrarPresencaDocumentacao,
} from "@/lib/api";
import type { AtendimentoDocumentacao } from "@/lib/api";
import { useChamada } from "@/lib/ChamadaContexto";
import { useSessao } from "@/lib/auth";
import { Aviso, Botao, Selo, Vazio } from "@/components/ui/Basicos";

interface Props {
  onVoltar: () => void;
  onAbrirDocumentos: (casoId: string) => void;
}

const CHAMADA_VIVA_MS = 90_000;

const ROTULO_STATUS: Record<AtendimentoDocumentacao["status"], string> = {
  entrevista: "entrevista em andamento",
  solicitado: "aguardando documentador",
  assumido: "assumido",
  encerrado: "encerrado",
};

function chamadaViva(item: AtendimentoDocumentacao): boolean {
  if (!item.sala) return false;
  const t = Date.parse(item.atualizado_em);
  return Number.isFinite(t) && Date.now() - t < CHAMADA_VIVA_MS;
}

function hora(iso: string | null): string {
  if (!iso) return "sem horário";
  const data = new Date(iso);
  if (!Number.isFinite(data.getTime())) return "sem horário";
  return data.toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" });
}

export default function PainelDocumentacao({ onVoltar, onAbrirDocumentos }: Props) {
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
      .then((r) => {
        setItens(r.atendimentos);
        setAtivas(r.entrevistas_ativas);
        setSolicitacoes(r.solicitacoes);
        setOnline(r.documentadores_online);
        setErro(null);
      })
      .catch((e) => setErro(e instanceof Error ? e.message : "Não foi possível atualizar a fila."));
  }, []);

  useEffect(() => {
    const marcar = () => void registrarPresencaDocumentacao().catch(() => undefined);
    marcar();
    carregar();
    const id = window.setInterval(carregar, 5_000);
    const presenca = window.setInterval(marcar, 30_000);
    return () => {
      window.clearInterval(id);
      window.clearInterval(presenca);
    };
  }, [carregar]);

  async function assumir(item: AtendimentoDocumentacao) {
    if (!item.sala) return;
    setAssumindo(item.entrevista_id);
    setErro(null);
    try {
      const reservado = await assumirAtendimentoDocumentacao(item.entrevista_id);
      const { token } = await criarSalaChamada(reservado.sala!);
      await chamada.entrar(
        reservado.sala!,
        "advogado",
        { nome: `Documentação · ${sessao.nome || "Atendente"}`, camera: false },
        token,
      );
      if (!reservado.caso_id) {
        throw new Error("O atendimento foi assumido, mas ainda não possui um caso vinculado.");
      }
      onAbrirDocumentos(reservado.caso_id);
    } catch (e) {
      setErro(e instanceof Error ? e.message : "Não foi possível assumir a chamada.");
    } finally {
      setAssumindo(null);
    }
  }

  return (
    <main className="mx-auto flex w-full max-w-[1180px] min-w-0 flex-col gap-5">
      <header className="overflow-hidden rounded-cartao border border-borda-forte bg-papel shadow-cartao">
        <div className="border-b border-borda bg-papel-2 px-4 py-4 sm:px-5">
          <Botao variante="texto" pequeno onClick={onVoltar}>
            ← Carteira
          </Botao>
          <span className="mt-3 block text-[11px] font-bold uppercase tracking-[0.12em] text-tinta-3">
            Central de atendimento
          </span>
          <h1 className="mt-1 truncate text-xl font-semibold text-tinta">
            Departamento de Documentação
          </h1>
          <p className="mt-2 max-w-[74ch] text-sm leading-[1.55] text-tinta-2">
            Acompanhe as entrevistas e assuma a mesma chamada quando o entrevistador solicitar.
          </p>
        </div>

        <div className="grid min-w-0 gap-3 p-4 sm:grid-cols-3 sm:p-5">
          <Metrica icone={<Radio size={18} aria-hidden />} rotulo="Entrevistas acontecendo" valor={ativas} tom="neutro" />
          <Metrica icone={<Headphones size={18} aria-hidden />} rotulo="Pedindo documentação" valor={solicitacoes} tom={solicitacoes > 0 ? "info" : "neutro"} />
          <Metrica icone={<UsersRound size={18} aria-hidden />} rotulo="Documentadores online" valor={online} tom="ok" />
        </div>
      </header>

      {erro && (
        <Aviso tom="critico" titulo="Não foi possível atualizar a fila">
          {erro}
        </Aviso>
      )}

      <section className="min-w-0 overflow-hidden rounded-cartao border border-borda-forte bg-papel shadow-cartao">
        <div className="flex min-w-0 items-baseline justify-between gap-3 border-b border-borda bg-papel-2 px-4 py-3 sm:px-5">
          <div className="min-w-0">
            <h2 className="m-0 truncate text-lg font-semibold text-tinta">Fila de atendimentos</h2>
            <p className="mt-1 text-xs text-tinta-3">Atualização a cada 5 segundos</p>
          </div>
          <Selo tom={itens.length > 0 ? "info" : "neutro"}>{itens.length} na fila</Selo>
        </div>

        {itens.length === 0 ? (
          <div className="p-4 sm:p-5">
            <Vazio>Nenhuma entrevista ativa agora.</Vazio>
          </div>
        ) : (
          <ul className="m-0 list-none divide-y divide-borda p-0">
            {itens.map((item) => (
              <li key={item.entrevista_id} className={item.status === "solicitado" ? "bg-acao-clara" : "bg-papel"}>
                <article
                  className={`grid min-w-0 gap-3 border-l-4 px-4 py-4 sm:px-5 min-[760px]:grid-cols-[minmax(0,1.2fr)_minmax(0,0.9fr)_170px] min-[760px]:items-center ${
                    item.status === "solicitado" ? "border-l-acao" : "border-l-borda"
                  }`}
                >
                  <div className="min-w-0">
                    <strong className="block truncate text-base text-tinta" title={item.cliente || undefined}>
                      {item.cliente || "Cliente ainda não identificado"}
                    </strong>
                    <span className="mt-1 block truncate text-xs text-tinta-3" title={item.entrevistador_nome}>
                      Entrevistador: {item.entrevistador_nome}
                    </span>
                  </div>

                  <div className="min-w-0">
                    <Selo tom={item.status === "solicitado" ? "info" : item.status === "assumido" ? "ok" : "neutro"}>
                      {item.status === "assumido" && item.documentador_nome
                        ? `assumido por ${item.documentador_nome}`
                        : ROTULO_STATUS[item.status]}
                    </Selo>
                    <span className="mt-2 block truncate text-xs text-tinta-3">
                      {item.status === "solicitado"
                        ? `solicitado às ${hora(item.solicitado_em)}`
                        : `atualizado às ${hora(item.atualizado_em)}`}
                    </span>
                  </div>

                  <div className="flex min-w-0 justify-start min-[760px]:justify-end">
                    {item.status === "solicitado" && chamadaViva(item) ? (
                      <Botao
                        variante="primario"
                        pequeno
                        onClick={() => void assumir(item)}
                        disabled={assumindo !== null}
                      >
                        {assumindo === item.entrevista_id ? "Entrando…" : "Assumir chamada"}
                      </Botao>
                    ) : item.status === "solicitado" ? (
                      <span className="inline-flex max-w-full items-center gap-2 truncate rounded-campo border border-borda bg-papel-2 px-3 py-2 text-[11px] uppercase tracking-wider text-tinta-3">
                        {item.sala ? "Chamada encerrada" : "Aguardando início"}
                      </span>
                    ) : (
                      <span className="text-xs text-tinta-3">Aguardando solicitação</span>
                    )}
                  </div>
                </article>
              </li>
            ))}
          </ul>
        )}
      </section>
    </main>
  );
}

function Metrica({
  icone,
  rotulo,
  valor,
  tom,
}: {
  icone: ReactNode;
  rotulo: string;
  valor: number;
  tom: "info" | "ok" | "neutro";
}) {
  const classe =
    tom === "info"
      ? "border-acao-borda bg-acao-clara text-acao"
      : tom === "ok"
        ? "border-ok-borda bg-ok-claro text-ok"
        : "border-borda bg-papel-2 text-tinta";

  return (
    <article className={`min-w-0 rounded-campo border px-4 py-3 ${classe}`}>
      <div className="flex items-center justify-between gap-3">
        <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-[10px] border border-current/20 bg-papel/70">
          {icone}
        </span>
        <strong className="text-2xl font-semibold tabular-nums leading-none">{valor}</strong>
      </div>
      <span className="mt-3 block truncate text-xs font-semibold text-tinta-2" title={rotulo}>
        {rotulo}
      </span>
    </article>
  );
}
