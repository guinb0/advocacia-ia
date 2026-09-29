"use client";

/**
 * Os documentos do caso ao lado da petição, sem sair dela.
 *
 * A gaveta não tem fundo escuro nem prende o foco: a petição continua editável
 * enquanto o documento está aberto — é para conferir um dado e seguir escrevendo.
 * Minimizada, vira uma aba na borda da tela que devolve o mesmo documento.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { ChevronLeft, ChevronRight, FileText, Loader2, Maximize2, Minus, Search, X } from "lucide-react";

import { PreviaDeEntrega, rotuloDoTipo } from "@/components/caso/PreviaArquivo";
import VisorEntrega from "@/components/caso/VisorEntrega";
import { Aviso, Botao } from "@/components/ui/Basicos";
import { obterCaso } from "@/lib/api";
import type { SituacaoCaso } from "@/lib/types";
import { cn } from "@/lib/utils";

type DocumentoDoCaso = { id: string; arquivo: string; rotulo: string };

/** Um arquivo pode atender dois itens (a CIN vale por RG e CPF): aparece uma vez só. */
function documentosDoCaso(situacao: SituacaoCaso): DocumentoDoCaso[] {
  const vistos = new Set<string>();
  const lista: DocumentoDoCaso[] = [];
  const incluir = (id: string, arquivo: string, rotulo: string) => {
    if (vistos.has(id)) return;
    vistos.add(id);
    lista.push({ id, arquivo, rotulo });
  };
  for (const item of situacao.itens) {
    for (const entrega of item.entregas) incluir(entrega.id, entrega.arquivo, item.nome);
  }
  for (const entrega of situacao.triagem ?? []) {
    incluir(entrega.id, entrega.arquivo, entrega.identificacao_ia?.trim() || "Ainda sem item do checklist");
  }
  return lista;
}

const BOTAO_ICONE =
  "inline-flex h-8 w-8 flex-none cursor-pointer items-center justify-center rounded-campo border-0 bg-transparent text-tinta-3 hover:bg-papel-3 hover:text-tinta disabled:cursor-not-allowed disabled:opacity-40";

type Props = { casoId: string; onFechar: () => void };

export default function GavetaDocumentos({ casoId, onFechar }: Props) {
  const [documentos, setDocumentos] = useState<DocumentoDoCaso[] | null>(null);
  const [erro, setErro] = useState<string | null>(null);
  const [abertoId, setAbertoId] = useState<string | null>(null);
  const [minimizada, setMinimizada] = useState(false);
  const [telaCheia, setTelaCheia] = useState(false);
  const [filtro, setFiltro] = useState("");
  const painel = useRef<HTMLElement>(null);

  const carregar = useCallback(async () => {
    setErro(null);
    setDocumentos(null);
    try {
      setDocumentos(documentosDoCaso(await obterCaso(casoId)));
    } catch (e) {
      setErro(e instanceof Error ? e.message : "Não foi possível carregar os documentos do caso.");
    }
  }, [casoId]);

  useEffect(() => {
    void carregar();
  }, [carregar]);

  const visiveis = useMemo(() => {
    const termo = filtro.trim().toLocaleLowerCase("pt-BR");
    if (!documentos || !termo) return documentos ?? [];
    return documentos.filter((d) => `${d.rotulo} ${d.arquivo}`.toLocaleLowerCase("pt-BR").includes(termo));
  }, [documentos, filtro]);

  const posicao = abertoId && documentos ? documentos.findIndex((d) => d.id === abertoId) : -1;
  const aberto = posicao >= 0 && documentos ? documentos[posicao] : null;

  // Esc só vale com o foco na gaveta: quem está digitando na petição não pode
  // perder o documento aberto por apertar Esc num campo dela.
  useEffect(() => {
    function aoTeclar(evento: KeyboardEvent) {
      if (evento.key !== "Escape" || telaCheia || !painel.current?.contains(document.activeElement)) return;
      if (aberto) setAbertoId(null);
      else onFechar();
    }
    window.addEventListener("keydown", aoTeclar);
    return () => window.removeEventListener("keydown", aoTeclar);
  }, [aberto, telaCheia, onFechar]);

  function passar(delta: number) {
    if (!documentos || posicao < 0) return;
    const proximo = documentos[posicao + delta];
    if (proximo) setAbertoId(proximo.id);
  }

  if (minimizada) {
    return (
      <button
        type="button"
        onClick={() => setMinimizada(false)}
        className="fixed right-0 top-1/3 z-[58] flex cursor-pointer items-center gap-2 rounded-l-campo border border-r-0 border-borda-forte bg-papel px-2 py-3 font-ui text-sm font-semibold text-acao shadow-modal [writing-mode:vertical-rl] hover:bg-acao-clara"
        title="Voltar a mostrar os documentos"
      >
        <FileText size={16} aria-hidden className="rotate-90" />
        {aberto ? `Documento: ${aberto.rotulo}` : "Documentos"}
      </button>
    );
  }

  return (
    <>
      <aside
        ref={painel}
        aria-label="Documentos do caso"
        className={cn(
          "fixed inset-y-0 right-0 z-[58] flex max-w-full flex-col border-l border-borda-forte bg-papel shadow-modal",
          aberto ? "w-[min(100vw,max(28rem,46vw))]" : "w-[min(100vw,22rem)]",
        )}
      >
        <header className="flex items-center gap-1 border-b border-borda bg-papel-2 px-3 py-2">
          {aberto ? (
            <>
              <button type="button" className={BOTAO_ICONE} onClick={() => setAbertoId(null)} title="Voltar para a lista">
                <ChevronLeft size={18} aria-hidden />
                <span className="sr-only">Voltar para a lista</span>
              </button>
              <div className="grid min-w-0 flex-1 leading-tight">
                <span className="truncate text-sm font-semibold text-tinta">{aberto.rotulo}</span>
                <span className="truncate font-codigo text-xs text-tinta-3">{aberto.arquivo}</span>
              </div>
              {documentos && documentos.length > 1 && (
                <>
                  <button
                    type="button"
                    className={BOTAO_ICONE}
                    onClick={() => passar(-1)}
                    disabled={posicao <= 0}
                    title="Documento anterior"
                  >
                    <ChevronLeft size={16} aria-hidden />
                    <span className="sr-only">Documento anterior</span>
                  </button>
                  <span className="text-xs tabular-nums text-tinta-3">
                    {posicao + 1}/{documentos.length}
                  </span>
                  <button
                    type="button"
                    className={BOTAO_ICONE}
                    onClick={() => passar(1)}
                    disabled={posicao >= documentos.length - 1}
                    title="Próximo documento"
                  >
                    <ChevronRight size={16} aria-hidden />
                    <span className="sr-only">Próximo documento</span>
                  </button>
                </>
              )}
              <button type="button" className={BOTAO_ICONE} onClick={() => setTelaCheia(true)} title="Abrir em tela cheia">
                <Maximize2 size={15} aria-hidden />
                <span className="sr-only">Abrir em tela cheia</span>
              </button>
            </>
          ) : (
            <h2 className="m-0 flex-1 pl-1 font-ui text-base font-semibold text-tinta">Documentos do caso</h2>
          )}
          <button type="button" className={BOTAO_ICONE} onClick={() => setMinimizada(true)} title="Minimizar">
            <Minus size={16} aria-hidden />
            <span className="sr-only">Minimizar</span>
          </button>
          <button type="button" className={BOTAO_ICONE} onClick={onFechar} title="Fechar">
            <X size={17} aria-hidden />
            <span className="sr-only">Fechar os documentos</span>
          </button>
        </header>

        {aberto ? (
          <div className="min-h-0 flex-1 bg-papel-3 p-2">
            <PreviaDeEntrega key={aberto.id} entregaId={aberto.id} arquivo={aberto.arquivo} />
          </div>
        ) : (
          <div className="grid min-h-0 flex-1 content-start gap-3 overflow-y-auto p-3">
            <p className="m-0 text-xs leading-relaxed text-tinta-3">
              Clique num documento para abri-lo ao lado da petição. Você continua escrevendo normalmente.
            </p>
            {erro && (
              <div className="grid gap-2">
                <Aviso tom="critico" titulo="Não deu para carregar os documentos">
                  {erro}
                </Aviso>
                <div>
                  <Botao variante="secundario" pequeno onClick={() => void carregar()}>
                    Tentar de novo
                  </Botao>
                </div>
              </div>
            )}
            {!documentos && !erro && (
              <p className="m-0 flex items-center gap-2 text-sm text-tinta-3" role="status">
                <Loader2 size={16} className="animate-spin" aria-hidden /> Carregando os documentos…
              </p>
            )}
            {documentos && documentos.length === 0 && (
              <p className="m-0 text-sm text-tinta-3">Este caso ainda não tem documentos enviados.</p>
            )}
            {documentos && documentos.length > 8 && (
              <label className="flex items-center gap-2 rounded-campo border border-borda-campo bg-papel px-2">
                <Search size={15} className="text-tinta-3" aria-hidden />
                <input
                  type="search"
                  value={filtro}
                  onChange={(e) => setFiltro(e.target.value)}
                  placeholder="Procurar documento"
                  className="min-h-9 flex-1 border-0 bg-transparent text-sm outline-none"
                />
              </label>
            )}
            {documentos && documentos.length > 0 && (
              <ul className="m-0 grid list-none gap-1 p-0">
                {visiveis.map((documento) => (
                  <li key={documento.id}>
                    <button
                      type="button"
                      onClick={() => setAbertoId(documento.id)}
                      className="flex w-full cursor-pointer items-start gap-2 rounded-campo border border-borda bg-papel px-3 py-2 text-left hover:border-acao hover:bg-acao-clara"
                    >
                      <FileText size={16} className="mt-[2px] flex-none text-tinta-3" aria-hidden />
                      <span className="grid min-w-0 gap-[2px]">
                        <span className="text-sm font-semibold text-tinta">{documento.rotulo}</span>
                        <span className="truncate text-xs text-tinta-3">
                          {rotuloDoTipo(documento.arquivo)} · {documento.arquivo}
                        </span>
                      </span>
                    </button>
                  </li>
                ))}
                {visiveis.length === 0 && <li className="text-sm text-tinta-3">Nenhum documento com esse nome.</li>}
              </ul>
            )}
          </div>
        )}
      </aside>

      {telaCheia && aberto && (
        <div className="relative z-[70]">
          <VisorEntrega entregaId={aberto.id} arquivo={aberto.arquivo} onFechar={() => setTelaCheia(false)} />
        </div>
      )}
    </>
  );
}
