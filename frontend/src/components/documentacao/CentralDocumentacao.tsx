"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";
import { BellRing, Headphones, Radio, UsersRound } from "lucide-react";

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

const ROTULO_STATUS: Record<AtendimentoDocumentacao["status"], string> = {
  entrevista: "entrevista em andamento",
  solicitado: "aguardando documentação",
  assumido: "assumido",
  encerrado: "encerrado",
};

function hora(iso: string | null): string {
  if (!iso) return "sem horário";
  const data = new Date(iso);
  if (!Number.isFinite(data.getTime())) return "sem horário";
  return data.toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" });
}

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
      const audio = new AudioContext();
      const som = audio.createOscillator();
      const volume = audio.createGain();
      som.frequency.value = 880;
      volume.gain.setValueAtTime(0.12, audio.currentTime);
      volume.gain.exponentialRampToValueAtTime(0.001, audio.currentTime + 0.45);
      som.connect(volume).connect(audio.destination);
      som.start();
      som.stop(audio.currentTime + 0.45);
    } catch {
      /* O alerta visual continua quando o navegador bloqueia o som. */
    }
    if ("Notification" in window && Notification.permission === "granted") {
      const aviso = new Notification("Documentação solicitada", {
        body: `${item.entrevistador_nome} pediu sua presença para atender ${item.cliente || "o cliente"}.`,
        tag: `documentacao-${item.entrevista_id}`,
        requireInteraction: true,
      });
      aviso.onclick = () => {
        window.focus();
        aviso.close();
      };
    }
  }, []);

  const carregar = useCallback(() => {
    void listarAtendimentosDocumentacao()
      .then((r) => {
        setFila(r.atendimentos);
        setMetricas({
          ativas: r.entrevistas_ativas,
          solicitacoes: r.solicitacoes,
          online: r.documentadores_online,
        });
        setErro(null);
        for (const item of r.atendimentos) {
          if (item.status !== "solicitado" || vistas.current.has(item.entrevista_id)) continue;
          vistas.current.add(item.entrevista_id);
          avisar(item);
        }
      })
      .catch((e) => setErro(e instanceof Error ? e.message : "Não foi possível atualizar a fila."));
  }, [avisar]);

  useEffect(() => {
    const marcar = () => void registrarPresencaDocumentacao().catch(() => undefined);
    marcar();
    carregar();
    const atualizacao = window.setInterval(carregar, 5_000);
    const presenca = window.setInterval(marcar, 30_000);
    return () => {
      window.clearInterval(atualizacao);
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
      if (!reservado.caso_id) throw new Error("O atendimento ainda não possui um caso vinculado.");
      setAlerta(null);
      document.title = "Acervo";
      onAbrirDocumentos(reservado.caso_id);
    } catch (e) {
      setErro(e instanceof Error ? e.message : "Não foi possível assumir a chamada.");
    } finally {
      setAssumindo(null);
    }
  }

  async function ativarNotificacoes() {
    if ("Notification" in window) setPermissao(await Notification.requestPermission());
  }

  return (
    <main className="mx-auto flex w-full max-w-[1180px] min-w-0 flex-col gap-5">
      <header className="overflow-hidden rounded-cartao border border-borda-forte bg-papel shadow-cartao">
        <div className="flex min-w-0 flex-col gap-4 border-b border-borda bg-papel-2 px-4 py-4 sm:px-5 lg:flex-row lg:items-end lg:justify-between">
          <div className="min-w-0">
            <Botao variante="texto" pequeno onClick={onVoltar}>
              ← Carteira
            </Botao>
            <span className="mt-3 block text-[11px] font-bold uppercase tracking-[0.12em] text-tinta-3">
              Central de atendimento
            </span>
            <h1 className="mt-1 truncate text-xl font-semibold leading-[1.15] text-tinta">
              Departamento de Documentação
            </h1>
            <p className="mt-2 max-w-[74ch] text-sm leading-[1.55] text-tinta-2">
              Acompanhe entrevistas em andamento, receba a convocação e entre na mesma
              chamada com os documentos do cliente à mão.
            </p>
          </div>

          <div className="flex min-w-0 flex-wrap items-center gap-2">
            <Selo tom={permissao === "granted" ? "ok" : "neutro"}>
              notificações {permissao === "granted" ? "ativas" : "pendentes"}
            </Selo>
            {permissao !== "granted" && permissao !== "indisponivel" && (
              <Botao variante="primario" pequeno onClick={() => void ativarNotificacoes()}>
                Ativar notificações
              </Botao>
            )}
          </div>
        </div>

        <div className="grid min-w-0 gap-3 p-4 sm:grid-cols-3 sm:p-5">
          <Metrica
            icone={<Radio size={18} aria-hidden />}
            rotulo="Entrevistas acontecendo"
            valor={metricas.ativas}
            tom="neutro"
          />
          <Metrica
            icone={<BellRing size={18} aria-hidden />}
            rotulo="Aguardando Documentação"
            valor={metricas.solicitacoes}
            tom={metricas.solicitacoes > 0 ? "info" : "neutro"}
          />
          <Metrica
            icone={<UsersRound size={18} aria-hidden />}
            rotulo="Documentadores online"
            valor={metricas.online}
            tom="ok"
          />
        </div>
      </header>

      {alerta && (
        <section
          className="overflow-hidden rounded-cartao border-2 border-acao bg-acao-clara shadow-cartao"
          role="alert"
          aria-live="assertive"
        >
          <div className="flex min-w-0 flex-col gap-4 px-4 py-4 sm:px-5 lg:flex-row lg:items-center lg:justify-between">
            <div className="min-w-0">
              <span className="inline-flex items-center gap-2 text-[11px] font-bold uppercase tracking-[0.12em] text-acao">
                <BellRing size={16} aria-hidden />
                Presença solicitada agora
              </span>
              <h2 className="mt-2 truncate text-lg font-semibold text-tinta">
                {alerta.cliente || "Cliente ainda não identificado"}
              </h2>
              <p className="mt-1 text-sm leading-[1.55] text-tinta-2">
                {alerta.entrevistador_nome} está aguardando você na chamada.
              </p>
            </div>
            <Botao
              variante="primario"
              onClick={() => void assumir(alerta)}
              disabled={assumindo !== null}
              className="shrink-0"
            >
              {assumindo === alerta.entrevista_id ? "Entrando…" : "Entrar e abrir documentos"}
            </Botao>
          </div>
        </section>
      )}

      {erro && (
        <Aviso tom="critico" titulo="Não foi possível atualizar a documentação">
          {erro}
        </Aviso>
      )}

      <section className="min-w-0 overflow-hidden rounded-cartao border border-borda-forte bg-papel shadow-cartao">
        <div className="flex min-w-0 items-baseline justify-between gap-3 border-b border-borda bg-papel-2 px-4 py-3 sm:px-5">
          <div className="min-w-0">
            <h2 className="m-0 truncate text-lg font-semibold text-tinta">Fila de atendimentos</h2>
            <p className="mt-1 text-xs text-tinta-3">Atualização a cada 5 segundos</p>
          </div>
          <Selo tom={fila.length > 0 ? "info" : "neutro"}>{fila.length} na fila</Selo>
        </div>

        {fila.length === 0 ? (
          <div className="p-4 sm:p-5">
            <Vazio>Nenhuma entrevista ativa agora. Você será avisado quando precisarem da Documentação.</Vazio>
          </div>
        ) : (
          <ul className="m-0 list-none divide-y divide-borda p-0">
            {fila.map((item) => (
              <AtendimentoLinha
                key={item.entrevista_id}
                item={item}
                assumindo={assumindo}
                onAssumir={assumir}
              />
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

function AtendimentoLinha({
  item,
  assumindo,
  onAssumir,
}: {
  item: AtendimentoDocumentacao;
  assumindo: string | null;
  onAssumir: (item: AtendimentoDocumentacao) => Promise<void>;
}) {
  const solicitado = item.status === "solicitado";
  return (
    <li className={solicitado ? "bg-acao-clara" : "bg-papel"}>
      <article
        className={`grid min-w-0 gap-3 border-l-4 px-4 py-4 sm:px-5 min-[760px]:grid-cols-[minmax(0,1.2fr)_minmax(0,0.9fr)_150px] min-[760px]:items-center ${
          solicitado ? "border-l-acao" : "border-l-borda"
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
          <Selo tom={solicitado ? "info" : item.status === "assumido" ? "ok" : "neutro"}>
            {item.status === "assumido" && item.documentador_nome
              ? `assumido por ${item.documentador_nome}`
              : ROTULO_STATUS[item.status]}
          </Selo>
          <span className="mt-2 block truncate text-xs text-tinta-3">
            {solicitado ? `solicitado às ${hora(item.solicitado_em)}` : `atualizado às ${hora(item.atualizado_em)}`}
          </span>
        </div>

        <div className="flex min-w-0 justify-start min-[760px]:justify-end">
          {solicitado ? (
            <Botao
              variante="primario"
              pequeno
              onClick={() => void onAssumir(item)}
              disabled={assumindo !== null}
              className="max-w-full"
            >
              <Headphones size={15} aria-hidden />
              <span className="min-w-0 truncate">
                {assumindo === item.entrevista_id ? "Entrando…" : "Assumir"}
              </span>
            </Botao>
          ) : (
            <span className="text-xs text-tinta-3">Aguardando solicitação</span>
          )}
        </div>
      </article>
    </li>
  );
}
