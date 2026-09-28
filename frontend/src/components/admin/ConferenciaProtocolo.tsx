"use client";

/**
 * Conferência dos documentos para protocolo: a IA separa o que vai junto com a
 * petição, o advogado confere (com prévia de cada um), marca o que faltou e só
 * então baixa o .zip — tudo em PDF.
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import { createPortal } from "react-dom";

import { AlertTriangle, Eye, FileText, Loader2, X } from "lucide-react";

import VisorEntrega from "@/components/caso/VisorEntrega";
import { Aviso, Botao, Selo } from "@/components/ui/Basicos";
import { BotaoProcesso } from "@/components/ui/BotaoProcesso";
import {
  conferirPacoteDeProtocolo,
  type ConferenciaDoProtocolo,
  type DocumentoDoProtocolo,
  type DocumentoFaltando,
} from "@/lib/agente";
import type { TomSelo } from "@/lib/formato";
import { cn } from "@/lib/utils";

export type SelecaoDoProtocolo = { selecionados: string[]; faltando: string[] };

const GRAVIDADE: Record<string, { rotulo: string; tom: TomSelo; simbolo: string; ordem: number }> = {
  COMPROMETE: { rotulo: "Trava o protocolo", tom: "critico", simbolo: "!", ordem: 0 },
  ERA_MELHOR_TER: { rotulo: "Era melhor ter", tom: "atencao", simbolo: "•", ordem: 1 },
  NAO_INTERFERE: { rotulo: "Não interfere", tom: "neutro", simbolo: "–", ordem: 2 },
};

function porGravidade(a: DocumentoFaltando, b: DocumentoFaltando) {
  return (GRAVIDADE[a.classificacao ?? ""]?.ordem ?? 1) - (GRAVIDADE[b.classificacao ?? ""]?.ordem ?? 1);
}

type Props = {
  casoId: string;
  onFechar: () => void;
  /** Salva, baixa o PDF e o .zip. Devolve a mensagem de erro, ou `null` quando deu tudo certo. */
  onConcluir: (selecao: SelecaoDoProtocolo) => Promise<string | null>;
};

export default function ConferenciaProtocolo({ casoId, onFechar, onConcluir }: Props) {
  const [conferencia, setConferencia] = useState<ConferenciaDoProtocolo | null>(null);
  const [erroAoCarregar, setErroAoCarregar] = useState<string | null>(null);
  const [marcados, setMarcados] = useState<Set<string>>(new Set());
  const [aberto, setAberto] = useState<string | null>(null);
  const [concluindo, setConcluindo] = useState(false);
  const [erroAoConcluir, setErroAoConcluir] = useState<string | null>(null);

  const carregar = useCallback(async () => {
    setConferencia(null);
    setErroAoCarregar(null);
    try {
      const resposta = await conferirPacoteDeProtocolo(casoId);
      setConferencia(resposta);
      setMarcados(new Set(resposta.documentos.filter((d) => d.sugerido).map((d) => d.entrega_id)));
    } catch (e) {
      setErroAoCarregar(e instanceof Error ? e.message : "Não foi possível conferir os documentos.");
    }
  }, [casoId]);

  useEffect(() => {
    void carregar();
  }, [carregar]);

  useEffect(() => {
    function aoTeclar(evento: KeyboardEvent) {
      if (evento.key === "Escape" && !aberto && !concluindo) onFechar();
    }
    window.addEventListener("keydown", aoTeclar);
    return () => window.removeEventListener("keydown", aoTeclar);
  }, [aberto, concluindo, onFechar]);

  // As seções seguem a sugestão original: marcar ou desmarcar não faz o item
  // pular de lugar enquanto a pessoa ainda está lendo a lista.
  const vao = useMemo(() => conferencia?.documentos.filter((d) => d.sugerido) ?? [], [conferencia]);
  const outros = useMemo(() => conferencia?.documentos.filter((d) => !d.sugerido) ?? [], [conferencia]);
  const ordem = useMemo(() => [...vao, ...outros], [vao, outros]);
  const posicaoAberta = aberto ? ordem.findIndex((d) => d.entrega_id === aberto) : -1;
  const documentoAberto = posicaoAberta >= 0 ? ordem[posicaoAberta] : null;

  function alternar(id: string) {
    setMarcados((atual) => {
      const novo = new Set(atual);
      if (novo.has(id)) novo.delete(id);
      else novo.add(id);
      return novo;
    });
  }

  async function concluir() {
    if (!conferencia) return;
    setConcluindo(true);
    setErroAoConcluir(null);
    const erro = await onConcluir({
      selecionados: conferencia.documentos.filter((d) => marcados.has(d.entrega_id)).map((d) => d.entrega_id),
      faltando: conferencia.faltando.map((f) => {
        const gravidade = GRAVIDADE[f.classificacao ?? ""];
        return [
          gravidade ? `${f.documento} (${gravidade.rotulo.toLowerCase()})` : f.documento,
          f.motivo,
          f.como_obter ? `Como conseguir: ${f.como_obter}` : "",
        ].filter(Boolean).join(" — ");
      }),
    });
    setConcluindo(false);
    if (erro) setErroAoConcluir(erro);
  }

  const total = conferencia ? conferencia.documentos.filter((d) => marcados.has(d.entrega_id)).length : 0;

  return createPortal(
    <div
      className="fixed inset-0 z-[60] flex items-center justify-center bg-tinta/40 p-3 sm:p-6"
      onMouseDown={(evento) => {
        if (evento.target === evento.currentTarget && !concluindo) onFechar();
      }}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="titulo-conferencia-protocolo"
        className="flex max-h-full w-full max-w-3xl flex-col overflow-hidden rounded-cartao border border-borda-forte bg-papel shadow-cartao"
      >
        <header className="flex items-start justify-between gap-3 border-b border-borda px-5 py-4">
          <div className="grid gap-1">
            <h2 id="titulo-conferencia-protocolo" className="m-0 font-titulo text-lg font-semibold text-tinta">
              Confira os documentos para protocolo
            </h2>
            <p className="m-0 text-sm leading-relaxed text-tinta-3">
              A IA separou o que deve ir junto com a petição. Clique em um documento para ver como ele está.
              Desmarque o que não deve ir e marque o que faltou.
            </p>
          </div>
          <button
            type="button"
            aria-label="Fechar"
            disabled={concluindo}
            onClick={onFechar}
            className="rounded-campo p-1 text-tinta-3 hover:bg-papel-2 hover:text-tinta disabled:opacity-50"
          >
            <X size={20} />
          </button>
        </header>

        <div className="grid gap-5 overflow-y-auto px-5 py-4">
          {!conferencia && !erroAoCarregar && (
            <div className="grid justify-items-center gap-2 py-10 text-center" role="status">
              <Loader2 size={28} className="animate-spin text-acao" aria-hidden />
              <p className="m-0 text-sm font-semibold text-tinta">A IA está lendo os documentos do caso…</p>
              <p className="m-0 max-w-sm text-xs leading-relaxed text-tinta-3">
                Ela confere cada arquivo contra a petição para decidir o que vai para o protocolo. Pode
                levar até um minuto.
              </p>
            </div>
          )}

          {erroAoCarregar && (
            <div className="grid gap-3">
              <Aviso tom="critico" titulo="Não foi possível conferir os documentos">
                {erroAoCarregar}
              </Aviso>
              <div>
                <Botao type="button" variante="secundario" pequeno onClick={() => void carregar()}>
                  Tentar de novo
                </Botao>
              </div>
            </div>
          )}

          {conferencia && (
            <>
              {conferencia.aviso && <Aviso tom="atencao">{conferencia.aviso}</Aviso>}

              <section className="grid gap-2" aria-labelledby="secao-vao">
                <h3 id="secao-vao" className="m-0 text-sm font-semibold text-tinta">
                  Vão para o protocolo
                </h3>
                <ul className="m-0 grid list-none gap-2 p-0">
                  <li className="flex items-center gap-3 rounded-campo border border-borda bg-papel-2 px-3 py-2">
                    <input type="checkbox" checked disabled className="h-5 w-5 flex-none" aria-label="Petição Inicial" />
                    <FileText size={18} className="flex-none text-tinta-3" aria-hidden />
                    <div className="grid min-w-0 gap-[2px]">
                      <span className="text-sm font-semibold text-tinta">Petição Inicial</span>
                      <span className="text-xs text-tinta-3">A petição sempre vai, em PDF.</span>
                    </div>
                  </li>
                  {vao.map((documento) => (
                    <LinhaDocumento
                      key={documento.entrega_id}
                      documento={documento}
                      marcado={marcados.has(documento.entrega_id)}
                      onAlternar={() => alternar(documento.entrega_id)}
                      onVer={() => setAberto(documento.entrega_id)}
                    />
                  ))}
                </ul>
                {vao.length === 0 && (
                  <p className="m-0 text-sm text-tinta-3">A IA não achou documento para juntar. Marque abaixo.</p>
                )}
              </section>

              {conferencia.faltando.length > 0 && (
                <section
                  className="grid gap-2 rounded-campo border border-atencao-borda bg-atencao-claro px-4 py-3"
                  aria-labelledby="secao-faltando"
                >
                  <h3 id="secao-faltando" className="m-0 flex items-center gap-2 text-sm font-semibold text-tinta">
                    <AlertTriangle size={16} className="text-atencao" aria-hidden />
                    Está faltando
                  </h3>
                  <ul className="m-0 grid list-none gap-2 p-0 text-sm leading-relaxed text-tinta-2">
                    {[...conferencia.faltando].sort(porGravidade).map((item) => {
                      const gravidade = GRAVIDADE[item.classificacao ?? ""];
                      return (
                        <li key={item.documento} className="grid gap-[2px]">
                          <span className="flex flex-wrap items-center gap-2">
                            <strong className="text-tinta">{item.documento}</strong>
                            {gravidade && (
                              <Selo tom={gravidade.tom} simbolo={gravidade.simbolo}>
                                {gravidade.rotulo}
                              </Selo>
                            )}
                          </span>
                          {item.motivo && <span>{item.motivo}</span>}
                          {item.como_obter && (
                            <span className="text-xs text-tinta-3">Como conseguir: {item.como_obter}</span>
                          )}
                        </li>
                      );
                    })}
                  </ul>
                  <p className="m-0 text-xs leading-relaxed text-tinta-3">
                    Se algum destes já estiver entre os arquivos abaixo, é só marcar. O que continuar faltando
                    entra no checklist como pendência.
                  </p>
                </section>
              )}

              {outros.length > 0 && (
                <section className="grid gap-2" aria-labelledby="secao-outros">
                  <div className="grid gap-[2px]">
                    <h3 id="secao-outros" className="m-0 text-sm font-semibold text-tinta">
                      Outros documentos do caso
                    </h3>
                    <p className="m-0 text-xs text-tinta-3">
                      Estes ficam de fora. Se algum precisar ir, marque.
                    </p>
                  </div>
                  <ul className="m-0 grid list-none gap-2 p-0">
                    {outros.map((documento) => (
                      <LinhaDocumento
                        key={documento.entrega_id}
                        documento={documento}
                        marcado={marcados.has(documento.entrega_id)}
                        onAlternar={() => alternar(documento.entrega_id)}
                        onVer={() => setAberto(documento.entrega_id)}
                      />
                    ))}
                  </ul>
                </section>
              )}

              {conferencia.pendencias.length > 0 && (
                <details className="rounded-campo border border-borda px-4 py-2 text-sm text-tinta-2">
                  <summary className="cursor-pointer font-semibold text-tinta">
                    Pendências da petição ({conferencia.pendencias.length})
                  </summary>
                  <ul className="mb-1 mt-2 grid gap-1 pl-5 leading-relaxed">
                    {conferencia.pendencias.map((p) => (
                      <li key={p}>{p}</li>
                    ))}
                  </ul>
                </details>
              )}
            </>
          )}
        </div>

        <footer className="grid gap-3 border-t border-borda px-5 py-4">
          {erroAoConcluir && (
            <Aviso tom="critico" titulo="Não foi possível baixar">
              {erroAoConcluir}
            </Aviso>
          )}
          <div className="flex flex-wrap items-center justify-between gap-3">
            <span className="text-sm text-tinta-2">
              {conferencia ? `Vão no .zip: a petição e mais ${total} documento${total === 1 ? "" : "s"}.` : ""}
            </span>
            <div className="flex flex-wrap gap-2">
              <Botao type="button" variante="texto" pequeno disabled={concluindo} onClick={onFechar}>
                Cancelar
              </Botao>
              <BotaoProcesso
                variante="primario"
                pequeno
                processando={concluindo}
                textoProcessando="Montando os documentos…"
                aguardando={!conferencia}
                onClick={() => void concluir()}
              >
                Concluir e baixar (.zip)
              </BotaoProcesso>
            </div>
          </div>
        </footer>
      </div>

      {documentoAberto && (
        <div className="relative z-[70]">
          <VisorEntrega
            entregaId={documentoAberto.entrega_id}
            arquivo={documentoAberto.arquivo}
            onFechar={() => setAberto(null)}
            navegacao={{
              posicao: posicaoAberta + 1,
              total: ordem.length,
              rotulo: documentoAberto.rotulo,
              onAnterior: () => setAberto(ordem[Math.max(0, posicaoAberta - 1)].entrega_id),
              onProximo: () => setAberto(ordem[Math.min(ordem.length - 1, posicaoAberta + 1)].entrega_id),
            }}
          />
        </div>
      )}
    </div>,
    document.body,
  );
}

function LinhaDocumento({
  documento,
  marcado,
  onAlternar,
  onVer,
}: {
  documento: DocumentoDoProtocolo;
  marcado: boolean;
  onAlternar: () => void;
  onVer: () => void;
}) {
  const citadoRetirado = documento.citado_na_peticao && !marcado;
  return (
    <li
      className={cn(
        "flex items-start gap-3 rounded-campo border px-3 py-2 transition-colors",
        marcado ? "border-acao-borda bg-acao-clara" : "border-borda bg-papel",
      )}
    >
      <input
        type="checkbox"
        checked={marcado}
        onChange={onAlternar}
        className="mt-[2px] h-5 w-5 flex-none cursor-pointer"
        aria-label={marcado ? `Tirar ${documento.rotulo} do protocolo` : `Colocar ${documento.rotulo} no protocolo`}
      />
      <button
        type="button"
        onClick={onVer}
        className="grid min-w-0 flex-1 gap-1 text-left"
        title="Clique para ver o documento"
      >
        <span className="flex flex-wrap items-center gap-2">
          <span className="text-sm font-semibold text-tinta">{documento.rotulo}</span>
          {documento.citado_na_peticao && <Selo tom="info">Citado na petição</Selo>}
          {!documento.converte_para_pdf && documento.categoria !== "planilha" && (
            <Selo tom="atencao" simbolo="!">Não vira PDF</Selo>
          )}
        </span>
        {documento.rotulo !== documento.arquivo && (
          <span className="truncate text-xs text-tinta-3">{documento.arquivo}</span>
        )}
        <span className="text-xs leading-relaxed text-tinta-2">{documento.motivo}</span>
        {citadoRetirado && (
          <span className="text-xs font-semibold text-critico">
            A petição cita este documento. Se ele não for, ajuste a petição.
          </span>
        )}
      </button>
      <button
        type="button"
        onClick={onVer}
        className="flex flex-none items-center gap-1 rounded-campo px-2 py-1 text-xs font-semibold text-acao hover:bg-papel-2"
      >
        <Eye size={15} aria-hidden />
        Ver
      </button>
    </li>
  );
}
