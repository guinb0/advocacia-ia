"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";
import {
  Activity,
  BellRing,
  CheckCircle2,
  ChevronDown,
  Clock3,
  FileCheck2,
  Files,
  FileWarning,
  FolderOpen,
  Headphones,
  Radio,
  UsersRound,
} from "lucide-react";

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
const CHAMADA_VIVA_MS = 90_000;

type Filtro = "todos" | "solicitados" | "em_chamada" | "com_pendencias";

function chamadaViva(item: AtendimentoDocumentacao): boolean {
  if (!item.sala) return false;
  const instante = Date.parse(item.atualizado_em);
  return Number.isFinite(instante) && Date.now() - instante < CHAMADA_VIVA_MS;
}

function hora(iso: string | null): string {
  if (!iso) return "sem horário";
  const data = new Date(iso);
  if (!Number.isFinite(data.getTime())) return "sem horário";
  return data.toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" });
}

function espera(iso: string | null): string {
  if (!iso) return "agora";
  const inicio = Date.parse(iso);
  if (!Number.isFinite(inicio)) return "agora";
  const minutos = Math.max(0, Math.floor((Date.now() - inicio) / 60_000));
  if (minutos < 1) return "há menos de 1 min";
  if (minutos < 60) return `há ${minutos} min`;
  const horas = Math.floor(minutos / 60);
  return `há ${horas}h ${minutos % 60}min`;
}

export default function CentralDocumentacao({ onVoltar, onAbrirDocumentos }: Props) {
  const [fila, setFila] = useState<AtendimentoDocumentacao[]>([]);
  const [metricas, setMetricas] = useState({
    ativas: 0, solicitacoes: 0, online: 0, arquivos: 0, pendencias: 0, conferir: 0, prontos: 0,
  });
  const [filtro, setFiltro] = useState<Filtro>("todos");
  const [expandidos, setExpandidos] = useState<Set<string>>(new Set());
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
          arquivos: r.arquivos_recebidos,
          pendencias: r.pendencias_obrigatorias,
          conferir: r.itens_a_conferir,
          prontos: r.casos_prontos,
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

  const filtrada = fila.filter((item) => {
    if (filtro === "solicitados") return item.status === "solicitado";
    if (filtro === "em_chamada") return chamadaViva(item);
    if (filtro === "com_pendencias") {
      return Boolean(item.documentos && (item.documentos.pendencias.length || item.documentos.a_conferir.length || item.documentos.em_triagem));
    }
    return true;
  });

  function alternarDetalhes(id: string) {
    setExpandidos((atuais) => {
      const proximos = new Set(atuais);
      if (proximos.has(id)) proximos.delete(id);
      else proximos.add(id);
      return proximos;
    });
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

        <div className="grid min-w-0 gap-3 p-4 sm:grid-cols-2 xl:grid-cols-4 sm:p-5">
          <Metrica
            icone={<Radio size={18} aria-hidden />}
            rotulo="Atendimentos ativos"
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
            icone={<FileWarning size={18} aria-hidden />}
            rotulo="Itens que exigem atenção"
            valor={metricas.conferir}
            tom={metricas.conferir > 0 ? "atencao" : "ok"}
          />
          <Metrica
            icone={<CheckCircle2 size={18} aria-hidden />}
            rotulo="Casos documentalmente prontos"
            valor={metricas.prontos}
            tom="ok"
          />
        </div>
        <div className="grid gap-px border-t border-borda bg-borda sm:grid-cols-3">
          <ResumoOperacional icone={<Files size={15} />} rotulo="Arquivos recebidos" valor={metricas.arquivos} />
          <ResumoOperacional icone={<Clock3 size={15} />} rotulo="Pendências obrigatórias" valor={metricas.pendencias} />
          <ResumoOperacional icone={<UsersRound size={15} />} rotulo="Equipe online" valor={metricas.online} />
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
        <div className="flex min-w-0 flex-col gap-3 border-b border-borda bg-papel-2 px-4 py-3 sm:px-5 lg:flex-row lg:items-center lg:justify-between">
          <div className="min-w-0">
            <h2 className="m-0 truncate text-lg font-semibold text-tinta">Operação em tempo real</h2>
            <p className="mt-1 text-xs text-tinta-3">Chamadas, prioridade e situação documental · atualização a cada 5 segundos</p>
          </div>
          <div className="flex flex-wrap gap-2">
            {([
              ["todos", "Todos", fila.length],
              ["solicitados", "Chamando equipe", metricas.solicitacoes],
              ["em_chamada", "Em chamada", fila.filter(chamadaViva).length],
              ["com_pendencias", "Com pendências", fila.filter((i) => Boolean(i.documentos?.pendencias.length)).length],
            ] as Array<[Filtro, string, number]>).map(([codigo, rotulo, total]) => (
              <button
                key={codigo}
                type="button"
                onClick={() => setFiltro(codigo)}
                className={`rounded-campo border px-3 py-2 text-[11px] font-semibold transition-colors ${
                  filtro === codigo
                    ? "border-tinta bg-tinta text-papel"
                    : "border-borda-forte bg-papel text-tinta-2 hover:border-tinta"
                }`}
              >
                {rotulo} <span className="ml-1 tabular-nums opacity-75">{total}</span>
              </button>
            ))}
          </div>
        </div>

        {filtrada.length === 0 ? (
          <div className="p-4 sm:p-5">
            <Vazio>{fila.length === 0
              ? "Nenhuma entrevista ativa agora. Você será avisado quando precisarem da Documentação."
              : "Nenhum atendimento corresponde a este filtro."}</Vazio>
          </div>
        ) : (
          <ul className="m-0 list-none divide-y divide-borda p-0">
            {filtrada.map((item) => (
              <AtendimentoLinha
                key={item.entrevista_id}
                item={item}
                assumindo={assumindo}
                onAssumir={assumir}
                aberto={expandidos.has(item.entrevista_id)}
                onAlternar={() => alternarDetalhes(item.entrevista_id)}
                onAbrirDocumentos={onAbrirDocumentos}
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
  tom: "info" | "ok" | "atencao" | "neutro";
}) {
  const classe =
    tom === "info"
      ? "border-acao-borda bg-acao-clara text-acao"
      : tom === "ok"
        ? "border-ok-borda bg-ok-claro text-ok"
        : tom === "atencao"
          ? "border-atencao bg-[color-mix(in_srgb,var(--atencao)_8%,var(--papel))] text-atencao"
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

function ResumoOperacional({ icone, rotulo, valor }: { icone: ReactNode; rotulo: string; valor: number }) {
  return (
    <div className="flex items-center justify-between gap-3 bg-papel px-4 py-3 sm:px-5">
      <span className="inline-flex min-w-0 items-center gap-2 text-xs text-tinta-3">
        {icone}<span className="truncate">{rotulo}</span>
      </span>
      <strong className="tabular-nums text-sm text-tinta">{valor}</strong>
    </div>
  );
}

function AtendimentoLinha({
  item,
  assumindo,
  onAssumir,
  aberto,
  onAlternar,
  onAbrirDocumentos,
}: {
  item: AtendimentoDocumentacao;
  assumindo: string | null;
  onAssumir: (item: AtendimentoDocumentacao) => Promise<void>;
  aberto: boolean;
  onAlternar: () => void;
  onAbrirDocumentos: (casoId: string) => void;
}) {
  const solicitado = item.status === "solicitado";
  const viva = chamadaViva(item);
  const docs = item.documentos;
  return (
    <li className={solicitado ? "bg-acao-clara" : "bg-papel"}>
      <article
        className={`border-l-4 ${
          solicitado ? "border-l-acao" : "border-l-borda"
        }`}
      >
        <div className="grid min-w-0 gap-4 px-4 py-4 sm:px-5 lg:grid-cols-[minmax(220px,1.2fr)_minmax(220px,1fr)_minmax(190px,0.8fr)_auto] lg:items-center">
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <i className={`h-2.5 w-2.5 shrink-0 rounded-full ${viva ? "bg-ok shadow-[0_0_0_4px_color-mix(in_srgb,var(--ok)_14%,transparent)]" : "bg-tinta-3"}`} />
              <strong className="block truncate text-base text-tinta" title={item.cliente || undefined}>
                {item.cliente || "Cliente ainda não identificado"}
              </strong>
            </div>
            <span className="mt-1.5 block truncate pl-[18px] text-xs text-tinta-3" title={item.entrevistador_nome}>
              com {item.entrevistador_nome} · iniciada às {hora(item.iniciado_em)}
            </span>
          </div>

          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <Selo tom={solicitado ? "info" : item.status === "assumido" ? "ok" : "neutro"}>
                {item.status === "assumido" && item.documentador_nome
                  ? `com ${item.documentador_nome}`
                  : ROTULO_STATUS[item.status]}
              </Selo>
              {viva && <span className="inline-flex items-center gap-1 text-[10px] font-semibold uppercase tracking-wider text-ok"><Activity size={12} /> ao vivo</span>}
            </div>
            <span className={`mt-2 block truncate text-xs ${solicitado ? "font-semibold text-acao" : "text-tinta-3"}`}>
              {solicitado ? `esperando ${espera(item.solicitado_em)}` : `última atividade ${espera(item.atualizado_em)}`}
            </span>
          </div>

          <div className="min-w-0">
            {docs ? (
              <>
                <div className="flex items-center justify-between gap-3 text-xs">
                  <span className="truncate font-semibold text-tinta-2">{docs.categoria || "Checklist"}</span>
                  <strong className="tabular-nums text-tinta">{docs.percentual}%</strong>
                </div>
                <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-papel-3" aria-label={`${docs.percentual}% dos documentos obrigatórios entregues`}>
                  <i className={`block h-full rounded-full ${docs.pronto ? "bg-ok" : docs.a_conferir.length ? "bg-atencao" : "bg-acao"}`} style={{ width: `${docs.percentual}%` }} />
                </div>
                <span className="mt-1.5 block text-[11px] text-tinta-3">
                  {docs.obrigatorios_entregues}/{docs.obrigatorios_total} obrigatórios · {docs.arquivos_recebidos} arquivo(s)
                </span>
              </>
            ) : (
              <span className="text-xs text-tinta-3">Caso ainda não criado</span>
            )}
          </div>

          <div className="flex flex-wrap items-center gap-2 lg:justify-end">
          {solicitado && viva ? (
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
          ) : solicitado ? (
            <Selo tom="neutro">chamada encerrada</Selo>
          ) : (
            item.caso_id && <Botao variante="secundario" pequeno onClick={() => onAbrirDocumentos(item.caso_id!)}><FolderOpen size={14} /> Abrir</Botao>
          )}
          {(docs || item.caso_id) && (
            <button type="button" onClick={onAlternar} aria-expanded={aberto} className="inline-flex items-center gap-1 border-none bg-transparent px-2 py-2 text-[11px] font-semibold text-tinta-3 hover:text-tinta">
              Detalhes <ChevronDown size={14} className={aberto ? "rotate-180" : ""} />
            </button>
          )}
          </div>
        </div>

        {aberto && (
          <div className="grid gap-4 border-t border-borda bg-papel-2 px-4 py-4 sm:px-5 lg:grid-cols-[1fr_1fr_auto]">
            <DetalheLista
              titulo="Pendências obrigatórias"
              icone={<Clock3 size={15} />}
              itens={docs?.pendencias ?? []}
              vazio="Nenhuma pendência obrigatória"
              tom={docs?.pendencias.length ? "atencao" : "ok"}
            />
            <DetalheLista
              titulo="Exigem conferência"
              icone={<FileWarning size={15} />}
              itens={[...(docs?.a_conferir ?? []), ...(docs?.em_triagem ? [`${docs.em_triagem} arquivo(s) sem classificação`] : [])]}
              vazio="Nada aguardando conferência"
              tom={(docs?.a_conferir.length ?? 0) + (docs?.em_triagem ?? 0) > 0 ? "atencao" : "ok"}
            />
            <div className="flex min-w-[180px] flex-col items-start gap-2 lg:items-end">
              {docs?.processando ? <Selo tom="info">{docs.processando} em processamento</Selo> : null}
              {docs?.ultima_entrega_em && <span className="text-[11px] text-tinta-3">Último envio {espera(docs.ultima_entrega_em)}</span>}
              {item.caso_id && (
                <Botao variante="secundario" pequeno onClick={() => onAbrirDocumentos(item.caso_id!)}>
                  <FolderOpen size={14} /> Ver documentos
                </Botao>
              )}
            </div>
          </div>
        )}
      </article>
    </li>
  );
}

function DetalheLista({ titulo, icone, itens, vazio, tom }: {
  titulo: string;
  icone: ReactNode;
  itens: string[];
  vazio: string;
  tom: "ok" | "atencao";
}) {
  return (
    <div className="min-w-0">
      <strong className="flex items-center gap-2 text-xs text-tinta">{icone}{titulo}</strong>
      {itens.length ? (
        <ul className="mb-0 mt-2 flex list-none flex-wrap gap-1.5 p-0">
          {itens.slice(0, 6).map((item) => <li key={item} className="rounded-campo border border-atencao/40 bg-papel px-2 py-1 text-[11px] text-tinta-2">{item}</li>)}
          {itens.length > 6 && <li className="px-2 py-1 text-[11px] text-tinta-3">+{itens.length - 6}</li>}
        </ul>
      ) : (
        <span className={`mt-2 inline-flex items-center gap-1.5 text-[11px] ${tom === "ok" ? "text-ok" : "text-tinta-3"}`}>
          <FileCheck2 size={13} /> {vazio}
        </span>
      )}
    </div>
  );
}
