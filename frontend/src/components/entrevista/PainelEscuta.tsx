"use client";

import { useEffect, useState } from "react";

import type { CampoOuvido, Lembrete, PerguntaPendente } from "@/lib/types";

/* O que a conversa já preencheu, e o que ainda falta perguntar.
 *
 * Fica ao lado do roteiro, visível o tempo todo. É a resposta ao que o
 * escritório pediu: "o entrevistador deve ver em tempo real tudo que foi
 * preenchido e tudo que necessita ser perguntado".
 *
 * A ordem das três seções não é arbitrária — é a ordem em que o entrevistador
 * precisa delas enquanto o cliente fala:
 *
 *   1. APROFUNDAR    o que ficou pela metade e volta DEPOIS da pergunta da vez.
 *   2. FALTA         o que o roteiro ainda pede.
 *   3. JÁ ENTROU     o que a conversa preencheu, para conferir de relance.
 *
 * A primeira seção já se chamou "pergunte agora", e o nome era o problema: ela
 * é o que o MODELO sugeriu aprofundar, e disputava com a sequência do roteiro a
 * pergunta seguinte. Quem manda na próxima pergunta é a barra de condução, no
 * alto da tela (`Conducao.tsx`); estas são para encaixar depois.
 *
 * AQUI HAVIA UMA QUARTA: "confirme o que eu ouvi", com nome e CPF esperando um
 * clique. Ela saiu por decisão do escritório, e a razão é a mesma que motivou a
 * condução: parar a entrevista para conferir a grafia de um nome trava o
 * processo com o cliente na linha. A conferência não sumiu — foi inteira para o
 * fim do roteiro, na `Conducao`, quando ninguém está mais esperando a próxima
 * pergunta. O que resta aqui é a contagem, sem botão, para o entrevistador
 * saber que a escuta ouviu sem ser convidado a parar por causa disso.
 *
 * "Já entrou" fica por último de propósito: é a seção que dá confiança, não a
 * que exige ação. No começo da entrevista ela está vazia e ninguém sente falta;
 * no fim ela é longa e ninguém precisa mais dela. */

interface Props {
  transcricao: { quando: number; texto: string; quem: "Entrevistador" | "Entrevistado" | "Falante não identificado" }[];
  parcial: string;
  preenchidas: CampoOuvido[];
  /** Quantas esperam conferência no fim. Só o número: conferir é lá. */
  aConferir: number;
  lembretes: Lembrete[];
  faltando: PerguntaPendente[];
  /** Uma chamada à escuta está em curso — o modelo interpretando um trecho. */
  interpretando: boolean;
  /** O microfone está captando (e não pausado). */
  captando: boolean;
  pausado: boolean;
  /** `Date.now()` do último trecho reconhecido; `null` se ainda não houve. */
  ultimaFala: number | null;
  /** `Date.now()` da última vez que o microfone captou SOM (não fala). */
  ultimoSom: number | null;
  /** Nível TÍPICO da fala: mediana dos blocos que têm som. `null` até haver
   *  amostra suficiente. Separa "ninguém falou ainda" de "está falando, mas o
   *  microfone está fraco demais para reconhecer direito". */
  nivelTipico: number | null;
  /** Segundos de áudio por segundo de relógio, medido no servidor. */
  chegada: number | null;
  erro: string | null;
  /** Levar o roteiro até a pergunta — o painel é índice, não só relatório. */
  onIrPara: (perguntaId: string) => void;
}

/* O que o indicador do topo diz, e por que estas palavras.
 *
 * A versão anterior alternava entre "ouvindo…" e "em espera" — e as duas
 * descreviam a MESMA coisa: se havia ou não uma chamada à API no ar. "Em
 * espera" era o estado normal com o microfone captando perfeitamente, o que
 * fazia o entrevistador achar que o sistema tinha parado.
 *
 * O que ele precisa saber é outra coisa: o microfone está captando, e há quanto
 * tempo a última fala foi reconhecida. Silêncio prolongado com alguém falando é
 * o sintoma de microfone mudo, e é o único caso em que ele precisa agir. */
/** Abaixo disto o áudio chega mais devagar que a fala: some conteúdo no
 *  caminho, ANTES do reconhecimento, e o buraco no texto não tem como ser
 *  explicado por quem só olha a transcrição. */
const CHEGADA_MINIMA = 0.9;

const ESTADO_BASE = "text-[10.5px] leading-none font-ui";
const ESTADO_OUVINDO = `${ESTADO_BASE} font-normal text-ok`;
const ESTADO_OCIOSO = `${ESTADO_BASE} font-normal text-tinta-3`;
const ESTADO_PAUSADO = `${ESTADO_BASE} font-normal text-atencao`;
/* Faz tempo que nada é reconhecido. Âmbar, não vermelho: pode ser só uma
 * pausa longa na conversa — mas se alguém está falando, é microfone mudo. */
const ESTADO_SILENCIO = `${ESTADO_BASE} font-normal text-atencao`;
/* Microfone mudo: vermelho, porque aqui a entrevista ESTÁ sendo perdida
 * enquanto se conversa. É o único estado do painel que exige ação imediata. */

function situacao(
  captando: boolean,
  pausado: boolean,
  interpretando: boolean,
  ultimaFala: number | null,
  ultimoSom: number | null,
  nivelTipico: number | null,
): { texto: string; classe: string; titulo: string } {

  if (pausado) {
    return {
      texto: "pausado",
      classe: ESTADO_PAUSADO,
      titulo: "O que for dito agora não entra na entrevista.",
    };
  }
  if (!captando) {
    return {
      texto: "microfone fechado",
      classe: ESTADO_OCIOSO,
      titulo: "Clique em “Começar a entrevista” para abrir o microfone.",
    };
  }
  if (interpretando) {
    return {
      texto: "interpretando…",
      classe: ESTADO_OUVINDO,
      titulo: "Um trecho da conversa está sendo lido contra o roteiro.",
    };
  }
  if (ultimaFala === null) {
    return {
      texto: "ouvindo — nada reconhecido ainda",
      classe: ESTADO_OCIOSO,
      titulo:
        "O microfone está aberto. O texto só entra quando um trecho de fala " +
        "para de mudar, o que leva alguns segundos após a pausa.",
    };
  }
  const segundos = Math.round((Date.now() - ultimaFala) / 1000);
  return {
    texto: segundos < 20 ? "ouvindo" : `ouvindo — nada há ${segundos}s`,
    classe: segundos < 45 ? ESTADO_OUVINDO : ESTADO_SILENCIO,
    titulo:
      segundos < 45
        ? "Última fala reconhecida há pouco."
        : "Faz tempo que nada é reconhecido. Se alguém está falando, confira o microfone.",
  };
}

export default function PainelEscuta({
  transcricao,
  parcial,
  preenchidas,
  aConferir,
  lembretes,
  faltando,
  interpretando,
  captando,
  pausado,
  ultimaFala,
  ultimoSom,
  nivelTipico,
  chegada,
  erro,
  onIrPara,
}: Props) {
  const obrigatoriasFaltando = faltando.filter((f) => f.obrigatoria);

  /* O "há Xs" precisa de um relógio próprio: sem ele o número congela no
   * último render, e um painel que diz "há 3s" há dois minutos mente pior do
   * que se não dissesse nada. 5s é o passo — o suficiente para o número andar,
   * pouco o bastante para não redesenhar a lista o tempo todo. */
  const [, tique] = useState(0);
  useEffect(() => {
    if (!captando || pausado) return;
    const id = setInterval(() => tique((n) => n + 1), 5000);
    return () => clearInterval(id);
  }, [captando, pausado]);

  const estado = situacao(
    captando,
    pausado,
    interpretando,
    ultimaFala,
    ultimoSom,
    nivelTipico,
  );
  const atrasado = captando && !pausado && chegada !== null && chegada < CHEGADA_MINIMA;

  return (
    <aside className="roteiro-transcricao border border-borda-forte p-[14px] sticky top-[18px] max-h-[calc(100vh-36px)] overflow-y-auto">
      <div className="flex items-baseline justify-between gap-2 mb-3 pb-[10px] border-b border-borda">
        <span className="text-[10px] font-semibold leading-none font-ui tracking-[0.14em] text-tinta-3">
          A ENTREVISTA ATÉ AQUI
        </span>
        <span className={estado.classe} title={estado.titulo}>
          {estado.texto}
        </span>
      </div>

      <section className="mb-[18px] border-b border-borda pb-4" aria-live="polite">
        <span className="block mb-2 text-[9.5px] font-semibold tracking-[0.13em] uppercase text-tinta-3">Transcrição em tempo real</span>
        <p className="mt-0 mb-2 text-[10.5px] leading-[1.45] text-tinta-3">
          O falante é identificado pela faixa da chamada ou inferido pelo texto. Quando não houver sinal suficiente, o trecho fica sem atribuição.
        </p>
        <div className="min-h-[180px] max-h-[42vh] overflow-y-auto bg-papel-2 border border-borda px-3 py-2 text-[12.5px] leading-[1.6] font-ui">
          {transcricao.length === 0 && !parcial && <p className="m-0 italic text-tinta-3">A fala reconhecida aparecerá aqui.</p>}
          {transcricao.map((trecho) => (
            <p key={`${trecho.quando}-${trecho.texto}`} className="my-2">
              <time className="mr-2 text-[10px] font-codigo text-tinta-3">{new Date(trecho.quando).toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit", second: "2-digit" })}</time>
              <strong className={`mr-2 text-[10px] uppercase tracking-[0.06em] ${trecho.quem === "Entrevistado" ? "text-ok" : trecho.quem === "Entrevistador" ? "text-acao" : "text-tinta-3"}`}>
                {trecho.quem}
              </strong>
              {trecho.texto}
            </p>
          ))}
          {parcial && <p className="my-2 text-tinta-3"><span className="mr-2 text-[10px] uppercase">ouvindo</span>{parcial}</p>}
        </div>
      </section>

      {/* Este não é sobre o microfone: é áudio que o navegador não conseguiu
        * entregar. Some fala ANTES do reconhecimento, então nenhum ajuste no
        * modelo recupera — e sem este aviso o buraco no texto não tem causa
        * visível. */}
      {atrasado && (
        <div className="mb-3 border-[1.5px] border-critico px-[11px] py-[10px] font-normal text-[12px] leading-[1.55] font-ui [&_strong]:text-critico">
          <strong>Está chegando menos áudio que o tempo corrido.</strong>{" "}
          {Math.round((chegada ?? 0) * 100)}% do relógio virou áudio transcrito. Parte
          disso pode ser pausa entre perguntas, que é normal; o resto é áudio que o
          navegador não deu conta de entregar. Se o número ficar baixo com a conversa
          correndo solta, feche programas pesados (abas demais, Docker, streaming) e
          não deixe esta aba em segundo plano.
        </div>
      )}

      {erro && (
        <p className="mb-3 mt-0 border-l-[3px] border-atencao px-[10px] py-2 bg-papel-2 font-normal text-[11.5px] leading-[1.5] font-ui text-tinta-3">
          {erro}
        </p>
      )}

      {/* 1. O que aprofundar — depois da pergunta da vez, nunca no lugar dela. */}
      <div className="hidden">
      {lembretes.length > 0 && (
        <section className="mb-[18px] last:mb-0">
          <span className="block mb-[7px] text-[9.5px] font-semibold leading-[1.4] font-ui tracking-[0.13em] uppercase text-tinta-3">
            aprofundar depois desta
          </span>
          <ul className="m-0 p-0 list-none">
            {lembretes.map((l) => (
              <li key={l.pergunte} className="mb-[7px] border-l-2 border-tinta pl-[9px]">
                <button
                  type="button"
                  className="border-none bg-transparent p-0 text-left text-tinta font-normal text-[13px] leading-[1.5] font-titulo cursor-pointer disabled:cursor-default enabled:hover:underline enabled:hover:underline-offset-[3px]"
                  onClick={() => l.pergunta_id && onIrPara(l.pergunta_id)}
                  disabled={!l.pergunta_id}
                  title={l.pergunta_id ? "Ir para o campo" : ""}
                >
                  {l.pergunte}
                </button>
              </li>
            ))}
          </ul>
        </section>
      )}

      {/* A contagem, sem botão. Um botão aqui é um convite a parar a entrevista
        * no meio — que é exatamente o que o escritório mandou tirar. */}
      {aConferir > 0 && (
        <p className="mb-3 mt-0 font-normal text-[11px] leading-[1.5] font-ui text-tinta-3">
          {aConferir} {aConferir === 1 ? "resposta ouvida fica" : "respostas ouvidas ficam"} para
          conferir no fim do roteiro.
        </p>
      )}

      {/* 2. O que o roteiro ainda pede. */}
      <section className="mb-[18px] last:mb-0">
        <span className="block mb-[7px] text-[9.5px] font-semibold leading-[1.4] font-ui tracking-[0.13em] uppercase text-tinta-3">
          falta perguntar ({faltando.length})
          {obrigatoriasFaltando.length > 0 && (
            <em className="ml-[6px] italic font-normal text-[9.5px] leading-none font-ui text-critico normal-case tracking-normal">
              {obrigatoriasFaltando.length} obrigatória(s)
            </em>
          )}
        </span>
        {faltando.length === 0 ? (
          <p className="m-0 font-normal text-[11.5px] leading-[1.5] font-ui text-ok">
            Nada pendente neste ponto do roteiro.
          </p>
        ) : (
          <ul className="m-0 p-0 list-none">
            {faltando.slice(0, 8).map((f) => (
              <li key={f.pergunta_id} className="mb-1">
                <button
                  type="button"
                  className={
                    f.obrigatoria
                      ? "border-none bg-transparent p-0 text-left font-normal text-[12px] leading-[1.45] font-ui text-tinta cursor-pointer hover:underline hover:underline-offset-[3px]"
                      : "border-none bg-transparent p-0 text-left font-normal text-[12px] leading-[1.45] font-ui text-tinta-3 cursor-pointer hover:underline hover:underline-offset-[3px]"
                  }
                  onClick={() => onIrPara(f.pergunta_id)}
                >
                  {f.obrigatoria && (
                    <span className="text-critico" aria-hidden>
                      *{" "}
                    </span>
                  )}
                  {f.pergunta}
                </button>
              </li>
            ))}
            {faltando.length > 8 && (
              <li className="italic font-normal text-[11px] leading-[1.4] font-ui text-tinta-3 pt-[2px]">
                e mais {faltando.length - 8}…
              </li>
            )}
          </ul>
        )}
      </section>

      {/* 3. O que já entrou, para conferir sem sair da conversa. */}
      {preenchidas.length > 0 && (
        <section className="mb-[18px] last:mb-0">
          <span className="block mb-[7px] text-[9.5px] font-semibold leading-[1.4] font-ui tracking-[0.13em] uppercase text-tinta-3">
            já entrou ({preenchidas.length})
          </span>
          <ul className="m-0 p-0 list-none">
            {preenchidas.map((p) => (
              <li key={p.pergunta_id} className="border-b border-borda py-[6px] last:border-b-0">
                <button
                  type="button"
                  className="group block w-full border-none bg-transparent p-0 text-left cursor-pointer"
                  onClick={() => onIrPara(p.pergunta_id)}
                >
                  <span className="block font-normal text-[10.5px] leading-[1.4] font-ui text-tinta-3">
                    {p.pergunta}
                  </span>
                  <span className="block font-normal text-[12px] leading-[1.45] font-ui text-tinta group-hover:underline group-hover:underline-offset-[3px]">
                    {p.valor}
                  </span>
                </button>
              </li>
            ))}
          </ul>
          <p className="mt-[9px] mb-0 pt-2 border-t border-borda font-normal text-[10.5px] leading-[1.5] font-ui text-tinta-3">
            Preenchido a partir da fala. Confira antes de gerar o contrato — a
            transcrição erra palavra.
          </p>
        </section>
      )}
      </div>
    </aside>
  );
}
