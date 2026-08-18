"use client";

import { useEffect, useState } from "react";

import type { CampoOuvido, Lembrete, PerguntaPendente } from "@/lib/types";
import estilos from "./PainelEscuta.module.css";

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
/** Silêncio absoluto por mais que isto, com o microfone aberto, é defeito. */
const SEGUNDOS_SEM_SOM = 12;

/* Microfone que capta, mas fraco demais.
 *
 * É o caso que "microfone sem som" NÃO pega: há som, então nada acusa, mas o
 * reconhecimento sai truncado e parece o modelo errando.
 *
 * Três pontos medidos nesta casa, na mediana dos blocos com som:
 *
 *     0,023  microfone ruim   — corta frase, troca palavra
 *     0,031  microfone atual  — sofrível, mas o entrevistador o considera normal
 *     0,061  microfone bom    — reconhece limpo
 *
 * A primeira versão usou 0,035 e gritava em cima dos 0,031 do uso normal. Aviso
 * que dispara no caso comum é aviso que se aprende a ignorar, e aí ele não serve
 * para o dia em que o problema é real. 0,028 fica abaixo do uso normal e acima
 * do ruim — margem estreita, porque os dois casos são mesmo próximos.
 *
 * Isto é AVISO, não filtro. Um limiar que erra aqui custa um alerta a mais; um
 * limiar que FILTRA e erra apaga a fala do cliente — foi exatamente o que já
 * aconteceu uma vez, e é a razão de este número nunca voltar a cortar áudio. */
const NIVEL_BAIXO = 0.028;

/** Abaixo disto o áudio chega mais devagar que a fala: some conteúdo no
 *  caminho, ANTES do reconhecimento, e o buraco no texto não tem como ser
 *  explicado por quem só olha a transcrição. */
const CHEGADA_MINIMA = 0.9;

function situacao(
  captando: boolean,
  pausado: boolean,
  interpretando: boolean,
  ultimaFala: number | null,
  ultimoSom: number | null,
  nivelTipico: number | null,
): { texto: string; classe: string; titulo: string; mudo?: boolean; baixo?: boolean } {
  /* O caso que motivou tudo isto vem PRIMEIRO, antes de qualquer outro estado.
   *
   * Microfone mudo e conversa em silêncio produzem a mesma tela — nenhuma das
   * duas gera texto. A diferença é que uma delas está perdendo a entrevista, e
   * quem conduz não tem como saber olhando a transcrição. */
  if (captando && !pausado) {
    const semSom = ultimoSom === null || Date.now() - ultimoSom > SEGUNDOS_SEM_SOM * 1000;
    if (semSom) {
      return {
        texto: "microfone sem som",
        classe: estilos.mudo,
        mudo: true,
        titulo:
          "O microfone está aberto mas não capta nada há mais de " +
          `${SEGUNDOS_SEM_SOM}s. Confira o dispositivo, o mudo do sistema e se ` +
          "outro programa tomou o microfone.",
      };
    }

    /* Depois do mudo e ANTES de qualquer estado normal: enquanto o microfone
     * estiver fraco, esta é a informação que muda o que o entrevistador faz. */
    if (nivelTipico !== null && nivelTipico < NIVEL_BAIXO) {
      return {
        texto: "microfone muito baixo",
        classe: estilos.mudo,
        baixo: true,
        titulo:
          "Há som, mas fraco demais para reconhecer com segurança. Aumente o " +
          "nível do microfone no Windows ou aproxime-o de quem fala.",
      };
    }
  }

  if (pausado) {
    return {
      texto: "pausado",
      classe: estilos.pausado,
      titulo: "O que for dito agora não entra na entrevista.",
    };
  }
  if (!captando) {
    return {
      texto: "microfone fechado",
      classe: estilos.ocioso,
      titulo: "Clique em “Começar a entrevista” para abrir o microfone.",
    };
  }
  if (interpretando) {
    return {
      texto: "interpretando…",
      classe: estilos.ouvindo,
      titulo: "Um trecho da conversa está sendo lido contra o roteiro.",
    };
  }
  if (ultimaFala === null) {
    return {
      texto: "ouvindo — nada reconhecido ainda",
      classe: estilos.ocioso,
      titulo:
        "O microfone está aberto. O texto só entra quando um trecho de fala " +
        "para de mudar, o que leva alguns segundos após a pausa.",
    };
  }
  const segundos = Math.round((Date.now() - ultimaFala) / 1000);
  return {
    texto: segundos < 20 ? "ouvindo" : `ouvindo — nada há ${segundos}s`,
    classe: segundos < 45 ? estilos.ouvindo : estilos.silencio,
    titulo:
      segundos < 45
        ? "Última fala reconhecida há pouco."
        : "Faz tempo que nada é reconhecido. Se alguém está falando, confira o microfone.",
  };
}

export default function PainelEscuta({
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
    <aside className={estilos.painel}>
      <div className={estilos.topo}>
        <span className={estilos.rotulo}>A ENTREVISTA ATÉ AQUI</span>
        <span className={estado.classe} title={estado.titulo}>
          {estado.texto}
        </span>
      </div>

      {/* Não basta a cor mudar no cantinho: quem está conduzindo a entrevista
        * está olhando o cliente, não o painel. Perder a conversa inteira é caro
        * demais para caber num rótulo de dez pixels. */}
      {estado.mudo && (
        <div className={estilos.alertaMudo}>
          <strong>Nada está sendo captado.</strong> O microfone está aberto, mas não
          chega som há mais de {SEGUNDOS_SEM_SOM} segundos. Confira se ele está mudo,
          se é o dispositivo certo e se outro programa o tomou — nada do que for dito
          agora será transcrito.
        </div>
      )}

      {/* Mesmo motivo do alerta de mudo: quem conduz está olhando o cliente, e
        * o custo de descobrir isto só na revisão é a entrevista inteira. */}
      {estado.baixo && (
        <div className={estilos.alertaMudo}>
          <strong>O microfone está muito baixo.</strong> Chega som, mas fraco demais
          para reconhecer com segurança — o texto vai sair truncado e com palavras
          trocadas. Aumente o nível do microfone no Windows (Configurações → Som →
          Entrada) ou aproxime-o de quem está falando.
        </div>
      )}

      {/* Este não é sobre o microfone: é áudio que o navegador não conseguiu
        * entregar. Some fala ANTES do reconhecimento, então nenhum ajuste no
        * modelo recupera — e sem este aviso o buraco no texto não tem causa
        * visível. */}
      {atrasado && (
        <div className={estilos.alertaMudo}>
          <strong>Está chegando menos áudio que o tempo corrido.</strong>{" "}
          {Math.round((chegada ?? 0) * 100)}% do relógio virou áudio transcrito. Parte
          disso pode ser pausa entre perguntas, que é normal; o resto é áudio que o
          navegador não deu conta de entregar. Se o número ficar baixo com a conversa
          correndo solta, feche programas pesados (abas demais, Docker, streaming) e
          não deixe esta aba em segundo plano.
        </div>
      )}

      {erro && <p className={estilos.erro}>{erro}</p>}

      {/* 1. O que aprofundar — depois da pergunta da vez, nunca no lugar dela. */}
      {lembretes.length > 0 && (
        <section className={estilos.secao}>
          <span className={estilos.tituloSecao}>aprofundar depois desta</span>
          <ul className={estilos.perguntas}>
            {lembretes.map((l) => (
              <li key={l.pergunte}>
                <button
                  type="button"
                  className={estilos.linkPergunta}
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
        <p className={estilos.aConferir}>
          {aConferir} {aConferir === 1 ? "resposta ouvida fica" : "respostas ouvidas ficam"} para
          conferir no fim do roteiro.
        </p>
      )}

      {/* 2. O que o roteiro ainda pede. */}
      <section className={estilos.secao}>
        <span className={estilos.tituloSecao}>
          falta perguntar ({faltando.length})
          {obrigatoriasFaltando.length > 0 && (
            <em className={estilos.obrigatorias}>
              {obrigatoriasFaltando.length} obrigatória(s)
            </em>
          )}
        </span>
        {faltando.length === 0 ? (
          <p className={estilos.vazio}>Nada pendente neste ponto do roteiro.</p>
        ) : (
          <ul className={estilos.pendentes}>
            {faltando.slice(0, 8).map((f) => (
              <li key={f.pergunta_id}>
                <button
                  type="button"
                  className={f.obrigatoria ? estilos.pendenteObrig : estilos.pendente}
                  onClick={() => onIrPara(f.pergunta_id)}
                >
                  {f.pergunta}
                </button>
              </li>
            ))}
            {faltando.length > 8 && (
              <li className={estilos.resto}>e mais {faltando.length - 8}…</li>
            )}
          </ul>
        )}
      </section>

      {/* 3. O que já entrou, para conferir sem sair da conversa. */}
      {preenchidas.length > 0 && (
        <section className={estilos.secao}>
          <span className={estilos.tituloSecao}>já entrou ({preenchidas.length})</span>
          <ul className={estilos.entraram}>
            {preenchidas.map((p) => (
              <li key={p.pergunta_id}>
                <button
                  type="button"
                  className={estilos.linkCampo}
                  onClick={() => onIrPara(p.pergunta_id)}
                >
                  <span className={estilos.campoNome}>{p.pergunta}</span>
                  <span className={estilos.valorEntrou}>{p.valor}</span>
                </button>
              </li>
            ))}
          </ul>
          <p className={estilos.aviso}>
            Preenchido a partir da fala. Confira antes de gerar o contrato — a
            transcrição erra palavra.
          </p>
        </section>
      )}
    </aside>
  );
}
