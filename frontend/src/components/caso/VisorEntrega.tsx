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

const ROTULOS_TIPO_DOCUMENTO: Record<string, string> = {
  "DOCUMENT.ID": "Documento de identidade",
  "DOCUMENT.CPF": "CPF",
  "DOCUMENT.PROOF_OF_ADDRESS": "Comprovante de endereço",
  "DOCUMENT.CTPS": "CTPS",
  "DOCUMENT.PAYSLIP": "Contracheque",
  "DOCUMENT.CNIS": "CNIS",
  "DOCUMENT.CAT": "CAT",
  "DOCUMENT.PERSONNEL_RECORD": "Ficha funcional",
  "DOCUMENT.POLICE_REPORT": "Boletim de ocorrência",
  "DOCUMENT.EMERGENCY_CARE_RECORD": "Atendimento de urgência",
  "DOCUMENT.MEDICAL_CERTIFICATE": "Atestado médico",
  "DOCUMENT.MEDICAL_REPORT": "Laudo médico",
  "DOCUMENT.MEDICAL_FOLLOW_UP": "Acompanhamento médico",
  "DOCUMENT.MEDICAL_CHART": "Prontuário médico",
  "DOCUMENT.TREATMENT_RECORD": "Registro de tratamento",
  "DOCUMENT.IMAGING_EXAM": "Exame de imagem",
  "DOCUMENT.IMAGING_REPORT": "Laudo de imagem",
  "DOCUMENT.PRESCRIPTION": "Receita médica",
  "DOCUMENT.INSS_DECISION": "Decisão do INSS",
  "DOCUMENT.INSS_GRANT_LETTER": "Carta de concessão do INSS",
  "DOCUMENT.INSS_BENEFIT_EXTENSION": "Prorrogação de benefício do INSS",
  "DOCUMENT.INSS_EXPERT_REPORT": "Laudo pericial do INSS",
  "DOCUMENT.INSS_ADMINISTRATIVE_FILE": "Processo administrativo do INSS",
  "DOCUMENT.PPP": "PPP",
  "DOCUMENT.ASO": "ASO",
  "DOCUMENT.PRIVATE_EXPERT_REPORT": "Parecer técnico particular",
  "DOCUMENT.ACCIDENT_SCENE_MEDIA": "Mídia do local do acidente",
  "DOCUMENT.OCCUPATIONAL_PROGRAM": "Programa ocupacional",
  "DOCUMENT.UNKNOWN": "Desconhecido",
  DESCONHECIDO: "Desconhecido",
};

function formatarTipoDocumento(tipo: string): string {
  const chave = tipo.trim().toUpperCase();
  const rotuloConhecido = ROTULOS_TIPO_DOCUMENTO[chave];
  if (rotuloConhecido) return rotuloConhecido;

  const limpo = tipo
    .replace(/^DOCUMENT\./i, "")
    .replace(/[_-]+/g, " ")
    .trim();
  if (!limpo || limpo === "—") return "—";
  if (limpo.toLowerCase() === "desconhecido") return "Desconhecido";
  return limpo
    .toLowerCase()
    .replace(/\b\p{L}/gu, (letra) => letra.toLocaleUpperCase("pt-BR"));
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
    let temporizador: ReturnType<typeof setTimeout> | undefined;
    async function carregar() {
      try {
        const d = await obterEntrega(entregaId);
        if (cancelado) return;
        setDetalhe(d);
        setErro(null);
        if (d.status_proc === "na_fila" || d.status_proc === "processando") {
          temporizador = setTimeout(carregar, 1500);
        }
      } catch (e) {
        if (!cancelado) setErro(e instanceof Error ? e.message : "Falha ao carregar a entrega.");
      }
    }
    void carregar();
    return () => {
      cancelado = true;
      if (temporizador) clearTimeout(temporizador);
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
  const errosValidacao = validacao?.erros ?? [];
  const tipoLido =
    extracao?.tipo?.descricao_detectado ??
    extracao?.tipo?.descricao ??
    detalhe?.tipo_detectado ??
    "—";
  const tipoLidoFormatado = formatarTipoDocumento(tipoLido);
  const scoreLegibilidade =
    extracao?.qualidade_imagem?.score_legibilidade ??
    validacao?.score_legibilidade ??
    detalhe?.score_legibilidade ??
    null;
  const tempoProcessamento = extracao?.tempo_processamento_s;
  const statusLeitura = detalhe?.status_proc ?? "pronto";
  const vereditoSalvo = validacao?.veredito ?? detalhe?.veredito;
  const dadosUtilizaveis =
    validacao?.dados_utilizaveis ?? detalhe?.dados_utilizaveis ?? false;
  const criadoEm = detalhe?.criado_em
    ? new Date(detalhe.criado_em).toLocaleString("pt-BR")
    : "—";
  const textoCompleto =
    extracao?.texto_completo ||
    (extracao?.texto_linhas ?? []).map((linha) => linha.texto).join("\n");

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
            ) : !extracao && detalhe.status_proc === "erro" ? (
              <Aviso tom="critico" titulo="Não foi possível ler agora">
                O arquivo original está preservado. {detalhe.erro_proc || "O serviço de OCR não respondeu."}
              </Aviso>
            ) : !extracao && (detalhe.status_proc === "na_fila" || detalhe.status_proc === "processando") ? (
              <Aviso tom="info" titulo="Leitura em andamento">
                Extraindo todo o conteúdo do documento. Esta tela será atualizada automaticamente.
              </Aviso>
            ) : !extracao ? (
              <Aviso tom="atencao" titulo="Documento antigo sem leitura">
                O arquivo original está preservado, mas este registro antigo ainda não possui texto extraído.
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
                    <span
                      className="block mt-[1px] max-w-full text-tinta text-[0.92rem] font-semibold leading-tight [overflow-wrap:anywhere]"
                      title={tipoLido}
                    >
                      {tipoLidoFormatado}
                    </span>
                  </div>
                  <div className="px-[11px] py-[9px] border border-borda rounded-campo bg-papel-2">
                    <span className="block text-tinta-3 text-xs">Nitidez</span>
                    <span className="block mt-[1px] text-tinta text-base font-semibold tabular-nums">
                      {scoreLegibilidade === null ? "—" : `${scoreLegibilidade}%`}
                    </span>
                  </div>
                  <div className="px-[11px] py-[9px] border border-borda rounded-campo bg-papel-2">
                    <span className="block text-tinta-3 text-xs">Dados encontrados</span>
                    <span className="block mt-[1px] text-tinta text-base font-semibold tabular-nums">
                      {validacao?.completude_percentual === undefined ? "—" : `${validacao.completude_percentual}%`}
                    </span>
                  </div>
                  <div className="px-[11px] py-[9px] border border-borda rounded-campo bg-papel-2">
                    <span className="block text-tinta-3 text-xs">Tempo de leitura</span>
                    <span className="block mt-[1px] text-tinta text-base font-semibold tabular-nums">
                      {tempoProcessamento === undefined ? "—" : `${tempoProcessamento}s`}
                    </span>
                  </div>
                </div>

                <span className="block my-[18px] mb-2 text-tinta text-sm font-bold">
                  Dados lidos ({campos.length})
                </span>

                {campos.length === 0 ? (
                  <div className="py-2">
                    {textoCompleto ? (
                      <>
                        <Aviso tom="info" titulo="Conteúdo jurídico preservado">
                          Este documento não possui campos cadastrais conhecidos. O texto integral abaixo foi
                          guardado e será usado pela IA jurídica com referência a este anexo.
                        </Aviso>
                        <pre className="mt-3 mb-4 p-3 max-h-[340px] overflow-auto whitespace-pre-wrap rounded-campo border border-borda bg-papel-2 text-tinta text-xs leading-relaxed font-codigo select-text">
                          {textoCompleto}
                        </pre>
                      </>
                    ) : (
                      <p className="mb-3 text-tinta-3 text-sm leading-[1.6]">
                        Este registro não tem campos estruturados de OCR salvos, mas os dados
                        de conferência do banco estão abaixo.
                      </p>
                    )}
                    <dl className="grid grid-cols-[max-content_1fr] gap-x-3 gap-y-2 text-sm">
                      <dt className="text-tinta-3">Arquivo</dt>
                      <dd className="m-0 text-tinta font-codigo [overflow-wrap:anywhere]">{detalhe.arquivo}</dd>
                      <dt className="text-tinta-3">Item</dt>
                      <dd className="m-0 text-tinta font-codigo">{detalhe.item_codigo}</dd>
                      <dt className="text-tinta-3">Leitura</dt>
                      <dd className="m-0 text-tinta">{statusLeitura}</dd>
                      <dt className="text-tinta-3">Conferência</dt>
                      <dd className="m-0 text-tinta">{vereditoSalvo ?? "—"}</dd>
                      <dt className="text-tinta-3">Dados utilizáveis</dt>
                      <dd className="m-0 text-tinta">{dadosUtilizaveis ? "sim" : "não"}</dd>
                      <dt className="text-tinta-3">Recebido em</dt>
                      <dd className="m-0 text-tinta">{criadoEm}</dd>
                    </dl>
                  </div>
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
                            {typeof campo.confianca === "number" ? `${Math.round(campo.confianca * 100)}%` : "—"}
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

                {errosValidacao.length > 0 && (
                  <>
                    <span className="block my-[18px] mb-2 text-tinta text-sm font-bold">
                      Problemas encontrados ({errosValidacao.length})
                    </span>
                    <ul className="list-none mb-[14px] mt-0 p-0">
                      {errosValidacao.map((e, i) => (
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
