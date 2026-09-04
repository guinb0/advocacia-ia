"use client";

import { useEffect, useMemo, useState } from "react";
import { AlertTriangle, CheckCircle2, ChevronDown, FileSearch, Files, Search } from "lucide-react";

import { obterEntrega } from "@/lib/api";
import { capitalizacaoNatural, semUnderscore } from "@/lib/formato";
import type { EntregaDetalhe, ItemSituacao } from "@/lib/types";
import { BarraAbas, BotaoAba, Cartao, Selo, Vazio } from "@/components/ui/Basicos";

const EXPLICACOES_GENERICAS = new Set([
  "dado localizado no documento.",
  "conferência e instrução do caso.",
]);

function textoUtil(texto: string | null | undefined): boolean {
  return Boolean(texto?.trim() && !EXPLICACOES_GENERICAS.has(texto.trim().toLocaleLowerCase("pt-BR")));
}

export default function ResumoDocumentos({ itens }: { itens: ItemSituacao[] }) {
  const entregas = useMemo(() => {
    const unicas = new Map<string, { id: string; arquivo: string; status_proc?: string }>();
    for (const item of itens) for (const entrega of item.entregas) unicas.set(entrega.id, entrega);
    return [...unicas.values()];
  }, [itens]);
  const chave = entregas.map((e) => `${e.id}:${e.status_proc}`).join("|");
  const [detalhes, setDetalhes] = useState<EntregaDetalhe[]>([]);
  const [carregando, setCarregando] = useState(false);
  const [tipoAtivo, setTipoAtivo] = useState("todos");
  const [busca, setBusca] = useState("");

  useEffect(() => {
    const prontas = entregas.filter((e) => e.status_proc === "pronto");
    if (!prontas.length) { setDetalhes([]); return; }
    let cancelado = false;
    setCarregando(true);
    Promise.allSettled(prontas.map((e) => obterEntrega(e.id))).then((resultados) => {
      if (cancelado) return;
      setDetalhes(resultados.flatMap((r) => r.status === "fulfilled" ? [r.value] : []));
      setCarregando(false);
    });
    return () => { cancelado = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [chave]);

  const documentos = useMemo(() => detalhes.map((entrega) => {
    const extracao = entrega.extracao;
    const semantica = extracao?.classificacao_semantica;
    const achados = semantica?.achados?.length ? semantica.achados : (extracao?.campos ?? []).map((campo) => ({
      campo: campo.rotulo, valor: campo.valor, importancia: campo.observacao || undefined, relevante_para: undefined,
    }));
    const tipoBruto = semantica?.tipo_semantico || extracao?.tipo?.descricao_detectado
      || entrega.tipo_detectado || "Documento não identificado";
    return { entrega, semantica, achados, finalidades: semantica?.serve_para ?? [], tipo: capitalizacaoNatural(tipoBruto) };
  }), [detalhes]);

  const tipos = useMemo(() => {
    const contagem = new Map<string, number>();
    for (const doc of documentos) contagem.set(doc.tipo, (contagem.get(doc.tipo) ?? 0) + 1);
    return [...contagem.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0], "pt-BR"));
  }, [documentos]);

  const visiveis = useMemo(() => {
    const termo = busca.trim().toLocaleLowerCase("pt-BR");
    return documentos.filter(({ entrega, tipo }) =>
      (tipoAtivo === "todos" || tipo === tipoAtivo)
      && (!termo || `${entrega.arquivo} ${tipo}`.toLocaleLowerCase("pt-BR").includes(termo)));
  }, [documentos, tipoAtivo, busca]);

  const totalCampos = documentos.reduce((total, doc) => total + doc.achados.length, 0);
  const revisar = documentos.filter((doc) => doc.achados.length === 0 || doc.tipo === "Documento não identificado").length;
  if (!entregas.length) return null;

  return (
    <Cartao titulo="Painel dos documentos" subtitulo="Veja primeiro o que importa. Abra um documento somente quando precisar conferir todos os dados extraídos.">
      {carregando && detalhes.length === 0 ? <Vazio>Montando a visão geral dos documentos…</Vazio>
        : detalhes.length === 0 ? <Vazio>Os documentos ainda estão sendo interpretados.</Vazio> : (
        <div className="space-y-5">
          <section className="grid grid-cols-2 gap-3 lg:grid-cols-4" aria-label="Visão geral dos documentos">
            <Indicador icone={<Files size={18} />} rotulo="Documentos lidos" valor={documentos.length} />
            <Indicador icone={<FileSearch size={18} />} rotulo="Tipos encontrados" valor={tipos.length} />
            <Indicador icone={<CheckCircle2 size={18} />} rotulo="Dados destacados" valor={totalCampos} tom="ok" />
            <Indicador icone={<AlertTriangle size={18} />} rotulo="Pedem uma olhada" valor={revisar} tom={revisar ? "atencao" : "ok"} />
          </section>

          <section className="rounded-cartao border border-borda bg-papel-2 p-3 sm:p-4" aria-label="Filtros dos documentos">
            <div className="relative mb-3">
              <Search className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-tinta-3" size={17} aria-hidden />
              <input type="search" value={busca} onChange={(e) => setBusca(e.target.value)}
                placeholder="Buscar por arquivo ou tipo de documento" aria-label="Buscar nos documentos"
                className="min-h-11 w-full rounded-campo border border-borda-campo bg-papel py-2 pl-10 pr-3 text-sm text-tinta outline-none transition focus:border-acao focus:ring-2 focus:ring-acao-clara" />
            </div>
            <BarraAbas aria-label="Filtrar por tipo de documento">
              <BotaoAba ativa={tipoAtivo === "todos"} onClick={() => setTipoAtivo("todos")}>Todos ({documentos.length})</BotaoAba>
              {tipos.map(([tipo, qtd]) => <BotaoAba key={tipo} ativa={tipoAtivo === tipo} onClick={() => setTipoAtivo(tipo)}>{tipo} ({qtd})</BotaoAba>)}
            </BarraAbas>
          </section>

          <div className="flex items-center justify-between gap-3">
            <strong className="text-sm text-tinta">{visiveis.length} {visiveis.length === 1 ? "documento" : "documentos"}</strong>
            <span className="text-xs text-tinta-3">Clique para ver todos os dados</span>
          </div>

          {visiveis.length === 0 ? <Vazio>Nenhum documento corresponde a este filtro.</Vazio> : (
            <div className="space-y-3">
              {visiveis.map(({ entrega, semantica, achados, finalidades, tipo }) => (
                <details key={entrega.id} className="group overflow-hidden rounded-cartao border border-borda-forte bg-papel shadow-cartao open:shadow-cartao-forte">
                  <summary className="flex cursor-pointer list-none items-center gap-3 px-4 py-4 transition-colors hover:bg-papel-2 [&::-webkit-details-marker]:hidden sm:px-5">
                    <span className="inline-flex h-10 w-10 shrink-0 items-center justify-center rounded-campo bg-acao-clara text-acao"><FileSearch size={19} aria-hidden /></span>
                    <span className="min-w-0 flex-1">
                      <strong className="block truncate text-sm text-tinta" title={entrega.arquivo}>{entrega.arquivo}</strong>
                      <span className="mt-1 flex flex-wrap items-center gap-2 text-xs text-tinta-3">
                        <span>{tipo}</span><span aria-hidden>·</span><span>{achados.length} {achados.length === 1 ? "dado" : "dados"}</span>
                        <span aria-hidden>·</span><span>{finalidades.length} {finalidades.length === 1 ? "item atendido" : "itens atendidos"}</span>
                      </span>
                      {achados.length > 0 && <span className="mt-2 hidden flex-wrap gap-1.5 sm:flex">
                        {achados.slice(0, 3).map((achado, i) => <span key={`${achado.campo}-previa-${i}`} className="max-w-[220px] truncate rounded-pill border border-borda bg-papel-2 px-2 py-1 text-[11px] text-tinta-2" title={`${achado.campo}: ${achado.valor}`}>
                          <b className="font-semibold text-tinta">{capitalizacaoNatural(semUnderscore(achado.campo))}:</b> {capitalizacaoNatural(String(achado.valor))}
                        </span>)}
                      </span>}
                    </span>
                    <Selo tom={achados.length ? (semantica ? "info" : "neutro") : "atencao"}>{achados.length ? "Lido" : "Conferir"}</Selo>
                    <ChevronDown size={18} className="shrink-0 text-tinta-3 transition-transform group-open:rotate-180" aria-hidden />
                  </summary>

                  <div className="border-t border-borda px-4 py-4 sm:px-5">
                    {achados.length ? <div className="grid gap-3 lg:grid-cols-2">{achados.map((achado, i) => (
                      <div key={`${achado.campo}-${i}`} className="rounded-campo border border-borda bg-papel-2 p-3">
                        <span className="block text-xs font-semibold text-tinta-3">{capitalizacaoNatural(semUnderscore(achado.campo))}</span>
                        <strong className="mt-1 block font-codigo text-sm text-tinta [overflow-wrap:anywhere]">{String(achado.valor)}</strong>
                        {textoUtil(achado.importancia) && <span className="mt-2 block text-xs leading-relaxed text-tinta-2">{achado.importancia}</span>}
                        {textoUtil(achado.relevante_para) && <span className="mt-1 block text-xs text-acao">Importante para: {achado.relevante_para}</span>}
                      </div>))}</div>
                      : <p className="m-0 text-sm text-tinta-3">Nenhum dado jurídico específico foi destacado. Confira o arquivo original.</p>}
                    {finalidades.length > 0 && <div className="mt-4 border-t border-borda pt-4">
                      <strong className="text-xs text-tinta">Itens do checklist atendidos</strong>
                      <div className="mt-2 flex flex-wrap gap-2">{finalidades.map((f, i) => <Selo key={`${f.item}-${i}`} tom="info">{f.item}</Selo>)}</div>
                    </div>}
                  </div>
                </details>
              ))}
            </div>
          )}
        </div>
      )}
    </Cartao>
  );
}

function Indicador({ icone, rotulo, valor, tom = "info" }: { icone: React.ReactNode; rotulo: string; valor: number; tom?: "info" | "ok" | "atencao" }) {
  const estilo = { info: "border-acao-borda bg-acao-clara text-acao", ok: "border-ok-borda bg-ok-claro text-ok", atencao: "border-atencao-borda bg-atencao-claro text-atencao" }[tom];
  return <div className="rounded-cartao border border-borda bg-papel p-3 shadow-cartao sm:p-4">
    <span className={`inline-flex h-8 w-8 items-center justify-center rounded-campo border ${estilo}`}>{icone}</span>
    <strong className="mt-3 block font-titulo text-[1.7rem] leading-none text-tinta tabular-nums">{valor}</strong>
    <span className="mt-1 block text-xs text-tinta-3">{rotulo}</span>
  </div>;
}
