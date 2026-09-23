"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import type { Peticao } from "@/lib/agente";

/** Uma seção como ela sai da tela: o corpo e o título do tópico.
 *
 * `label` viaja junto porque o título É a peça — "DO CONTRATO DE TRABALHO" vira
 * parágrafo em negrito no .docx (ver `app/peticao_local.montar_docx`). Antes só
 * o corpo era editável, e renomear um tópico exigia pedir à IA. */
type SecaoEditada = { code: string; content: string; label?: string };

/** Uma peça em edição: as seções pendentes e, quando mudou, o nome da peça. */
type EnvioDeEdicao = { secoes: SecaoEditada[]; titulo?: string };

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
 * TRÊS COISAS SÃO EDITÁVEIS, NÃO UMA
 *
 * O corpo de cada seção, o TÍTULO de cada seção e o NOME da peça. Os três
 * seguem o mesmo caminho de gravação, e o mesmo diferencial contra o que o
 * servidor tem — um título renomeado sozinho grava igual a um parágrafo
 * reescrito.
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
  titulo,
  salvar,
  onSalvo,
  atrasoMs = ATRASO_PADRAO_MS,
}: {
  /** Id da peça em edição; `null` quando nenhuma está aberta. */
  chave: string | null;
  secoes: SecaoEditada[] | undefined;
  /** O nome da peça como está no servidor. */
  titulo?: string;
  salvar: (chave: string, envio: EnvioDeEdicao) => Promise<Peticao>;
  onSalvo?: (peticao: Peticao, chave: string) => void;
  atrasoMs?: number;
}) {
  const [edicao, setEdicao] = useState<Record<string, string>>({});
  const [rotulos, setRotulos] = useState<Record<string, string>>({});
  const [tituloEditado, setTituloEditado] = useState<string | null>(null);
  const [situacao, setSituacao] = useState<SituacaoDoSalvamento>("salvo");
  const [erro, setErro] = useState<string | null>(null);
  const [salvoEm, setSalvoEm] = useState<Date | null>(null);

  /** O que o servidor tem — a referência do que falta gravar. */
  const salvo = useRef<Record<string, string>>({});
  const rotuloSalvo = useRef<Record<string, string>>({});
  const tituloSalvo = useRef<string>("");
  const edicaoRef = useRef(edicao);
  edicaoRef.current = edicao;
  const rotulosRef = useRef(rotulos);
  rotulosRef.current = rotulos;
  const tituloRef = useRef(tituloEditado);
  tituloRef.current = tituloEditado;
  const chaveRef = useRef(chave);
  const salvarRef = useRef(salvar);
  salvarRef.current = salvar;
  const onSalvoRef = useRef(onSalvo);
  onSalvoRef.current = onSalvo;
  const emVoo = useRef<Promise<void> | null>(null);
  const relogio = useRef<ReturnType<typeof setTimeout> | null>(null);

  /** O que ainda não está no servidor. `secoes` leva corpo E rótulo juntos: a
   *  gravação é da seção inteira, então mandar um sem o outro apagaria o que
   *  não foi mandado. */
  const pendentes = useCallback(
    (
      textos: Record<string, string>,
      titulos: Record<string, string>,
      nome: string | null,
    ): EnvioDeEdicao => {
      const secoesPendentes = Object.keys(salvo.current)
        .filter(
          (code) =>
            (textos[code] !== undefined && textos[code] !== salvo.current[code]) ||
            (titulos[code] !== undefined && titulos[code] !== rotuloSalvo.current[code]),
        )
        .map((code) => ({
          code,
          content: textos[code] ?? salvo.current[code],
          label: titulos[code] ?? rotuloSalvo.current[code] ?? "",
        }));
      const nomePendente = nome !== null && nome !== tituloSalvo.current ? nome : undefined;
      return { secoes: secoesPendentes, titulo: nomePendente };
    },
    [],
  );

  const nadaPendente = useCallback(
    (envio: EnvioDeEdicao) => envio.secoes.length === 0 && envio.titulo === undefined,
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
    const envio = pendentes(edicaoRef.current, rotulosRef.current, tituloRef.current);
    if (!chaveAtual || nadaPendente(envio)) {
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
          ...Object.fromEntries(envio.secoes.map((s) => [s.code, s.content])),
        };
        rotuloSalvo.current = {
          ...rotuloSalvo.current,
          ...Object.fromEntries(envio.secoes.map((s) => [s.code, s.label ?? ""])),
        };
        if (envio.titulo !== undefined) tituloSalvo.current = envio.titulo;
        setErro(null);
        setSalvoEm(new Date());
        setSituacao(
          nadaPendente(pendentes(edicaoRef.current, rotulosRef.current, tituloRef.current))
            ? "salvo"
            : "pendente",
        );
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
  }, [cancelarRelogio, nadaPendente, pendentes]);

  // A peça veio (ou voltou) do servidor.
  useEffect(() => {
    const doServidor = Object.fromEntries((secoes ?? []).map((s) => [s.code, s.content]));
    const rotulosDoServidor = Object.fromEntries(
      (secoes ?? []).map((s) => [s.code, s.label ?? ""]),
    );
    const nomeDoServidor = titulo ?? "";
    const mesmaPeca = chaveRef.current === chave;
    chaveRef.current = chave;
    const base = salvo.current;
    const baseRotulos = rotuloSalvo.current;
    const baseTitulo = tituloSalvo.current;
    salvo.current = doServidor;
    rotuloSalvo.current = rotulosDoServidor;
    tituloSalvo.current = nomeDoServidor;
    setEdicao((atual) => {
      if (!mesmaPeca) return doServidor;
      const combinada = { ...doServidor };
      for (const code of Object.keys(doServidor)) {
        const local = atual[code];
        if (local !== undefined && local !== base[code]) combinada[code] = local;
      }
      return combinada;
    });
    setRotulos((atual) => {
      if (!mesmaPeca) return rotulosDoServidor;
      const combinada = { ...rotulosDoServidor };
      for (const code of Object.keys(rotulosDoServidor)) {
        const local = atual[code];
        if (local !== undefined && local !== baseRotulos[code]) combinada[code] = local;
      }
      return combinada;
    });
    setTituloEditado((atual) => {
      if (!mesmaPeca) return nomeDoServidor;
      return atual !== null && atual !== baseTitulo ? atual : nomeDoServidor;
    });
  }, [chave, secoes, titulo]);

  // Cada mudança no texto: grava depois da pausa.
  useEffect(() => {
    if (nadaPendente(pendentes(edicao, rotulos, tituloEditado))) {
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
  }, [
    edicao,
    rotulos,
    tituloEditado,
    atrasoMs,
    cancelarRelogio,
    gravar,
    nadaPendente,
    pendentes,
  ]);

  // Trocar de peça ou sair da tela não pode perder a digitação da última pausa.
  useEffect(
    () => () => {
      cancelarRelogio();
      const envio = pendentes(edicaoRef.current, rotulosRef.current, tituloRef.current);
      if (chave && !nadaPendente(envio)) {
        void salvarRef.current(chave, envio).catch(() => undefined);
      }
    },
    [chave, cancelarRelogio, nadaPendente, pendentes],
  );

  // Fechar a aba com texto ainda não gravado: tenta gravar e pede confirmação.
  useEffect(() => {
    function aoSair(evento: BeforeUnloadEvent) {
      const envio = pendentes(edicaoRef.current, rotulosRef.current, tituloRef.current);
      if (nadaPendente(envio) && !emVoo.current) return;
      void gravar().catch(() => undefined);
      evento.preventDefault();
      evento.returnValue = "";
    }
    window.addEventListener("beforeunload", aoSair);
    return () => window.removeEventListener("beforeunload", aoSair);
  }, [gravar, nadaPendente, pendentes]);

  const editar = useCallback((codigo: string, valor: string) => {
    setEdicao((atual) => ({ ...atual, [codigo]: valor }));
  }, []);

  const editarRotulo = useCallback((codigo: string, valor: string) => {
    setRotulos((atual) => ({ ...atual, [codigo]: valor }));
  }, []);

  const editarTitulo = useCallback((valor: string) => setTituloEditado(valor), []);

  /** Troca o texto pelo do servidor, descartando o que não foi gravado — para
   *  ações que substituem a peça inteira (aceitar/descartar revisão). */
  const substituir = useCallback(
    (novas: SecaoEditada[] | undefined) => {
      cancelarRelogio();
      const doServidor = Object.fromEntries((novas ?? []).map((s) => [s.code, s.content]));
      const rotulosDoServidor = Object.fromEntries(
        (novas ?? []).map((s) => [s.code, s.label ?? ""]),
      );
      salvo.current = doServidor;
      rotuloSalvo.current = rotulosDoServidor;
      setEdicao(doServidor);
      setRotulos(rotulosDoServidor);
    },
    [cancelarRelogio],
  );

  return {
    edicao,
    editar,
    rotulos,
    editarRotulo,
    titulo: tituloEditado ?? "",
    editarTitulo,
    situacao,
    erro,
    salvoEm,
    /** Grava agora o que estiver pendente e espera terminar. */
    descarregar: gravar,
    substituir,
  };
}
