"use client";

/**
 * Relatório de follow-up: clientes com documento obrigatório pendente, com nome,
 * telefone, o que falta e o alerta de quando é preciso LIGAR (o WhatsApp
 * automático não está resolvendo). Retrato operacional para o atendimento —
 * não é ranking de cliente. Ver `carteira.relatorio_follow_up`.
 */

import { useCallback, useEffect, useState } from "react";
import { History, X } from "lucide-react";

import {
  callHistory,
  registerCall,
  relatorioFollowUp,
  type Call,
  type RelatorioFollowUp,
} from "@/lib/api";
import { Aviso, Botao, Cartao, Selo, Vazio } from "@/components/ui/Basicos";

export default function FollowUp() {
  const [dados, setDados] = useState<RelatorioFollowUp | null>(null);
  const [carregando, setCarregando] = useState(true);
  const [erro, setErro] = useState<string | null>(null);
  const [soLigar, setSoLigar] = useState(false);
  const [histories, setHistories] = useState<Record<string, Call[]>>({});
  const [openCaseId, setOpenCaseId] = useState<string | null>(null);
  const [loadingHistory, setLoadingHistory] = useState<string | null>(null);
  const [historyErrors, setHistoryErrors] = useState<Record<string, string>>({});
  const [confirmingCaseId, setConfirmingCaseId] = useState<string | null>(null);
  const [confirmationErrors, setConfirmationErrors] = useState<Record<string, string>>({});

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

  useEffect(() => {
    if (!openCaseId) {
      return;
    }
    function closeOnEscape(event: KeyboardEvent) {
      if (event.key === "Escape") {
        setOpenCaseId(null);
      }
    }
    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, [openCaseId]);

  const lista = (dados?.clientes ?? []).filter((c) => !soLigar || c.precisa_ligar);
  const selectedClient = (dados?.clientes ?? []).find((client) => client.caso_id === openCaseId) ?? null;

  async function openHistory(casoId: string) {
    setOpenCaseId(casoId);
    if (histories[casoId] || loadingHistory === casoId) {
      return;
    }
    setLoadingHistory(casoId);
    setHistoryErrors((current) => ({ ...current, [casoId]: "" }));
    try {
      const history = await callHistory(casoId);
      setHistories((current) => ({ ...current, [casoId]: history.calls }));
    } catch (e) {
      setHistoryErrors((current) => ({
        ...current,
        [casoId]: e instanceof Error ? e.message : "Não foi possível carregar o histórico.",
      }));
    } finally {
      setLoadingHistory(null);
    }
  }

  async function confirmCall(casoId: string) {
    if (confirmingCaseId) {
      return;
    }
    setConfirmingCaseId(casoId);
    setConfirmationErrors((current) => ({ ...current, [casoId]: "" }));
    try {
      const call = await registerCall(casoId);
      setHistories((current) => (
        current[casoId]
          ? { ...current, [casoId]: [call, ...current[casoId]] }
          : current
      ));
      await recarregar();
    } catch (e) {
      setConfirmationErrors((current) => ({
        ...current,
        [casoId]: e instanceof Error ? e.message : "Não foi possível registrar a ligação.",
      }));
    } finally {
      setConfirmingCaseId(null);
    }
  }

  return (
    <>
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
                  <th className="py-2 font-semibold">Histórico</th>
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
                      {c.ultima_ligacao ? (
                        <span className="grid gap-1">
                          <Botao
                            variante="secundario"
                            pequeno
                            className="justify-self-start whitespace-nowrap"
                            disabled={confirmingCaseId !== null}
                            onClick={() => void confirmCall(c.caso_id)}
                          >
                            {confirmingCaseId === c.caso_id ? "Registrando…" : "Ligar"}
                          </Botao>
                          {confirmationErrors[c.caso_id] && (
                            <span className="text-[11px] leading-[1.4] text-critico">
                              {confirmationErrors[c.caso_id]}
                            </span>
                          )}
                        </span>
                      ) : c.precisa_ligar ? (
                        <span className="grid gap-1">
                          <button
                            type="button"
                            className={
                              "justify-self-start cursor-pointer rounded-pill border-0 bg-transparent p-0 text-left " +
                              "focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 " +
                              "focus-visible:outline-foco disabled:cursor-wait disabled:opacity-60"
                            }
                            disabled={confirmingCaseId !== null}
                            aria-label="Confirmar ligação realizada"
                            onClick={() => void confirmCall(c.caso_id)}
                          >
                            <Selo tom="critico" simbolo="!">
                              {confirmingCaseId === c.caso_id ? "Registrando…" : "LIGAR"}
                            </Selo>
                          </button>
                          <span className="text-[11px] leading-[1.4] text-tinta-3">{c.motivo_ligacao}</span>
                          {confirmationErrors[c.caso_id] && (
                            <span className="text-[11px] leading-[1.4] text-critico">
                              {confirmationErrors[c.caso_id]}
                            </span>
                          )}
                        </span>
                      ) : (
                        <Selo tom={c.follow_up_ativo ? "ok" : "neutro"}>
                          {c.follow_up_ativo ? "follow-up ativo" : "no prazo"}
                        </Selo>
                      )}
                    </td>
                    <td className="py-2">
                      <Botao
                        variante="secundario"
                        pequeno
                        className="whitespace-nowrap"
                        aria-haspopup="dialog"
                        onClick={() => void openHistory(c.caso_id)}
                      >
                        <History size={15} strokeWidth={2} aria-hidden />
                        Abrir histórico
                      </Botao>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Cartao>

      {selectedClient && (
        <CallHistoryModal
          clientName={selectedClient.cliente}
          calls={histories[selectedClient.caso_id]}
          error={historyErrors[selectedClient.caso_id]}
          loading={loadingHistory === selectedClient.caso_id}
          onClose={() => setOpenCaseId(null)}
        />
      )}
    </>
  );
}

function CallHistoryModal({
  clientName,
  loading,
  error,
  calls,
  onClose,
}: {
  clientName: string;
  loading: boolean;
  error: string | undefined;
  calls: Call[] | undefined;
  onClose: () => void;
}) {
  return (
    <div
      className="fixed inset-0 z-50 flex items-end justify-center bg-tinta/45 p-3 sm:items-center sm:p-6"
      role="dialog"
      aria-modal="true"
      aria-labelledby="titulo-historico-ligacoes"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) {
          onClose();
        }
      }}
    >
      <section className="w-full max-w-xl overflow-hidden rounded-cartao border border-borda-forte bg-papel shadow-cartao">
        <header className="flex items-start justify-between gap-4 border-b border-borda px-5 py-4 sm:px-6">
          <div className="min-w-0">
            <div className="mb-1 flex items-center gap-2 text-acao">
              <History size={18} strokeWidth={2} aria-hidden />
              <span className="text-xs font-bold uppercase tracking-wide">Ligações</span>
            </div>
            <h2 id="titulo-historico-ligacoes" className="truncate font-titulo text-xl font-semibold text-tinta">
              Histórico de {clientName || "cliente"}
            </h2>
          </div>
          <Botao variante="discreto" pequeno aria-label="Fechar histórico" onClick={onClose}>
            <X size={18} strokeWidth={2} aria-hidden />
          </Botao>
        </header>
        <div className="max-h-[60vh] overflow-y-auto px-5 py-5 sm:px-6">
          {loading ? (
            <div className="flex min-h-40 items-center justify-center text-sm text-tinta-3">Carregando histórico…</div>
          ) : error ? (
            <Aviso tom="critico" titulo="Não foi possível abrir o histórico">{error}</Aviso>
          ) : !calls || calls.length === 0 ? (
            <Vazio>Nenhuma ligação foi registrada para este cliente.</Vazio>
          ) : (
            <ol className="grid gap-3">
              {calls.map((call, index) => (
                <li key={call.id} className="flex gap-3">
                  <div className="flex w-5 flex-col items-center" aria-hidden>
                    <span className="mt-[6px] size-3 rounded-full border-[3px] border-acao bg-papel" />
                    {index < calls.length - 1 && <span className="mt-1 w-px flex-1 bg-borda-forte" />}
                  </div>
                  <div className="min-w-0 flex-1 rounded-campo border border-borda bg-papel-2 px-4 py-3">
                    <strong className="block text-sm font-semibold text-tinta">{call.atendente_nome}</strong>
                    <time className="mt-1 block font-codigo text-xs tabular-nums text-tinta-3" dateTime={call.realizada_em}>
                      {formatDateTime(call.realizada_em)}
                    </time>
                  </div>
                </li>
              ))}
            </ol>
          )}
        </div>
        <footer className="flex justify-end border-t border-borda bg-papel-2 px-5 py-3 sm:px-6">
          <Botao variante="secundario" pequeno onClick={onClose}>Fechar</Botao>
        </footer>
      </section>
    </div>
  );
}

function formatDateTime(value: string): string {
  const data = new Date(value);
  if (Number.isNaN(data.getTime())) {
    return value;
  }
  return new Intl.DateTimeFormat("pt-BR", {
    dateStyle: "short",
    timeStyle: "short",
  }).format(data);
}

function Indicador({ rotulo, valor, destaque }: { rotulo: string; valor: string; destaque?: boolean }) {
  return (
    <div className={`rounded-campo border p-3 ${destaque ? "border-atencao bg-atencao-claro" : "border-borda-forte bg-papel"}`}>
      <strong className="block text-[1.4rem] leading-none tabular-nums text-tinta">{valor}</strong>
      <span className="text-xs text-tinta-3">{rotulo}</span>
    </div>
  );
}
