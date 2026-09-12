"use client";

/**
 * Tela do Revisor: a fila de petições que precisam de revisão, com aprovação,
 * e as métricas de atividade (volume e tempo — operacionais, não avaliação de
 * qualidade). Abrir uma petição marca o INÍCIO da revisão; aprovar ou devolver
 * para ajustes marca a CONCLUSÃO. Ver `app/revisao.py`.
 */

import { useCallback, useEffect, useState } from "react";

import {
  concluirRevisao,
  filaDeRevisao,
  iniciarRevisao,
  metricasDeRevisao,
  type MetricasRevisao,
  type PeticaoParaRevisar,
} from "@/lib/api";
import { listarCasos } from "@/lib/api";
import { gerarAnaliseEPeticao } from "@/lib/agente";
import { baixarArquivoDaPeticao, buscarPeticao, type Peticao } from "@/lib/agente";
import { Aviso, Botao, Cartao, Selo, Vazio } from "@/components/ui/Basicos";
import { BotaoProcesso } from "@/components/ui/BotaoProcesso";

function baixarBlob(arquivo: Blob, nome: string): void {
  const url = URL.createObjectURL(arquivo);
  const link = document.createElement("a");
  link.href = url;
  link.download = nome;
  link.click();
  URL.revokeObjectURL(url);
}

function tempoLegivel(segundos: number): string {
  if (!segundos) return "—";
  const h = Math.floor(segundos / 3600);
  const m = Math.round((segundos % 3600) / 60);
  return h ? `${h}h ${m}min` : `${m || 1}min`;
}

export default function Revisao() {
  const [fila, setFila] = useState<PeticaoParaRevisar[]>([]);
  const [metricas, setMetricas] = useState<MetricasRevisao | null>(null);
  const [carregando, setCarregando] = useState(true);
  const [erro, setErro] = useState<string | null>(null);
  const [aberto, setAberto] = useState<string | null>(null);

  const recarregar = useCallback(async () => {
    setCarregando(true);
    setErro(null);
    try {
      const [f, m] = await Promise.all([filaDeRevisao(), metricasDeRevisao()]);
      setFila(f.pendentes);
      setMetricas(m);
    } catch (e) {
      setErro(e instanceof Error ? e.message : "Não foi possível carregar a fila de revisão.");
    } finally {
      setCarregando(false);
    }
  }, []);

  useEffect(() => {
    void recarregar();
  }, [recarregar]);

  return (
    <div className="grid gap-5">
      <Cartao
        titulo="Revisão de petições"
        subtitulo="As petições que aguardam revisão. Abrir uma marca o início; aprovar ou devolver para ajustes conclui."
      >
        {metricas && (
          <div className="mb-4 grid grid-cols-2 gap-3 md:grid-cols-4">
            <Indicador rotulo="Aguardando revisão" valor={String(fila.length)} />
            <Indicador rotulo="Revisadas" valor={String(metricas.revisadas)} />
            <Indicador rotulo="Aprovadas" valor={String(metricas.aprovadas)} />
            <Indicador rotulo="Tempo médio" valor={tempoLegivel(metricas.tempo_medio_s)} />
          </div>
        )}

        {erro && <Aviso tom="critico" titulo="Erro">{erro}</Aviso>}

        {carregando && fila.length === 0 ? (
          <Vazio>Carregando a fila…</Vazio>
        ) : fila.length === 0 ? (
          <Vazio>Nenhuma petição aguardando revisão agora.</Vazio>
        ) : (
          <ul className="grid gap-3 m-0 list-none p-0">
            {fila.map((p) => (
              <ItemFila
                key={p.caso_id}
                peticao={p}
                aberto={aberto === p.caso_id}
                onAbrir={() => setAberto(aberto === p.caso_id ? null : p.caso_id)}
                onConcluido={() => {
                  setAberto(null);
                  void recarregar();
                }}
              />
            ))}
          </ul>
        )}
      </Cartao>

      {metricas && metricas.por_revisor.length > 0 && (
        <Cartao titulo="Métricas por revisor" subtitulo={metricas.aviso}>
          <ul className="grid gap-2 m-0 list-none p-0">
            {metricas.por_revisor.map((r) => (
              <li key={r.revisor} className="flex flex-wrap items-baseline justify-between gap-2 border-b border-borda py-2 last:border-0">
                <span className="min-w-0 truncate text-tinta" title={r.revisor}>{r.revisor}</span>
                <span className="text-xs text-tinta-3 tabular-nums">
                  {r.revisadas} revisada(s) · {r.aprovadas} aprovada(s) · {r.ajustes} ajuste(s) · média {tempoLegivel(r.tempo_medio_s)}
                </span>
              </li>
            ))}
          </ul>
        </Cartao>
      )}
    </div>
  );
}

type EstadoLote = "aguardando" | "gerando" | "pronta" | "falhou";

/** Dispara uma requisição por caso: o navegador não espera uma terminar para
 * começar a próxima, e a fila de revisão continua sendo o ponto único para
 * editar/aprovar cada minuta quando terminar. */
export function GeradorEmLote({ aoConcluir }: { aoConcluir: () => Promise<void> }) {
  const [casos, setCasos] = useState<Array<{ id: string; cliente: string; categoria: string }>>([]);
  const [selecionados, setSelecionados] = useState<string[]>([]);
  const [estados, setEstados] = useState<Record<string, { estado: EstadoLote; detalhe?: string }>>({});
  const [erro, setErro] = useState<string | null>(null);

  useEffect(() => {
    void listarCasos().then((lista) => setCasos(lista)).catch(() => setErro("Não foi possível listar os casos."));
  }, []);

  function alternar(id: string) {
    setSelecionados((atuais) => atuais.includes(id) ? atuais.filter((item) => item !== id) : [...atuais, id]);
  }

  async function gerarLote() {
    if (!selecionados.length) return;
    setErro(null);
    setEstados(Object.fromEntries(selecionados.map((id) => [id, { estado: "gerando" as const }])));
    await Promise.allSettled(selecionados.map(async (id) => {
      try {
        await gerarAnaliseEPeticao(id);
        setEstados((atual) => ({ ...atual, [id]: { estado: "pronta" } }));
      } catch (falha) {
        setEstados((atual) => ({ ...atual, [id]: { estado: "falhou", detalhe: falha instanceof Error ? falha.message : "Falha ao gerar." } }));
      }
    }));
    await aoConcluir();
  }

  const gerando = Object.values(estados).some((item) => item.estado === "gerando");
  return (
    <Cartao titulo="Fila de geração" subtitulo="Selecione vários casos para gerar as minutas ao mesmo tempo. Ao terminar, cada uma aparece abaixo para revisão e edição individual.">
      {erro && <Aviso tom="critico" titulo="Fila indisponível">{erro}</Aviso>}
      {casos.length === 0 ? <Vazio>Nenhum caso disponível para inclusão na fila.</Vazio> : <>
        <div className="max-h-64 overflow-y-auto rounded-campo border border-borda">
          {casos.map((caso) => {
            const situacao = estados[caso.id];
            return <label key={caso.id} className="flex cursor-pointer items-center justify-between gap-3 border-b border-borda px-3 py-2 last:border-0 hover:bg-papel-2">
              <span className="flex min-w-0 items-center gap-3"><input type="checkbox" checked={selecionados.includes(caso.id)} disabled={gerando} onChange={() => alternar(caso.id)} /><span className="min-w-0"><strong className="block truncate text-tinta">{caso.cliente}</strong><small className="text-tinta-3">{caso.categoria}</small></span></span>
              {situacao && <Selo tom={situacao.estado === "pronta" ? "ok" : situacao.estado === "falhou" ? "critico" : "atencao"}>{situacao.estado === "gerando" ? "gerando" : situacao.estado === "pronta" ? "pronta" : "falhou"}</Selo>}
            </label>;
          })}
        </div>
        <div className="mt-4 flex flex-wrap items-center justify-between gap-3">
          <span className="text-sm text-tinta-3">{selecionados.length} caso(s) selecionado(s). As falhas ficam isoladas e não impedem os demais.</span>
          <BotaoProcesso variante="primario" onClick={() => void gerarLote()} processando={gerando} textoProcessando="Gerando minutas…" pendencia={selecionados.length ? null : "Selecione ao menos um caso."}>Gerar petições selecionadas</BotaoProcesso>
        </div>
      </>}
    </Cartao>
  );
}

function Indicador({ rotulo, valor }: { rotulo: string; valor: string }) {
  return (
    <div className="rounded-campo border border-borda-forte bg-papel p-3">
      <strong className="block text-[1.4rem] leading-none tabular-nums text-tinta">{valor}</strong>
      <span className="text-xs text-tinta-3">{rotulo}</span>
    </div>
  );
}

function ItemFila({
  peticao,
  aberto,
  onAbrir,
  onConcluido,
}: {
  peticao: PeticaoParaRevisar;
  aberto: boolean;
  onAbrir: () => void;
  onConcluido: () => void;
}) {
  const [conteudo, setConteudo] = useState<Peticao | null>(null);
  const [carregando, setCarregando] = useState(false);
  const [concluindo, setConcluindo] = useState<"aprovada" | "ajustes" | null>(null);
  const [erro, setErro] = useState<string | null>(null);

  async function abrir() {
    onAbrir();
    if (aberto || conteudo) return;
    setCarregando(true);
    setErro(null);
    try {
      // Marca o INÍCIO da revisão e traz o texto para conferência.
      await iniciarRevisao(peticao.caso_id);
      setConteudo(await buscarPeticao(peticao.caso_id, "local"));
    } catch (e) {
      setErro(e instanceof Error ? e.message : "Não foi possível abrir a petição.");
    } finally {
      setCarregando(false);
    }
  }

  async function baixarPdf() {
    try {
      const arquivo = await baixarArquivoDaPeticao(peticao.caso_id, "local", "pdf");
      baixarBlob(arquivo, `Peticao - ${peticao.cliente}.pdf`);
    } catch (e) {
      setErro(e instanceof Error ? e.message : "Não foi possível baixar o PDF.");
    }
  }

  async function concluir(resultado: "aprovada" | "ajustes") {
    setConcluindo(resultado);
    setErro(null);
    try {
      await concluirRevisao(peticao.caso_id, resultado);
      onConcluido();
    } catch (e) {
      setErro(e instanceof Error ? e.message : "Não foi possível concluir a revisão.");
      setConcluindo(null);
    }
  }

  return (
    <li className="rounded-campo border border-borda bg-papel-2 p-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="min-w-0">
          <strong className="block truncate text-tinta" title={peticao.cliente}>{peticao.cliente}</strong>
          <span className="text-xs text-tinta-3">
            {peticao.categoria} · versão {peticao.versao}
            {peticao.revisor_andamento ? ` · em revisão por ${peticao.revisor_andamento}` : ""}
          </span>
        </div>
        <div className="flex items-center gap-2">
          {peticao.revisor_andamento && <Selo tom="atencao">em revisão</Selo>}
          <Botao variante="secundario" pequeno onClick={() => void abrir()}>
            {aberto ? "Ocultar" : "Abrir e revisar"}
          </Botao>
        </div>
      </div>

      {aberto && (
        <div className="mt-3 border-t border-borda pt-3">
          {erro && <Aviso tom="critico" titulo="Erro">{erro}</Aviso>}
          {carregando ? (
            <Vazio>Abrindo a petição…</Vazio>
          ) : conteudo ? (
            <>
              <div className="mb-3 flex flex-wrap gap-2">
                <Botao variante="texto" pequeno onClick={() => void baixarPdf()}>Baixar PDF</Botao>
              </div>
              <div className="max-h-[50vh] overflow-y-auto rounded-campo border border-borda bg-papel p-4">
                {(conteudo.sections ?? []).map((s) => (
                  <section key={s.code} className="mb-4 last:mb-0">
                    {s.label && (
                      <h4 className="mb-1 mt-0 text-xs font-bold uppercase tracking-wide text-tinta">{s.label}</h4>
                    )}
                    <p className="m-0 whitespace-pre-wrap text-sm leading-relaxed text-tinta-2">{s.content || "—"}</p>
                  </section>
                ))}
              </div>
              <div className="mt-3 flex flex-wrap gap-2">
                <BotaoProcesso
                  variante="primario"
                  onClick={() => concluir("aprovada")}
                  processando={concluindo === "aprovada"}
                  textoProcessando="Aprovando…"
                  aguardando={concluindo !== null}
                >
                  Aprovar petição
                </BotaoProcesso>
                <BotaoProcesso
                  variante="secundario"
                  onClick={() => concluir("ajustes")}
                  processando={concluindo === "ajustes"}
                  textoProcessando="Devolvendo…"
                  aguardando={concluindo !== null}
                >
                  Devolver para ajustes
                </BotaoProcesso>
              </div>
            </>
          ) : null}
        </div>
      )}
    </li>
  );
}
