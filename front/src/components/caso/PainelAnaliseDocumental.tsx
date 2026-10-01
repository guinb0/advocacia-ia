"use client";

import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { Loader2 } from "lucide-react";

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

/* Resultado da SKILL DOCUMENTAL (não o texto dela). A tela responde três perguntas, nesta ordem:
 * os documentos estão bons? o que eu faço agora? e, só para quem quiser, o que a análise viu.
 * Cada item mostra "de onde saiu" (documento + trecho) dentro dos detalhes. */

type Status = AnaliseDocumental["status"];
type Resultado = NonNullable<AnaliseDocumental["resultado"]>;

const EM_ANDAMENTO: Status[] = ["queued", "processing", "analyzing"];

/** A partir daqui a tela oferece recomeçar: a análise normal leva de 1 a 5 minutos. */
const MINUTOS_PARA_OFERECER_RECOMECO = 10;

const ETAPA_EM_ANDAMENTO: Record<string, string> = {
  queued: "Na fila para começar…",
  processing: "Juntando o que foi lido de cada documento…",
  analyzing: "Analisando os documentos…",
};

const CLASSE_FALTANTE = {
  COMPROMETE: { tom: "critico", simbolo: "🔴", texto: "COMPROMETE" },
  ERA_MELHOR_TER: { tom: "atencao", simbolo: "🟡", texto: "AJUDARIA" },
  NAO_INTERFERE: { tom: "neutro", simbolo: "⚪", texto: "NÃO INTERFERE" },
} as const;

/** O backend manda a frase para a pessoa e, depois de "Detalhe técnico:", o que é para o suporte. */
function separarErro(erro: string | undefined): { frase: string; detalhe: string } {
  const texto = (erro ?? "").trim();
  const corte = texto.indexOf("Detalhe técnico:");
  if (corte < 0) return { frase: texto || "A análise não terminou.", detalhe: "" };
  return { frase: texto.slice(0, corte).trim(), detalhe: texto.slice(corte).trim() };
}

const contradicoesAbertas = (r: Resultado) =>
  r.inconsistencias.filter((i) => !i.estado || i.estado === "DETECTED" || i.estado === "NEEDS_CONFIRMATION");
const faltantesGraves = (r: Resultado) =>
  r.documentos_faltantes.filter((f) => f.classificacao === "COMPROMETE" && f.estado !== "REJECTED");

/** Quantas coisas a análise ainda manda fazer (o que aparece em "O que fazer agora"). */
function pendenciasDaAnalise(r: Resultado | undefined): number {
  if (!r) return 0;
  return contradicoesAbertas(r).length + faltantesGraves(r).length + r.perguntas.filter((p) => !p.resposta).length;
}

function minutosDesde(iso: string | undefined): number {
  if (!iso) return 0;
  const ms = Date.now() - new Date(iso).getTime();
  return Number.isFinite(ms) ? ms / 60_000 : 0;
}

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

function Veredito({ resultado }: { resultado: Resultado }) {
  const contradicoes = resultado.inconsistencias.filter((i) => i.estado !== "REJECTED");
  const compromete = resultado.documentos_faltantes.filter(
    (f) => f.classificacao === "COMPROMETE" && f.estado !== "REJECTED",
  );
  const positivo = !contradicoes.length && !compromete.length && resultado.diagnostico?.sentido !== "NEGATIVO";
  const motivo =
    resultado.diagnostico?.sentido === (positivo ? "POSITIVO" : "NEGATIVO") && resultado.diagnostico.motivo
      ? resultado.diagnostico.motivo
      : positivo
        ? "Os documentos não se contradizem e não falta nenhum documento importante."
        : "Há pontos nos documentos que precisam ser resolvidos antes da peça.";
  return (
    <div
      className={
        positivo
          ? "flex gap-3 rounded-cartao border-2 border-ok-borda bg-ok-claro p-4"
          : "flex gap-3 rounded-cartao border-2 border-critico-borda bg-critico-claro p-4"
      }
    >
      <span
        aria-hidden
        className={`grid h-10 w-10 flex-none place-items-center rounded-full text-xl font-bold text-papel ${positivo ? "bg-ok" : "bg-critico"}`}
      >
        {positivo ? "✓" : "!"}
      </span>
      <div>
        <strong className="block text-lg leading-tight text-tinta">
          {positivo ? "Os documentos estão em ordem" : "Os documentos precisam de atenção"}
        </strong>
        <p className="m-0 mt-1 text-sm text-tinta-2">{motivo}</p>
      </div>
    </div>
  );
}

/** Um cartão de "o que fazer": número grande, o que fazer em negrito, e o porquê embaixo. */
function Tarefa({
  numero,
  titulo,
  tom,
  children,
}: {
  numero: number;
  titulo: string;
  tom: "critico" | "atencao" | "info";
  children: ReactNode;
}) {
  const cor = { critico: "bg-critico", atencao: "bg-atencao", info: "bg-acao" }[tom];
  return (
    <li className="flex gap-3 rounded-campo border border-borda bg-papel p-3">
      <span
        aria-hidden
        className={`grid h-8 w-8 flex-none place-items-center rounded-full text-sm font-bold text-papel ${cor}`}
      >
        {numero}
      </span>
      <div className="min-w-0 flex-1 text-sm">
        <strong className="block text-base leading-snug text-tinta">{titulo}</strong>
        {children}
      </div>
    </li>
  );
}

export default function PainelAnaliseDocumental({
  casoId,
  iniciarSozinho = false,
  mostrarContinuar = true,
  onStatus,
}: {
  casoId: string;
  /** Na documentação a análise da skill começa sozinha, uma vez por caso, se ainda não houver resultado. */
  iniciarSozinho?: boolean;
  /** "Continuar para elaboração da peça" só faz sentido onde a peça está na mesma tela (dossiê). */
  mostrarContinuar?: boolean;
  /** Estado da análise e quantas pendências ela ainda aponta. */
  onStatus?: (status: Status, pendencias: number) => void;
}) {
  const [analise, setAnalise] = useState<AnaliseDocumental | null>(null);
  const [erro, setErro] = useState<string | null>(null);
  const [respostas, setRespostas] = useState<Record<string, string>>({});
  const [plano, setPlano] = useState<PlanoDeOrganizacao | null>(null);
  const [ocupado, setOcupado] = useState<string | null>(null);
  const temporizador = useRef<ReturnType<typeof setTimeout> | null>(null);
  const disparouSozinho = useRef<string | null>(null);
  const montado = useRef(true);

  const status: Status = analise?.status ?? "none";
  const pendencias = pendenciasDaAnalise(analise?.resultado);
  useEffect(() => {
    onStatus?.(status, pendencias);
  }, [onStatus, status, pendencias]);

  const carregar = useCallback(async () => {
    try {
      const atual = await obterAnaliseDocumental(casoId);
      setAnalise(atual);
      setErro(null);
      return atual;
    } catch (e) {
      setErro(e instanceof Error ? e.message : "Não foi possível ler a análise dos documentos.");
      return null;
    }
  }, [casoId]);

  /* Polling enquanto a fila trabalha: queued → processing → analyzing → ready|error.
   * Na documentação, se ainda não há análise, dispara a skill uma vez. */
  const ciclo = useCallback(async () => {
    const atual = await carregar();
    if (!montado.current) return;
    if (iniciarSozinho && disparouSozinho.current !== casoId && atual?.status === "none") {
      disparouSozinho.current = casoId;
      try {
        setAnalise(await iniciarAnaliseDocumental(casoId));
      } catch (e) {
        setErro(e instanceof Error ? e.message : "Não foi possível começar a análise.");
        return;
      }
      temporizador.current = setTimeout(() => void ciclo(), 2500);
      return;
    }
    if (atual && EM_ANDAMENTO.includes(atual.status)) {
      temporizador.current = setTimeout(() => void ciclo(), 4000);
    }
  }, [carregar, casoId, iniciarSozinho]);

  useEffect(() => {
    montado.current = true;
    void ciclo();
    return () => {
      montado.current = false;
      if (temporizador.current) clearTimeout(temporizador.current);
    };
  }, [ciclo]);

  const iniciar = async () => {
    setErro(null);
    setOcupado("analise");
    try {
      setAnalise(await iniciarAnaliseDocumental(casoId));
      if (temporizador.current) clearTimeout(temporizador.current);
      temporizador.current = setTimeout(() => void ciclo(), 2500);
    } catch (e) {
      setErro(e instanceof Error ? e.message : "Não foi possível começar a análise.");
    } finally {
      setOcupado(null);
    }
  };

  const executar = async (chave: string, acao: () => Promise<unknown>, falha: string) => {
    setOcupado(chave);
    try {
      await acao();
    } catch (e) {
      setErro(e instanceof Error ? e.message : falha);
    } finally {
      setOcupado(null);
    }
  };

  const enviarResposta = (perguntaId: string) => {
    const texto = (respostas[perguntaId] ?? "").trim();
    if (!texto) return;
    void executar(
      perguntaId,
      async () => {
        await responderPerguntaDocumental(casoId, perguntaId, texto);
        await carregar();
      },
      "Não foi possível salvar a resposta.",
    );
  };

  const marcar = (id: string, novo: "CONFIRMED" | "REJECTED") =>
    void executar(
      id,
      async () => {
        await definirEstadoInsight(casoId, id, novo);
        await carregar();
      },
      "Não foi possível registrar.",
    );

  const continuar = () =>
    void executar(
      "continuar",
      async () => {
        await continuarParaAPeca(casoId);
        document.getElementById("fluxo-peticao")?.scrollIntoView({ behavior: "smooth", block: "start" });
      },
      "Não foi possível continuar.",
    );

  const r = analise?.resultado;
  const nome = (id: string) => r?.documentos.find((d) => d.documento_id === id)?.arquivo ?? id;

  return (
    <section className="space-y-4" aria-label="Análise dos documentos">
      {erro && (
        <Aviso tom="critico" titulo="Algo deu errado">
          {erro}
        </Aviso>
      )}

      {status === "none" && !erro && (
        <div className="rounded-cartao border border-borda bg-papel-2 p-4">
          <p className="m-0 text-base text-tinta">A análise ainda não foi feita.</p>
          <p className="m-0 mt-1 text-sm text-tinta-2">
            Clique no botão quando os documentos já estiverem enviados. O sistema lê todos eles e diz o que está
            errado ou faltando.
          </p>
          <Botao variante="primario" className="mt-3" carregando={ocupado === "analise"} onClick={iniciar}>
            Analisar os documentos
          </Botao>
        </div>
      )}

      {EM_ANDAMENTO.includes(status) && (
        <div className="rounded-cartao border border-acao-borda bg-acao-clara p-4" role="status">
          <div className="flex items-center gap-3">
            <Loader2 aria-hidden className="size-6 flex-none animate-spin text-acao" />
            <div>
              <strong className="block text-base text-tinta">{ETAPA_EM_ANDAMENTO[status]}</strong>
              <span className="text-sm text-tinta-2">
                Leva de 1 a 5 minutos. Pode fazer outra coisa: a análise continua e esta tela atualiza sozinha.
              </span>
            </div>
          </div>
          {minutosDesde(analise?.iniciada_em) > MINUTOS_PARA_OFERECER_RECOMECO && (
            <div className="mt-3 flex flex-wrap items-center gap-3 border-t border-acao-borda pt-3 text-sm">
              <span>Está demorando mais que o normal?</span>
              <Botao pequeno carregando={ocupado === "analise"} onClick={iniciar}>
                Recomeçar a análise
              </Botao>
            </div>
          )}
        </div>
      )}

      {status === "error" && (
        <div className="rounded-cartao border-2 border-critico-borda bg-critico-claro p-4" role="alert">
          <strong className="block text-base text-tinta">A análise não terminou</strong>
          <p className="m-0 mt-1 text-sm text-tinta-2">{separarErro(analise?.erro).frase}</p>
          <Botao variante="primario" className="mt-3" carregando={ocupado === "analise"} onClick={iniciar}>
            Tentar de novo
          </Botao>
          {separarErro(analise?.erro).detalhe && (
            <details className="mt-3 text-xs text-tinta-3">
              <summary className="cursor-pointer">Detalhe para o suporte</summary>
              <p className="m-0 mt-1 [overflow-wrap:anywhere]">{separarErro(analise?.erro).detalhe}</p>
            </details>
          )}
        </div>
      )}

      {status === "ready" && r && (
        <Pronta
          r={r}
          nome={nome}
          respostas={respostas}
          setRespostas={setRespostas}
          ocupado={ocupado}
          enviarResposta={enviarResposta}
          marcar={marcar}
          plano={plano}
          verPlano={() =>
            void executar("plano", async () => setPlano(await planoDeOrganizacao(casoId)), "Falha ao montar o plano.")
          }
          confirmarPlano={() =>
            void executar("org", async () => setPlano(await confirmarOrganizacao(casoId)), "Falha ao organizar.")
          }
          analise={analise}
          analisarDeNovo={iniciar}
          mostrarContinuar={mostrarContinuar}
          continuar={continuar}
        />
      )}
    </section>
  );
}

function Pronta({
  r,
  nome,
  respostas,
  setRespostas,
  ocupado,
  enviarResposta,
  marcar,
  plano,
  verPlano,
  confirmarPlano,
  analise,
  analisarDeNovo,
  mostrarContinuar,
  continuar,
}: {
  r: Resultado;
  nome: (id: string) => string;
  respostas: Record<string, string>;
  setRespostas: (r: Record<string, string>) => void;
  ocupado: string | null;
  enviarResposta: (id: string) => void;
  marcar: (id: string, novo: "CONFIRMED" | "REJECTED") => void;
  plano: PlanoDeOrganizacao | null;
  verPlano: () => void;
  confirmarPlano: () => void;
  analise: AnaliseDocumental | null;
  analisarDeNovo: () => void;
  mostrarContinuar: boolean;
  continuar: () => void;
}) {
  const contradicoes = contradicoesAbertas(r);
  const aResolver = r.inconsistencias.filter((i) => i.estado === "CONFIRMED" || i.estado === "CORRECTED");
  const faltamGraves = faltantesGraves(r);
  const ajudariam = r.documentos_faltantes.filter((f) => f.classificacao === "ERA_MELHOR_TER" && f.estado !== "REJECTED");
  const naoInterferem = r.documentos_faltantes.filter((f) => f.classificacao === "NAO_INTERFERE");
  const perguntasAbertas = r.perguntas.filter((p) => !p.resposta);
  const perguntasRespondidas = r.perguntas.filter((p) => p.resposta);
  const temTarefa = contradicoes.length + faltamGraves.length + perguntasAbertas.length > 0;
  let numero = 0;

  return (
    <>
      <Veredito resultado={r} />

      <div>
        <h3 className="m-0 mb-2 text-base font-semibold text-tinta">O que fazer agora</h3>
        {!temTarefa ? (
          <Aviso tom="ok" titulo="Nada para resolver aqui">
            Pode seguir para o próximo passo.
          </Aviso>
        ) : (
          <ol className="m-0 list-none space-y-2 p-0">
            {contradicoes.map((i) => (
              <Tarefa key={i.id} numero={++numero} tom="critico" titulo={`Resolver: ${i.titulo}`}>
                {i.impacto && <p className="m-0 mt-1 text-tinta-2">Por que importa: {i.impacto}</p>}
                {i.acao_sugerida && <p className="m-0 mt-1 text-tinta-2">O que fazer: {i.acao_sugerida}</p>}
                <details className="mt-1 text-xs text-tinta-3">
                  <summary className="cursor-pointer">Ver onde os documentos divergem</summary>
                  {i.fontes.map((f, n) => (
                    <div key={n} className="mt-1">
                      <span>{f.arquivo ?? f.origem}:</span> <code>{f.valor || f.citacao}</code>
                      <Origem arquivo={f.arquivo ?? String(f.origem)} pagina={f.pagina} trecho={f.citacao} />
                    </div>
                  ))}
                </details>
                <div className="mt-2 flex flex-wrap gap-2">
                  <Botao pequeno variante="primario" carregando={ocupado === i.id} onClick={() => marcar(i.id, "CONFIRMED")}>
                    Entendi, vou resolver
                  </Botao>
                  <Botao pequeno variante="discreto" onClick={() => marcar(i.id, "REJECTED")}>
                    Não é problema
                  </Botao>
                </div>
              </Tarefa>
            ))}

            {faltamGraves.map((f) => (
              <Tarefa key={f.id} numero={++numero} tom="critico" titulo={`Conseguir o documento: ${f.documento}`}>
                <p className="m-0 mt-1 text-tinta-2">Sem ele, fica comprometido: {f.hipotese}</p>
                <p className="m-0 mt-1 text-tinta-2">Como conseguir: {f.como_obter}</p>
                {(f.responsavel || f.prazo_ou_dificuldade) && (
                  <p className="m-0 mt-1 text-xs text-tinta-3">
                    {f.responsavel && `Quem providencia: ${f.responsavel}`}
                    {f.responsavel && f.prazo_ou_dificuldade ? " · " : ""}
                    {f.prazo_ou_dificuldade}
                  </p>
                )}
              </Tarefa>
            ))}

            {perguntasAbertas.map((p) => (
              <Tarefa key={p.id} numero={++numero} tom="atencao" titulo={`Responder: ${p.pergunta}`}>
                {p.motivo && <p className="m-0 mt-1 text-xs text-tinta-3">Por que perguntamos: {p.motivo}</p>}
                <div className="mt-2 flex flex-wrap gap-2">
                  <input
                    className="min-w-[220px] flex-1 rounded-campo border border-borda-campo bg-papel px-3 py-2 text-sm"
                    value={respostas[p.id] ?? ""}
                    onChange={(e) => setRespostas({ ...respostas, [p.id]: e.target.value })}
                    onKeyDown={(e) => {
                      if (e.key === "Enter") enviarResposta(p.id);
                    }}
                    placeholder="Escreva a resposta aqui"
                  />
                  <Botao pequeno variante="primario" carregando={ocupado === p.id} onClick={() => enviarResposta(p.id)}>
                    Salvar resposta
                  </Botao>
                </div>
              </Tarefa>
            ))}
          </ol>
        )}
      </div>

      {ajudariam.length > 0 && (
        <details className="rounded-campo border border-borda bg-papel p-3 text-sm">
          <summary className="cursor-pointer font-semibold">
            Documentos que ajudariam, mas não são obrigatórios ({ajudariam.length})
          </summary>
          <ul className="m-0 mt-2 space-y-2 pl-5">
            {ajudariam.map((f) => (
              <li key={f.id}>
                <strong>{f.documento}</strong> — {f.como_obter}
              </li>
            ))}
          </ul>
        </details>
      )}

      <details className="rounded-campo border border-borda bg-papel p-3 text-sm">
        <summary className="cursor-pointer font-semibold">Ver a análise completa</summary>
        <div className="mt-3 space-y-4">
          {(r.resumo_do_caso.questao_central || r.resumo_do_caso.objetivo_do_cliente) && (
            <div>
              <h4 className="m-0 text-sm font-semibold">Resumo do caso</h4>
              <p className="m-0 mt-1">{r.resumo_do_caso.questao_central}</p>
              {r.resumo_do_caso.objetivo_do_cliente && (
                <p className="m-0 mt-1 text-xs text-tinta-3">Objetivo do cliente: {r.resumo_do_caso.objetivo_do_cliente}</p>
              )}
            </div>
          )}

          {aResolver.length > 0 && (
            <div>
              <h4 className="m-0 text-sm font-semibold">Contradições marcadas para resolver</h4>
              <ul className="m-0 mt-1 pl-5">
                {aResolver.map((i) => (
                  <li key={i.id}>{i.titulo}</li>
                ))}
              </ul>
            </div>
          )}

          {r.fatos_extraidos.length > 0 && (
            <div>
              <h4 className="m-0 text-sm font-semibold">O que os documentos mostram</h4>
              <p className="m-0 mt-1 text-xs text-tinta-3">
                Confirme o que estiver certo e rejeite o que estiver errado. O que for rejeitado não vai para a peça.
              </p>
              <ul className="m-0 mt-2 grid list-none gap-2 p-0 md:grid-cols-2">
                {r.fatos_extraidos
                  .filter((f) => f.estado !== "REJECTED")
                  .map((f) => (
                    <li key={f.id} className="rounded-campo border border-borda p-2">
                      <div>
                        {f.fato} {f.estado === "CONFIRMED" && <Selo tom="ok">confirmado</Selo>}
                      </div>
                      <Origem arquivo={f.proveniencia.arquivo} pagina={f.proveniencia.pagina} trecho={f.proveniencia.citacao} />
                      {f.estado !== "CONFIRMED" && (
                        <div className="mt-1 flex gap-2">
                          <Botao pequeno onClick={() => marcar(f.id, "CONFIRMED")}>
                            Está certo
                          </Botao>
                          <Botao pequeno variante="discreto" onClick={() => marcar(f.id, "REJECTED")}>
                            Está errado
                          </Botao>
                        </div>
                      )}
                    </li>
                  ))}
              </ul>
            </div>
          )}

          {r.provas.length > 0 && (
            <div>
              <h4 className="m-0 text-sm font-semibold">Provas encontradas</h4>
              <ul className="m-0 mt-1 list-none space-y-1 p-0">
                {r.provas.map((p) => (
                  <li key={p.id}>
                    <Selo tom={p.status === "SUFICIENTE" ? "ok" : "atencao"}>
                      {p.status === "SUFICIENTE" ? "prova boa" : "prova fraca"}
                    </Selo>{" "}
                    {p.fato} — <span className="text-tinta-3">{p.documento_ids.map(nome).join(", ")}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {perguntasRespondidas.length > 0 && (
            <div>
              <h4 className="m-0 text-sm font-semibold">Perguntas já respondidas</h4>
              <ul className="m-0 mt-1 pl-5">
                {perguntasRespondidas.map((p) => (
                  <li key={p.id}>
                    {p.pergunta} <span className="text-tinta-3">→ {p.resposta}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {naoInterferem.length > 0 && (
            <div>
              <h4 className="m-0 text-sm font-semibold">Documentos que não fazem diferença</h4>
              <ul className="m-0 mt-1 pl-5">
                {naoInterferem.map((f) => (
                  <li key={f.id}>
                    {f.documento}{" "}
                    <Selo tom={CLASSE_FALTANTE.NAO_INTERFERE.tom} simbolo={CLASSE_FALTANTE.NAO_INTERFERE.simbolo}>
                      {CLASSE_FALTANTE.NAO_INTERFERE.texto}
                    </Selo>
                  </li>
                ))}
              </ul>
            </div>
          )}

          <div>
            <h4 className="m-0 text-sm font-semibold">Documento por documento ({r.documentos.length})</h4>
            {r.documentos.map((d) => (
              <div key={d.documento_id} className="mt-2 rounded-campo border border-borda p-3">
                <strong>{d.tipo}</strong> <span className="text-tinta-3">{d.arquivo}</span>{" "}
                {!d.legivel && <Selo tom="critico">ilegível</Selo>} {d.duplicado_de && <Selo tom="atencao">repetido</Selo>}{" "}
                {d.atualizacao === "DESATUALIZADO" && <Selo tom="atencao">desatualizado</Selo>}
                {d.pontos_fortes.length > 0 && <p className="m-0 mt-1">✅ {d.pontos_fortes.join("; ")}</p>}
                {d.vulnerabilidades.length > 0 && <p className="m-0 mt-1">⚠️ {d.vulnerabilidades.join("; ")}</p>}
                {d.motivo_atualizacao && <p className="m-0 mt-1 text-tinta-3">{d.motivo_atualizacao}</p>}
              </div>
            ))}
          </div>

          <div className="space-y-2 rounded-campo border border-borda p-3">
            <h4 className="m-0 text-sm font-semibold">Organizar a pasta do caso (opcional)</h4>
            <p className="m-0 text-xs text-tinta-3">
              Gera um PDF por documento, com nome e ordem padronizados. Os arquivos originais não mudam.
            </p>
            {!plano || plano.status === "none" ? (
              <Botao pequeno carregando={ocupado === "plano"} onClick={verPlano}>
                Ver como a pasta vai ficar
              </Botao>
            ) : (
              <>
                <ul className="m-0 pl-5 text-xs">
                  {plano.plano?.resumo.documentos.map((d) => (
                    <li key={d.documento_id + d.nome_final}>
                      {d.nome_final}
                      {d.duplicado ? " (repetido — será mantido)" : ""}
                    </li>
                  ))}
                </ul>
                {plano.plano?.resumo.problemas.map((p, n) => (
                  <Aviso key={n} tom="atencao">
                    {p.arquivo}: {p.problema}
                  </Aviso>
                ))}
                {plano.status === "aguardando_confirmacao" && (
                  <Botao variante="primario" pequeno carregando={ocupado === "org"} onClick={confirmarPlano}>
                    Confirmar e organizar
                  </Botao>
                )}
                {plano.status === "concluida" && (
                  <Aviso tom="ok">Pasta organizada. Os arquivos originais foram preservados.</Aviso>
                )}
              </>
            )}
          </div>

          <div className="flex flex-wrap items-center gap-3 border-t border-borda pt-3 text-xs text-tinta-3">
            <span>
              Chegaram documentos novos depois desta análise? Faça de novo para incluir.
              {analise?.skill_sha256 ? ` (skill ${analise.skill_name}, versão ${analise.skill_sha256.slice(0, 8)})` : ""}
            </span>
            <Botao pequeno carregando={ocupado === "analise"} onClick={analisarDeNovo}>
              Analisar de novo
            </Botao>
          </div>
        </div>
      </details>

      {mostrarContinuar && (
        <div className="flex flex-wrap items-center justify-between gap-2 border-t border-borda pt-3">
          <p className="m-0 text-xs text-tinta-3">
            {perguntasAbertas.length > 0
              ? `${perguntasAbertas.length} pergunta(s) sem resposta — a peça vai tratar como pendência.`
              : "Nada pendente de resposta."}
          </p>
          <Botao variante="primario" carregando={ocupado === "continuar"} onClick={continuar}>
            Continuar para elaboração da peça
          </Botao>
        </div>
      )}
    </>
  );
}
