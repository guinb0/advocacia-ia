"use client";

import { useEffect, useMemo, useState } from "react";

import { obterEntrega } from "@/lib/api";
import type { EntregaDetalhe, ItemSituacao } from "@/lib/types";
import { Cartao, Selo, Vazio } from "@/components/ui/Basicos";

export default function ResumoDocumentos({ itens }: { itens: ItemSituacao[] }) {
  const entregas = useMemo(() => {
    const unicas = new Map<string, { id: string; arquivo: string; status_proc?: string }>();
    for (const item of itens) {
      for (const entrega of item.entregas) unicas.set(entrega.id, entrega);
    }
    return [...unicas.values()];
  }, [itens]);
  const chave = entregas.map((e) => `${e.id}:${e.status_proc}`).join("|");
  const [detalhes, setDetalhes] = useState<EntregaDetalhe[]>([]);
  const [carregando, setCarregando] = useState(false);

  useEffect(() => {
    const prontas = entregas.filter((e) => e.status_proc === "pronto");
    if (!prontas.length) {
      setDetalhes([]);
      return;
    }
    let cancelado = false;
    setCarregando(true);
    Promise.allSettled(prontas.map((e) => obterEntrega(e.id))).then((resultados) => {
      if (cancelado) return;
      setDetalhes(resultados.flatMap((r) => r.status === "fulfilled" ? [r.value] : []));
      setCarregando(false);
    });
    return () => { cancelado = true; };
    // A chave muda quando o OCR termina ou uma entrega é adicionada/removida.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [chave]);

  if (!entregas.length) return null;

  return (
    <Cartao
      titulo="Resumo dos documentos enviados"
      subtitulo="Dados importantes de cada arquivo e como eles ajudam na instrução do caso. Confira sempre no documento original."
    >
      {carregando && detalhes.length === 0 ? (
        <Vazio>Montando o resumo dos documentos…</Vazio>
      ) : detalhes.length === 0 ? (
        <Vazio>Os documentos ainda estão sendo interpretados.</Vazio>
      ) : (
        <div className="flex flex-col gap-3">
          {detalhes.map((entrega) => {
            const extracao = entrega.extracao;
            const semantica = extracao?.classificacao_semantica;
            const achados = semantica?.achados?.length
              ? semantica.achados
              : (extracao?.campos ?? []).map((campo) => ({
                  campo: campo.rotulo,
                  valor: campo.valor,
                  importancia: campo.observacao || undefined,
                  relevante_para: undefined,
                }));
            const finalidades = semantica?.serve_para ?? [];
            const tipo = semantica?.tipo_semantico || extracao?.tipo?.descricao_detectado
              || entrega.tipo_detectado || "Documento não identificado";
            return (
              <article key={entrega.id} className="border border-borda rounded-campo bg-papel-2 p-4">
                <div className="flex items-start justify-between gap-3 flex-wrap">
                  <div>
                    <h4 className="m-0 text-sm font-semibold text-tinta [overflow-wrap:anywhere]">{entrega.arquivo}</h4>
                    <p className="mt-1 mb-0 text-xs text-tinta-3">Identificado como: <strong className="text-tinta">{tipo}</strong></p>
                  </div>
                  <Selo tom={semantica ? "info" : "neutro"}>{semantica ? "Interpretado" : "OCR"}</Selo>
                </div>

                {achados.length > 0 ? (
                  <div className="flex flex-col gap-3 mt-4">
                    {achados.map((achado, indice) => (
                      <div key={`${achado.campo}-${indice}`} className="grid grid-cols-[minmax(120px,0.7fr)_minmax(180px,1fr)] gap-4 max-[640px]:grid-cols-1 max-[640px]:gap-1">
                        <strong className="text-xs text-tinta">{achado.campo}</strong>
                        <div className="text-xs leading-[1.55] text-tinta-2">
                          <strong className="font-codigo text-tinta">{achado.valor}</strong>
                          {achado.importancia && <span className="block mt-1">Por que importa: {achado.importancia}</span>}
                          {achado.relevante_para && <span className="block text-acao">Importante para: {achado.relevante_para}</span>}
                        </div>
                      </div>
                    ))}
                  </div>
                ) : (
                  <p className="mt-3 mb-0 text-xs text-tinta-3">Nenhum dado jurídico específico foi destacado neste arquivo.</p>
                )}

                {finalidades.length > 0 && (
                  <div className="mt-4 pt-3 border-t border-borda">
                    <strong className="text-xs text-tinta">Este documento ajuda em:</strong>
                    <ul className="mt-2 mb-0 pl-5 text-xs leading-[1.55] text-tinta-2">
                      {finalidades.map((finalidade, indice) => (
                        <li key={`${finalidade.item}-${indice}`}><strong>{finalidade.item}</strong> — {finalidade.porque}</li>
                      ))}
                    </ul>
                  </div>
                )}
              </article>
            );
          })}
        </div>
      )}
    </Cartao>
  );
}
