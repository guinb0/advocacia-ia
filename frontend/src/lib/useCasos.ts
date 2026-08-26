"use client";

import { useCallback, useEffect, useState } from "react";

import * as api from "./api";
import type { Caso, CasoCriado, Categoria, SituacaoCaso } from "./types";

export function useCategorias() {
  const [categorias, setCategorias] = useState<Categoria[]>([]);

  useEffect(() => {
    let cancelado = false;
    api
      .listarCategorias()
      .then((lista) => {
        if (!cancelado) setCategorias(lista);
      })
      .catch(() => {
        /* a tela mostra a lista vazia */
      });
    return () => {
      cancelado = true;
    };
  }, []);

  return categorias;
}

export function useCasos() {
  const [casos, setCasos] = useState<Caso[]>([]);
  const [carregando, setCarregando] = useState(true);
  const [erro, setErro] = useState<string | null>(null);

  const recarregar = useCallback(async () => {
    setCarregando(true);
    try {
      setCasos(await api.listarCasos());
      setErro(null);
    } catch (e) {
      setErro(e instanceof Error ? e.message : "Falha ao carregar os casos.");
    } finally {
      setCarregando(false);
    }
  }, []);

  useEffect(() => {
    void recarregar();
  }, [recarregar]);

  const criar = useCallback(
    async (cliente: string, categoria: string, observacao = ""): Promise<CasoCriado> => {
      const caso = await api.criarCaso(cliente, categoria, observacao);
      await recarregar();
      return caso;
    },
    [recarregar],
  );

  const excluir = useCallback(
    async (casoId: string) => {
      await api.excluirCaso(casoId);
      await recarregar();
    },
    [recarregar],
  );

  return { casos, carregando, erro, recarregar, criar, excluir };
}

/** Situação de um caso: checklist com status, progresso e envio de documentos. */
export function useSituacao(casoId: string | null) {
  const [situacao, setSituacao] = useState<SituacaoCaso | null>(null);
  const [carregando, setCarregando] = useState(false);
  const [erro, setErro] = useState<string | null>(null);
  /** Código do item que está sendo processado no momento (o OCR leva segundos). */
  const [enviando, setEnviando] = useState<string | null>(null);

  const recarregar = useCallback(async () => {
    if (!casoId) {
      setSituacao(null);
      return;
    }
    setCarregando(true);
    try {
      setSituacao(await api.obterCaso(casoId));
      setErro(null);
    } catch (e) {
      setErro(e instanceof Error ? e.message : "Falha ao carregar o caso.");
    } finally {
      setCarregando(false);
    }
  }, [casoId]);

  useEffect(() => {
    void recarregar();
  }, [recarregar]);

  const enviar = useCallback(
    async (itemCodigo: string, arquivo: File, usarParaRgECpf = false) => {
      if (!casoId) return;
      setEnviando(itemCodigo);
      setErro(null);
      try {
        // Volta assim que o arquivo é aceito; a leitura segue no servidor e o
        // efeito de polling abaixo atualiza a tela quando terminar.
        await api.enviarDocumento(casoId, itemCodigo, arquivo, "pt", usarParaRgECpf);
        await recarregar();
      } catch (e) {
        setErro(e instanceof Error ? e.message : "Falha ao enviar o documento.");
      } finally {
        setEnviando(null);
      }
    },
    [casoId, recarregar],
  );

  /* Enquanto algum item estiver sendo lido, recarrega sozinho. Para de checar
   * assim que nada mais está em processamento — sem timer eterno rodando. */
  const processando = situacao?.itens.some((i) => i.status === "processando") ?? false;

  useEffect(() => {
    if (!processando) return;
    const id = setInterval(() => void recarregar(), 3000);
    return () => clearInterval(id);
  }, [processando, recarregar]);

  const removerEntrega = useCallback(
    async (entregaId: string) => {
      try {
        await api.excluirEntrega(entregaId);
        await recarregar();
      } catch (e) {
        setErro(e instanceof Error ? e.message : "Falha ao remover a entrega.");
      }
    },
    [recarregar],
  );

  const vincularIdentidade = useCallback(
    async (entregaId: string, itemCodigo: string) => {
      if (!casoId) return;
      setEnviando(itemCodigo);
      setErro(null);
      try {
        await api.vincularIdentidadeUnificada(casoId, entregaId);
        await recarregar();
      } catch (e) {
        setErro(e instanceof Error ? e.message : "Não foi possível vincular RG e CPF.");
      } finally {
        setEnviando(null);
      }
    },
    [casoId, recarregar],
  );

  return {
    situacao,
    carregando,
    erro,
    enviando,
    recarregar,
    enviar,
    removerEntrega,
    vincularIdentidade,
  };
}
