"use client";

import { useEffect, useRef, useState } from "react";

import { obterEntrega } from "@/lib/api";
import { ESTILO_VEREDITO } from "@/lib/formato";
import type { EntregaDetalhe } from "@/lib/types";
import { useArquivoEntrega } from "@/lib/useArquivo";
import { Aviso, Selo } from "./Basicos";
import estilos from "./VisorEntrega.module.css";

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
  const veredito = validacao ? ESTILO_VEREDITO[validacao.veredito] : null;

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
            <h2 className={estilos.titulo}>Documento enviado</h2>
            <div className={estilos.arquivo}>{arquivo}</div>
          </div>
          <button
            ref={fecharRef}
            type="button"
            className="botao botao--secundario botao--pequeno"
            onClick={onFechar}
          >
            Fechar ✕
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
              <Aviso tom="critico" titulo="Falha ao carregar os dados">
                {erro}
              </Aviso>
            ) : !detalhe ? (
              <p className={estilos.vazio}>Carregando os dados extraídos…</p>
            ) : !extracao ? (
              <Aviso tom="atencao" titulo="Sem leitura guardada">
                Esta entrega foi registrada sem extração guardada. Reenvie o arquivo para
                extrair os campos.
              </Aviso>
            ) : (
              <>
                {validacao && veredito && (
                  <div className={`aviso ${veredito.classe}`} role="status">
                    <span className="avisoSimbolo" aria-hidden>
                      {veredito.icone}
                    </span>
                    <div>
                      <strong>{veredito.rotulo}</strong>
                      <br />
                      {validacao.resumo}
                    </div>
                  </div>
                )}

                <div className={estilos.meta}>
                  <div className={estilos.metaItem}>
                    <span className={estilos.metaChave}>Tipo lido</span>
                    <span className={estilos.metaValor}>{extracao.tipo.descricao_detectado}</span>
                  </div>
                  <div className={estilos.metaItem}>
                    <span className={estilos.metaChave}>Nitidez</span>
                    <span className={estilos.metaValor}>
                      {extracao.qualidade_imagem.score_legibilidade}%
                    </span>
                  </div>
                  <div className={estilos.metaItem}>
                    <span className={estilos.metaChave}>Dados encontrados</span>
                    <span className={estilos.metaValor}>
                      {validacao?.completude_percentual ?? 0}%
                    </span>
                  </div>
                  <div className={estilos.metaItem}>
                    <span className={estilos.metaChave}>Tempo de leitura</span>
                    <span className={estilos.metaValor}>{extracao.tempo_processamento_s}s</span>
                  </div>
                </div>

                <span className={estilos.rotuloSecao}>Dados lidos ({campos.length})</span>

                {campos.length === 0 ? (
                  <p className={estilos.vazio}>
                    Nenhum campo estruturado foi extraído deste documento.
                  </p>
                ) : (
                  <table className={estilos.tabela}>
                    <thead>
                      <tr>
                        <th>Campo</th>
                        <th>Valor lido</th>
                        <th style={{ textAlign: "right" }}>Certeza</th>
                        <th>Conferência</th>
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
                    <span className={estilos.rotuloSecao}>
                      Problemas encontrados ({validacao.erros.length})
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
            className="botao botao--secundario botao--pequeno"
            href={urlArquivo ?? undefined}
            target="_blank"
            rel="noreferrer"
            aria-disabled={!urlArquivo}
          >
            Abrir em nova aba
          </a>
          <a
            className="botao botao--secundario botao--pequeno"
            href={urlArquivo ?? undefined}
            download={arquivo}
            aria-disabled={!urlArquivo}
          >
            Baixar o arquivo
          </a>
        </div>
      </div>
    </div>
  );
}
