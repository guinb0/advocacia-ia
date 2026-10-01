"use client";

import { useState } from "react";
import type { CertezaJuridica, NomeDoScore, RaciocinioJuridico, TeseDoMotor } from "@/lib/agente";

const ABAS = ["Grafo", "Scores", "Prova e lacunas", "Contrateses", "Proposições"] as const;
type Aba = (typeof ABAS)[number];

const ROTULO_REQUISITO: Record<string, string> = {
  atendido: "atendido",
  so_alegado: "só alegado",
  contraditorio: "contraditório",
  ausente: "sem fato",
};

const ROTULO_SCORE: Record<NomeDoScore, string> = {
  factual_support: "Suporte fático",
  evidentiary_strength: "Força da prova",
  legal_support: "Suporte jurídico",
  precedent_strength: "Força do precedente",
  contradiction_risk: "Risco de contradição",
  strategic_value: "Valor estratégico",
};

const ROTULO_CERTEZA: Record<CertezaJuridica, string> = {
  BINDING: "vinculante",
  STRONG: "forte",
  PERSUASIVE: "persuasiva",
  CONTESTED: "controvertida",
  UNSETTLED: "não assentada",
  RESEARCH_REQUIRED: "pesquisa necessária",
};

const pct = (v: number) => `${Math.round(v * 100)}%`;

function corDoEstado(estado: string): string {
  if (estado === "atendido" || estado === "forte") return "border-borda";
  if (estado === "ausente" || estado === "contraditorio") return "border-red-400";
  return "border-amber-400";
}

function Grafo({ tese }: { tese: TeseDoMotor }) {
  return (
    <div className="grid gap-2">
      <ul className="m-0 pl-4">
        {tese.explicacao.map((linha, i) => (
          <li key={i} className={i === 0 ? "list-none -ml-4 font-semibold" : ""}>
            {linha.replace(/^- /, "")}
          </li>
        ))}
      </ul>
      <p className="m-0 text-xs text-tinta-3">
        {tese.grafo.nos.length} nós · {tese.grafo.arestas.length} ligações · origem de cada ligação:{" "}
        {[...new Set(tese.grafo.arestas.map((a) => a.origem).filter(Boolean))].join(", ") || "—"}
      </p>
    </div>
  );
}

function Scores({ teses, ordem }: { teses: TeseDoMotor[]; ordem: string[] }) {
  const ordenadas = [...teses].sort((a, b) => ordem.indexOf(a.tese_id) - ordem.indexOf(b.tese_id));
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-xs border-collapse">
        <thead>
          <tr className="text-left text-tinta-3">
            <th className="pr-2 font-medium">Tese</th>
            <th className="pr-2 font-medium">Prioridade</th>
            {Object.values(ROTULO_SCORE).map((r) => (
              <th key={r} className="pr-2 font-medium">
                {r}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {ordenadas.map((t) => (
            <tr key={t.tese_id} className="border-t border-borda align-top">
              <td className="pr-2">{t.tese}</td>
              <td className="pr-2">{typeof t.scores.prioridade === "number" ? pct(t.scores.prioridade) : "—"}</td>
              {(Object.keys(ROTULO_SCORE) as NomeDoScore[]).map((k) => {
                const s = t.scores[k];
                return (
                  <td key={k} className={`pr-2 ${k === "contradiction_risk" && s && s.valor >= 0.5 ? "text-red-700" : ""}`}>
                    {s ? <span title={s.motivos.join("\n")}>{pct(s.valor)}</span> : "—"}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
      <p className="m-0 text-xs text-tinta-3">Passe o mouse sobre um score para ver os motivos. Scores ordenam e alertam; não incluem nem excluem tese.</p>
    </div>
  );
}

function ProvaELacunas({ dados }: { dados: RaciocinioJuridico }) {
  return (
    <div className="grid gap-2">
      <div className="overflow-x-auto">
        <table className="w-full text-xs border-collapse">
          <thead>
            <tr className="text-left text-tinta-3">
              <th className="pr-2 font-medium">Tese / requisito</th>
              <th className="pr-2 font-medium">Provas disponíveis</th>
              <th className="pr-2 font-medium">Força</th>
              <th className="font-medium">Prova típica / alternativa</th>
            </tr>
          </thead>
          <tbody>
            {dados.matriz_de_prova.map((m) => (
              <tr key={m.requisito_id} className="border-t border-borda align-top">
                <td className="pr-2">
                  <span className="text-tinta-3">{m.tese}</span> · {m.requisito}
                </td>
                <td className="pr-2">
                  {m.provas_disponiveis.map((p) => `${p.documento || p.fato_id} (${p.classe}${p.contraditoria ? ", contraditória" : ""})`).join("; ") || "—"}
                </td>
                <td className="pr-2">
                  <span className={`px-1 border ${corDoEstado(m.forca)}`}>{m.forca}</span>
                  {m.prova_futura_necessaria.length > 0 && <span className="text-tinta-3"> · produzir: {m.prova_futura_necessaria.join(", ")}</span>}
                </td>
                <td className="text-tinta-3">
                  {m.prova_tipica} / {m.alternativa}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {dados.lacunas.length > 0 && (
        <ul className="m-0 pl-4">
          {dados.lacunas.map((l, i) => (
            <li key={i}>
              Tese: {l.tese} / Requisito: {l.requisito} / Força: {l.forca} / Ausente: {l.ausente} / Alternativa: {l.alternativa}
              <span className="text-tinta-3"> — {l.motivo}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function Contrateses({ teses, vulneraveis }: { teses: TeseDoMotor[]; vulneraveis: RaciocinioJuridico["capitulos_vulneraveis"] }) {
  const com = teses.filter((t) => t.contrateses.length > 0);
  return (
    <div className="grid gap-2">
      {com.map((t) => (
        <div key={t.tese_id}>
          <span className="text-xs font-semibold text-tinta-3">{t.tese}</span>
          <ul className="m-0 pl-4">
            {t.contrateses.map((c, i) => (
              <li key={i}>
                «{c.defesa}» <span className="text-tinta-3">({c.forca}, {c.origem})</span>
                {" · "}
                {c.respondida === true ? "enfrentada na peça" : c.respondida === false ? <strong>não enfrentada</strong> : "não auditada"}
                {" · "}
                {c.tem_prova ? "há prova que a afasta" : <strong>sem prova que a afaste</strong>}
                {c.trecho_resposta && <span className="block text-xs text-tinta-3">Resposta na peça: «{c.trecho_resposta}»</span>}
                {c.orientacao && <span className="block text-xs text-tinta-3">{c.orientacao}</span>}
              </li>
            ))}
          </ul>
        </div>
      ))}
      {vulneraveis.length > 0 && <p className="m-0 text-xs">Capítulos vulneráveis: {[...new Set(vulneraveis.map((v) => v.tese))].join("; ")}</p>}
      {com.length === 0 && <p className="m-0 text-xs text-tinta-3">Nenhuma contratese levantada.</p>}
    </div>
  );
}

function Proposicoes({ teses }: { teses: TeseDoMotor[] }) {
  return (
    <div className="grid gap-2">
      {teses.map((t) => (
        <div key={t.tese_id}>
          <span className="text-xs font-semibold text-tinta-3">{t.tese}</span>
          <ul className="m-0 pl-4">
            {t.proposicoes.map((p) => (
              <li key={p.id}>
                {p.texto} —{" "}
                <strong>{p.certeza ? ROTULO_CERTEZA[p.certeza] : "não pesquisada"}</strong>
                {p.classificacao === "presumida" && <span className="text-tinta-3"> (relação presumida)</span>}
                {p.conflito && (
                  <span className="text-tinta-3">
                    {" "}
                    · conflito: {p.conflito.position_a.length} a favor × {p.conflito.position_b.length} contra
                    {p.conflito.controlling_authority ? ` (prevalece ${p.conflito.controlling_authority})` : " (não resolvido)"}
                  </span>
                )}
                {(p.autoridades ?? []).length > 0 && (
                  <span className="block text-xs text-tinta-3">
                    {(p.autoridades ?? []).map((a) => `${a.titulo} [${a.posicao}]`).join("; ")}
                  </span>
                )}
              </li>
            ))}
          </ul>
        </div>
      ))}
    </div>
  );
}

/** Motor jurídico: por que cada tese existe (grafo), scores, prova e lacunas, contrateses e certeza por proposição. */
export function MotorJuridico({ dados, pendencias }: { dados: RaciocinioJuridico; pendencias: string[] }) {
  const [aba, setAba] = useState<Aba>("Grafo");
  const [teseId, setTeseId] = useState(dados.teses[0]?.tese_id ?? "");
  const tese = dados.teses.find((t) => t.tese_id === teseId) ?? dados.teses[0];

  return (
    <section className="grid gap-2">
      <h4 className="m-0 text-xs font-semibold text-tinta-2">Motor jurídico (catálogo {dados.versao_catalogo})</h4>
      {dados.falhas.length > 0 && <p className="m-0 text-xs text-red-700">Falhas do motor: {dados.falhas.join("; ")}</p>}
      {pendencias.length > 0 && (
        <ul className="m-0 pl-4 text-xs">
          {pendencias.map((p, i) => (
            <li key={i}>{p}</li>
          ))}
        </ul>
      )}
      <div role="tablist" className="flex flex-wrap gap-1">
        {ABAS.map((a) => (
          <button
            key={a}
            type="button"
            role="tab"
            aria-selected={aba === a}
            onClick={() => setAba(a)}
            className={`px-2 py-0.5 text-xs border cursor-pointer ${aba === a ? "border-tinta-2 font-semibold" : "border-borda bg-transparent"}`}
          >
            {a}
          </button>
        ))}
      </div>
      {dados.teses.length === 0 ? (
        <p className="m-0 text-xs text-tinta-3">O motor não montou teses para esta peça.</p>
      ) : (
        <div role="tabpanel">
          {aba === "Grafo" && tese && (
            <div className="grid gap-2">
              <select className="text-xs border border-borda p-1 w-fit" value={tese.tese_id} onChange={(e) => setTeseId(e.target.value)}>
                {dados.teses.map((t) => (
                  <option key={t.tese_id} value={t.tese_id}>
                    {t.tese}
                  </option>
                ))}
              </select>
              <div className="flex flex-wrap gap-1">
                {tese.requisitos.map((r) => (
                  <span key={r.id} className={`px-1.5 py-0.5 border text-xs ${corDoEstado(r.estado)}`} title={r.origem}>
                    {r.requisito}: {ROTULO_REQUISITO[r.estado] ?? r.estado}
                  </span>
                ))}
              </div>
              <Grafo tese={tese} />
            </div>
          )}
          {aba === "Scores" && <Scores teses={dados.teses} ordem={dados.ordem_por_prioridade} />}
          {aba === "Prova e lacunas" && <ProvaELacunas dados={dados} />}
          {aba === "Contrateses" && <Contrateses teses={dados.teses} vulneraveis={dados.capitulos_vulneraveis} />}
          {aba === "Proposições" && <Proposicoes teses={dados.teses} />}
        </div>
      )}
      {dados.alertas.length > 0 && (
        <ul className="m-0 pl-4 text-xs">
          {dados.alertas.map((a, i) => (
            <li key={i}>{a}</li>
          ))}
        </ul>
      )}
    </section>
  );
}
