"use client";

/* O atendimento que a entrevista vai conduzir.
 *
 * A agenda e o alerta "cliente entrou na sala" levam à tela da entrevista, mas a
 * navegação aqui é por estado (ver `useHomeModel`), não por rota: não há URL que
 * carregue o atendimento. Fica no sessionStorage — sobrevive ao F5 da aba, não
 * vaza para outra aba — e um evento avisa a entrevista já montada. */

import { useEffect, useState } from "react";

import { obterConfigAtendimento } from "./api/atendimentos";

export interface AtendimentoAtivo {
  id: string;
  sala: string | null;
  cliente: string;
  telefone?: string;
}

const CHAVE = "atendimento:ativo";
const EVENTO = "atendimento:ativo";

export function lerAtendimentoAtivo(): AtendimentoAtivo | null {
  if (typeof window === "undefined") return null;
  try {
    const bruto = window.sessionStorage.getItem(CHAVE);
    return bruto ? (JSON.parse(bruto) as AtendimentoAtivo) : null;
  } catch {
    return null;
  }
}

export function definirAtendimentoAtivo(atendimento: AtendimentoAtivo | null): void {
  if (typeof window === "undefined") return;
  try {
    if (atendimento) window.sessionStorage.setItem(CHAVE, JSON.stringify(atendimento));
    else window.sessionStorage.removeItem(CHAVE);
  } catch {
    /* sessionStorage bloqueado: a entrevista abre como avulsa */
  }
  window.dispatchEvent(new Event(EVENTO));
}

export function useAtendimentoAtivo(): AtendimentoAtivo | null {
  const [ativo, setAtivo] = useState<AtendimentoAtivo | null>(null);
  useEffect(() => {
    const ler = () => setAtivo(lerAtendimentoAtivo());
    ler();
    window.addEventListener(EVENTO, ler);
    return () => window.removeEventListener(EVENTO, ler);
  }, []);
  return ativo;
}

let fluxoV2Cache: Promise<boolean> | null = null;

/** O fluxo novo vem ligado do servidor (`FLUXO_ATENDIMENTO_V2`); sem resposta, fica o antigo. */
export function useFluxoV2(): boolean | null {
  const [ligado, setLigado] = useState<boolean | null>(null);
  useEffect(() => {
    fluxoV2Cache ??= obterConfigAtendimento()
      .then((c) => c.fluxo_v2 !== false)
      .catch(() => {
        fluxoV2Cache = null;
        return false;
      });
    let vivo = true;
    void fluxoV2Cache.then((v) => vivo && setLigado(v));
    return () => {
      vivo = false;
    };
  }, []);
  return ligado;
}
