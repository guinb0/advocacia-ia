"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import {
  confirmarOrganizacao,
  continuarParaAPeca,
  definirEstadoInsight,
  iniciarAnaliseDocumental,
  obterAnaliseDocumental,
  planoDeOrganizacao,
  responderPerguntaDocumental,
  type AnaliseDocumental,
  type PlanoDeOrganizacao,
} from "@/lib/api";
import { Aviso, Botao, Selo } from "@/components/ui/Basicos";

/* Resultado da SKILL DOCUMENTAL (não o texto dela): resumo, pontos, inconsistências (com impacto
 * e ação), provas, faltantes classificados, documento a documento e as perguntas que só o
 * advogado responde. Cada item mostra "de onde saiu" (documento + trecho). */

const ROTULO_STATUS: Record<AnaliseDocumental["status"], string> = {
  none: "Ainda não analisado",
  queued: "Na fila",
  processing: "Lendo os documentos…",
  analyzing: "Analisando pela skill documental…",
  ready: "Análise pronta",
  error: "A análise falhou",
};

const CLASSE_FALTANTE = {
  COMPROMETE: { tom: "critico", simbolo: "🔴", texto: "COMPROMETE" },
  ERA_MELHOR_TER: { tom: "atencao", simbolo: "🟡", texto: "ERA MELHOR TER, MAS PODE PASSAR" },
  NAO_INTERFERE: { tom: "neutro", simbolo: "⚪", texto: "NÃO INTERFERE" },
} as const;

function Origem({ arquivo, pagina, trecho }: { arquivo: string; pagina?: number | null; trecho: string }) {
  return (
    <details className="mt-1 text-xs text-tinta-3">
      <summary className="cursor-pointer">
        De onde isso saiu? — {arquivo}
        {pagina ? `, p. ${pagina}` : ""}
      </summary>
      <blockquote className="mt-1 border-l-2 border-borda pl-2 italic">“{trecho}”</blockquote>
    </details>
  );
}

export default function PainelAnaliseDocumental({ casoId }: { casoId: string }) {
  const [analise, setAnalise] = useState<AnaliseDocumental | null>(null);
  const [erro, setErro] = useState<string | null>(null);
  const [respostas, setRespostas] = useState<Record<string, string>>({});
  const [plano, setPlano] = useState<PlanoDeOrganizacao | null>(null);
  const [ocupado, setOcupado] = useState<string | null>(null);
  const temporizador = useRef<ReturnType<typeof setTimeout> | null>(null);

  const carregar = useCallback(async () => {
    try {
      const atual = await obterAnaliseDocumental(casoId);
      setAnalise(atual);
      return atual;
    } catch (e) {
      setErro(e instanceof Error ? e.message : "Não foi possível ler a análise documental.");
      return null;
    }
  }, [casoId]);

  /* Polling enquanto a fila trabalha: queued → processing → analyzing → ready|error. */
  useEffect(() => {
    let vivo = true;
    const ciclo = async () => {
      const atual = await carregar();
      if (vivo && atual && ["queued", "processing", "analyzing"].includes(atual.status)) {
        temporizador.current = setTimeout(ciclo, 4000);
      }
    };
    void ciclo();
    return () => {
      vivo = false;
      if (temporizador.current) clearTimeout(temporizador.current);
    };
  }, [carregar]);

  const iniciar = async () => {
    setErro(null);
    setOcupado("analise");
    try {
      setAnalise(await iniciarAnaliseDocumental(casoId));
      temporizador.current = setTimeout(() => void carregar(), 2500);
    } catch (e) {
      setErro(e instanceof Error ? e.message : "Não foi possível iniciar a análise.");
    } finally {
      setOcupado(null);
    }
  };

  const r = analise?.resultado;
  const nome = (id: string) => r?.documentos.find((d) => d.documento_id === id)?.arquivo ?? id;
  const emAndamento = !!analise && ["queued", "processing", "analyzing"].includes(analise.status);
  const semResposta = (r?.perguntas ?? []).filter((p) => !p.resposta).length;

  const enviarResposta = async (perguntaId: string) => {
    const texto = (respostas[perguntaId] ?? "").trim();
    if (!texto) return;
    setOcupado(perguntaId);
    try {
      await responderPerguntaDocumental(casoId, perguntaId, texto);
      await carregar();
    } catch (e) {
      setErro(e instanceof Error ? e.message : "Não foi possível salvar a resposta.");
    } finally {
      setOcupado(null);
    }
  };

  const estado = async (id: string, novo: "CONFIRMED" | "REJECTED") => {
    try {
      await definirEstadoInsight(casoId, id, novo);
      await carregar();
    } catch (e) {
      setErro(e instanceof Error ? e.message : "Não foi possível registrar.");
    }
  };

  const continuar = async () => {
    setOcupado("continuar");
    try {
      await continuarParaAPeca(casoId);
      document.getElementById("fluxo-peticao")?.scrollIntoView({ behavior: "smooth", block: "start" });
    } catch (e) {
      setErro(e instanceof Error ? e.message : "Não foi possível continuar.");
    } finally {
      setOcupado(null);
    }
  };

  const verPlano = async () => {
    setOcupado("plano");
    try {
      setPlano(await planoDeOrganizacao(casoId));
    } catch (e) {
      setErro(e instanceof Error ? e.message : "Falha ao montar o plano.");
    } finally {
      setOcupado(null);
    }
  };

  const confirmar = async () => {
    setOcupado("org");
    try {
      setPlano(await confirmarOrganizacao(casoId));
    } catch (e) {
      setErro(e instanceof Error ? e.message : "Falha ao organizar.");
    } finally {
      setOcupado(null);
    }
  };

  return (
    <section
      className="space-y-4 rounded-campo border border-borda bg-papel p-4"
      aria-label="Análise dos documentos pela skill documental"
    >
      <header className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h2 className="text-base font-semibold">Análise dos documentos</h2>
          <p className="text-xs text-tinta-3">
            {ROTULO_STATUS[analise?.status ?? "none"]}
            {analise?.skill_sha256 ? ` · skill ${analise.skill_name} (${analise.skill_sha256.slice(0, 8)})` : ""}
          </p>
        </div>
        <Botao variante="primario" carregando={ocupado === "analise" || emAndamento} textoCarregando="Analisando…" onClick={iniciar}>
          {r ? "Analisar de novo" : "Analisar documentos"}
        </Botao>
      </header>

      {erro && <Aviso tom="critico">{erro}</Aviso>}
      {analise?.status === "error" && (
        <Aviso tom="critico" titulo="A análise falhou">
          {analise.erro}
        </Aviso>
      )}

      {r && (
        <>
          <div>
            <h3 className="text-sm font-semibold">Resumo do caso</h3>
            <p className="text-sm">{r.resumo_do_caso.questao_central}</p>
            <p className="text-xs text-tinta-3">Objetivo do cliente: {r.resumo_do_caso.objetivo_do_cliente}</p>
          </div>

          <div>
            <h3 className="text-sm font-semibold">Pontos relevantes</h3>
            <ul className="grid gap-2 md:grid-cols-2">
              {r.fatos_extraidos
                .filter((f) => f.estado !== "REJECTED")
                .map((f) => (
                  <li key={f.id} className="rounded-campo border border-borda p-2 text-sm">
                    <div>
                      {f.fato} {f.estado === "CONFIRMED" && <Selo tom="ok">confirmado</Selo>}
                    </div>
                    <Origem arquivo={f.proveniencia.arquivo} pagina={f.proveniencia.pagina} trecho={f.proveniencia.citacao} />
                    <div className="mt-1 flex gap-2">
                      <Botao pequeno onClick={() => estado(f.id, "CONFIRMED")}>
                        Confirmar
                      </Botao>
                      <Botao pequeno variante="discreto" onClick={() => estado(f.id, "REJECTED")}>
                        Rejeitar
                      </Botao>
                    </div>
                  </li>
                ))}
            </ul>
          </div>

          {r.inconsistencias.length > 0 && (
            <div>
              <h3 className="text-sm font-semibold">Inconsistências</h3>
              {r.inconsistencias
                .filter((i) => i.estado !== "REJECTED")
                .map((i) => (
                  <div key={i.id} className="mt-2 rounded-campo border border-atencao-borda bg-atencao-claro p-3 text-sm">
                    <strong>⚠ {i.titulo}</strong>
                    {i.fontes.map((f, n) => (
                      <div key={n} className="mt-1">
                        <span className="text-tinta-3">{f.arquivo ?? f.origem}:</span> <code>{f.valor || f.citacao}</code>
                        <Origem arquivo={f.arquivo ?? String(f.origem)} pagina={f.pagina} trecho={f.citacao} />
                      </div>
                    ))}
                    <p className="mt-1">
                      <strong>Impacto:</strong> {i.impacto}
                    </p>
                    <p>
                      <strong>Ação sugerida:</strong> {i.acao_sugerida}
                    </p>
                    <div className="mt-1 flex gap-2">
                      <Botao pequeno onClick={() => estado(i.id, "CONFIRMED")}>
                        É isso mesmo
                      </Botao>
                      <Botao pequeno variante="discreto" onClick={() => estado(i.id, "REJECTED")}>
                        Não é problema
                      </Botao>
                    </div>
                  </div>
                ))}
            </div>
          )}

          {r.provas.length > 0 && (
            <div>
              <h3 className="text-sm font-semibold">Provas encontradas</h3>
              <ul className="text-sm">
                {r.provas.map((p) => (
                  <li key={p.id}>
                    <Selo tom={p.status === "SUFICIENTE" ? "ok" : "atencao"}>{p.status}</Selo> {p.fato} —{" "}
                    {p.documento_ids.map(nome).join(", ")}
                  </li>
                ))}
              </ul>
            </div>
          )}

          {r.documentos_faltantes.length > 0 && (
            <div>
              <h3 className="text-sm font-semibold">Documentos faltantes</h3>
              {r.documentos_faltantes.map((f) => {
                const c = CLASSE_FALTANTE[f.classificacao];
                return (
                  <div key={f.id} className="mt-2 rounded-campo border border-borda p-3 text-sm">
                    <strong>{f.documento}</strong>{" "}
                    <Selo tom={c.tom} simbolo={c.simbolo}>
                      {c.texto}
                    </Selo>
                    <p>Necessário/útil para: {f.hipotese}</p>
                    <p>Como obter: {f.como_obter}</p>
                    <p className="text-tinta-3">
                      Responsável: {f.responsavel}
                      {f.prazo_ou_dificuldade ? ` · ${f.prazo_ou_dificuldade}` : ""}
                    </p>
                  </div>
                );
              })}
            </div>
          )}

          <details>
            <summary className="cursor-pointer text-sm font-semibold">Análise documento a documento ({r.documentos.length})</summary>
            {r.documentos.map((d) => (
              <div key={d.documento_id} className="mt-2 rounded-campo border border-borda p-3 text-sm">
                <strong>{d.tipo}</strong> <span className="text-tinta-3">{d.arquivo}</span>{" "}
                {!d.legivel && <Selo tom="critico">ilegível</Selo>} {d.duplicado_de && <Selo tom="atencao">duplicado</Selo>}{" "}
                {d.atualizacao === "DESATUALIZADO" && <Selo tom="atencao">desatualizado</Selo>}
                {d.pontos_fortes.length > 0 && <p>✅ {d.pontos_fortes.join("; ")}</p>}
                {d.vulnerabilidades.length > 0 && <p>⚠️ {d.vulnerabilidades.join("; ")}</p>}
                {d.motivo_atualizacao && (
                  <p className="text-tinta-3">
                    {d.motivo_atualizacao}
                    {d.pode_melhorar === false ? " (não pode melhorar)" : ""}
                  </p>
                )}
                {d.relacao_com_teses.map((t, n) => (
                  <p key={n} className="text-tinta-3">
                    ↳ {t.hipotese}: {t.papel}
                  </p>
                ))}
              </div>
            ))}
          </details>

          {r.perguntas.length > 0 && (
            <div>
              <h3 className="text-sm font-semibold">Perguntas que os documentos não respondem</h3>
              {r.perguntas.map((p) => (
                <div key={p.id} className="mt-2 text-sm">
                  <p>{p.pergunta}</p>
                  {p.resposta ? (
                    <p className="text-tinta-3">Resposta: {p.resposta}</p>
                  ) : (
                    <div className="mt-1 flex gap-2">
                      <input
                        className="flex-1 rounded-campo border border-borda px-2 py-1"
                        value={respostas[p.id] ?? ""}
                        onChange={(e) => setRespostas({ ...respostas, [p.id]: e.target.value })}
                        placeholder="Resposta do advogado ou do cliente"
                      />
                      <Botao pequeno carregando={ocupado === p.id} onClick={() => enviarResposta(p.id)}>
                        Responder
                      </Botao>
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}

          <div className="space-y-2 rounded-campo border border-borda p-3 text-sm">
            <h3 className="font-semibold">Organização dos documentos (1 documento = 1 PDF)</h3>
            {!plano || plano.status === "none" ? (
              <Botao carregando={ocupado === "plano"} onClick={verPlano}>
                Ver plano de organização
              </Botao>
            ) : (
              <>
                <ul className="text-xs">
                  {plano.plano?.resumo.documentos.map((d) => (
                    <li key={d.documento_id + d.nome_final}>
                      {d.nome_final}
                      {d.duplicado ? " (duplicado — será mantido)" : ""}
                    </li>
                  ))}
                </ul>
                {plano.plano?.resumo.problemas.map((p, n) => (
                  <Aviso key={n} tom="atencao">
                    {p.arquivo}: {p.problema}
                  </Aviso>
                ))}
                <p className="text-xs text-tinta-3">
                  {plano.plano?.resumo.exclusoes} Também serão gerados: {plano.plano?.resumo.arquivos_extras.join(" e ")}. Os
                  arquivos originais não são alterados.
                </p>
                {plano.status === "aguardando_confirmacao" && (
                  <Botao variante="primario" carregando={ocupado === "org"} onClick={confirmar}>
                    Confirmar e organizar
                  </Botao>
                )}
                {plano.status === "concluida" && (
                  <Aviso tom="ok">
                    Pasta organizada. Originais preservados: {plano.resultado?.originais_preservados ? "sim" : "verificar"}.
                  </Aviso>
                )}
              </>
            )}
          </div>

          <div className="flex flex-wrap items-center justify-between gap-2 border-t border-borda pt-3">
            <p className="text-xs text-tinta-3">
              {semResposta > 0
                ? `${semResposta} pergunta(s) sem resposta — a peça tratará como pendência.`
                : "Nada pendente de resposta."}{" "}
              Esta análise segue para a peça como contexto; estrutura e estilo continuam vindo da skill da peça.
            </p>
            <Botao variante="primario" carregando={ocupado === "continuar"} onClick={continuar}>
              Continuar para elaboração da peça
            </Botao>
          </div>
        </>
      )}
    </section>
  );
}
