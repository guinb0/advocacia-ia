"use client";

import { useState } from "react";
import type { CamadaJuridica as Dados } from "@/lib/agente";
import { MotorJuridico } from "./MotorJuridico";

const ROTULO_DECISAO: Record<string, string> = {
  SUPPORTED: "Incluída",
  POTENTIAL_NEEDS_CONFIRMATION: "A confirmar",
  REJECTED_NO_FACTUAL_BASIS: "Sem suporte factual",
  REJECTED_LEGAL: "Óbice jurídico",
  REJECTED_STRATEGIC: "Decisão estratégica",
};

const ROTULO_ESTADO: Record<string, string> = {
  confirmado: "confirmado",
  alegado: "alegado (só relato)",
  inferido: "inferido (sem fonte)",
};

const ROTULO_GATE: Record<string, string> = {
  LEGAL: "Base legal",
  FACT: "Fatos",
  CALCULATION: "Cálculos",
  CONSISTENCY: "Consistência",
  TEMPORAL: "Datas",
  FACT_CERTAINTY: "Certeza dos fatos",
  SEMANTIC_CONTRADICTION: "Contradição semântica",
  CITATION_GATE: "Citações",
  CROSS_SECTION: "Entre seções",
  COUNTERARGUMENT: "Contrateses",
  LEGAL_CERTAINTY: "Certeza jurídica",
  PRECEDENT_QUALITY: "Qualidade dos precedentes",
};

const ROTULO_CHECK: Record<string, string> = {
  EXISTS: "existe",
  VALID_ON_DATE: "vigente na data",
  NOT_SUPERSEDED: "não superada",
  SUPPORTS_CLAIM: "sustenta a afirmação",
};

const brl = (v: number) => v.toLocaleString("pt-BR", { style: "currency", currency: "BRL" });

function linkDoAcervo(authorityId: string): string {
  return `/home?tela=acervoJuridico&autoridade=${encodeURIComponent(authorityId)}`;
}

function Check({ nome, valor }: { nome: string; valor: boolean | null | undefined }) {
  const texto = valor === true ? "ok" : valor === false ? "falhou" : "não verificado";
  const cor = valor === true ? "border-borda" : valor === false ? "border-red-400" : "border-amber-400";
  return (
    <span className={`px-1.5 py-0.5 border text-xs ${cor}`}>
      {ROTULO_CHECK[nome] ?? nome}: {texto}
    </span>
  );
}

function Bloco({ titulo, children }: { titulo: string; children: React.ReactNode }) {
  return (
    <section className="grid gap-1">
      <h4 className="m-0 text-xs font-semibold text-tinta-2">{titulo}</h4>
      {children}
    </section>
  );
}

type Tese = Dados["teses"][number];

/** Por que a tese não entrou no corpo da peça: motivo, fatos encontrados e o que faltou, autoridades e status. */
function CartaoTeseNaoIncluida({ tese, autoridades }: { tese: Tese; autoridades: number }) {
  const necessarios = tese.fatos_necessarios ?? [];
  const detalhados = tese.fatos_detalhados ?? [];
  return (
    <li className="grid gap-1 border border-borda p-2 list-none">
      <span className="text-xs font-semibold uppercase tracking-wide text-tinta-3">Tese não incluída</span>
      <strong>{tese.tese}</strong>
      <span>
        <span className="text-tinta-3">Motivo: </span>
        {tese.rebaixada_por || tese.motivo || "não informado"}
      </span>
      {(necessarios.length > 0 || detalhados.length > 0) && (
        <div>
          <span className="text-tinta-3">Fatos encontrados:</span>
          <ul className="m-0 pl-4">
            {detalhados.map((f) => (
              <li key={f.id}>
                {f.fato}: {ROTULO_ESTADO[f.estado] ?? f.estado}
              </li>
            ))}
            {necessarios
              .filter((n) => !n.fato_id || !detalhados.some((f) => f.id === n.fato_id))
              .map((n, i) => (
                <li key={`n${i}`}>
                  {n.fato}: {n.presente ? ROTULO_ESTADO[n.estado] ?? "encontrado" : "não encontrado"}
                </li>
              ))}
          </ul>
        </div>
      )}
      <span className="text-tinta-3">Autoridades encontradas: {autoridades}</span>
      <span className="text-tinta-3">
        Status: <code>{tese.decisao}</code>
      </span>
    </li>
  );
}

/** Como a peça foi montada: teses consideradas, fonte única, base jurídica, cálculos e o resultado de cada gate. */
export function CamadaJuridica({ dados }: { dados: Dados }) {
  const [aberto, setAberto] = useState(false);
  const veredito = dados.auditoria?.veredito;
  const bloqueios = (dados.auditoria?.achados ?? []).filter((a) => a.severidade === "bloqueia");
  const alertas = (dados.auditoria?.achados ?? []).filter((a) => a.severidade !== "bloqueia");
  const incluidas = dados.teses.filter((t) => t.decisao === "SUPPORTED");
  const naoIncluidas = dados.teses.filter((t) => t.decisao !== "SUPPORTED");
  const falhas = dados.falhas ?? [];
  const sombra = dados.modo === "shadow" || dados.modo === "assistido";
  const comparacao = dados.comparacao_com_legado;

  const canonico = dados.canonico;
  const pedidos = dados.pedidos ?? [];
  const matriz = dados.matriz_tese_fato_prova ?? [];
  const divergencias = (dados.auditoria?.impressoes_digitais ?? []).filter((i) => i.ocorrencias.some((o) => !o.ok));
  const bloqueiosPorGate = bloqueios.reduce<Record<string, typeof bloqueios>>((acc, a) => {
    (acc[a.auditor] ??= []).push(a);
    return acc;
  }, {});

  const resumo = falhas.length
    ? `${falhas.length} falha(s) da camada`
    : veredito
      ? veredito.pronta
        ? "READY"
        : `BLOCKED · ${bloqueios.length} bloqueio(s)`
      : "não executada";

  return (
    <div className="grid gap-2 border border-borda p-3 bg-papel">
      <button
        type="button"
        className="flex items-center justify-between gap-2 text-left text-xs font-semibold text-tinta-3 uppercase tracking-wide bg-transparent border-0 p-0 cursor-pointer"
        onClick={() => setAberto((atual) => !atual)}
        aria-expanded={aberto}
      >
        <span>
          Auditoria jurídica
          {dados.modo === "assistido"
            ? " (modo assistido — orientou o aprofundamento e gerou pendências)"
            : sombra
              ? " (modo sombra — não alterou esta peça)"
              : ""}{" "}
          · {resumo} · {incluidas.length} de{" "}
          {dados.teses.length} teses incluídas
        </span>
        <span aria-hidden>{aberto ? "▲" : "▼"}</span>
      </button>

      {aberto && (
        <div className="grid gap-3 text-sm text-tinta-2">
          {falhas.length > 0 && (
            <Bloco titulo="Falhas da camada jurídica">
              <ul className="m-0 pl-4">
                {falhas.map((f, i) => (
                  <li key={i}>{f}</li>
                ))}
              </ul>
            </Bloco>
          )}

          {comparacao && (
            <Bloco titulo="O que mudaria nesta peça com a camada jurídica">
              <ul className="m-0 pl-4">
                <li>
                  Teses sustentadas que a peça entregue não desenvolve:{" "}
                  {comparacao.teses_sustentadas_ausentes_no_legado.join("; ") || "nenhuma"}
                </li>
                <li>
                  Teses a confirmar sem registro nas pendências:{" "}
                  {comparacao.teses_a_confirmar_sem_registro_no_legado.join("; ") || "nenhuma"}
                </li>
                <li>
                  Citações sem autoridade verificada: {comparacao.citacoes_reprovadas_no_legado.length} de{" "}
                  {comparacao.citacoes_no_legado}
                </li>
                <li>
                  Pedidos: {comparacao.pedidos.legado} na peça × {comparacao.pedidos.camada} no plano da camada
                  {comparacao.pedidos.so_na_camada.length > 0 && ` (só na camada: ${comparacao.pedidos.so_na_camada.join("; ")})`}
                </li>
                {comparacao.valor_da_causa.calculado_pela_camada != null && (
                  <li>
                    Valor da causa: declarado {comparacao.valor_da_causa.legado_declarado.map(brl).join(" / ") || "—"} × calculado{" "}
                    {brl(comparacao.valor_da_causa.calculado_pela_camada)}
                  </li>
                )}
                <li>Em modo strict, a peça {comparacao.veredito_se_fosse_strict?.pronta ? "estaria pronta" : "não estaria pronta"}.</li>
              </ul>
            </Bloco>
          )}

          {veredito && (
            <Bloco
              titulo={`Gates — ${veredito.status ?? (veredito.pronta ? "READY" : "BLOCKED")} (data da petição ${dados.data_referencia})`}
            >
              <ul className="m-0 p-0 list-none flex flex-wrap gap-2">
                {Object.entries(veredito.auditores).map(([nome, a]) => (
                  <li key={nome} className={`px-2 py-0.5 border ${a.status === "PASS" ? "border-borda" : "border-red-400"}`}>
                    {ROTULO_GATE[nome] ?? nome}: {a.status === "PASS" ? "passou" : `bloqueou (${a.bloqueios})`}
                    {a.alertas > 0 && ` · ${a.alertas} alerta(s)`}
                  </li>
                ))}
              </ul>
            </Bloco>
          )}

          {bloqueios.length > 0 && (
            <Bloco titulo={sombra ? "O que o modo strict bloquearia" : "O que impede a peça de ficar pronta"}>
              {Object.entries(bloqueiosPorGate).map(([gate, lista]) => (
                <div key={gate}>
                  <span className="text-xs font-semibold text-tinta-3">{ROTULO_GATE[gate] ?? gate}</span>
                  <ul className="m-0 pl-4">
                    {lista.map((a, i) => (
                      <li key={i}>
                        {a.nivel === "CRITICAL" && <strong className="text-red-700">CRÍTICO </strong>}
                        <strong>{a.codigo}</strong>
                        {a.secao && <span className="text-tinta-3"> [{a.secao}]</span>} {a.trecho && <>«{a.trecho}»</>}{" "}
                        {a.detalhe && <span className="text-tinta-3">— {a.detalhe}</span>}
                      </li>
                    ))}
                  </ul>
                </div>
              ))}
            </Bloco>
          )}

          {dados.raciocinio && <MotorJuridico dados={dados.raciocinio} pendencias={dados.pendencias_do_motor ?? []} />}

          {canonico && canonico.campos.length > 0 && (
            <Bloco titulo={`Dados canônicos (fonte única · petição em ${canonico.petition_date})`}>
              <div className="overflow-x-auto">
                <table className="w-full text-xs border-collapse">
                  <thead>
                    <tr className="text-left text-tinta-3">
                      <th className="pr-2 font-medium">Campo</th>
                      <th className="pr-2 font-medium">Valor</th>
                      <th className="pr-2 font-medium">Certeza</th>
                      <th className="font-medium">Origem</th>
                    </tr>
                  </thead>
                  <tbody>
                    {canonico.campos.map((c) => (
                      <tr key={c.chave} className="border-t border-borda align-top">
                        <td className="pr-2">
                          {c.rotulo} <code className="text-tinta-3">{c.chave}</code>
                        </td>
                        <td className="pr-2">
                          {c.certeza === "CONTRADICTED"
                            ? (c.versoes ?? []).map((v) => `«${v.valor}» (${v.fontes.join(", ")})`).join(" × ")
                            : c.exibicao}
                        </td>
                        <td className={`pr-2 ${c.certeza === "CONTRADICTED" || c.certeza === "INFERRED" ? "text-red-700" : ""}`}>
                          {c.rotulo_certeza}
                        </td>
                        <td className="text-tinta-3">
                          {c.calculation_id ? `calculado (${c.calculation_id})` : c.documento || c.fonte || "—"}
                          {c.pagina && `, p. ${c.pagina}`}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {canonico.ausentes.length > 0 && (
                <p className="m-0 text-xs text-tinta-3">Sem dado no caso: {canonico.ausentes.join(", ")}</p>
              )}
            </Bloco>
          )}

          {dados.contradicoes.length > 0 && (
            <Bloco titulo={`Contradições entre fontes (${dados.contradicoes.length})`}>
              <ul className="m-0 pl-4">
                {dados.contradicoes.map((c) => (
                  <li key={c.id}>
                    <code>{c.chave}</code>:{" "}
                    {c.versoes.map((v) => `«${v.valor ?? v.detalhe ?? ""}»${v.fontes?.length ? ` (${v.fontes.join(", ")})` : ""}`).join(" × ")}
                  </li>
                ))}
              </ul>
            </Bloco>
          )}

          {divergencias.length > 0 && (
            <Bloco titulo="Divergências entre seções">
              <ul className="m-0 pl-4">
                {divergencias.map((d) => (
                  <li key={d.chave}>
                    <code>{d.chave}</code> esperado {d.esperado}:{" "}
                    {d.ocorrencias
                      .filter((o) => !o.ok)
                      .map((o) => `${o.secao} «${o.trecho}»`)
                      .join("; ")}
                  </li>
                ))}
              </ul>
            </Bloco>
          )}

          {dados.alertas_juridicos.length > 0 && (
            <Bloco titulo="Alertas da base jurídica">
              <ul className="m-0 pl-4">
                {dados.alertas_juridicos.map((a, i) => (
                  <li key={i}>{a}</li>
                ))}
              </ul>
            </Bloco>
          )}

          <Bloco titulo={`Teses incluídas (${incluidas.length})`}>
            <ul className="m-0 pl-4">
              {incluidas.map((t) => (
                <li key={t.id}>
                  {t.tese}
                  {t.exige_pericia && " · perícia"}
                  {t.pendente_de_calculo && " · cálculo pendente"}
                  <span className="text-tinta-3"> — {t.motivo}</span>
                  {(dados.autoridades_por_tese[t.id] ?? []).length > 0 && (
                    <span className="text-tinta-3">
                      {" "}
                      · autoridades: {(dados.autoridades_por_tese[t.id] ?? []).map((a) => a.titulo).join("; ")}
                    </span>
                  )}
                </li>
              ))}
            </ul>
          </Bloco>

          {naoIncluidas.length > 0 && (
            <Bloco titulo={`Teses não incluídas (${naoIncluidas.length})`}>
              <ul className="m-0 p-0 grid gap-2">
                {naoIncluidas.map((t) => (
                  <CartaoTeseNaoIncluida key={t.id} tese={t} autoridades={(dados.autoridades_por_tese[t.id] ?? []).length} />
                ))}
              </ul>
              <p className="m-0 text-xs text-tinta-3">
                {Object.entries(ROTULO_DECISAO)
                  .map(([codigo, rotulo]) => `${rotulo}: ${dados.teses.filter((t) => t.decisao === codigo).length}`)
                  .join(" · ")}
              </p>
            </Bloco>
          )}
          {dados.nao_avaliadas.length > 0 && (
            <p className="m-0 text-xs text-tinta-3">Itens do catálogo não avaliados: {dados.nao_avaliadas.join("; ")}</p>
          )}

          {matriz.length > 0 && (
            <Bloco titulo="Matriz tese × fato × prova">
              <div className="overflow-x-auto">
                <table className="w-full text-xs border-collapse">
                  <thead>
                    <tr className="text-left text-tinta-3">
                      <th className="pr-2 font-medium">Tese</th>
                      <th className="pr-2 font-medium">Fatos que sustentam</th>
                      <th className="pr-2 font-medium">Faltam</th>
                      <th className="font-medium">Provas</th>
                    </tr>
                  </thead>
                  <tbody>
                    {matriz.map((m) => (
                      <tr key={m.tese_id} className="border-t border-borda align-top">
                        <td className="pr-2">
                          {m.tese} <span className="text-tinta-3">({ROTULO_DECISAO[m.decisao] ?? m.decisao})</span>
                        </td>
                        <td className="pr-2">{m.fatos.map((f) => `${f.fato} (${ROTULO_ESTADO[f.estado] ?? f.estado})`).join("; ") || "—"}</td>
                        <td className="pr-2">{m.faltantes.join("; ") || "—"}</td>
                        <td>
                          {[...m.provas, ...m.documentos].join("; ") || "—"}
                          {m.exige_pericia && " · perícia"}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Bloco>
          )}

          {pedidos.length > 0 && (
            <Bloco titulo={`Pedidos estruturados (${pedidos.length})`}>
              <ul className="m-0 pl-4">
                {pedidos.map((p) => (
                  <li key={p.request_id}>
                    <code>{p.request_id}</code> {p.title}
                    {p.value != null && ` — ${brl(p.value)}`}
                    {p.calculation_id && <span className="text-tinta-3"> ({p.calculation_id})</span>}
                    {p.status !== "SUPPORTED" && <strong> · {p.status === "PENDING_CALCULATION" ? "cálculo pendente" : p.status}</strong>}
                    {p.expert_evidence_required && " · perícia"}
                    {p.reflexes.length > 0 && <span className="text-tinta-3"> · reflexos: {p.reflexes.join(", ")}</span>}
                  </li>
                ))}
              </ul>
            </Bloco>
          )}

          {dados.calculos.length > 0 && (
            <Bloco titulo="Cálculos">
              <ul className="m-0 pl-4">
                {dados.calculos.map((c, i) => (
                  <li key={i}>
                    {c.rubrica}: {c.erro ? <span className="text-tinta-3">{c.erro}</span> : `${brl(c.valor)} — ${c.memoria.join(" | ")}`}
                  </li>
                ))}
              </ul>
              {dados.valor_da_causa?.valor ? <p className="m-0">Valor da causa: {brl(dados.valor_da_causa.valor)}</p> : null}
            </Bloco>
          )}

          {dados.fatos.length > 0 && (
            <Bloco titulo={`Fatos (${dados.fatos.length})`}>
              <ul className="m-0 pl-4">
                {dados.fatos.slice(0, 60).map((f) => (
                  <li key={f.id}>
                    <span className="text-tinta-3">{f.estado}</span> · {f.chave ? `${f.chave} = ${f.valor}` : f.fato}
                    <span className="text-tinta-3">
                      {" "}
                      — {f.documento || f.fonte || "sem fonte"}
                      {f.pagina && `, p. ${f.pagina}`}
                      {f.contradicoes.length > 0 && " · contraditório"}
                    </span>
                  </li>
                ))}
              </ul>
            </Bloco>
          )}

          {(dados.citacoes ?? []).length > 0 && (
            <Bloco titulo="Citações conferidas">
              <ul className="m-0 p-0 grid gap-2 list-none">
                {(dados.citacoes ?? []).map((c, i) => (
                  <li key={i} className="grid gap-1 border border-borda p-2">
                    <span>
                      {c.trecho} — <strong>{c.classificacao ?? c.status}</strong>
                      {c.authority_id && (
                        <>
                          {" · "}
                          <a href={linkDoAcervo(c.authority_id)} target="_blank" rel="noreferrer" className="underline">
                            {c.titulo || c.authority_id}
                            {c.versao && ` (versão ${c.versao})`}
                          </a>
                        </>
                      )}
                    </span>
                    {c.checks && (
                      <span className="flex flex-wrap gap-1">
                        {(["EXISTS", "VALID_ON_DATE", "NOT_SUPERSEDED", "SUPPORTS_CLAIM"] as const).map((k) => (
                          <Check key={k} nome={k} valor={c.checks?.[k]} />
                        ))}
                      </span>
                    )}
                    {c.afirmacao && <span className="text-xs text-tinta-3">Afirmação: {c.afirmacao}</span>}
                    {c.trecho_oficial && <span className="text-xs text-tinta-3">Texto oficial: «{c.trecho_oficial}»</span>}
                    {c.sucessora && (
                      <span className="text-xs">
                        Superada por:{" "}
                        <a href={linkDoAcervo(c.sucessora.id)} target="_blank" rel="noreferrer" className="underline">
                          {c.sucessora.titulo}
                        </a>
                      </span>
                    )}
                    {c.motivo && <span className="text-xs text-tinta-3">{c.motivo}</span>}
                  </li>
                ))}
              </ul>
            </Bloco>
          )}

          {alertas.length > 0 && (
            <Bloco titulo="Alertas dos auditores">
              <ul className="m-0 pl-4">
                {alertas.map((a, i) => (
                  <li key={i}>
                    {a.auditor} · {a.codigo} {a.trecho && <>«{a.trecho}»</>}
                  </li>
                ))}
              </ul>
            </Bloco>
          )}

          {dados.etapas.length > 0 && (
            <Bloco titulo="Etapas">
              <ul className="m-0 pl-4">
                {dados.etapas.map((e, i) => (
                  <li key={i}>
                    {e.etapa}
                    {e.modelo && ` · ${e.modelo}`}
                    {typeof e.duracao_ms === "number" && ` · ${(e.duracao_ms / 1000).toFixed(1)} s`}
                    {e.tokens_entrada_aprox ? ` · ~${e.tokens_entrada_aprox + (e.tokens_saida_aprox ?? 0)} tokens` : ""}
                    {!e.ok && <span className="text-tinta-3"> · falhou: {e.erro}</span>}
                    {(e.consultas ?? []).length > 0 && ` · ${(e.consultas ?? []).length} consultas jurídicas`}
                  </li>
                ))}
              </ul>
            </Bloco>
          )}
        </div>
      )}
    </div>
  );
}
