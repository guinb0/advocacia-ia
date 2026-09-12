"use client";

import { useEffect, useState } from "react";

import { listarTiposDocumento } from "./api";
import type { TipoDocumentoGlossario } from "./types";

/* Uma busca só para a tela inteira. O checklist monta um "Corrigir classificação"
 * por documento, e cada um pedindo o glossário de novo seria uma ida ao servidor
 * por arquivo do caso para buscar a mesma lista. */
let emCurso: Promise<TipoDocumentoGlossario[]> | null = null;

/** Descarta a lista guardada — chamado depois de criar ou editar um tipo. */
export function invalidarTiposDocumento(): void {
  emCurso = null;
}

/** Os tipos ATIVOS do glossário, para as opções de classificação. */
export function useTiposDocumento() {
  const [tipos, setTipos] = useState<TipoDocumentoGlossario[]>([]);
  const [erro, setErro] = useState<string | null>(null);

  useEffect(() => {
    let cancelado = false;
    if (!emCurso) {
      emCurso = listarTiposDocumento(false).catch((e: unknown) => {
        // Falha não fica guardada: a próxima tela tenta de novo.
        emCurso = null;
        throw e;
      });
    }
    emCurso
      .then((lista) => {
        if (!cancelado) setTipos(lista);
      })
      .catch((e: unknown) => {
        if (!cancelado) {
          setErro(e instanceof Error ? e.message : "Não foi possível carregar o glossário.");
        }
      });
    return () => {
      cancelado = true;
    };
  }, []);

  return { tipos, erro };
}
