"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import type { Peticao } from "@/lib/agente";

type SecaoEditada = { code: string; content: string };

export type SituacaoDoSalvamento = "salvo" | "pendente" | "salvando" | "erro";

/** Pausa na digitação que dispara a gravação. */
const ATRASO_PADRAO_MS = 1500;
/** Depois de uma falha, quanto esperar para tentar de novo sozinho. */
const NOVA_TENTATIVA_MS = 5000;

/**
 * O texto de uma peça em edição, gravado sozinho a cada pausa na digitação.
 *
 * Antes a edição só ia ao banco no botão "Salvar e baixar": quem fechava a aba,
 * voltava ao dossiê ou deixava o chat recarregar a peça perdia o que tinha
 * escrito. Agora cada pausa grava — e só as seções que mudaram, para que uma
 * gravação atrasada não devolva ao banco o texto antigo de outra seção.
 *
 * O backend agrupa as gravações seguidas do mesmo usuário numa só versão
 * (`app/peticao_local.JANELA_EDICAO_MANUAL`); sem isso cada pausa seria uma
 * versão nova no histórico.
 *
 * Quando a peça muda no servidor (revisão aceita, chat, geração), o texto
 * vem de lá — exceto nas seções com digitação ainda não gravada, que não se
 * perdem e seguem para a próxima gravação.
 */
export function useEdicaoAutoSalva({
  chave,
  secoes,
  salvar,
  onSalvo,
  atrasoMs = ATRASO_PADRAO_MS,
}: {
  /** Id da peça em edição; `null` quando nenhuma está aberta. */
  chave: string | null;
  secoes: SecaoEditada[] | undefined;
  salvar: (chave: string, secoes: SecaoEditada[]) => Promise<Peticao>;
  onSalvo?: (peticao: Peticao, chave: string) => void;
  atrasoMs?: number;
}) {
  const [edicao, setEdicao] = useState<Record<string, string>>({});
  const [situacao, setSituacao] = useState<SituacaoDoSalvamento>("salvo");
  const [erro, setErro] = useState<string | null>(null);
  const [salvoEm, setSalvoEm] = useState<Date | null>(null);

  /** O que o servidor tem, seção a seção — a referência do que falta gravar. */
  const salvo = useRef<Record<string, string>>({});
  const edicaoRef = useRef(edicao);
  edicaoRef.current = edicao;
  const chaveRef = useRef(chave);
  const salvarRef = useRef(salvar);
  salvarRef.current = salvar;
  const onSalvoRef = useRef(onSalvo);
  onSalvoRef.current = onSalvo;
  const emVoo = useRef<Promise<void> | null>(null);
  const relogio = useRef<ReturnType<typeof setTimeout> | null>(null);

  const pendentes = useCallback(
    (atual: Record<string, string>): SecaoEditada[] =>
      Object.entries(atual)
        .filter(([code, content]) => code in salvo.current && content !== salvo.current[code])
        .map(([code, content]) => ({ code, content })),
    [],
  );

  const cancelarRelogio = useCallback(() => {
    if (relogio.current) clearTimeout(relogio.current);
    relogio.current = null;
  }, []);

  const gravar = useCallback(async (): Promise<void> => {
    cancelarRelogio();
    while (emVoo.current) await emVoo.current.catch(() => undefined);
    const chaveAtual = chaveRef.current;
    const envio = pendentes(edicaoRef.current);
    if (!chaveAtual || envio.length === 0) {
      setSituacao("salvo");
      return;
    }
    setSituacao("salvando");
    const tarefa = (async () => {
      try {
        const atualizada = await salvarRef.current(chaveAtual, envio);
        if (chaveRef.current !== chaveAtual) return;
        salvo.current = {
          ...salvo.current,
          ...Object.fromEntries(envio.map((s) => [s.code, s.content])),
        };
        setErro(null);
        setSalvoEm(new Date());
        setSituacao(pendentes(edicaoRef.current).length ? "pendente" : "salvo");
        onSalvoRef.current?.(atualizada, chaveAtual);
      } catch (e) {
        if (chaveRef.current !== chaveAtual) return;
        setErro(e instanceof Error ? e.message : "Não foi possível salvar.");
        setSituacao("erro");
        cancelarRelogio();
        relogio.current = setTimeout(() => void gravar().catch(() => undefined), NOVA_TENTATIVA_MS);
        throw e;
      }
    })();
    emVoo.current = tarefa;
    try {
      await tarefa;
    } finally {
      if (emVoo.current === tarefa) emVoo.current = null;
    }
  }, [cancelarRelogio, pendentes]);

  // A peça veio (ou voltou) do servidor.
  useEffect(() => {
    const doServidor = Object.fromEntries((secoes ?? []).map((s) => [s.code, s.content]));
    const mesmaPeca = chaveRef.current === chave;
    chaveRef.current = chave;
    const base = salvo.current;
    salvo.current = doServidor;
    setEdicao((atual) => {
      if (!mesmaPeca) return doServidor;
      const combinada = { ...doServidor };
      for (const code of Object.keys(doServidor)) {
        const local = atual[code];
        if (local !== undefined && local !== base[code]) combinada[code] = local;
      }
      return combinada;
    });
  }, [chave, secoes]);

  // Cada mudança no texto: grava depois da pausa.
  useEffect(() => {
    if (pendentes(edicao).length === 0) {
      cancelarRelogio();
      if (!emVoo.current) {
        setSituacao("salvo");
        setErro(null);
      }
      return;
    }
    setSituacao((atual) => (atual === "salvando" ? atual : "pendente"));
    cancelarRelogio();
    relogio.current = setTimeout(() => void gravar().catch(() => undefined), atrasoMs);
  }, [edicao, atrasoMs, cancelarRelogio, gravar, pendentes]);

  // Trocar de peça ou sair da tela não pode perder a digitação da última pausa.
  useEffect(
    () => () => {
      cancelarRelogio();
      const envio = pendentes(edicaoRef.current);
      if (chave && envio.length) void salvarRef.current(chave, envio).catch(() => undefined);
    },
    [chave, cancelarRelogio, pendentes],
  );

  // Fechar a aba com texto ainda não gravado: tenta gravar e pede confirmação.
  useEffect(() => {
    function aoSair(evento: BeforeUnloadEvent) {
      if (!pendentes(edicaoRef.current).length && !emVoo.current) return;
      void gravar().catch(() => undefined);
      evento.preventDefault();
      evento.returnValue = "";
    }
    window.addEventListener("beforeunload", aoSair);
    return () => window.removeEventListener("beforeunload", aoSair);
  }, [gravar, pendentes]);

  const editar = useCallback((codigo: string, valor: string) => {
    setEdicao((atual) => ({ ...atual, [codigo]: valor }));
  }, []);

  /** Troca o texto pelo do servidor, descartando o que não foi gravado — para
   *  ações que substituem a peça inteira (aceitar/descartar revisão). */
  const substituir = useCallback(
    (novas: SecaoEditada[] | undefined) => {
      cancelarRelogio();
      const doServidor = Object.fromEntries((novas ?? []).map((s) => [s.code, s.content]));
      salvo.current = doServidor;
      setEdicao(doServidor);
    },
    [cancelarRelogio],
  );

  return {
    edicao,
    editar,
    situacao,
    erro,
    salvoEm,
    /** Grava agora o que estiver pendente e espera terminar. */
    descarregar: gravar,
    substituir,
  };
}
