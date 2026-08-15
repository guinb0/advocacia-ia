"use client";

import { useRef } from "react";

import estilos from "./EntrevistaComChamada.module.css";
import PainelChamada from "./PainelChamada";
import Roteiro from "./Roteiro";
import type { ManipuladorRoteiro } from "./Roteiro";

/* A tela da entrevista: roteiro à esquerda, chamada à direita.
 *
 * As duas colunas não são decoração — elas existem porque a entrevista é feita
 * com as duas coisas ao mesmo tempo, e alternar de aba entre a pergunta e a
 * chamada faria o entrevistador perder o fio da conversa.
 *
 * A ligação entre elas é uma só, e é a que importa: a faixa remota da chamada
 * (a voz do entrevistado, isolada) vira a fonte da transcrição do roteiro. */

interface Props {
  /** O `entrevistaId` vai junto: é por ele que se baixa o áudio depois que esta
   *  tela fecha (ver `app/gravacao.py`). */
  onConcluir: (
    respostas: Record<string, string | string[]>,
    relato: string,
    entrevistaId: string,
  ) => void;
  /** Sai da entrevista sem concluir — o que foi respondido se perde. */
  onFechar: () => void;
}

export default function EntrevistaComChamada({ onConcluir, onFechar }: Props) {
  const roteiro = useRef<ManipuladorRoteiro>(null);

  return (
    <div className={estilos.tela}>
      <div className={estilos.cabecalho}>
        <span className={estilos.marca}>ENTREVISTA EM ANDAMENTO</span>
        <button
          type="button"
          className={estilos.fechar}
          onClick={() => {
            /* Fechar já se sabe que perde as respostas — o rótulo diz. O que
             * ele não diz é que leva junto o vídeo, que não está guardado em
             * lugar nenhum além desta aba. */
            if (
              roteiro.current?.temVideoPendente() &&
              !window.confirm(
                "O vídeo gravado ainda não foi baixado e será perdido ao fechar. " +
                  "Fechar mesmo assim?",
              )
            ) {
              return;
            }
            onFechar();
          }}
        >
          Fechar sem concluir
        </button>
      </div>

      <div className={estilos.colunas}>
        <div className={estilos.esquerda}>
          <Roteiro ref={roteiro} onConcluir={onConcluir} />
        </div>

        <div className={estilos.direita}>
          {/* A faixa da chamada alimenta a transcrição: quando o cliente entra,
           * a voz DELE — isolada da do entrevistador — vira a fonte do roteiro,
           * no lugar do microfone da máquina.
           *
           * Já esteve desligada por um tempo: a faixa remota chegava muda e o
           * VAD do Whisper descartava a resposta inteira. A causa era o
           * AudioContext forçado a 16 kHz recebendo a faixa do WebRTC a 48 kHz —
           * corrigido reamostrando no worklet (ver `montar` em transcricao.ts e
           * o cabeçalho de `worklet-pcm.js`). */}
          <PainelChamada
            onFaixaRemota={(trilha) => void roteiro.current?.usarFaixaDaChamada(trilha)}
            onFimDaFaixa={() => roteiro.current?.aoPerderChamada()}
          />
        </div>
      </div>
    </div>
  );
}
