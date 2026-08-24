"use client";

/* Painel de saúde do agente jurídico: latência dos dois bancos dele (aplicação e
 * corpus de jurisprudência) e o cache, mais quanto cada agente de IA (estratégia,
 * pesquisa, redação...) tem demorado e acertado nas últimas 24h.
 *
 * Fala só com `/api/agente/saude`, que é o Acervo repassando o `/health/inspection`
 * do agente — a tela nunca conhece o endereço nem o token dele.
 */

import { useCallback, useEffect, useState } from "react";

import { Aviso, Botao, Selo, Tabela, Th } from "@/components/ui/Basicos";
import { ApiError } from "@/lib/api";
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
    <div className="flex justify-between items-center gap-[10px] px-4 py-[14px] border border-borda rounded-cartao bg-papel">
      <span className="font-semibold text-sm">{nome}</span>
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
      <td className={CELULA}>{item.agent_name}</td>
      <td className={CELULA_META}>{item.task}</td>
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

  return (
    <div className="max-w-[1240px] mx-auto px-5 pt-6 pb-16">
      <Botao variante="secundario" onClick={onVoltar}>
        ← Voltar para a carteira
      </Botao>

      <header className="flex justify-between items-start gap-4 mt-5 mb-2">
        <div>
          <h1 className="m-0 mb-[6px] text-[1.6rem]">Saúde do agente jurídico</h1>
          <p className="m-0 max-w-[66ch] text-tinta-3 leading-[1.5]">
            Latência dos dois bancos que o agente usa e o desempenho de cada tipo de
            geração (estratégia, pesquisa, redação, classificação...) nas últimas
            {" "}
            {dados?.agents?.window_hours ?? 24} horas. &ldquo;Duração&rdquo; é o tempo
            do agente inteiro, incluindo retentativa quando o modelo erra o formato;
            &ldquo;raciocínio&rdquo; é só a chamada ao modelo — quando os dois divergem
            muito, o agente está retentando, não o provedor lento.
          </p>
        </div>
        <Botao variante="secundario" pequeno onClick={() => void carregar()} disabled={carregando}>
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

      {dados?.ligado && dados.dependencies && (
        <section className="mt-7">
          <h2 className="m-0 mb-3 text-[1.05rem]">Bancos e cache</h2>
          <div className="grid grid-cols-[repeat(auto-fit,minmax(220px,1fr))] gap-3">
            {Object.entries(dados.dependencies).map(([chave, dep]) => (
              <CartaoDependencia key={chave} nome={NOME_DEPENDENCIA[chave] ?? chave} dep={dep} />
            ))}
          </div>
        </section>
      )}

      {dados?.ligado && dados.agents && (
        <section className="mt-7">
          <h2 className="m-0 mb-3 text-[1.05rem]">Desempenho por agente</h2>
          {dados.agents.by_agent.length === 0 ? (
            <p className="m-0 text-tinta-3">
              Nenhuma execução de IA nas últimas {dados.agents.window_hours} horas.
            </p>
          ) : (
            <div className="overflow-x-auto border border-borda rounded-cartao">
              <Tabela>
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
        </section>
      )}
    </div>
  );
}
