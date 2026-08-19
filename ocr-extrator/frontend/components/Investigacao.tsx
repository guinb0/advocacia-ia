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
import estilos from "./Investigacao.module.css";

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

  return <main className={estilos.pagina}>
    <button className="botao botao--secundario botao--pequeno" onClick={onVoltar}>← Voltar</button>
    <header><h1>Investigação do caso</h1><p>Coleta fontes públicas, preserva a procedência e busca indícios. Todo resultado exige conferência humana.</p></header>
    <form className={estilos.formulario} onSubmit={coletar}>
      <label>CNPJ da empresa<input value={cnpj} onChange={e => setCnpj(e.target.value)} placeholder="00.000.000/0000-00" /></label>
      <label>Número do processo<input value={processo} onChange={e => setProcesso(e.target.value)} placeholder="0000000-00.0000.0.00.0000" /></label>
      <label>Tribunal<select value={tribunal} onChange={e => setTribunal(e.target.value)}><option value="trt8">TRT8</option><option value="tst">TST</option>{Array.from({length: 24}, (_, i) => i + 1).filter(n => n !== 8).map(n => <option key={n} value={`trt${n}`}>TRT{n}</option>)}</select></label>
      <button className="botao botao--primario" disabled={ocupado || (!cnpj && !processo)}>{ocupado ? "Coletando…" : "Coletar e vetorizar"}</button>
    </form>
    {erro && <div className={estilos.erro}>{erro}</div>}{aviso && <div className={estilos.aviso}>{aviso}</div>}
    {evidencias.length > 0 && <section><h2>Fontes encontradas</h2><div className={estilos.lista}>{evidencias.map(e => <article key={e.identificador}><span>{e.categoria} · confiança {e.confianca}</span><h3>{e.titulo}</h3><a href={e.url} target="_blank" rel="noreferrer">Abrir fonte ↗</a></article>)}</div></section>}
    <section className={estilos.busca}><h2>Buscar peculiaridades</h2><div><input value={consulta} onChange={e => setConsulta(e.target.value)} /><button className="botao botao--secundario" onClick={pesquisar} disabled={ocupado || (!cnpj && !processo)}>Buscar nos vetores</button></div></section>
    {resultados.length > 0 && <section><h2>Indícios relacionados</h2><div className={estilos.lista}>{resultados.map((r, i) => <article key={`${r.url}-${i}`}><span>Similaridade {(r.similaridade * 100).toFixed(1)}%</span><h3>{r.titulo}</h3><p>{r.texto}</p><a href={r.url} target="_blank" rel="noreferrer">Conferir origem ↗</a></article>)}</div></section>}
    <section className={estilos.analise}><h2>Analisar o relato contra as evidências</h2><textarea value={relato} onChange={e => setRelato(e.target.value)} placeholder="Cole ou escreva o relato do cliente. A análise usará somente as fontes coletadas para este CNPJ/processo." /><button className="botao botao--primario" onClick={analisar} disabled={ocupado || relato.trim().length < 20 || (!cnpj && !processo)}>Gerar insights fundamentados</button></section>
    {analise && <section><h2>Leitura investigativa</h2><div className={estilos.resumo}>{analise.resumo}</div><h3>Insights</h3><div className={estilos.lista}>{analise.insights.map((item, i) => <article key={i}><span>{item.tipo} · confiança {item.confianca} · {item.evidencias.join(", ")}</span><h3>{item.achado}</h3><p>{item.impacto}</p><strong>Como conferir:</strong> {item.como_verificar}</article>)}</div><h3>Perguntas para a entrevista</h3><ul>{analise.perguntas_entrevista.map((p, i) => <li key={i}>{p}</li>)}</ul><h3>Provas a buscar</h3><ul>{analise.provas_a_buscar.map((p, i) => <li key={i}>{p}</li>)}</ul><p className={estilos.aviso}>{analise.aviso}</p></section>}
  </main>;
}
