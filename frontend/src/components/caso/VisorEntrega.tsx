"use client";

import { useEffect, useRef, useState } from "react";

import { baixarArquivoEntregaPdf, obterEntrega } from "@/lib/api";
import { ESTILO_VEREDITO } from "@/lib/formato";
import type { EntregaDetalhe } from "@/lib/types";
import { useArquivoEntrega } from "@/lib/useArquivo";
import { Aviso, LinkBotao, Selo } from "@/components/ui/Basicos";

function ehPdf(nome: string): boolean {
  return nome.toLowerCase().endsWith(".pdf");
}

interface Props {
  entregaId: string;
  arquivo: string;
  onFechar: () => void;
}

/** Mostra o arquivo como chegou (sem baixar) e os campos que o OCR extraiu. */
export default function VisorEntrega({ entregaId, arquivo, onFechar }: Props) {
  const [detalhe, setDetalhe] = useState<EntregaDetalhe | null>(null);
  const [erro, setErro] = useState<string | null>(null);
  const [baixandoPdf, setBaixandoPdf] = useState(false);
  const [erroPdf, setErroPdf] = useState<string | null>(null);
  const fecharRef = useRef<HTMLButtonElement>(null);
  const { url: urlArquivo, erro: erroArquivo } = useArquivoEntrega(entregaId);

  useEffect(() => {
    let cancelado = false;
    obterEntrega(entregaId)
      .then((d) => {
        if (!cancelado) setDetalhe(d);
      })
      .catch((e) => {
        if (!cancelado) setErro(e instanceof Error ? e.message : "Falha ao carregar a entrega.");
      });
    return () => {
      cancelado = true;
    };
  }, [entregaId]);

  // Esc fecha; o foco vai para o botão de fechar para quem navega por teclado.
  useEffect(() => {
    fecharRef.current?.focus();
    function aoTeclar(e: KeyboardEvent) {
      if (e.key === "Escape") {
        e.stopPropagation();
        onFechar();
      }
    }
    window.addEventListener("keydown", aoTeclar, true);
    return () => window.removeEventListener("keydown", aoTeclar, true);
  }, [onFechar]);

  const extracao = detalhe?.extracao;
  const validacao = extracao?.validacao;
  const campos = extracao?.campos ?? [];
  const veredito = validacao ? ESTILO_VEREDITO[validacao.veredito] : null;

  async function baixarPdf() {
    setBaixandoPdf(true);
    setErroPdf(null);
    try {
      const pdf = await baixarArquivoEntregaPdf(entregaId);
      const url = URL.createObjectURL(pdf.arquivo);
      const link = document.createElement("a");
      link.href = url;
      link.download = pdf.nome;
      link.click();
      URL.revokeObjectURL(url);
    } catch (e) {
      setErroPdf(e instanceof Error ? e.message : "Não foi possível gerar o PDF.");
    } finally {
      setBaixandoPdf(false);
    }
  }

  return (
    <div
      className="fixed inset-0 flex items-center justify-center p-6 z-50 bg-[rgba(20,32,46,0.45)]"
      onClick={(e) => {
        if (e.target === e.currentTarget) onFechar();
      }}
      role="dialog"
      aria-modal="true"
      aria-label={`Documento ${arquivo}`}
    >
      <div className="w-[min(1100px,100%)] max-h-full flex flex-col border border-borda-forte rounded-cartao bg-papel shadow-modal overflow-hidden">
        <div className="flex justify-between items-center gap-4 px-5 py-[14px] border-b border-borda bg-papel-2 flex-wrap">
          <div>
            <h2 className="m-0 text-lg">Documento enviado</h2>
            <div className="mt-[2px] text-tinta-3 font-codigo text-xs [overflow-wrap:anywhere]">{arquivo}</div>
          </div>
          {/* Botão nativo, não o primitivo <Botao>: ele não encaminha `ref`, e
            * o foco ao abrir depende de um ref real no DOM. */}
          <button
            ref={fecharRef}
            type="button"
            className="min-h-8 px-[11px] py-[6px] text-xs gap-[6px] inline-flex items-center justify-center border border-borda-campo bg-papel text-acao rounded-campo font-ui font-semibold text-center no-underline cursor-pointer transition-[background-color,border-color,color] duration-[120ms] ease-out hover:bg-acao-clara hover:border-acao"
            onClick={onFechar}
          >
            Fechar ✕
          </button>
        </div>

        <div className="grid grid-cols-[minmax(280px,45%)_1fr] max-[900px]:grid-cols-1 overflow-hidden min-h-0">
          <div className="flex items-center justify-center p-[14px] border-r border-borda bg-papel-3 overflow-auto min-h-[260px]">
            {erroArquivo ? (
              <p className="p-6 text-tinta-3 text-sm leading-[1.6] text-center">{erroArquivo}</p>
            ) : !urlArquivo ? (
              <p className="p-6 text-tinta-3 text-sm leading-[1.6] text-center">Carregando o arquivo…</p>
            ) : ehPdf(arquivo) ? (
              <iframe
                className="w-full h-[68vh] border-none rounded-campo bg-papel"
                src={urlArquivo}
                title={`Pré-visualização de ${arquivo}`}
              />
            ) : (
              /* eslint-disable-next-line @next/next/no-img-element -- é um
                 object URL de blob, que o otimizador do Next não processa. */
              <img
                className="max-w-full max-h-[68vh] rounded-campo shadow-cartao-forte object-contain block"
                src={urlArquivo}
                alt={`Documento ${arquivo}`}
              />
            )}
          </div>

          <div className="px-5 pb-5 pt-[18px] overflow-auto min-h-0">
            {erro ? (
              <Aviso tom="critico" titulo="Falha ao carregar os dados">
                {erro}
              </Aviso>
            ) : !detalhe ? (
              <p className="py-6 text-tinta-3 text-sm leading-[1.6]">Carregando os dados extraídos…</p>
            ) : !extracao ? (
              <Aviso tom="atencao" titulo="Sem leitura guardada">
                Esta entrega foi registrada sem extração guardada. Reenvie o arquivo para
                extrair os campos.
              </Aviso>
            ) : (
              <>
                {validacao && veredito && (
                  <Aviso tom={veredito.tom} titulo={veredito.rotulo}>
                    {validacao.resumo}
                  </Aviso>
                )}

                <div className="grid grid-cols-[repeat(auto-fit,minmax(120px,1fr))] gap-2 my-[14px] mb-[18px]">
                  <div className="px-[11px] py-[9px] border border-borda rounded-campo bg-papel-2">
                    <span className="block text-tinta-3 text-xs">Tipo lido</span>
                    <span className="block mt-[1px] text-tinta text-base font-semibold tabular-nums">
                      {extracao.tipo.descricao_detectado}
                    </span>
                  </div>
                  <div className="px-[11px] py-[9px] border border-borda rounded-campo bg-papel-2">
                    <span className="block text-tinta-3 text-xs">Nitidez</span>
                    <span className="block mt-[1px] text-tinta text-base font-semibold tabular-nums">
                      {extracao.qualidade_imagem.score_legibilidade}%
                    </span>
                  </div>
                  <div className="px-[11px] py-[9px] border border-borda rounded-campo bg-papel-2">
                    <span className="block text-tinta-3 text-xs">Dados encontrados</span>
                    <span className="block mt-[1px] text-tinta text-base font-semibold tabular-nums">
                      {validacao?.completude_percentual ?? 0}%
                    </span>
                  </div>
                  <div className="px-[11px] py-[9px] border border-borda rounded-campo bg-papel-2">
                    <span className="block text-tinta-3 text-xs">Tempo de leitura</span>
                    <span className="block mt-[1px] text-tinta text-base font-semibold tabular-nums">
                      {extracao.tempo_processamento_s}s
                    </span>
                  </div>
                </div>

                <span className="block my-[18px] mb-2 text-tinta text-sm font-bold">
                  Dados lidos ({campos.length})
                </span>

                {campos.length === 0 ? (
                  <p className="py-6 text-tinta-3 text-sm leading-[1.6]">
                    Nenhum campo estruturado foi extraído deste documento.
                  </p>
                ) : (
                  <table className="w-full border-collapse">
                    <thead>
                      <tr>
                        <th className="pr-[10px] py-[9px] pl-0 border-b border-borda-forte text-tinta-2 text-xs font-bold text-left">
                          Campo
                        </th>
                        <th className="pr-[10px] py-[9px] pl-0 border-b border-borda-forte text-tinta-2 text-xs font-bold text-left">
                          Valor lido
                        </th>
                        <th className="pr-[10px] py-[9px] pl-0 border-b border-borda-forte text-tinta-2 text-xs font-bold text-right">
                          Certeza
                        </th>
                        <th className="pr-[10px] py-[9px] pl-0 border-b border-borda-forte text-tinta-2 text-xs font-bold text-left">
                          Conferência
                        </th>
                      </tr>
                    </thead>
                    <tbody>
                      {campos.map((campo) => (
                        <tr key={campo.nome} className="last:[&>td]:border-b-0">
                          <td className="pr-[10px] py-[10px] pl-0 border-b border-borda text-tinta-2 text-sm align-top text-tinta-3 whitespace-nowrap">
                            {campo.rotulo}
                          </td>
                          <td className="pr-[10px] py-[10px] pl-0 border-b border-borda text-tinta-2 text-sm align-top">
                            <span className="text-tinta font-codigo tabular-nums text-sm select-all [overflow-wrap:anywhere]">
                              {campo.valor || "—"}
                            </span>
                            {campo.observacao && (
                              <div className="pt-1 text-tinta-3 text-xs leading-[1.5]">{campo.observacao}</div>
                            )}
                          </td>
                          <td className="pr-[10px] py-[10px] pl-0 border-b border-borda align-top text-tinta-3 font-codigo tabular-nums text-xs text-right whitespace-nowrap">
                            {Math.round(campo.confianca * 100)}%
                          </td>
                          <td className="pr-[10px] py-[10px] pl-0 border-b border-borda align-top">
                            {campo.valido === null ? null : campo.valido ? (
                              <Selo tom="ok" simbolo="✓">
                                válido
                              </Selo>
                            ) : (
                              <Selo tom="critico" simbolo="✕">
                                inválido
                              </Selo>
                            )}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}

                {validacao && validacao.erros.length > 0 && (
                  <>
                    <span className="block my-[18px] mb-2 text-tinta text-sm font-bold">
                      Problemas encontrados ({validacao.erros.length})
                    </span>
                    <ul className="list-none mb-[14px] mt-0 p-0">
                      {validacao.erros.map((e, i) => (
                        <li
                          key={i}
                          className="flex gap-2 px-3 py-[9px] mb-[6px] border border-critico-borda border-l-4 rounded-campo bg-critico-claro text-tinta-2 text-sm leading-[1.55]"
                        >
                          <span className="flex-none text-critico font-bold" aria-hidden>
                            ✕
                          </span>
                          {e}
                        </li>
                      ))}
                    </ul>
                  </>
                )}
              </>
            )}
          </div>
        </div>

        {/* Ambos usam o object URL, não a rota da API: uma aba nova ou um
            download disparam GET sem o Authorization e tomariam 401. */}
        <div className="flex items-center gap-[10px] flex-wrap px-5 py-[14px] border-t border-borda bg-papel-2">
          {erroPdf && (
            <span className="basis-full text-critico text-xs" role="alert">{erroPdf}</span>
          )}
          <LinkBotao
            variante="secundario"
            pequeno
            href={urlArquivo ?? undefined}
            target="_blank"
            rel="noreferrer"
            desabilitado={!urlArquivo}
          >
            Abrir em nova aba
          </LinkBotao>
          <LinkBotao
            variante="secundario"
            pequeno
            href={urlArquivo ?? undefined}
            download={arquivo}
            desabilitado={!urlArquivo}
          >
            Baixar o arquivo
          </LinkBotao>
          <button
            type="button"
            className="min-h-8 px-[11px] py-[6px] text-xs inline-flex items-center justify-center border border-borda-campo bg-papel text-acao rounded-campo font-ui font-semibold cursor-pointer hover:bg-acao-clara hover:border-acao disabled:opacity-50 disabled:cursor-default"
            onClick={() => void baixarPdf()}
            disabled={baixandoPdf}
          >
            {baixandoPdf ? "Gerando PDF…" : "Baixar em PDF"}
          </button>
        </div>
      </div>
    </div>
  );
}
