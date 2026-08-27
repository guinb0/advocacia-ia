"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import * as api from "./api";
import type { Caso, Entrega, SituacaoCaso } from "./types";

/* A carteira é a visão do sócio: a fila ordenada por risco de travar, não por
 * data. `GET /api/casos` devolve só o cadastro do caso, então o progresso vem
 * de `GET /api/casos/{id}` (o mesmo `montar_situacao` da tela do caso).
 *
 * CARREGAMENTO EM LOTES, não tudo de uma vez.
 *
 * Antes as N situações vinham num `Promise.all` só — com o armazenamento em
 * JSON local isso era de graça, mas em SQL Server viraram N idas ao banco que
 * seguravam a primeira pintura da tela até a última responder. Agora o detalhe
 * chega em lotes: o primeiro destrava a Mesa do dia (a lista já aparece), e os
 * demais entram em segundo plano para completar os contadores do topo sem
 * travar quem já está olhando a fila. */

export type Severidade = "critico" | "atencao" | "pronto" | "neutro";

/** Quantos casos carregam por vez. Também é o tamanho da página da fila. */
export const LOTE_CARTEIRA = 5;

/** Dias parados a partir dos quais um caso sem documento vira cobrança. */
const DIAS_PARA_COBRAR = 7;

export interface AcaoCaso {
  rotulo: string;
  severidade: Severidade;
  /** Símbolo do selo, para que o estado não dependa só da cor. */
  simbolo: string;
}

export interface LinhaCarteira {
  caso: Caso;
  situacao: SituacaoCaso;
  categoriaNome: string;
  diasParado: number;
  severidade: Severidade;
  acao: AcaoCaso;
  /** Situação em linguagem humana, como no desenho: "Parado há 12 dias · …". */
  frase: string;
  /** Ordena a fila: menor primeiro. */
  peso: number;
}

export interface ChegandoAgora {
  entrega: Entrega;
  cliente: string;
  estagio: string;
  severidade: Severidade;
}

export interface Triagem {
  travados: number;
  aConferir: number;
  pedidosProntos: number;
  completos: number;
  ativos: number;
}

function diasDesde(iso: string): number {
  const quando = new Date(iso).getTime();
  if (Number.isNaN(quando)) return 0;
  return Math.max(0, Math.floor((Date.now() - quando) / 86_400_000));
}

function pluralDias(dias: number): string {
  if (dias === 0) return "hoje";
  return dias === 1 ? "há 1 dia" : `há ${dias} dias`;
}

/** Une as frases do backend numa linha só, sem inventar texto novo. */
function frasePara(situacao: SituacaoCaso, dias: number): string {
  const { progresso, itens } = situacao;
  const partes: string[] = [];

  if (progresso.pronto) {
    return `Instrução completa: ${progresso.obrigatorios_entregues} de ${progresso.obrigatorios_total} obrigatórios validados. Pronto para a inicial.`;
  }

  if (progresso.obrigatorios_pendentes > 0 && dias >= DIAS_PARA_COBRAR) {
    partes.push(`Parado ${pluralDias(dias)} · cliente não responde ao pedido`);
  }

  if (progresso.itens_a_conferir > 0) {
    partes.push(
      `${progresso.itens_a_conferir} ${progresso.itens_a_conferir === 1 ? "documento" : "documentos"} a conferir`,
    );
    // O primeiro alerta do OCR explica o "por quê" melhor que qualquer resumo
    // nosso — vai verbatim, como manda o guia.
    const alerta = itens
      .filter((item) => item.status === "conferir")
      .flatMap((item) => item.entregas.flatMap((e) => e.alertas))
      .find(Boolean);
    if (alerta) partes.push(alerta.replace(/\s+/g, " ").trim());
  }

  if (progresso.obrigatorios_pendentes > 0) {
    partes.push(`${progresso.obrigatorios_pendentes} obrigatórios sem arquivo`);
  }

  if (partes.length === 0) partes.push(`Aguardando cliente ${pluralDias(dias)}`);
  return partes.join(" · ");
}

/* O rótulo é a próxima providência, escrita como se fosse dita em voz alta.
 * Antes vinha em caixa alta ("COBRAR CLIENTE", "CONFERIR 3"): lido como
 * carimbo, e caixa alta em bloco atrasa a leitura de quem tem menos prática
 * com a tela. O símbolo acompanha o rótulo para que o selo não informe só pela
 * cor. */
function acaoPara(situacao: SituacaoCaso, dias: number): AcaoCaso {
  const { progresso } = situacao;
  if (progresso.pronto) {
    return { rotulo: "Pronto para a inicial", severidade: "pronto", simbolo: "✓" };
  }
  if (progresso.obrigatorios_pendentes > 0 && dias >= DIAS_PARA_COBRAR) {
    return { rotulo: "Cobrar o cliente", severidade: "critico", simbolo: "✕" };
  }
  if (progresso.itens_a_conferir > 0) {
    const quantos = progresso.itens_a_conferir;
    return {
      rotulo: `Conferir ${quantos} ${quantos === 1 ? "documento" : "documentos"}`,
      severidade: "atencao",
      simbolo: "!",
    };
  }
  if (progresso.obrigatorios_pendentes > 0) {
    return { rotulo: "Enviar o pedido", severidade: "neutro", simbolo: "→" };
  }
  return { rotulo: "Aguardando o cliente", severidade: "neutro", simbolo: "•" };
}

function montarLinha(situacao: SituacaoCaso): LinhaCarteira {
  const dias = diasDesde(situacao.caso.atualizado_em || situacao.caso.criado_em);
  const acao = acaoPara(situacao, dias);
  const { progresso } = situacao;

  /* Ordena por risco de travar: o que depende de decisão do advogado sobe.
   * O desempate por dias parados evita que dois casos iguais fiquem trocando
   * de lugar a cada render. */
  const base =
    acao.severidade === "critico"
      ? 0
      : acao.severidade === "atencao"
        ? 1_000
        : progresso.pronto
          ? 2_000
          : 3_000;

  return {
    caso: situacao.caso,
    situacao,
    categoriaNome: situacao.categoria?.nome ?? situacao.caso.categoria,
    diasParado: dias,
    severidade: acao.severidade,
    acao,
    frase: frasePara(situacao, dias),
    peso: base - dias,
  };
}

function estagioDaEntrega(entrega: Entrega): { estagio: string; severidade: Severidade } {
  if (entrega.tipo_confere === false) {
    return { estagio: "Tipo diferente do esperado", severidade: "atencao" };
  }
  if (entrega.dados_utilizaveis || entrega.confirmado_manual) {
    const score = entrega.score_legibilidade;
    return {
      estagio: score !== null ? `Lido — nitidez ${score}%` : "Lido e aceito",
      severidade: "pronto",
    };
  }
  const score = entrega.score_legibilidade;
  return {
    estagio: score !== null ? `Ilegível (${score}%) — pedir de novo` : "Não foi possível ler",
    severidade: "critico",
  };
}

export function useCarteira() {
  const [situacoes, setSituacoes] = useState<SituacaoCaso[]>([]);
  /** Total de casos cadastrados — sabido pela lista, antes dos detalhes. */
  const [totalCasos, setTotalCasos] = useState(0);
  /** Carregando o PRIMEIRO lote (a tela ainda não pode aparecer). */
  const [carregando, setCarregando] = useState(true);
  /** Ainda há lotes chegando em segundo plano (contadores incompletos). */
  const [carregandoDetalhes, setCarregandoDetalhes] = useState(true);
  const [erro, setErro] = useState<string | null>(null);
  /* Uma execução por vez: se `recarregar` for chamado de novo (ou a tela
   * desmontar) no meio dos lotes, o loop antigo para de escrever no estado. */
  const execucao = useRef(0);

  const recarregar = useCallback(async () => {
    const meu = ++execucao.current;
    setCarregando(true);
    setCarregandoDetalhes(true);
    setSituacoes([]);
    try {
      const casos = await api.listarCasos();
      if (execucao.current !== meu) return;
      setTotalCasos(casos.length);
      if (casos.length === 0) {
        setCarregando(false);
        setCarregandoDetalhes(false);
      }
      // Em lotes: o primeiro destrava a tela, o resto completa os contadores.
      for (let i = 0; i < casos.length; i += LOTE_CARTEIRA) {
        const lote = casos.slice(i, i + LOTE_CARTEIRA);
        const detalhes = await Promise.all(
          lote.map((caso) => api.obterCaso(caso.id).catch(() => null)),
        );
        if (execucao.current !== meu) return;
        const validos = detalhes.filter(
          (s): s is SituacaoCaso => s !== null && !!s.progresso,
        );
        setSituacoes((atuais) => [...atuais, ...validos]);
        // Assim que o primeiro lote chega, a Mesa do dia já pode aparecer.
        if (i === 0) setCarregando(false);
      }
      if (execucao.current === meu) setErro(null);
    } catch (e) {
      if (execucao.current === meu) {
        setErro(e instanceof Error ? e.message : "Falha ao carregar a carteira.");
      }
    } finally {
      if (execucao.current === meu) {
        setCarregando(false);
        setCarregandoDetalhes(false);
      }
    }
  }, []);

  useEffect(() => {
    void recarregar();
    // Para a escrita de lotes pendentes se a carteira sair da tela.
    return () => {
      execucao.current += 1;
    };
  }, [recarregar]);

  const linhas = useMemo(
    () => situacoes.map(montarLinha).sort((a, b) => a.peso - b.peso),
    [situacoes],
  );

  const triagem = useMemo<Triagem>(
    () => ({
      travados: linhas.filter((l) => l.severidade === "critico").length,
      aConferir: linhas.reduce((soma, l) => soma + l.situacao.progresso.itens_a_conferir, 0),
      pedidosProntos: linhas.filter((l) => l.situacao.progresso.obrigatorios_pendentes > 0).length,
      completos: linhas.filter((l) => l.situacao.progresso.pronto).length,
      ativos: linhas.length,
    }),
    [linhas],
  );

  const chegandoAgora = useMemo<ChegandoAgora[]>(() => {
    const todas = situacoes.flatMap((s) =>
      s.itens.flatMap((item) =>
        item.entregas.map((entrega) => ({ entrega, cliente: s.caso.cliente })),
      ),
    );
    // Uma entrega que atende RG e CPF aparece duas vezes em `itens`.
    const vistas = new Set<string>();
    return todas
      .filter(({ entrega }) => {
        if (vistas.has(entrega.id)) return false;
        vistas.add(entrega.id);
        return true;
      })
      .sort((a, b) => b.entrega.criado_em.localeCompare(a.entrega.criado_em))
      .slice(0, 4)
      .map(({ entrega, cliente }) => ({ entrega, cliente, ...estagioDaEntrega(entrega) }));
  }, [situacoes]);

  const pedidos = useMemo(
    () =>
      linhas
        .filter((l) => l.situacao.progresso.obrigatorios_pendentes > 0)
        .slice(0, 4)
        .map((l) => ({
          casoId: l.caso.id,
          cliente: l.caso.cliente,
          faltantes: l.situacao.progresso.obrigatorios_pendentes,
          reenvios: l.situacao.progresso.itens_a_conferir,
        })),
    [linhas],
  );

  return {
    linhas,
    triagem,
    chegandoAgora,
    pedidos,
    carregando,
    carregandoDetalhes,
    totalCasos,
    erro,
    recarregar,
  };
}
