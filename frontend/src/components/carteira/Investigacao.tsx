"use client";

import { FormEvent, useState } from "react";
import {
  buscarInvestigacao,
  coletarInvestigacao,
  analisarInvestigacao,
  type AnaliseInvestigativa,
  type EvidenciaInvestigativa,
  type ResultadoInvestigativo,
} from "@/lib/api";
import { Botao, Campo, CampoSeletor } from "@/components/ui/Basicos";

export default function Investigacao({ onVoltar }: { onVoltar: () => void }) {
  const [cnpj, setCnpj] = useState("");
  const [processo, setProcesso] = useState("");
  const [tribunal, setTribunal] = useState("trt8");
  const [consulta, setConsulta] = useState("contradições, jornada, grupo econômico e fatos relevantes");
  const [relato, setRelato] = useState("");
  const [evidencias, setEvidencias] = useState<EvidenciaInvestigativa[]>([]);
  const [resultados, setResultados] = useState<ResultadoInvestigativo[]>([]);
  const [analise, setAnalise] = useState<AnaliseInvestigativa | null>(null);
  const [aviso, setAviso] = useState<string | null>(null);
  const [erro, setErro] = useState<string | null>(null);
  const [ocupado, setOcupado] = useState(false);

  async function coletar(evento: FormEvent) {
    evento.preventDefault(); setOcupado(true); setErro(null); setAviso(null);
    try {
      const resposta = await coletarInvestigacao({
        cnpj: cnpj || undefined, numero_processo: processo || undefined, tribunal,
      });
      setEvidencias(resposta.evidencias);
      setAviso(`${resposta.fontes} fontes e ${resposta.chunks} trechos vetorizados.${resposta.avisos.length ? " Algumas fontes estavam indisponíveis." : ""}`);
    } catch (falha) { setErro(falha instanceof Error ? falha.message : "Falha na coleta."); }
    finally { setOcupado(false); }
  }

  async function pesquisar() {
    setOcupado(true); setErro(null);
    try {
      const resposta = await buscarInvestigacao({ consulta, cnpj: cnpj || undefined, numero_processo: processo || undefined });
      setResultados(resposta.resultados); setAviso(resposta.aviso);
    } catch (falha) { setErro(falha instanceof Error ? falha.message : "Falha na busca."); }
    finally { setOcupado(false); }
  }

  async function analisar() {
    setOcupado(true); setErro(null);
    try {
      setAnalise(await analisarInvestigacao({ relato, cnpj: cnpj || undefined, numero_processo: processo || undefined, tribunal }));
    } catch (falha) { setErro(falha instanceof Error ? falha.message : "Falha na análise."); }
    finally { setOcupado(false); }
  }

  return <div className="min-w-0 space-y-6">
    <Botao variante="secundario" pequeno onClick={onVoltar}>← Voltar</Botao>
    <header>
      <h1>Investigação do caso</h1>
      <p className="text-tinta-2 max-w-[75ch]">Coleta fontes públicas, preserva a procedência e busca indícios. Todo resultado exige conferência humana.</p>
    </header>
    <form
      className="grid min-w-0 grid-cols-[minmax(0,1fr)_minmax(0,1.4fr)_minmax(120px,0.6fr)_max-content] items-end gap-3 rounded-cartao border border-borda bg-papel p-[18px] max-[1100px]:grid-cols-2 max-[700px]:grid-cols-1"
      onSubmit={coletar}
    >
      <label className="grid min-w-0 gap-[6px] text-tinta-2 text-sm">
        CNPJ da empresa
        <Campo value={cnpj} onChange={e => setCnpj(e.target.value)} placeholder="00.000.000/0000-00" />
      </label>
      <label className="grid min-w-0 gap-[6px] text-tinta-2 text-sm">
        Número do processo
        <Campo value={processo} onChange={e => setProcesso(e.target.value)} placeholder="0000000-00.0000.0.00.0000" />
      </label>
      <label className="grid min-w-0 gap-[6px] text-tinta-2 text-sm">
        Tribunal
        <CampoSeletor value={tribunal} onChange={e => setTribunal(e.target.value)}>
          <option value="trt8">TRT8</option>
          <option value="tst">TST</option>
          {Array.from({ length: 24 }, (_, i) => i + 1).filter(n => n !== 8).map(n => (
            <option key={n} value={`trt${n}`}>TRT{n}</option>
          ))}
        </CampoSeletor>
      </label>
      <Botao variante="primario" disabled={ocupado || (!cnpj && !processo)} className="max-[1100px]:w-full">
        {ocupado ? "Coletando…" : "Coletar e vetorizar"}
      </Botao>
    </form>
    {erro && <div className="my-4 px-[14px] py-3 rounded-campo bg-critico-claro text-critico">{erro}</div>}
    {aviso && <div className="my-4 px-[14px] py-3 rounded-campo bg-acao-clara text-tinta">{aviso}</div>}
    {evidencias.length > 0 && (
      <section>
        <h2>Fontes encontradas</h2>
        <div className="grid gap-3">
          {evidencias.map(e => (
            <article key={e.identificador} className="p-4 border border-borda rounded-cartao bg-papel">
              <span className="text-tinta-3 text-xs">{e.categoria} · confiança {e.confianca}</span>
              <h3 className="my-[6px] text-base">{e.titulo}</h3>
              <a href={e.url} target="_blank" rel="noreferrer" className="text-acao text-sm">Abrir fonte ↗</a>
            </article>
          ))}
        </div>
      </section>
    )}
    <section className="my-[26px]">
      <h2>Buscar peculiaridades</h2>
      <div className="grid min-w-0 grid-cols-[minmax(0,1fr)_max-content] gap-[10px] max-[850px]:grid-cols-1">
        <Campo value={consulta} onChange={e => setConsulta(e.target.value)} />
        <Botao variante="secundario" onClick={pesquisar} disabled={ocupado || (!cnpj && !processo)}>Buscar nos vetores</Botao>
      </div>
    </section>
    {resultados.length > 0 && (
      <section>
        <h2>Indícios relacionados</h2>
        <div className="grid gap-3">
          {resultados.map((r, i) => (
            <article key={`${r.url}-${i}`} className="p-4 border border-borda rounded-cartao bg-papel">
              <span className="text-tinta-3 text-xs">Similaridade {(r.similaridade * 100).toFixed(1)}%</span>
              <h3 className="my-[6px] text-base">{r.titulo}</h3>
              <p className="whitespace-pre-wrap text-tinta-2 leading-[1.55]">{r.texto}</p>
              <a href={r.url} target="_blank" rel="noreferrer" className="text-acao text-sm">Conferir origem ↗</a>
            </article>
          ))}
        </div>
      </section>
    )}
    <section className="my-[30px] grid gap-3">
      <h2>Analisar o relato contra as evidências</h2>
      <Campo
        area
        value={relato}
        onChange={e => setRelato(e.target.value)}
        placeholder="Cole ou escreva o relato do cliente. A análise usará somente as fontes coletadas para este CNPJ/processo."
        style={{ minHeight: "150px" }}
      />
      <Botao
        variante="primario"
        onClick={analisar}
        disabled={ocupado || relato.trim().length < 20 || (!cnpj && !processo)}
        className="justify-self-start"
      >
        Gerar insights fundamentados
      </Botao>
    </section>
    {analise && (
      <section>
        <h2>Leitura investigativa</h2>
        <div className="p-4 border-l-4 border-acao bg-acao-clara leading-[1.55]">{analise.resumo}</div>
        <h3>Insights</h3>
        <div className="grid gap-3">
          {analise.insights.map((item, i) => (
            <article key={i} className="p-4 border border-borda rounded-cartao bg-papel">
              <span className="text-tinta-3 text-xs">{item.tipo} · confiança {item.confianca} · {item.evidencias.join(", ")}</span>
              <h3 className="my-[6px] text-base">{item.achado}</h3>
              <p className="whitespace-pre-wrap text-tinta-2 leading-[1.55]">{item.impacto}</p>
              <strong>Como conferir:</strong> {item.como_verificar}
            </article>
          ))}
        </div>
        <h3>Perguntas para a entrevista</h3>
        <ul>{analise.perguntas_entrevista.map((p, i) => <li key={i}>{p}</li>)}</ul>
        <h3>Provas a buscar</h3>
        <ul>{analise.provas_a_buscar.map((p, i) => <li key={i}>{p}</li>)}</ul>
        <p className="my-4 px-[14px] py-3 rounded-campo bg-acao-clara text-tinta">{analise.aviso}</p>
      </section>
    )}
  </div>;
}
