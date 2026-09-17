"use client";

import { useCallback, useEffect, useState } from "react";

import * as api from "./api";
import type { Caso, CasoCriado, Categoria, OpcoesReclassificacao, SituacaoCaso } from "./types";

/** Quantos arquivos por request no envio em massa. Uma pasta grande é enviada em
 *  blocos deste tamanho, em sequência: mantém cada request rápido e garante que
 *  todo arquivo seja analisado, sem o teto do servidor recusar o lote inteiro. */
const TAMANHO_LOTE_ENVIO = 40;

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
    async (
      cliente: string,
      categoria: string,
      observacao = "",
      telefone = "",
      tipoAcao = "",
    ): Promise<CasoCriado> => {
      const caso = await api.criarCaso(cliente, categoria, observacao, telefone, tipoAcao);
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
export function useSituacao(casoId: string | null, atualizarAoVivo = false) {
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
        /* Arquivo idêntico a outro do caso volta 409 e NADA foi gravado. A equipe
         * pode insistir quando sabe que precisa das duas cópias; a confirmação fica
         * no histórico do documento. */
        const repetidos = api.duplicidadesDoErro(e);
        const mensagem = e instanceof Error ? e.message : "Falha ao enviar o documento.";
        if (
          repetidos &&
          window.confirm(
            `${mensagem}\n\nEnviar mesmo assim? A confirmação fica registrada no histórico do documento.`,
          )
        ) {
          try {
            await api.enviarDocumento(casoId, itemCodigo, arquivo, "pt", usarParaRgECpf, true);
            await recarregar();
          } catch (e2) {
            setErro(e2 instanceof Error ? e2.message : "Falha ao enviar o documento.");
          }
        } else {
          setErro(mensagem);
        }
      } finally {
        setEnviando(null);
      }
    },
    [casoId, recarregar],
  );

  const enviarLote = useCallback(
    async (arquivos: File[]) => {
      if (!casoId || arquivos.length === 0) return;
      setEnviando("__lote__");
      setErro(null);
      try {
        // Em blocos: uma pasta com centenas de arquivos entra INTEIRA, sem
        // estourar um único request e sem deixar nenhum arquivo de fora. Um
        // bloco que falha não impede os demais — todo arquivo é tentado.
        let recebidos = 0;
        const recusados: { arquivo: string; motivo: string }[] = [];
        for (let i = 0; i < arquivos.length; i += TAMANHO_LOTE_ENVIO) {
          const bloco = arquivos.slice(i, i + TAMANHO_LOTE_ENVIO);
          try {
            const r = await api.enviarDocumentosEmLote(casoId, bloco);
            recebidos += r.recebidos.length;
            recusados.push(...r.recusados);
          } catch (e) {
            const motivo = e instanceof Error ? e.message : "falha no envio";
            for (const f of bloco) recusados.push({ arquivo: f.name, motivo });
          }
          await recarregar();
        }
        if (recusados.length > 0) {
          const amostra = recusados
            .slice(0, 10)
            .map((item) => `${item.arquivo}: ${item.motivo}`)
            .join("; ");
          const resto = recusados.length > 10 ? ` … e mais ${recusados.length - 10}` : "";
          setErro(
            `${recebidos} arquivo(s) recebido(s), mas ${recusados.length} não entraram: ${amostra}${resto}`,
          );
        }
      } catch (e) {
        setErro(e instanceof Error ? e.message : "Falha ao enviar os documentos.");
      } finally {
        setEnviando(null);
      }
    },
    [casoId, recarregar],
  );

  /* Enquanto algum item estiver sendo lido, recarrega sozinho. Para de checar
   * assim que nada mais está em processamento — sem timer eterno rodando. */
  const processando =
    situacao?.itens.some((i) => i.status === "processando") ||
    situacao?.triagem?.some(
      (e) => e.status_proc === "na_fila" || e.status_proc === "processando",
    ) ||
    false;

  useEffect(() => {
    if (!processando && !atualizarAoVivo) return;
    const intervalo = atualizarAoVivo ? 2_000 : 3_000;
    const atualizarVisivel = () => {
      if (document.visibilityState === "visible") void recarregar();
    };
    const id = window.setInterval(atualizarVisivel, intervalo);
    window.addEventListener("focus", atualizarVisivel);
    document.addEventListener("visibilitychange", atualizarVisivel);
    return () => {
      window.clearInterval(id);
      window.removeEventListener("focus", atualizarVisivel);
      document.removeEventListener("visibilitychange", atualizarVisivel);
    };
  }, [atualizarAoVivo, processando, recarregar]);

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

  const reatribuir = useCallback(
    async (entregaId: string, itens: string[], opcoes?: OpcoesReclassificacao) => {
      setErro(null);
      try {
        await api.reatribuirEntrega(entregaId, itens, opcoes);
        await recarregar();
      } catch (e) {
        // A suspeita de duplicidade volta para quem pediu: é ali, ao lado do
        // documento, que a pessoa confirma ou desiste.
        if (api.duplicidadesDoErro(e)) throw e;
        setErro(e instanceof Error ? e.message : "Não foi possível atribuir o documento.");
      }
    },
    [recarregar],
  );

  const trocarCategoria = useCallback(
    async (categoria: string) => {
      if (!casoId) return;
      await api.atualizarCategoriaCaso(casoId, categoria);
      await recarregar();
    },
    [casoId, recarregar],
  );

  return {
    situacao,
    carregando,
    erro,
    enviando,
    recarregar,
    trocarCategoria,
    enviar,
    enviarLote,
    removerEntrega,
    vincularIdentidade,
    reatribuir,
  };
}
