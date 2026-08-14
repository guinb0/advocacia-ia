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
 * A ordem das quatro seções não é arbitrária — é a ordem em que o entrevistador
 * precisa delas enquanto o cliente fala:
 *
 *   1. PERGUNTE      o que dizer agora. Fica no topo porque é acionável.
 *   2. CONFIRME      nome e CPF ouvidos, esperando um clique.
 *   3. FALTA         o que o roteiro ainda pede.
 *   4. JÁ ENTROU     o que a conversa preencheu, para conferir de relance.
 *
 * "Já entrou" fica por último de propósito: é a seção que dá confiança, não a
 * que exige ação. No começo da entrevista ela está vazia e ninguém sente falta;
 * no fim ela é longa e ninguém precisa mais dela. */

interface Props {
  preenchidas: CampoOuvido[];
  sugestoes: CampoOuvido[];
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
  erro: string | null;
  /** Aceitar uma sugestão de nome/CPF. */
  onAceitar: (perguntaId: string, valor: string) => void;
  onDescartar: (perguntaId: string) => void;
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

function situacao(
  captando: boolean,
  pausado: boolean,
  interpretando: boolean,
  ultimaFala: number | null,
  ultimoSom: number | null,
): { texto: string; classe: string; titulo: string; mudo?: boolean } {
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
  sugestoes,
  lembretes,
  faltando,
  interpretando,
  captando,
  pausado,
  ultimaFala,
  ultimoSom,
  erro,
  onAceitar,
  onDescartar,
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

  const estado = situacao(captando, pausado, interpretando, ultimaFala, ultimoSom);

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

      {erro && <p className={estilos.erro}>{erro}</p>}

      {/* 1. O que dizer agora. */}
      {lembretes.length > 0 && (
        <section className={estilos.secao}>
          <span className={estilos.tituloSecao}>pergunte agora</span>
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

      {/* 2. O que precisa de confirmação humana antes de virar dado. */}
      {sugestoes.length > 0 && (
        <section className={estilos.secao}>
          <span className={estilos.tituloSecao}>confirme o que eu ouvi</span>
          {sugestoes.map((s) => (
            <div key={s.pergunta_id} className={estilos.sugestao}>
              <span className={estilos.campoNome}>{s.pergunta}</span>
              <strong className={estilos.valorOuvido}>{s.valor}</strong>
              {s.trecho && <em className={estilos.citacao}>“{s.trecho}”</em>}
              <div className={estilos.acoes}>
                <button
                  type="button"
                  className={estilos.aceitar}
                  onClick={() => onAceitar(s.pergunta_id, s.valor)}
                >
                  Está certo
                </button>
                <button
                  type="button"
                  className={estilos.descartar}
                  onClick={() => onDescartar(s.pergunta_id)}
                >
                  Descartar
                </button>
              </div>
            </div>
          ))}
        </section>
      )}

      {/* 3. O que o roteiro ainda pede. */}
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

      {/* 4. O que já entrou, para conferir sem sair da conversa. */}
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
