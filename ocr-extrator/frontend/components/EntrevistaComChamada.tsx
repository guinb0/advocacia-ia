"use client";

import { useRef, useState } from "react";
import type { ReactNode } from "react";

import AudioDaEntrevista from "./AudioDaEntrevista";
import estilos from "./EntrevistaComChamada.module.css";
import PainelChamada from "./PainelChamada";
import Roteiro from "./Roteiro";
import type { FaseEntrevista, ManipuladorRoteiro } from "./Roteiro";

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
  /** Resultado processado e alterações feitas pelo entrevistador na revisão. */
  onRespostas?: (
    respostas: Record<string, string | string[]>,
    relato: string,
    entrevistaId: string,
  ) => void;
  /** Fluxo jurídico liberado somente depois do processamento. */
  depois?: ReactNode;
}

/** Baixa um texto como arquivo, sem passar pelo servidor. */
function baixarTexto(nome: string, conteudo: string): void {
  const url = URL.createObjectURL(new Blob([conteudo], { type: "text/plain;charset=utf-8" }));
  const link = document.createElement("a");
  link.href = url;
  link.download = nome;
  link.click();
  URL.revokeObjectURL(url);
}

/** "14:07:32" — a hora de parede, que é como se procura um trecho no áudio. */
function relogio(quando: number): string {
  return new Date(quando).toLocaleTimeString("pt-BR");
}

export default function EntrevistaComChamada({
  onConcluir,
  onFechar,
  onRespostas,
  depois,
}: Props) {
  const roteiro = useRef<ManipuladorRoteiro>(null);
  /* O último estado reportado pelo roteiro.
   *
   * O botão de encerrar deixou de morar dentro do `Roteiro`: com as etapas
   * seguintes na mesma rolagem, ele caía NO MEIO do atendimento — "concluir
   * entrevista" acima da avaliação e do contrato, que ainda estavam por fazer.
   * Agora ele é o último elemento da tela, e usa o que o roteiro já reportou. */
  const ultimo = useRef<[Record<string, string | string[]>, string, string]>([{}, "", ""]);
  const [fase, setFase] = useState<FaseEntrevista>("preparacao");

  return (
    <div className={estilos.tela}>
      <div className={estilos.cabecalho}>
        <span className={estilos.marca}>
          {fase === "preparacao" && "PREPARAÇÃO DA ENTREVISTA"}
          {fase === "entrevista" && "ENTREVISTA EM ANDAMENTO"}
          {fase === "processando" && "ORGANIZANDO A ENTREVISTA"}
          {fase === "revisao" && "REVISÃO DOS RESULTADOS"}
        </span>
        <button
          type="button"
          className={estilos.fechar}
          disabled={fase === "processando"}
          onClick={() => {
            if (
              fase === "entrevista" &&
              !window.confirm(
                "A entrevista ainda está em andamento. Cancelar agora não gera o formulário de revisão. Cancelar mesmo assim?",
              )
            ) {
              return;
            }
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
          {fase === "preparacao" && "Fechar"}
          {fase === "entrevista" && "Cancelar entrevista"}
          {fase === "processando" && "Processando…"}
          {fase === "revisao" && "Fechar revisão"}
        </button>
      </div>

      <div className={estilos.colunas}>
        <div className={estilos.esquerda}>
          {/* Sem `onConcluir`: o roteiro não fecha mais o atendimento sozinho.
            * Ele só reporta o que foi respondido, e quem encerra é o botão lá
            * embaixo, depois das etapas seguintes. */}
          <Roteiro
            ref={roteiro}
            onFase={setFase}
            onRespostas={(respostas, relato, entrevistaId) => {
              ultimo.current = [respostas, relato, entrevistaId];
              onRespostas?.(respostas, relato, entrevistaId);
            }}
          />

          {fase === "revisao" && (
            <>
              <div className={estilos.continuacao}>{depois}</div>
            <div className={estilos.fecho}>
              <span className={estilos.fechoRotulo}>ARQUIVOS DA ENTREVISTA</span>

              <p className={estilos.encerrarNota}>
                A gravação foi encerrada. Baixe o que precisa antes de continuar — o{" "}
                <strong>vídeo existe só nesta aba</strong> e some ao fechar a tela.
              </p>

              {ultimo.current[2] && <AudioDaEntrevista entrevistaId={ultimo.current[2]} />}

              <div className={estilos.arquivos}>
                <button
                  type="button"
                  className={estilos.concluir}
                  onClick={() => {
                    const trechos = roteiro.current?.transcricaoBruta() ?? [];
                    const cabecalho = [
                      "TRANSCRIÇÃO COMPLETA DA ENTREVISTA",
                      `Gerada em ${new Date().toLocaleString("pt-BR")}`,
                      `${trechos.length} trecho(s) reconhecido(s)`,
                      "",
                      "Registro original da conversa, na ordem em que foi transcrita.",
                      "",
                      "-".repeat(62),
                      "",
                    ].join("\n");
                    baixarTexto(
                      `Entrevista ${new Date().toLocaleDateString("pt-BR")}.txt`,
                      cabecalho +
                        trechos.map((t) => `[${relogio(t.quando)}] ${t.texto}`).join("\n"),
                    );
                  }}
                >
                  Baixar transcrição completa (.txt)
                </button>
                <span className={estilos.encerrarNota}>
                  O vídeo fica no bloco <strong>VÍDEO</strong>, no alto desta tela.
                </span>
              </div>

              <button
                type="button"
                className={estilos.concluir}
                onClick={() => {
                  if (
                    roteiro.current?.temVideoPendente() &&
                    !window.confirm(
                      "O vídeo gravado ainda não foi baixado e será perdido ao sair. " +
                        "Sair mesmo assim?",
                    )
                  ) {
                    return;
                  }
                  onConcluir(...ultimo.current);
                }}
              >
                Continuar fluxo jurídico
              </button>
            </div>
            </>
          )}
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
