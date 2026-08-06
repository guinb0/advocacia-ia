"use client";

import { useEffect, useRef, useState } from "react";

import { obterEntrega } from "@/lib/api";
import type { EntregaDetalhe } from "@/lib/types";
import { useArquivoEntrega } from "@/lib/useArquivo";
import estilos from "./VisorEntrega.module.css";

const CLASSE_VEREDITO = {
  APROVADO: estilos.ok,
  APROVADO_COM_RESSALVAS: estilos.warn,
  REPROVADO: estilos.err,
} as const;

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

  return (
    <div
      className={estilos.fundo}
      onClick={(e) => {
        if (e.target === e.currentTarget) onFechar();
      }}
      role="dialog"
      aria-modal="true"
      aria-label={`Documento ${arquivo}`}
    >
      <div className={estilos.painel}>
        <div className={estilos.cabecalho}>
          <div>
            <span className={estilos.titulo}>DOCUMENTO ENVIADO</span>
            <div className={estilos.arquivo}>{arquivo}</div>
          </div>
          <button ref={fecharRef} type="button" className={estilos.fechar} onClick={onFechar}>
            FECHAR ✕
          </button>
        </div>

        <div className={estilos.corpo}>
          <div className={estilos.midia}>
            {erroArquivo ? (
              <p className={estilos.semPreview}>{erroArquivo}</p>
            ) : !urlArquivo ? (
              <p className={estilos.semPreview}>Carregando o arquivo…</p>
            ) : ehPdf(arquivo) ? (
              <iframe
                className={estilos.pdf}
                src={urlArquivo}
                title={`Pré-visualização de ${arquivo}`}
              />
            ) : (
              /* eslint-disable-next-line @next/next/no-img-element -- é um
                 object URL de blob, que o otimizador do Next não processa. */
              <img className={estilos.imagem} src={urlArquivo} alt={`Documento ${arquivo}`} />
            )}
          </div>

          <div className={estilos.dados}>
            {erro ? (
              <div className={`${estilos.resumo} ${estilos.err}`}>{erro}</div>
            ) : !detalhe ? (
              <p className={estilos.vazio}>Carregando os dados extraídos…</p>
            ) : !extracao ? (
              <p className={estilos.vazio}>
                Esta entrega foi registrada sem extração guardada. Reenvie o arquivo para
                extrair os campos.
              </p>
            ) : (
              <>
                {validacao && (
                  <div
                    className={`${estilos.resumo} ${CLASSE_VEREDITO[validacao.veredito] ?? ""}`}
                  >
                    {validacao.resumo}
                  </div>
                )}

                <div className={estilos.meta}>
                  <span>
                    tipo lido <strong>{extracao.tipo.descricao_detectado}</strong>
                  </span>
                  <span>
                    legibilidade <strong>{extracao.qualidade_imagem.score_legibilidade}%</strong>
                  </span>
                  <span>
                    completude <strong>{validacao?.completude_percentual ?? 0}%</strong>
                  </span>
                  <span>
                    leitura <strong>{extracao.tempo_processamento_s}s</strong>
                  </span>
                </div>

                <span className={estilos.rotuloSecao}>CAMPOS EXTRAÍDOS ({campos.length})</span>

                {campos.length === 0 ? (
                  <p className={estilos.vazio}>
                    Nenhum campo estruturado foi extraído deste documento.
                  </p>
                ) : (
                  <table className={estilos.tabela}>
                    <thead>
                      <tr>
                        <th>Campo</th>
                        <th>Valor</th>
                        <th style={{ textAlign: "right" }}>Conf.</th>
                        <th />
                      </tr>
                    </thead>
                    <tbody>
                      {campos.map((campo) => (
                        <tr key={campo.nome}>
                          <td className={estilos.campoRotulo}>{campo.rotulo}</td>
                          <td>
                            <span className={estilos.campoValor}>{campo.valor || "—"}</span>
                            {campo.observacao && (
                              <div className={estilos.observacao}>{campo.observacao}</div>
                            )}
                          </td>
                          <td className={estilos.confianca}>
                            {Math.round(campo.confianca * 100)}%
                          </td>
                          <td>
                            {campo.valido === null ? null : campo.valido ? (
                              <span className={`${estilos.selo} ${estilos.ok}`}>VÁLIDO</span>
                            ) : (
                              <span className={`${estilos.selo} ${estilos.err}`}>INVÁLIDO</span>
                            )}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}

                {validacao && validacao.erros.length > 0 && (
                  <>
                    <span className={estilos.rotuloSecao} style={{ marginTop: 18 }}>
                      PROBLEMAS ({validacao.erros.length})
                    </span>
                    <ul className={estilos.listaMsg}>
                      {validacao.erros.map((e, i) => (
                        <li key={i}>{e}</li>
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
        <div className={estilos.rodape}>
          <a
            className={estilos.acao}
            href={urlArquivo ?? undefined}
            target="_blank"
            rel="noreferrer"
            aria-disabled={!urlArquivo}
          >
            Abrir em nova aba
          </a>
          <a className={estilos.acao} href={urlArquivo ?? undefined} download={arquivo}>
            Baixar arquivo
          </a>
        </div>
      </div>
    </div>
  );
}
