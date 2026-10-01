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
import { BotaoProcesso } from "@/components/ui/BotaoProcesso";

type Acao = "coletar" | "buscar" | "analisar";

const MINIMO_RELATO = 20;

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
  /* O erro fica junto do botão que falhou. Antes era um só, no topo da página:
   * quem clicava em "Gerar insights", lá embaixo, não via a falha. */
  const [falha, setFalha] = useState<{ acao: Acao; texto: string } | null>(null);
  const [emCurso, setEmCurso] = useState<Acao | null>(null);

  const semAlvo = !cnpj && !processo ? "Informe o CNPJ da empresa ou o número do processo." : null;
  const faltaRelato =
    relato.trim().length < MINIMO_RELATO
      ? `Escreva o relato do cliente acima (mínimo de ${MINIMO_RELATO} caracteres).`
      : null;

  async function executar(acao: Acao, tarefa: () => Promise<void>, mensagemPadrao: string) {
    setEmCurso(acao);
    setFalha(null);
    try {
      await tarefa();
    } catch (e) {
      setFalha({ acao, texto: e instanceof Error ? e.message : mensagemPadrao });
    } finally {
      setEmCurso(null);
    }
  }

  function coletar(evento: FormEvent) {
    evento.preventDefault();
    if (semAlvo || emCurso) return;
    setAviso(null);
    void executar("coletar", async () => {
      const resposta = await coletarInvestigacao({
        cnpj: cnpj || undefined, numero_processo: processo || undefined, tribunal,
      });
      setEvidencias(resposta.evidencias);
      setAviso(`${resposta.fontes} fontes e ${resposta.chunks} trechos vetorizados.${resposta.avisos.length ? " Algumas fontes estavam indisponíveis." : ""}`);
    }, "Falha na coleta.");
  }

  function pesquisar() {
    return executar("buscar", async () => {
      const resposta = await buscarInvestigacao({ consulta, cnpj: cnpj || undefined, numero_processo: processo || undefined });
      setResultados(resposta.resultados); setAviso(resposta.aviso);
    }, "Falha na busca.");
  }

  function analisar() {
    return executar("analisar", async () => {
      setAnalise(await analisarInvestigacao({ relato, cnpj: cnpj || undefined, numero_processo: processo || undefined, tribunal }));
    }, "Falha na análise.");
  }

  /** Os três botões dividem o servidor: enquanto um trabalha, os outros esperam. */
  const estadoDe = (acao: Acao) => ({
    processando: emCurso === acao,
    aguardando: emCurso !== null && emCurso !== acao,
    erro: falha?.acao === acao ? falha.texto : null,
  });

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
      {/* Pendência só ao clicar: os campos que faltam estão na mesma linha, e uma
        * frase fixa embaixo do botão desalinharia o formulário. */}
      <BotaoProcesso
        type="submit"
        variante="primario"
        {...estadoDe("coletar")}
        textoProcessando="Coletando…"
        pendencia={semAlvo}
        pendenciaAoClicar
        className="max-[1100px]:w-full"
      >
        Coletar e vetorizar
      </BotaoProcesso>
    </form>
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
      <div className="grid min-w-0 grid-cols-[minmax(0,1fr)_max-content] items-start gap-[10px] max-[850px]:grid-cols-1">
        <Campo value={consulta} onChange={e => setConsulta(e.target.value)} />
        <BotaoProcesso
          variante="secundario"
          onClick={pesquisar}
          {...estadoDe("buscar")}
          textoProcessando="Buscando…"
          pendencia={semAlvo ? "Informe no topo da página o CNPJ ou o número do processo." : null}
          pendenciaAoClicar
        >
          Buscar nos vetores
        </BotaoProcesso>
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
      <BotaoProcesso
        variante="primario"
        onClick={analisar}
        {...estadoDe("analisar")}
        textoProcessando="Gerando insights…"
        dica="Cruzando o relato com as fontes coletadas"
        pendencia={semAlvo ? "Informe no topo da página o CNPJ ou o número do processo." : faltaRelato}
        className="justify-self-start"
      >
        Gerar insights fundamentados
      </BotaoProcesso>
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
