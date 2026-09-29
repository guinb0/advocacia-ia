"use client";

/**
 * Preparação para protocolo: a IA separa o que vai junto com a petição, o advogado
 * confere (com prévia de cada um), tira o que não deve ir, coloca o que faltou —
 * do caso ou do próprio computador — e só então confirma e baixa o .zip.
 *
 * Tirar um documento daqui não apaga nada: ele só volta para "Outros documentos
 * do caso". E o que se coloca pelo computador vale só para este pacote — não vira
 * documento do caso nem passa por nova leitura.
 */

import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";

import { AlertTriangle, CheckCircle2, Eye, FileText, Loader2, Plus, Upload, X } from "lucide-react";

import { PreviaDeArquivoLocal, rotuloDoTipo, tipoDoArquivo } from "@/components/caso/PreviaArquivo";
import VisorEntrega from "@/components/caso/VisorEntrega";
import { Aviso, Botao, Selo } from "@/components/ui/Basicos";
import { BotaoProcesso } from "@/components/ui/BotaoProcesso";
import {
  conferirPacoteDeProtocolo,
  type AvulsoDoProtocolo,
  type ConferenciaDoProtocolo,
  type DocumentoDoProtocolo,
  type DocumentoFaltando,
} from "@/lib/agente";
import type { TomSelo } from "@/lib/formato";

export type SelecaoDoProtocolo = { selecionados: string[]; faltando: string[]; avulsos: AvulsoDoProtocolo[] };

export type ResumoDoPacote = { nome: string; arquivos: number; problemas: string[] };

export type ResultadoDaPreparacao = { erro: string } | { pacote: ResumoDoPacote };

const GRAVIDADE: Record<string, { rotulo: string; tom: TomSelo; simbolo: string; ordem: number }> = {
  COMPROMETE: { rotulo: "Trava o protocolo", tom: "critico", simbolo: "!", ordem: 0 },
  ERA_MELHOR_TER: { rotulo: "Era melhor ter", tom: "atencao", simbolo: "•", ordem: 1 },
  NAO_INTERFERE: { rotulo: "Não interfere", tom: "neutro", simbolo: "–", ordem: 2 },
};

/** Os mesmos limites do servidor (`pacote_protocolo.MAXIMO_*`): recusar aqui poupa o envio. */
const MAXIMO_AVULSOS = 20;
const MAXIMO_MB_AVULSO = 30;
/** O PJe só recebe PDF: aceita o que o servidor sabe converter. */
const ACEITOS = ".pdf,.png,.jpg,.jpeg,.webp,.bmp,.tif,.tiff,.docx";

function porGravidade(a: DocumentoFaltando, b: DocumentoFaltando) {
  return (GRAVIDADE[a.classificacao ?? ""]?.ordem ?? 1) - (GRAVIDADE[b.classificacao ?? ""]?.ordem ?? 1);
}

/** A ordem em que o servidor grava a pasta: planilha, documentos pelo número que a
 *  petição cita, os acrescentados do caso e, por fim, os colocados do computador. */
function ordemDoPacote(a: DocumentoDoProtocolo, b: DocumentoDoProtocolo, original: string[]) {
  const peso = (d: DocumentoDoProtocolo) => (d.categoria === "planilha" ? 0 : d.numero !== null ? 1 : 2);
  return (
    peso(a) - peso(b) ||
    (a.numero ?? 0) - (b.numero ?? 0) ||
    original.indexOf(a.entrega_id) - original.indexOf(b.entrega_id)
  );
}

function semExtensao(nome: string) {
  return nome.includes(".") ? nome.slice(0, nome.lastIndexOf(".")) : nome;
}

type Avulso = AvulsoDoProtocolo & { chave: string };

type Props = {
  casoId: string;
  onFechar: () => void;
  /** Salva a petição e monta o .zip com a seleção conferida. */
  onConcluir: (selecao: SelecaoDoProtocolo) => Promise<ResultadoDaPreparacao>;
};

export default function ConferenciaProtocolo({ casoId, onFechar, onConcluir }: Props) {
  const [conferencia, setConferencia] = useState<ConferenciaDoProtocolo | null>(null);
  const [erroAoCarregar, setErroAoCarregar] = useState<string | null>(null);
  const [noPacote, setNoPacote] = useState<Set<string>>(new Set());
  const [avulsos, setAvulsos] = useState<Avulso[]>([]);
  const [recusados, setRecusados] = useState<string[]>([]);
  const [aberto, setAberto] = useState<string | null>(null);
  const [avulsoAberto, setAvulsoAberto] = useState<string | null>(null);
  const [concluindo, setConcluindo] = useState(false);
  const [erroAoConcluir, setErroAoConcluir] = useState<string | null>(null);
  const [pronto, setPronto] = useState<ResumoDoPacote | null>(null);
  const seletor = useRef<HTMLInputElement>(null);

  const carregar = useCallback(async () => {
    setConferencia(null);
    setErroAoCarregar(null);
    try {
      const resposta = await conferirPacoteDeProtocolo(casoId);
      setConferencia(resposta);
      setNoPacote(new Set(resposta.documentos.filter((d) => d.sugerido).map((d) => d.entrega_id)));
    } catch (e) {
      setErroAoCarregar(e instanceof Error ? e.message : "Não foi possível conferir os documentos.");
    }
  }, [casoId]);

  useEffect(() => {
    void carregar();
  }, [carregar]);

  useEffect(() => {
    function aoTeclar(evento: KeyboardEvent) {
      if (evento.key !== "Escape" || concluindo) return;
      if (avulsoAberto) setAvulsoAberto(null);
      else if (!aberto) onFechar();
    }
    window.addEventListener("keydown", aoTeclar);
    return () => window.removeEventListener("keydown", aoTeclar);
  }, [aberto, avulsoAberto, concluindo, onFechar]);

  const idsOriginais = useMemo(() => conferencia?.documentos.map((d) => d.entrega_id) ?? [], [conferencia]);
  const selecionados = useMemo(
    () =>
      (conferencia?.documentos.filter((d) => noPacote.has(d.entrega_id)) ?? []).sort((a, b) =>
        ordemDoPacote(a, b, idsOriginais),
      ),
    [conferencia, noPacote, idsOriginais],
  );
  const foraDoPacote = useMemo(
    () => conferencia?.documentos.filter((d) => !noPacote.has(d.entrega_id)) ?? [],
    [conferencia, noPacote],
  );
  // Quem entra sem número recebe o próximo livre, como o servidor faz ao montar.
  const rotulosFinais = useMemo(() => {
    let proximo = Math.max(0, ...(conferencia?.documentos.map((d) => d.numero ?? 0) ?? [])) + 1;
    const rotulos = new Map<string, string>();
    for (const d of selecionados) {
      if (d.categoria === "planilha" || d.numero !== null) rotulos.set(d.entrega_id, d.rotulo);
      else rotulos.set(d.entrega_id, `Doc ${proximo++}. ${d.rotulo}`);
    }
    for (const a of avulsos) rotulos.set(a.chave, `Doc ${proximo++}. ${a.nome.trim() || semExtensao(a.arquivo.name)}`);
    return rotulos;
  }, [conferencia, selecionados, avulsos]);

  const navegaveis = useMemo(() => [...selecionados, ...foraDoPacote], [selecionados, foraDoPacote]);
  const posicaoAberta = aberto ? navegaveis.findIndex((d) => d.entrega_id === aberto) : -1;
  const documentoAberto = posicaoAberta >= 0 ? navegaveis[posicaoAberta] : null;
  const avulsoEmPrevia = avulsos.find((a) => a.chave === avulsoAberto) ?? null;

  const citadosFora = foraDoPacote.filter((d) => d.citado_na_peticao);
  const semPdf = selecionados
    .filter((d) => !d.converte_para_pdf && d.categoria !== "planilha")
    .map((d) => rotulosFinais.get(d.entrega_id) ?? d.rotulo);

  function tirar(id: string) {
    setNoPacote((atual) => {
      const novo = new Set(atual);
      novo.delete(id);
      return novo;
    });
  }

  function colocar(id: string) {
    setNoPacote((atual) => new Set(atual).add(id));
  }

  function receberArquivos(lista: FileList | null) {
    if (!lista?.length) return;
    const avisos: string[] = [];
    const novos: Avulso[] = [];
    for (const arquivo of Array.from(lista)) {
      const repetido = [...avulsos, ...novos].some(
        (a) => a.arquivo.name === arquivo.name && a.arquivo.size === arquivo.size,
      );
      if (repetido) {
        avisos.push(`«${arquivo.name}» já está na lista.`);
      } else if (arquivo.size === 0) {
        avisos.push(`«${arquivo.name}» está vazio.`);
      } else if (arquivo.size > MAXIMO_MB_AVULSO * 1024 * 1024) {
        avisos.push(`«${arquivo.name}» passa de ${MAXIMO_MB_AVULSO} MB.`);
      } else if (!["pdf", "imagem", "docx"].includes(tipoDoArquivo(arquivo.name))) {
        avisos.push(`«${arquivo.name}» não é PDF, imagem nem Word — o PJe não aceitaria.`);
      } else if (avulsos.length + novos.length >= MAXIMO_AVULSOS) {
        avisos.push(`Limite de ${MAXIMO_AVULSOS} documentos novos: «${arquivo.name}» ficou de fora.`);
      } else {
        novos.push({ chave: crypto.randomUUID(), arquivo, nome: semExtensao(arquivo.name) });
      }
    }
    setAvulsos((atual) => [...atual, ...novos]);
    setRecusados(avisos);
    if (seletor.current) seletor.current.value = "";
  }

  async function concluir() {
    if (!conferencia) return;
    setConcluindo(true);
    setErroAoConcluir(null);
    const resultado = await onConcluir({
      selecionados: selecionados.map((d) => d.entrega_id),
      avulsos: avulsos.map(({ arquivo, nome }) => ({ arquivo, nome: nome.trim() || semExtensao(arquivo.name) })),
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
    if ("erro" in resultado) setErroAoConcluir(resultado.erro);
    else setPronto(resultado.pacote);
  }

  const total = selecionados.length + avulsos.length;

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
              Preparação para protocolo
            </h2>
            {!pronto && (
              <ol className="m-0 flex list-none flex-wrap gap-x-4 gap-y-1 p-0 text-sm text-tinta-2">
                <li><strong className="text-acao">1.</strong> Confira a lista</li>
                <li><strong className="text-acao">2.</strong> Clique para ver cada documento</li>
                <li><strong className="text-acao">3.</strong> Tire ou coloque o que precisar</li>
                <li><strong className="text-acao">4.</strong> Confirme</li>
              </ol>
            )}
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

        {pronto ? (
          <PacotePronto pacote={pronto} onFechar={onFechar} />
        ) : (
          <>
            <div className="grid gap-5 overflow-y-auto px-5 py-4">
              {!conferencia && !erroAoCarregar && (
                <div className="grid justify-items-center gap-2 py-10 text-center" role="status">
                  <Loader2 size={28} className="animate-spin text-acao" aria-hidden />
                  <p className="m-0 text-sm font-semibold text-tinta">Separando os documentos do caso…</p>
                  <p className="m-0 max-w-sm text-xs leading-relaxed text-tinta-3">
                    A IA usa a leitura e a análise que os documentos já têm para decidir o que vai com a
                    petição. Pode levar até um minuto.
                  </p>
                </div>
              )}

              {erroAoCarregar && (
                <div className="grid gap-3">
                  <Aviso tom="critico" titulo="Não foi possível separar os documentos">
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
                    <div className="grid gap-[2px]">
                      <h3 id="secao-vao" className="m-0 text-sm font-semibold text-tinta">
                        Documentos selecionados para protocolo
                      </h3>
                      <p className="m-0 text-xs text-tinta-3">
                        Nesta ordem, dentro do .zip. O <X size={11} className="inline" aria-hidden /> tira do pacote,
                        mas não apaga o documento do caso.
                      </p>
                    </div>
                    <ul className="m-0 grid list-none gap-2 p-0">
                      <li className="flex items-center gap-3 rounded-campo border border-borda bg-papel-2 px-3 py-2">
                        <FileText size={18} className="flex-none text-tinta-3" aria-hidden />
                        <div className="grid min-w-0 gap-[2px]">
                          <span className="text-sm font-semibold text-tinta">Petição Inicial</span>
                          <span className="text-xs text-tinta-3">Sempre vai primeiro, em PDF.</span>
                        </div>
                      </li>
                      {selecionados.map((documento) => (
                        <LinhaNoPacote
                          key={documento.entrega_id}
                          titulo={rotulosFinais.get(documento.entrega_id) ?? documento.rotulo}
                          arquivo={documento.arquivo}
                          motivo={documento.motivo}
                          selos={
                            <>
                              {documento.citado_na_peticao && <Selo tom="info">Citado na petição</Selo>}
                              {!documento.converte_para_pdf && documento.categoria !== "planilha" && (
                                <Selo tom="atencao" simbolo="!">Não vira PDF</Selo>
                              )}
                            </>
                          }
                          onVer={() => setAberto(documento.entrega_id)}
                          onTirar={() => tirar(documento.entrega_id)}
                        />
                      ))}
                      {avulsos.map((avulso) => (
                        <LinhaNoPacote
                          key={avulso.chave}
                          titulo={rotulosFinais.get(avulso.chave) ?? avulso.nome}
                          arquivo={avulso.arquivo.name}
                          motivo={`${rotuloDoTipo(avulso.arquivo.name)} do seu computador — vale só para este pacote.`}
                          selos={<Selo tom="ok">Novo</Selo>}
                          onVer={() => setAvulsoAberto(avulso.chave)}
                          onTirar={() => setAvulsos((atual) => atual.filter((a) => a.chave !== avulso.chave))}
                        >
                          <label className="flex flex-wrap items-center gap-2 text-xs text-tinta-3">
                            Nome no pacote:
                            <input
                              value={avulso.nome}
                              maxLength={100}
                              onChange={(e) =>
                                setAvulsos((atual) =>
                                  atual.map((a) => (a.chave === avulso.chave ? { ...a, nome: e.target.value } : a)),
                                )
                              }
                              className="min-h-8 min-w-0 flex-1 rounded-campo border border-borda-campo bg-papel px-2 text-sm text-tinta"
                            />
                          </label>
                        </LinhaNoPacote>
                      ))}
                    </ul>
                    {selecionados.length + avulsos.length === 0 && (
                      <p className="m-0 text-sm text-tinta-3">
                        Só a petição vai por enquanto. Coloque documentos abaixo.
                      </p>
                    )}
                    <div className="grid gap-2">
                      <div>
                        <Botao type="button" variante="secundario" pequeno onClick={() => seletor.current?.click()}>
                          <Upload size={15} aria-hidden /> Colocar documentos novos
                        </Botao>
                        <input
                          ref={seletor}
                          type="file"
                          multiple
                          accept={ACEITOS}
                          className="hidden"
                          onChange={(e) => receberArquivos(e.target.files)}
                        />
                      </div>
                      <p className="m-0 text-xs text-tinta-3">
                        Do seu computador: PDF, foto ou Word, até {MAXIMO_MB_AVULSO} MB cada. Eles entram só neste
                        .zip.
                      </p>
                      {recusados.length > 0 && (
                        <Aviso tom="atencao" titulo="Alguns arquivos não entraram">
                          <ul className="m-0 grid gap-1 pl-4">
                            {recusados.map((r) => (
                              <li key={r}>{r}</li>
                            ))}
                          </ul>
                        </Aviso>
                      )}
                    </div>
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
                        Tem o arquivo? Coloque por “Outros documentos do caso” ou “Colocar documentos novos”. O que
                        continuar faltando vai para o checklist como pendência.
                      </p>
                    </section>
                  )}

                  {foraDoPacote.length > 0 && (
                    <details className="group rounded-campo border border-borda" open={selecionados.length === 0}>
                      <summary className="cursor-pointer list-none px-4 py-3 text-sm font-semibold text-tinta">
                        <span className="mr-1 inline-block transition-transform group-open:rotate-90" aria-hidden>
                          ›
                        </span>
                        Outros documentos do caso ({foraDoPacote.length}) — ficam de fora
                      </summary>
                      <ul className="m-0 grid list-none gap-2 px-4 pb-4 pt-0">
                        {foraDoPacote.map((documento) => (
                          <LinhaFora
                            key={documento.entrega_id}
                            documento={documento}
                            onVer={() => setAberto(documento.entrega_id)}
                            onColocar={() => colocar(documento.entrega_id)}
                          />
                        ))}
                      </ul>
                    </details>
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
              {conferencia && (citadosFora.length > 0 || semPdf.length > 0) && (
                <Aviso tom="atencao" titulo="Confira antes de confirmar">
                  <ul className="m-0 grid gap-1 pl-4">
                    {citadosFora.map((d) => (
                      <li key={d.entrega_id}>
                        A petição cita <strong>{d.rotulo}</strong>, mas ele está fora do pacote.
                      </li>
                    ))}
                    {semPdf.map((rotulo) => (
                      <li key={rotulo}>
                        <strong>{rotulo}</strong> não pode ser convertido para PDF e vai no formato original.
                      </li>
                    ))}
                  </ul>
                </Aviso>
              )}
              {erroAoConcluir && (
                <Aviso tom="critico" titulo="O pacote não foi preparado">
                  {erroAoConcluir}
                </Aviso>
              )}
              <div className="flex flex-wrap items-center justify-between gap-3">
                <span className="text-sm text-tinta-2">
                  {conferencia
                    ? `Vão no .zip: a petição e mais ${total} documento${total === 1 ? "" : "s"}.`
                    : ""}
                </span>
                <div className="flex flex-wrap gap-2">
                  <Botao type="button" variante="texto" pequeno disabled={concluindo} onClick={onFechar}>
                    Cancelar
                  </Botao>
                  <BotaoProcesso
                    variante="primario"
                    pequeno
                    processando={concluindo}
                    textoProcessando="Preparando o .zip…"
                    aguardando={!conferencia}
                    onClick={() => void concluir()}
                  >
                    Confirmar e preparar protocolo
                  </BotaoProcesso>
                </div>
              </div>
            </footer>
          </>
        )}
      </div>

      {documentoAberto && (
        <div className="relative z-[70]">
          <VisorEntrega
            entregaId={documentoAberto.entrega_id}
            arquivo={documentoAberto.arquivo}
            onFechar={() => setAberto(null)}
            navegacao={{
              posicao: posicaoAberta + 1,
              total: navegaveis.length,
              rotulo: rotulosFinais.get(documentoAberto.entrega_id) ?? documentoAberto.rotulo,
              onAnterior: () => setAberto(navegaveis[Math.max(0, posicaoAberta - 1)].entrega_id),
              onProximo: () => setAberto(navegaveis[Math.min(navegaveis.length - 1, posicaoAberta + 1)].entrega_id),
            }}
          />
        </div>
      )}

      {avulsoEmPrevia && (
        <div
          className="fixed inset-0 z-[70] flex items-center justify-center bg-tinta/40 p-3 sm:p-6"
          onMouseDown={(evento) => {
            if (evento.target === evento.currentTarget) setAvulsoAberto(null);
          }}
        >
          <div
            role="dialog"
            aria-modal="true"
            aria-label={`Documento ${avulsoEmPrevia.arquivo.name}`}
            className="flex h-full max-h-[90vh] w-full max-w-4xl flex-col overflow-hidden rounded-cartao border border-borda-forte bg-papel shadow-modal"
          >
            <div className="flex items-center justify-between gap-3 border-b border-borda bg-papel-2 px-4 py-3">
              <div className="grid min-w-0">
                <span className="truncate text-sm font-semibold text-tinta">
                  {rotulosFinais.get(avulsoEmPrevia.chave) ?? avulsoEmPrevia.nome}
                </span>
                <span className="truncate font-codigo text-xs text-tinta-3">{avulsoEmPrevia.arquivo.name}</span>
              </div>
              <Botao variante="secundario" pequeno onClick={() => setAvulsoAberto(null)}>
                Fechar <X size={14} aria-hidden />
              </Botao>
            </div>
            <div className="min-h-0 flex-1 bg-papel-3 p-2">
              <PreviaDeArquivoLocal arquivo={avulsoEmPrevia.arquivo} />
            </div>
          </div>
        </div>
      )}
    </div>,
    document.body,
  );
}

function LinhaNoPacote({
  titulo,
  arquivo,
  motivo,
  selos,
  onVer,
  onTirar,
  children,
}: {
  titulo: string;
  arquivo: string;
  motivo: string;
  selos?: ReactNode;
  onVer: () => void;
  onTirar: () => void;
  children?: ReactNode;
}) {
  return (
    <li className="flex items-start gap-3 rounded-campo border border-acao-borda bg-acao-clara px-3 py-2">
      <FileText size={18} className="mt-[2px] flex-none text-acao" aria-hidden />
      <div className="grid min-w-0 flex-1 gap-1">
        <button type="button" onClick={onVer} className="grid min-w-0 gap-1 text-left" title="Clique para ver o documento">
          <span className="flex flex-wrap items-center gap-2">
            <span className="text-sm font-semibold text-tinta">{titulo}</span>
            {selos}
          </span>
          {!titulo.endsWith(semExtensao(arquivo)) && <span className="truncate text-xs text-tinta-3">{arquivo}</span>}
          <span className="text-xs leading-relaxed text-tinta-2">{motivo}</span>
        </button>
        {children}
      </div>
      <button
        type="button"
        onClick={onVer}
        className="flex flex-none items-center gap-1 rounded-campo px-2 py-1 text-xs font-semibold text-acao hover:bg-papel"
      >
        <Eye size={15} aria-hidden />
        Ver
      </button>
      <button
        type="button"
        onClick={onTirar}
        aria-label={`Tirar ${titulo} do pacote`}
        title="Tirar do pacote (o documento continua no caso)"
        className="flex flex-none items-center rounded-campo p-1 text-tinta-3 hover:bg-critico-claro hover:text-critico"
      >
        <X size={18} aria-hidden />
      </button>
    </li>
  );
}

function LinhaFora({
  documento,
  onVer,
  onColocar,
}: {
  documento: DocumentoDoProtocolo;
  onVer: () => void;
  onColocar: () => void;
}) {
  return (
    <li className="flex items-start gap-3 rounded-campo border border-borda bg-papel px-3 py-2">
      <button type="button" onClick={onVer} className="grid min-w-0 flex-1 gap-1 text-left" title="Clique para ver o documento">
        <span className="flex flex-wrap items-center gap-2">
          <span className="text-sm font-semibold text-tinta">{documento.rotulo}</span>
          {documento.citado_na_peticao && <Selo tom="critico" simbolo="!">A petição cita</Selo>}
        </span>
        {documento.rotulo !== documento.arquivo && (
          <span className="truncate text-xs text-tinta-3">{documento.arquivo}</span>
        )}
        <span className="text-xs leading-relaxed text-tinta-2">{documento.motivo}</span>
      </button>
      <button
        type="button"
        onClick={onVer}
        className="flex flex-none items-center gap-1 rounded-campo px-2 py-1 text-xs font-semibold text-acao hover:bg-papel-2"
      >
        <Eye size={15} aria-hidden />
        Ver
      </button>
      <Botao type="button" variante="secundario" pequeno onClick={onColocar}>
        <Plus size={14} aria-hidden /> Colocar
      </Botao>
    </li>
  );
}

function PacotePronto({ pacote, onFechar }: { pacote: ResumoDoPacote; onFechar: () => void }) {
  return (
    <div className="grid gap-4 overflow-y-auto px-5 py-6">
      <div className="flex items-start gap-3">
        <CheckCircle2 size={28} className="flex-none text-ok" aria-hidden />
        <div className="grid gap-1">
          <p className="m-0 text-base font-semibold text-tinta">Pronto! O .zip foi baixado.</p>
          <p className="m-0 text-sm text-tinta-2 [overflow-wrap:anywhere]">
            <strong>{pacote.nome}</strong> — {pacote.arquivos} arquivos dentro, com a lista de documentação e o
            checklist.
          </p>
        </div>
      </div>
      {pacote.problemas.length > 0 ? (
        <Aviso tom="atencao" titulo="Estes documentos precisam da sua atenção">
          <ul className="m-0 grid gap-1 pl-4">
            {pacote.problemas.map((p) => (
              <li key={p}>{p}</li>
            ))}
          </ul>
          <p className="mb-0 mt-2">Eles também estão no Checklist.pdf, dentro do .zip.</p>
        </Aviso>
      ) : (
        <p className="m-0 text-sm text-tinta-2">Todos os documentos entraram. Confira o Checklist.pdf antes de protocolar.</p>
      )}
      <div className="flex justify-end">
        <Botao variante="primario" pequeno onClick={onFechar}>
          Fechar
        </Botao>
      </div>
    </div>
  );
}
