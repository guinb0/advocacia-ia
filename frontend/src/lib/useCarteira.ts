"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import * as api from "./api";
import type { Caso, Entrega, SituacaoCaso } from "./types";

/* A carteira é a visão do sócio: a fila ordenada por risco de travar, não por
 * data. Tudo aqui é derivado — nenhum status é guardado à mão, pela mesma razão
 * que `casos.py` não guarda: sairia do lugar assim que alguém apagasse uma
 * entrega.
 *
 * A fila vem paginada de `GET /api/carteira` (10 casos por página). Antes era
 * `GET /api/casos` mais um `GET /api/casos/{id}` por caso — a carteira inteira
 * no navegador e uma requisição por caso. A ordem por risco e os contadores da
 * triagem continuam medidos sobre a carteira toda, no servidor: paginá-los faria
 * o topo da tela mudar de número ao virar de página. */

export type Severidade = "critico" | "atencao" | "pronto" | "neutro";

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

export const CASOS_POR_PAGINA = 10;

export function useCarteira() {
  const [pagina, setPagina] = useState(1);
  const [dados, setDados] = useState<api.PaginaCarteira | null>(null);
  const [carregando, setCarregando] = useState(true);
  const [erro, setErro] = useState<string | null>(null);

  const recarregar = useCallback(async () => {
    setCarregando(true);
    try {
      const resposta = await api.obterCarteira(pagina, CASOS_POR_PAGINA);
      setDados(resposta);
      // O servidor prende a página ao total: apagar o último caso de uma página
      // deixaria o cursor além do fim e a lista viria vazia sem explicação.
      if (resposta.pagina !== pagina) setPagina(resposta.pagina);
      setErro(null);
    } catch (e) {
      setErro(e instanceof Error ? e.message : "Falha ao carregar a carteira.");
    } finally {
      setCarregando(false);
    }
  }, [pagina]);

  useEffect(() => {
    void recarregar();
  }, [recarregar]);

  /* A página já vem ordenada por risco do servidor; reordenar aqui pelo mesmo
   * peso mantém as duas pontas de acordo caso uma delas mude. */
  const linhas = useMemo(
    () =>
      (dados?.situacoes ?? [])
        .filter((s) => !!s.progresso)
        .map(montarLinha)
        .sort((a, b) => a.peso - b.peso),
    [dados],
  );

  const triagem = useMemo<Triagem>(
    () =>
      dados?.triagem ?? {
        travados: 0,
        aConferir: 0,
        pedidosProntos: 0,
        completos: 0,
        ativos: 0,
      },
    [dados],
  );

  const chegandoAgora = useMemo<ChegandoAgora[]>(
    () =>
      (dados?.chegando_agora ?? []).map(({ entrega, cliente }) => ({
        entrega,
        cliente,
        ...estagioDaEntrega(entrega),
      })),
    [dados],
  );

  const pedidos = useMemo(() => dados?.pedidos ?? [], [dados]);

  const paginacao = useMemo(
    () => ({
      pagina: dados?.pagina ?? pagina,
      paginas: dados?.paginas ?? 1,
      total: dados?.total ?? 0,
      tamanho: dados?.tamanho ?? CASOS_POR_PAGINA,
      /** Índice do primeiro caso desta página na fila inteira, base 1. */
      primeiro: dados && dados.total > 0 ? (dados.pagina - 1) * dados.tamanho + 1 : 0,
      ultimo: dados ? Math.min(dados.pagina * dados.tamanho, dados.total) : 0,
    }),
    [dados, pagina],
  );

  const irPara = useCallback(
    (destino: number) => {
      setPagina((atual) => {
        const limite = dados?.paginas ?? 1;
        const alvo = Math.min(Math.max(1, destino), Math.max(1, limite));
        return alvo === atual ? atual : alvo;
      });
    },
    [dados],
  );

  return {
    linhas,
    triagem,
    chegandoAgora,
    pedidos,
    carregando,
    erro,
    recarregar,
    paginacao,
    irPara,
  };
}
