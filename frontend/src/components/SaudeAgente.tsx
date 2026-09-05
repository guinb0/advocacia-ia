"use client";

/* Painel de saúde do agente jurídico: latência dos dois bancos dele (aplicação e
 * corpus de jurisprudência) e o cache, mais quanto cada agente de IA (estratégia,
 * pesquisa, redação...) tem demorado e acertado nas últimas 24h.
 *
 * Fala só com `/api/agente/saude`, que é o Acervo repassando o `/health/inspection`
 * do agente — a tela nunca conhece o endereço nem o token dele.
 */

import { useCallback, useEffect, useState } from "react";
import { Activity, ArrowLeft, Database, Gauge, RefreshCcw, ServerCog } from "lucide-react";

import { Aviso, Botao, Cartao, Selo, Tabela, Th, Vazio } from "@/components/ui/Basicos";
import {
  ApiError,
  conectarWhatsapp,
  desconectarWhatsapp,
  statusWhatsapp,
  type StatusWhatsapp,
} from "@/lib/api";
import {
  saudeDoAgente,
  type DependenciaAgente,
  type DesempenhoAgente,
  type SaudeAgente as SaudeAgenteDados,
} from "@/lib/agente";

interface Props {
  onVoltar: () => void;
}

const NOME_DEPENDENCIA: Record<string, string> = {
  database: "Banco de aplicação",
  cache: "Cache (Redis)",
  jurisprudence: "Corpus de jurisprudência",
};

/* As classes de célula ficam em constante porque o CSS Module usava seletor
 * descendente (`.tabela th, .tabela td`) e o Tailwind não tem equivalente:
 * cada célula carrega as suas. Uma constante mantém a regra em UM lugar, que
 * era o único ganho real do seletor. */
const CELULA = "px-[14px] py-[10px] text-left whitespace-nowrap border-b border-borda";
const CELULA_META = `${CELULA} text-tinta-3`;

function tomDaDependencia(dep: DependenciaAgente): "ok" | "atencao" | "critico" {
  if (dep.status === "ok") return "ok";
  if (dep.status === "not_configured") return "atencao";
  return "critico";
}

function textoDaDependencia(dep: DependenciaAgente): string {
  if (dep.status === "ok") return `${dep.latency_ms} ms`;
  if (dep.status === "not_configured") return "não configurado";
  return dep.detail ? `fora do ar (${dep.detail})` : "fora do ar";
}

function CartaoDependencia({ nome, dep }: { nome: string; dep: DependenciaAgente }) {
  return (
    <div className="flex min-w-0 items-center justify-between gap-3 rounded-campo border border-borda bg-papel-2 px-4 py-3">
      <span className="flex min-w-0 items-center gap-2">
        <span className="grid size-8 shrink-0 place-items-center rounded-campo border border-acao-borda bg-acao-clara text-acao">
          <Database size={15} aria-hidden />
        </span>
        <span className="min-w-0 truncate font-semibold text-sm" title={nome}>
          {nome}
        </span>
      </span>
      <Selo tom={tomDaDependencia(dep)}>{textoDaDependencia(dep)}</Selo>
    </div>
  );
}

function linhaDoAgente(item: DesempenhoAgente) {
  const ultimaExecucao = item.last_run_at
    ? new Date(item.last_run_at).toLocaleString("pt-BR")
    : "—";
  const raciocinio = item.reasoning;
  return (
    <tr key={`${item.agent_name}-${item.task}`}>
      <td className={`${CELULA} max-w-[180px]`}>
        <span className="block truncate" title={item.agent_name}>
          {item.agent_name}
        </span>
      </td>
      <td className={`${CELULA_META} max-w-[170px]`}>
        <span className="block truncate" title={item.task}>
          {item.task}
        </span>
      </td>
      <td className={CELULA}>{item.runs}</td>
      <td className={CELULA}>{item.avg_duration_ms.toLocaleString("pt-BR")} ms</td>
      <td className={CELULA}>{item.max_duration_ms.toLocaleString("pt-BR")} ms</td>
      {raciocinio ? (
        <>
          <td className={CELULA}>{raciocinio.avg_call_latency_ms.toLocaleString("pt-BR")} ms</td>
          <td className={CELULA_META}>
            {raciocinio.min_call_latency_ms.toLocaleString("pt-BR")}–
            {raciocinio.max_call_latency_ms.toLocaleString("pt-BR")} ms
          </td>
        </>
      ) : (
        <td colSpan={2} className={CELULA_META}>
          sem chamada ao modelo
        </td>
      )}
      <td className={CELULA}>
        <Selo tom={item.success_rate >= 0.9 ? "ok" : item.success_rate >= 0.5 ? "atencao" : "critico"}>
          {(item.success_rate * 100).toFixed(0)}%
        </Selo>
      </td>
      <td className={CELULA_META}>{ultimaExecucao}</td>
    </tr>
  );
}

/** Conexão do WhatsApp do escritório (Evolution): verde/vermelho e, se caiu, o
 *  QR para religar. Faz o próprio polling — vale mesmo com o agente desligado, e
 *  dá autonomia ao escritório para reconectar ou trocar de número sozinho. */
function CartaoWhatsapp() {
  const [status, setStatus] = useState<StatusWhatsapp | null>(null);
  const [qr, setQr] = useState<{ qrcode: string; codigo: string } | null>(null);
  const [pedindoQr, setPedindoQr] = useState(false);
  const [desconectando, setDesconectando] = useState(false);
  const [erro, setErro] = useState<string | null>(null);

  useEffect(() => {
    let vivo = true;
    const ler = () => {
      void statusWhatsapp()
        .then((s) => {
          if (!vivo) return;
          setStatus(s);
          // Reconectou: o QR já não serve, some da tela.
          if (s.conectado) setQr(null);
        })
        .catch(() => {});
    };
    ler();
    // Enquanto o QR está na tela, checa mais rápido para sumir assim que parear.
    const id = window.setInterval(ler, qr ? 3000 : 15000);
    return () => {
      vivo = false;
      window.clearInterval(id);
    };
  }, [qr]);

  async function pedirQr() {
    setPedindoQr(true);
    setErro(null);
    try {
      const r = await conectarWhatsapp();
      setQr({ qrcode: r.qrcode, codigo: r.codigo });
    } catch (e) {
      setErro(e instanceof ApiError ? e.message : "Não foi possível gerar o QR.");
    } finally {
      setPedindoQr(false);
    }
  }

  async function desconectar() {
    if (!window.confirm("Desconectar o WhatsApp do escritório? Para voltar, será preciso escanear um novo QR.")) return;
    setDesconectando(true);
    setErro(null);
    try {
      await desconectarWhatsapp();
      const s = await statusWhatsapp();
      setStatus(s);
      setQr(null);
    } catch (e) {
      setErro(e instanceof ApiError ? e.message : "Não foi possível desconectar.");
    } finally {
      setDesconectando(false);
    }
  }

  const conectado = status?.conectado;
  const conectando = status?.estado === "connecting";
  const selo = !status
    ? { tom: "info" as const, texto: "Verificando…" }
    : !status.configurado
      ? { tom: "atencao" as const, texto: "Não configurado" }
      : conectado
        ? { tom: "ok" as const, texto: "Conectado" }
        : conectando
          ? { tom: "atencao" as const, texto: "Conectando…" }
          : { tom: "critico" as const, texto: "Desconectado" };

  return (
    <Cartao
      titulo="WhatsApp do escritório"
      subtitulo="Conexão da Evolution — de onde saem os avisos e os links de assinatura ao cliente."
      className="min-w-0 overflow-hidden"
    >
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <span
            className={`inline-block h-2.5 w-2.5 rounded-full ${
              conectado ? "bg-ok" : conectando ? "bg-atencao-marca" : "bg-critico"
            }`}
            aria-hidden
          />
          <Selo tom={selo.tom} simbolo={conectado ? "✓" : "!"}>{selo.texto}</Selo>
          {conectado && status?.numero ? (
            <span className="text-sm font-semibold tabular-nums text-tinta">
              {status.numero}
              {status.perfil && <span className="ml-1 font-normal text-tinta-3">· {status.perfil}</span>}
            </span>
          ) : (
            status?.instancia && (
              <span className="text-xs text-tinta-3">instância “{status.instancia}”</span>
            )
          )}
        </div>
        {status && status.configurado && conectado && (
          <Botao variante="secundario" pequeno onClick={() => void desconectar()} disabled={desconectando}>
            {desconectando ? "Desconectando…" : "Desconectar número"}
          </Botao>
        )}
        {status && status.configurado && !conectado && (
          <Botao variante="primario" pequeno onClick={() => void pedirQr()} disabled={pedindoQr}>
            {pedindoQr ? "Gerando QR…" : qr ? "Gerar outro QR" : "Conectar / trocar número"}
          </Botao>
        )}
      </div>

      {!conectado && status?.configurado && (
        <p className="mt-2 mb-0 text-sm text-atencao">
          O WhatsApp do escritório está fora do ar — os avisos e links não estão saindo.
          Escaneie o QR abaixo com o aparelho para religar.
        </p>
      )}

      {erro && (
        <Aviso tom="critico" titulo="Erro">
          {erro}
        </Aviso>
      )}

      {qr && !conectado && (
        <div className="mt-4 flex flex-col items-center gap-3 rounded-campo border border-borda bg-papel-2 p-4">
          {qr.qrcode ? (
            /* eslint-disable-next-line @next/next/no-img-element -- QR base64 dinâmico da Evolution. */
            <img
              src={qr.qrcode.startsWith("data:") ? qr.qrcode : `data:image/png;base64,${qr.qrcode}`}
              alt="QR code para conectar o WhatsApp"
              className="h-56 w-56 rounded bg-white p-2"
            />
          ) : (
            <p className="m-0 text-sm text-tinta-3">A Evolution não devolveu a imagem do QR.</p>
          )}
          <p className="m-0 text-center text-xs text-tinta-3">
            No celular: WhatsApp → Aparelhos conectados → Conectar um aparelho, e aponte para o código.
            {qr.codigo ? " Código de pareamento: " : ""}
            {qr.codigo && <strong className="font-codigo text-tinta">{qr.codigo}</strong>}
          </p>
        </div>
      )}
    </Cartao>
  );
}

export default function SaudeAgente({ onVoltar }: Props) {
  const [dados, setDados] = useState<SaudeAgenteDados | null>(null);
  const [carregando, setCarregando] = useState(true);
  const [erro, setErro] = useState<string | null>(null);
  const [atualizadoEm, setAtualizadoEm] = useState<Date | null>(null);

  const carregar = useCallback(async () => {
    setCarregando(true);
    try {
      setDados(await saudeDoAgente());
      setErro(null);
      setAtualizadoEm(new Date());
    } catch (e) {
      setErro(e instanceof ApiError ? e.message : "Não foi possível carregar.");
    } finally {
      setCarregando(false);
    }
  }, []);

  useEffect(() => {
    void carregar();
  }, [carregar]);

  const totalAgentes = dados?.agents?.by_agent.length ?? 0;
  const dependencias = dados?.dependencies ? Object.values(dados.dependencies) : [];
  const dependenciasOk = dependencias.filter((dep) => dep.status === "ok").length;
  const mediaSucesso =
    totalAgentes > 0
      ? dados!.agents!.by_agent.reduce((soma, item) => soma + item.success_rate, 0) / totalAgentes
      : null;

  return (
    <div className="min-w-0 space-y-6">
      <Botao variante="texto" onClick={onVoltar} className="inline-flex items-center gap-2">
        <ArrowLeft size={16} aria-hidden />
        Voltar para a carteira
      </Botao>

      <header className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0">
          <p className="mb-2 mt-0 font-ui text-xs font-bold uppercase tracking-[0.12em] text-tinta-3">
            Operação técnica
          </p>
          <h1 className="m-0 mb-[6px] text-tinta font-titulo text-xl font-semibold">
            Saúde do agente jurídico
          </h1>
          <p className="m-0 max-w-[70ch] text-tinta-3 leading-[1.5]">
            Latência das dependências e desempenho das execuções de IA nas últimas{" "}
            {dados?.agents?.window_hours ?? 24} horas, com leitura curta para acompanhamento
            do escritório.
          </p>
        </div>
        <Botao variante="secundario" pequeno onClick={() => void carregar()} disabled={carregando}>
          <RefreshCcw size={14} aria-hidden />
          {carregando ? "Atualizando…" : "Atualizar"}
        </Botao>
      </header>

      {atualizadoEm && !carregando && (
        <p className="text-tinta-3 text-xs">Atualizado às {atualizadoEm.toLocaleTimeString("pt-BR")}</p>
      )}

      {erro && (
        <Aviso tom="critico" titulo="Não foi possível carregar">
          {erro}
        </Aviso>
      )}

      {carregando && !dados && <p className="m-0 text-tinta-3">Carregando…</p>}

      {dados && !dados.ligado && (
        <Aviso tom="atencao" titulo="Agente não configurado">
          A integração com o agente jurídico está desligada neste ambiente
          (`AGENTE_API_URL` vazio).
        </Aviso>
      )}

      {dados?.ligado && (
        <div className="grid min-w-0 grid-cols-[repeat(auto-fit,minmax(min(100%,190px),1fr))] gap-3">
          <div className="rounded-campo border border-borda bg-papel px-4 py-3 shadow-cartao">
            <div className="flex items-center gap-2 text-xs font-semibold text-tinta-3">
              <ServerCog size={14} aria-hidden />
              Integração
            </div>
            <div className="mt-2">
              <Selo tom={dados.status === "ok" ? "ok" : "atencao"} simbolo={dados.status === "ok" ? "✓" : "!"}>
                {dados.status === "ok" ? "operando" : "instável"}
              </Selo>
            </div>
          </div>
          <div className="rounded-campo border border-borda bg-papel px-4 py-3 shadow-cartao">
            <div className="flex items-center gap-2 text-xs font-semibold text-tinta-3">
              <Database size={14} aria-hidden />
              Dependências OK
            </div>
            <div className="mt-1 font-titulo text-lg font-semibold text-tinta tabular-nums">
              {dependenciasOk}/{dependencias.length || 3}
            </div>
          </div>
          <div className="rounded-campo border border-borda bg-papel px-4 py-3 shadow-cartao">
            <div className="flex items-center gap-2 text-xs font-semibold text-tinta-3">
              <Activity size={14} aria-hidden />
              Agentes medidos
            </div>
            <div className="mt-1 font-titulo text-lg font-semibold text-tinta tabular-nums">
              {totalAgentes}
            </div>
          </div>
          <div className="rounded-campo border border-borda bg-papel px-4 py-3 shadow-cartao">
            <div className="flex items-center gap-2 text-xs font-semibold text-tinta-3">
              <Gauge size={14} aria-hidden />
              Sucesso médio
            </div>
            <div className="mt-1 font-titulo text-lg font-semibold text-tinta tabular-nums">
              {mediaSucesso === null ? "—" : `${(mediaSucesso * 100).toFixed(0)}%`}
            </div>
          </div>
        </div>
      )}

      <CartaoWhatsapp />

      {dados?.ligado && dados.dependencies && (
        <Cartao
          titulo="Bancos e cache"
          subtitulo="Serviços que sustentam as consultas e a leitura jurídica."
          className="min-w-0 overflow-hidden"
        >
          <div className="grid min-w-0 grid-cols-[repeat(auto-fit,minmax(min(100%,220px),1fr))] gap-3">
            {Object.entries(dados.dependencies).map(([chave, dep]) => (
              <CartaoDependencia key={chave} nome={NOME_DEPENDENCIA[chave] ?? chave} dep={dep} />
            ))}
          </div>
        </Cartao>
      )}

      {dados?.ligado && dados.agents && (
        <Cartao
          titulo="Desempenho por agente"
          subtitulo="Duração total, tempo de chamada ao modelo e taxa de sucesso por tarefa."
          className="min-w-0 overflow-hidden"
        >
          {dados.agents.by_agent.length === 0 ? (
            <Vazio>
              Nenhuma execução de IA nas últimas {dados.agents.window_hours} horas.
            </Vazio>
          ) : (
            <div className="max-w-full overflow-x-auto rounded-cartao border border-borda">
              <Tabela className="min-w-[920px]">
                <thead>
                  <tr>
                    {[
                      "Agente", "Tarefa", "Execuções", "Duração média", "Duração máxima",
                      "Raciocínio (média)", "Raciocínio (mín–máx)", "Taxa de sucesso",
                      "Última execução",
                    ].map((titulo) => (
                      <Th key={titulo} className="whitespace-nowrap uppercase tracking-[0.03em]">
                        {titulo}
                      </Th>
                    ))}
                  </tr>
                </thead>
                <tbody>{dados.agents.by_agent.map(linhaDoAgente)}</tbody>
              </Tabela>
            </div>
          )}
        </Cartao>
      )}
    </div>
  );
}
