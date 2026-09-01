"use client";

import { useEffect, useState } from "react";

import { baixarArquivoEntrega } from "./api";

/** Object URL do arquivo da entrega, buscado com o token.
 *
 * `<img src>` e `<iframe src>` disparam um GET cru, sem o header Authorization —
 * apontá-los direto para a API daria 401 assim que a autenticação entrasse. Por
 * isso o arquivo vem por `fetch` autenticado e vira um blob local.
 */
export function useArquivoEntrega(entregaId: string | null) {
  const [url, setUrl] = useState<string | null>(null);
  const [erro, setErro] = useState<string | null>(null);

  useEffect(() => {
    if (!entregaId) return;
    let cancelado = false;
    let criada: string | null = null;

    baixarArquivoEntrega(entregaId)
      .then((blob) => {
        if (cancelado) return;
        criada = URL.createObjectURL(blob);
        setUrl(criada);
      })
      .catch((e: unknown) => {
        if (!cancelado) setErro(e instanceof Error ? e.message : "Falha ao carregar o arquivo.");
      });

    return () => {
      cancelado = true;
      // Sem revogar, cada abertura do visor vaza um blob até recarregar a página.
      if (criada) URL.revokeObjectURL(criada);
    };
  }, [entregaId]);

  return { url, erro };
}
