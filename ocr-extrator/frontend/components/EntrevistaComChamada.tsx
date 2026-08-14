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
  onConcluir: (respostas: Record<string, string | string[]>, relato: string) => void;
  /** Sai da entrevista sem concluir — o que foi respondido se perde. */
  onFechar: () => void;
}

export default function EntrevistaComChamada({ onConcluir, onFechar }: Props) {
  const roteiro = useRef<ManipuladorRoteiro>(null);

  return (
    <div className={estilos.tela}>
      <div className={estilos.cabecalho}>
        <span className={estilos.marca}>ENTREVISTA EM ANDAMENTO</span>
        <button type="button" className={estilos.fechar} onClick={onFechar}>
          Fechar sem concluir
        </button>
      </div>

      <div className={estilos.colunas}>
        <div className={estilos.esquerda}>
          <Roteiro ref={roteiro} onConcluir={onConcluir} />
        </div>

        <div className={estilos.direita}>
          {/* A faixa da chamada NÃO alimenta mais a transcrição.
           *
           * Ela chegava, mas chegava muda: com o serviço de pé e recebendo
           * dados, o detector de voz descartava o áudio inteiro —
           *
           *     Processing audio with duration 00:04.608
           *     VAD filter removed 00:04.608 of audio
           *
           * Enquanto isso não for diagnosticado, quem transcreve é o microfone
           * desta máquina (o botão do topo do roteiro). Religar é trocar este
           * no-op de volta por `roteiro.current?.usarFaixaDaChamada(trilha)` —
           * o resto da fiação continua no lugar. */}
          <PainelChamada
            onFaixaRemota={() => {}}
            onFimDaFaixa={() => roteiro.current?.aoPerderChamada()}
          />
        </div>
      </div>
    </div>
  );
}
