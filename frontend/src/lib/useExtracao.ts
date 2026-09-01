"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { ApiError, extrair, listarTipos, verificarSaude } from "./api";
import type { Documento, TipoDocumento } from "./types";

export const TAMANHO_MAXIMO = 20 * 1024 * 1024;

function ehPdf(arquivo: File): boolean {
  return arquivo.type === "application/pdf" || arquivo.name.toLowerCase().endsWith(".pdf");
}

export type EstadoModelo = "verificando" | "carregando" | "pronto" | "indisponivel";

let verificacaoModelo: Promise<EstadoModelo> | null = null;

function verificarModeloUmaVez(): Promise<EstadoModelo> {
  if (!verificacaoModelo) {
    verificacaoModelo = verificarSaude()
      .then((pronto) => (pronto ? "pronto" : "indisponivel"))
      .catch(() => "indisponivel");
  }
  return verificacaoModelo;
}

/** Estado do painel de status do modelo, no topo da página. */
export function useModelo() {
  const [estado, setEstado] = useState<EstadoModelo>("verificando");

  useEffect(() => {
    let cancelado = false;

    setEstado("carregando");
    verificarModeloUmaVez().then((resultado) => {
      if (!cancelado) setEstado(resultado);
    });

    return () => {
      cancelado = true;
    };
  }, []);

  return estado;
}

export function useTipos() {
  const [tipos, setTipos] = useState<TipoDocumento[]>([]);

  useEffect(() => {
    let cancelado = false;
    listarTipos()
      .then((lista) => {
        if (!cancelado) setTipos(lista.filter((t) => t.codigo !== "desconhecido"));
      })
      .catch(() => {
        /* o seletor fica só com "Detectar automaticamente" */
      });
    return () => {
      cancelado = true;
    };
  }, []);

  return tipos;
}

export function useExtracao() {
  const [arquivo, setArquivo] = useState<File | null>(null);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [resultado, setResultado] = useState<Documento | null>(null);
  const [processando, setProcessando] = useState(false);
  const [erro, setErro] = useState<string | null>(null);

  // Revoga a URL anterior: sem isso cada troca de arquivo vaza um blob.
  const urlAnterior = useRef<string | null>(null);
  useEffect(() => {
    return () => {
      if (urlAnterior.current) URL.revokeObjectURL(urlAnterior.current);
    };
  }, []);

  const escolher = useCallback((novo: File | null) => {
    setErro(null);
    setResultado(null);

    if (!novo) return;
    if (!novo.type.startsWith("image/") && !ehPdf(novo)) {
      setErro("O arquivo precisa ser uma imagem ou PDF.");
      return;
    }
    if (novo.size > TAMANHO_MAXIMO) {
      setErro("O arquivo passa de 20MB.");
      return;
    }

    if (urlAnterior.current) URL.revokeObjectURL(urlAnterior.current);
    const url = ehPdf(novo) ? null : URL.createObjectURL(novo);
    urlAnterior.current = url;

    setArquivo(novo);
    setPreviewUrl(url);
  }, []);

  const limpar = useCallback(() => {
    if (urlAnterior.current) URL.revokeObjectURL(urlAnterior.current);
    urlAnterior.current = null;
    setArquivo(null);
    setPreviewUrl(null);
    setResultado(null);
    setErro(null);
  }, []);

  const processar = useCallback(
    async (idioma: string, tipo: string) => {
      if (!arquivo) return;
      setProcessando(true);
      setErro(null);
      setResultado(null);
      try {
        setResultado(await extrair(arquivo, idioma, tipo));
      } catch (e) {
        setErro(e instanceof ApiError || e instanceof Error ? e.message : "Falha desconhecida.");
      } finally {
        setProcessando(false);
      }
    },
    [arquivo],
  );

  return { arquivo, previewUrl, resultado, processando, erro, escolher, limpar, processar };
}
