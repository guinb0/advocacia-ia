"use client";

/* Painel de saúde do agente jurídico: latência dos dois bancos dele (aplicação e
 * corpus de jurisprudência) e o cache, mais quanto cada agente de IA (estratégia,
 * pesquisa, redação...) tem demorado e acertado nas últimas 24h.
 *
 * Fala só com `/api/agente/saude`, que é o Acervo repassando o `/health/inspection`
 * do agente — a tela nunca conhece o endereço nem o token dele.
 */

import { useCallback, useEffect, useState } from "react";

import { Aviso, Selo } from "@/components/Basicos";
import { ApiError } from "@/lib/api";
import {
  saudeDoAgente,
  type DependenciaAgente,
  type DesempenhoAgente,
  type SaudeAgente as SaudeAgenteDados,
} from "@/lib/agente";
import estilos from "./SaudeAgente.module.css";

interface Props {
  onVoltar: () => void;
}

const NOME_DEPENDENCIA: Record<string, string> = {
  database: "Banco de aplicação",
  cache: "Cache (Redis)",
  jurisprudence: "Corpus de jurisprudência",
};

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
    <div className={estilos.cartaoDependencia}>
      <span className={estilos.nomeDependencia}>{nome}</span>
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
      <td>{item.agent_name}</td>
      <td className={estilos.meta}>{item.task}</td>
      <td>{item.runs}</td>
      <td>{item.avg_duration_ms.toLocaleString("pt-BR")} ms</td>
      <td>{item.max_duration_ms.toLocaleString("pt-BR")} ms</td>
      {raciocinio ? (
        <>
          <td>{raciocinio.avg_call_latency_ms.toLocaleString("pt-BR")} ms</td>
          <td className={estilos.meta}>
            {raciocinio.min_call_latency_ms.toLocaleString("pt-BR")}–
            {raciocinio.max_call_latency_ms.toLocaleString("pt-BR")} ms
          </td>
        </>
      ) : (
        <td colSpan={2} className={estilos.meta}>
          sem chamada ao modelo
        </td>
      )}
      <td>
        <Selo tom={item.success_rate >= 0.9 ? "ok" : item.success_rate >= 0.5 ? "atencao" : "critico"}>
          {(item.success_rate * 100).toFixed(0)}%
        </Selo>
      </td>
      <td className={estilos.meta}>{ultimaExecucao}</td>
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
    <div className={estilos.container}>
      <button type="button" className="botao botao--secundario" onClick={onVoltar}>
        ← Voltar para a carteira
      </button>

      <header className={estilos.cabecalho}>
        <div>
          <h1>Saúde do agente jurídico</h1>
          <p>
            Latência dos dois bancos que o agente usa e o desempenho de cada tipo de
            geração (estratégia, pesquisa, redação, classificação...) nas últimas
            {" "}
            {dados?.agents?.window_hours ?? 24} horas. &ldquo;Duração&rdquo; é o tempo
            do agente inteiro, incluindo retentativa quando o modelo erra o formato;
            &ldquo;raciocínio&rdquo; é só a chamada ao modelo — quando os dois divergem
            muito, o agente está retentando, não o provedor lento.
          </p>
        </div>
        <button
          type="button"
          className="botao botao--secundario botao--pequeno"
          onClick={() => void carregar()}
          disabled={carregando}
        >
          {carregando ? "Atualizando…" : "Atualizar"}
        </button>
      </header>

      {atualizadoEm && !carregando && (
        <p className={estilos.meta}>Atualizado às {atualizadoEm.toLocaleTimeString("pt-BR")}</p>
      )}

      {erro && (
        <Aviso tom="critico" titulo="Não foi possível carregar">
          {erro}
        </Aviso>
      )}

      {carregando && !dados && <p className={estilos.vazio}>Carregando…</p>}

      {dados && !dados.ligado && (
        <Aviso tom="atencao" titulo="Agente não configurado">
          A integração com o agente jurídico está desligada neste ambiente
          (`AGENTE_API_URL` vazio).
        </Aviso>
      )}

      {dados?.ligado && dados.dependencies && (
        <section className={estilos.secao}>
          <h2>Bancos e cache</h2>
          <div className={estilos.grade}>
            {Object.entries(dados.dependencies).map(([chave, dep]) => (
              <CartaoDependencia key={chave} nome={NOME_DEPENDENCIA[chave] ?? chave} dep={dep} />
            ))}
          </div>
        </section>
      )}

      {dados?.ligado && dados.agents && (
        <section className={estilos.secao}>
          <h2>Desempenho por agente</h2>
          {dados.agents.by_agent.length === 0 ? (
            <p className={estilos.vazio}>
              Nenhuma execução de IA nas últimas {dados.agents.window_hours} horas.
            </p>
          ) : (
            <div className={estilos.tabelaScroll}>
              <table className={estilos.tabela}>
                <thead>
                  <tr>
                    <th>Agente</th>
                    <th>Tarefa</th>
                    <th>Execuções</th>
                    <th>Duração média</th>
                    <th>Duração máxima</th>
                    <th>Raciocínio (média)</th>
                    <th>Raciocínio (mín–máx)</th>
                    <th>Taxa de sucesso</th>
                    <th>Última execução</th>
                  </tr>
                </thead>
                <tbody>{dados.agents.by_agent.map(linhaDoAgente)}</tbody>
              </table>
            </div>
          )}
        </section>
      )}
    </div>
  );
}
