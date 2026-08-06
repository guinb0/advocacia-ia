"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import * as api from "./api";
import type { Caso, Entrega, SituacaoCaso } from "./types";

/* A carteira é a visão do sócio: a fila ordenada por risco de travar, não por
 * data. `GET /api/casos` devolve só o cadastro do caso, então o progresso vem
 * de `GET /api/casos/{id}` (o mesmo `montar_situacao` da tela do caso) buscado
 * em paralelo. Tudo aqui é derivado — nenhum status é guardado à mão, pela
 * mesma razão que `casos.py` não guarda: sairia do lugar assim que alguém
 * apagasse uma entrega. */

export type Severidade = "critico" | "atencao" | "pronto" | "neutro";

/** Dias parados a partir dos quais um caso sem documento vira cobrança. */
const DIAS_PARA_COBRAR = 7;

export interface AcaoCaso {
  rotulo: string;
  severidade: Severidade;
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

function acaoPara(situacao: SituacaoCaso, dias: number): AcaoCaso {
  const { progresso } = situacao;
  if (progresso.pronto) return { rotulo: "PRONTO ✓", severidade: "pronto" };
  if (progresso.obrigatorios_pendentes > 0 && dias >= DIAS_PARA_COBRAR) {
    return { rotulo: "COBRAR CLIENTE", severidade: "critico" };
  }
  if (progresso.itens_a_conferir > 0) {
    return { rotulo: `CONFERIR ${progresso.itens_a_conferir}`, severidade: "atencao" };
  }
  if (progresso.obrigatorios_pendentes > 0) {
    return { rotulo: "ENVIAR PEDIDO", severidade: "neutro" };
  }
  return { rotulo: "AGUARDANDO", severidade: "neutro" };
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
    return { estagio: "tipo divergente · confira o arquivo", severidade: "atencao" };
  }
  if (entrega.dados_utilizaveis || entrega.confirmado_manual) {
    const score = entrega.score_legibilidade;
    return {
      estagio: `classificado ✓${score !== null ? ` · legibilidade ${score}%` : ""} · entregue`,
      severidade: "pronto",
    };
  }
  const score = entrega.score_legibilidade;
  return {
    estagio: score !== null ? `ilegível ${score}% · reenvio pedido` : "não foi possível ler",
    severidade: "critico",
  };
}

export function useCarteira() {
  const [situacoes, setSituacoes] = useState<SituacaoCaso[]>([]);
  const [carregando, setCarregando] = useState(true);
  const [erro, setErro] = useState<string | null>(null);

  const recarregar = useCallback(async () => {
    setCarregando(true);
    try {
      const casos = await api.listarCasos();
      // Storage local em JSON: as N leituras saem de uma vez sem custo real.
      const detalhes = await Promise.all(
        casos.map((caso) =>
          api.obterCaso(caso.id).catch(() => null),
        ),
      );
      setSituacoes(detalhes.filter((s): s is SituacaoCaso => s !== null && !!s.progresso));
      setErro(null);
    } catch (e) {
      setErro(e instanceof Error ? e.message : "Falha ao carregar a carteira.");
    } finally {
      setCarregando(false);
    }
  }, []);

  useEffect(() => {
    void recarregar();
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

  return { linhas, triagem, chegandoAgora, pedidos, carregando, erro, recarregar };
}
