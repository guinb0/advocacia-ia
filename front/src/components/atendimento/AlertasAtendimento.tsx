"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Bell, X } from "lucide-react";

import { Botao } from "@/components/ui/Basicos";
import {
  assumirAtendimento,
  listarAlertasAtivos,
  type AlertaAtendimento,
} from "@/lib/api/atendimentos";
import { definirAtendimentoAtivo } from "@/lib/atendimentoAtivo";
import type { Tela } from "@/lib/telas";

/* Os alertas do atendimento, em qualquer tela.
 *
 * Quem decide se o alerta vale é o servidor (presença viva, estado do
 * atendimento); aqui só se desenha o que veio e se toca o aviso UMA vez por
 * alerta. Ocultar esconde nesta aba — resolver é o servidor que faz, quando o
 * atendimento anda. */

const INTERVALO_VISIVEL_MS = 5_000;
const INTERVALO_OCULTO_MS = 30_000;
const CHAVE_AVISADOS = "alertas:avisados";
const CHAVE_OCULTOS = "alertas:ocultos";
const MAXIMO_LEMBRADOS = 200;

function lerConjunto(armazem: Storage | undefined, chave: string): Set<string> {
  try {
    return new Set(JSON.parse(armazem?.getItem(chave) ?? "[]") as string[]);
  } catch {
    return new Set();
  }
}

function gravarConjunto(armazem: Storage | undefined, chave: string, valores: Set<string>) {
  try {
    armazem?.setItem(chave, JSON.stringify([...valores].slice(-MAXIMO_LEMBRADOS)));
  } catch {
    /* armazenamento cheio ou bloqueado: no pior caso o aviso toca de novo */
  }
}

function tocarAviso() {
  try {
    const Contexto = window.AudioContext ?? (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
    if (!Contexto) return;
    const ctx = new Contexto();
    const agora = ctx.currentTime;
    [0, 0.22].forEach((atraso, i) => {
      const osc = ctx.createOscillator();
      const ganho = ctx.createGain();
      osc.frequency.value = i === 0 ? 880 : 1175;
      ganho.gain.setValueAtTime(0.0001, agora + atraso);
      ganho.gain.exponentialRampToValueAtTime(0.25, agora + atraso + 0.02);
      ganho.gain.exponentialRampToValueAtTime(0.0001, agora + atraso + 0.2);
      osc.connect(ganho).connect(ctx.destination);
      osc.start(agora + atraso);
      osc.stop(agora + atraso + 0.22);
    });
    window.setTimeout(() => void ctx.close(), 800);
  } catch {
    /* sem áudio (aba sem interação ainda): o cartão na tela continua */
  }
}

function notificar(alerta: AlertaAtendimento) {
  if (typeof Notification === "undefined" || Notification.permission !== "granted") return;
  try {
    new Notification(alerta.titulo, { body: alerta.texto, tag: alerta.id });
  } catch {
    /* alguns navegadores só notificam via service worker */
  }
}

function minutosDesde(iso?: string): number | null {
  if (!iso) return null;
  const t = Date.parse(iso.endsWith("Z") || /[+-]\d\d:\d\d$/.test(iso) ? iso : `${iso}Z`);
  return Number.isNaN(t) ? null : Math.max(0, Math.floor((Date.now() - t) / 60_000));
}

interface Props {
  onNavegar: (tela: Tela) => void;
  onAbrirCaso: (casoId: string) => void;
}

export default function AlertasAtendimento({ onNavegar, onAbrirCaso }: Props) {
  const [alertas, setAlertas] = useState<AlertaAtendimento[]>([]);
  const [ocultos, setOcultos] = useState<Set<string>>(new Set());
  const [ocupado, setOcupado] = useState<string | null>(null);
  const [erro, setErro] = useState<string | null>(null);
  const avisados = useRef<Set<string>>(new Set());

  useEffect(() => {
    avisados.current = lerConjunto(window.localStorage, CHAVE_AVISADOS);
    setOcultos(lerConjunto(window.sessionStorage, CHAVE_OCULTOS));
  }, []);

  const consultar = useCallback(async () => {
    try {
      const lista = await listarAlertasAtivos();
      setAlertas(lista);
      const novos = lista.filter((a) => !avisados.current.has(a.id));
      if (novos.length) {
        novos.forEach((a) => avisados.current.add(a.id));
        gravarConjunto(window.localStorage, CHAVE_AVISADOS, avisados.current);
        tocarAviso();
        novos.forEach(notificar);
      }
    } catch {
      /* sem sessão ou rede: tenta na próxima volta, sem ruído na tela */
    }
  }, []);

  useEffect(() => {
    let timer: number | undefined;
    let vivo = true;
    const ciclo = async () => {
      await consultar();
      if (!vivo) return;
      timer = window.setTimeout(ciclo, document.hidden ? INTERVALO_OCULTO_MS : INTERVALO_VISIVEL_MS);
    };
    void ciclo();
    const aoVoltar = () => {
      if (!document.hidden) {
        window.clearTimeout(timer);
        void ciclo();
      }
    };
    document.addEventListener("visibilitychange", aoVoltar);
    return () => {
      vivo = false;
      window.clearTimeout(timer);
      document.removeEventListener("visibilitychange", aoVoltar);
    };
  }, [consultar]);

  const pedirPermissao = () => {
    if (typeof Notification !== "undefined" && Notification.permission === "default") {
      void Notification.requestPermission().catch(() => undefined);
    }
  };

  const ocultar = (id: string) => {
    const proximos = new Set(ocultos).add(id);
    setOcultos(proximos);
    gravarConjunto(window.sessionStorage, CHAVE_OCULTOS, proximos);
  };

  const irParaSala = (alerta: AlertaAtendimento) => {
    definirAtendimentoAtivo({
      id: alerta.atendimento_id,
      sala: alerta.dados.sala ?? null,
      cliente: alerta.dados.cliente ?? "",
    });
    onNavegar("entrevista");
  };

  const agir = async (alerta: AlertaAtendimento) => {
    pedirPermissao();
    setErro(null);
    if (alerta.acao === "entrar") {
      irParaSala(alerta);
      return;
    }
    if (alerta.acao === "assumir") {
      setOcupado(alerta.id);
      try {
        await assumirAtendimento(alerta.atendimento_id);
        irParaSala(alerta);
        void consultar();
      } catch (e) {
        setErro(e instanceof Error ? e.message : "Não foi possível assumir o atendimento.");
      } finally {
        setOcupado(null);
      }
      return;
    }
    const caso = alerta.dados.casos?.[0];
    if (caso?.id) onAbrirCaso(caso.id);
    else onNavegar("documentacao");
  };

  const visiveis = alertas.filter((a) => !ocultos.has(a.id));
  if (!visiveis.length) return null;

  return (
    <div
      className="fixed right-4 bottom-4 z-50 flex w-[min(380px,calc(100vw-2rem))] flex-col gap-2"
      role="region"
      aria-label="Alertas de atendimento"
      aria-live="polite"
    >
      {erro && (
        <div className="rounded-campo border border-critico-borda bg-critico-claro px-3 py-2 text-xs text-critico">{erro}</div>
      )}
      {visiveis.slice(0, 4).map((alerta) => {
        const minutos = minutosDesde(alerta.dados.desde);
        const rotulo =
          alerta.acao === "entrar" ? "Entrar na sala" : alerta.acao === "assumir" ? "Assumir atendimento" : "Abrir caso";
        const urgente = alerta.tipo === "escalonamento";
        return (
          <div
            key={alerta.id}
            className={`rounded-cartao border bg-papel p-3 shadow-cartao ${urgente ? "border-critico-borda" : "border-acao-borda"}`}
          >
            <div className="flex items-start gap-2">
              <Bell aria-hidden className={`mt-[2px] size-4 shrink-0 ${urgente ? "text-critico" : "text-acao"}`} />
              <div className="min-w-0 flex-1">
                <div className="text-sm font-semibold text-tinta">{alerta.titulo}</div>
                <div className="mt-[2px] text-xs leading-[1.5] text-tinta-2">{alerta.texto}</div>
                {minutos !== null && alerta.tipo !== "documentacao_pendente" && (
                  <div className="mt-[2px] text-xs text-tinta-3">
                    Aguardando há {minutos} min{alerta.dados.responsavel ? ` · Responsável: ${alerta.dados.responsavel}` : ""}
                  </div>
                )}
                {alerta.tipo === "documentacao_pendente" && (
                  <div className="mt-1 space-y-[2px] text-xs text-tinta-3">
                    {alerta.dados.responsavel && <div>Responsável: {alerta.dados.responsavel}</div>}
                    {!!alerta.dados.disponiveis?.length && <div>Disponíveis: {alerta.dados.disponiveis.join(", ")}</div>}
                    {!!alerta.dados.pendentes?.length && <div>Pendentes: {alerta.dados.pendentes.join(", ")}</div>}
                  </div>
                )}
                <div className="mt-2 flex flex-wrap gap-2">
                  <Botao
                    variante="primario"
                    pequeno
                    carregando={ocupado === alerta.id}
                    textoCarregando="Assumindo…"
                    onClick={() => void agir(alerta)}
                  >
                    {rotulo}
                  </Botao>
                </div>
              </div>
              <button
                type="button"
                className="shrink-0 rounded p-1 text-tinta-3 hover:bg-papel-3 hover:text-tinta"
                onClick={() => ocultar(alerta.id)}
                aria-label="Ocultar alerta nesta aba"
                title="Ocultar nesta aba (o alerta continua valendo)"
              >
                <X className="size-4" aria-hidden />
              </button>
            </div>
          </div>
        );
      })}
    </div>
  );
}
