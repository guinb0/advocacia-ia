"use client";

import { useRef, useState } from "react";
import type { ReactNode } from "react";

import AudioDaEntrevista from "./AudioDaEntrevista";
import { Aviso } from "./Basicos";
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
  /** As respostas conforme elas mudam, sem esperar o fim.
   *
   * É o que permite o atendimento continuar NA MESMA TELA: as etapas seguintes
   * (avaliação, documentos, assinatura) ficam logo abaixo do roteiro, e leem o
   * que já foi respondido enquanto a entrevista ainda corre. */
  onRespostas?: (
    respostas: Record<string, string | string[]>,
    relato: string,
    entrevistaId: string,
  ) => void;
  /** O que vem DEPOIS do roteiro, na mesma rolagem.
   *
   * O escritório pediu "tudo numa paulada só": não há mais o corte de concluir
   * a entrevista para então aparecer outra tela. Rolou até o fim das perguntas,
   * o atendimento continua ali mesmo — com a chamada de pé e a gravação
   * correndo, que é o que o roteiro manda para a etapa da avaliação. */
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
  /* O encerramento tem duas etapas, e é de propósito.
   *
   * A gravação corre até o FIM — durante a avaliação, os documentos e o envio
   * dos primeiros arquivos, que é quando o cliente diz coisas que valem estar
   * no áudio. Fechá-la é o primeiro clique; sair é o segundo, depois de os
   * arquivos estarem à mão. Sair direto deixaria vídeo, áudio e transcrição
   * para trás, e o vídeo não existe em lugar nenhum além desta aba. */
  const [fechando, setFechando] = useState(false);
  const [encerrada, setEncerrada] = useState<string | null>(null);
  const [erroFecho, setErroFecho] = useState<string | null>(null);

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
          {/* Sem `onConcluir`: o roteiro não fecha mais o atendimento sozinho.
            * Ele só reporta o que foi respondido, e quem encerra é o botão lá
            * embaixo, depois das etapas seguintes. */}
          <Roteiro
            ref={roteiro}
            onRespostas={(respostas, relato, entrevistaId) => {
              ultimo.current = [respostas, relato, entrevistaId];
              onRespostas?.(respostas, relato, entrevistaId);
            }}
          />

          {/* O atendimento continua aqui embaixo, sem trocar de tela.
            *
            * Na mesma medida do roteiro (860px). Estes painéis foram desenhados
            * para o cartão estreito da tela de casos e não tinham limite de
            * largura própria — soltos aqui, esticavam até o fim da coluna e
            * terminavam num degrau visível em relação às perguntas acima. */}
          <div className={estilos.continuacao}>
            {depois}
          </div>

          {encerrada === null ? (
            <div className={estilos.encerrar}>
              <button
                type="button"
                className={estilos.concluir}
                disabled={fechando}
                onClick={() => {
                  /* Sem esta pergunta, sair descartaria em silêncio o nome e o
                   * CPF que a escuta ouviu — o contrato e a procuração
                   * nasceriam em branco justamente nos dois campos que
                   * identificam o cliente. */
                  const aConferir = roteiro.current?.sugestoesPendentes() ?? 0;
                  if (
                    aConferir > 0 &&
                    !window.confirm(
                      `${aConferir} resposta(s) que eu ouvi ainda não foram conferidas ` +
                        "(nome e/ou CPF) e serão descartadas. Encerrar mesmo assim?",
                    )
                  ) {
                    return;
                  }
                  setFechando(true);
                  setErroFecho(null);
                  void roteiro.current
                    ?.encerrarGravacao()
                    .then((id) => setEncerrada(id))
                    .catch((e: unknown) => {
                      // O áudio pode não fechar (serviço fora, rede). O
                      // atendimento não fica preso por isso: o fecho abre do
                      // mesmo jeito, com a transcrição e o vídeo, e o aviso
                      // diz o que faltou.
                      setEncerrada("");
                      setErroFecho(
                        e instanceof Error ? e.message : "A gravação não pôde ser fechada.",
                      );
                    })
                    .finally(() => setFechando(false));
                }}
              >
                {fechando ? "Fechando a gravação…" : "Encerrar o atendimento"}
              </button>
              <span className={estilos.encerrarNota}>
                Só depois da avaliação, dos documentos e do que o cliente conseguir
                enviar agora. A gravação corre até aqui.
              </span>
            </div>
          ) : (
            /* O fecho: a gravação parou e os três arquivos ficam à mão.
             *
             * Vídeo, áudio e transcrição bruta são coisas diferentes e servem a
             * perguntas diferentes — o vídeo prova quem estava na sala, o áudio
             * é a conversa, e a transcrição é o que dá para ler e buscar seis
             * meses depois sem ouvir quarenta minutos. */
            <div className={estilos.fecho}>
              <span className={estilos.fechoRotulo}>ATENDIMENTO ENCERRADO</span>

              {erroFecho && (
                <Aviso tom="atencao" titulo="A gravação não fechou">
                  {erroFecho} O vídeo e a transcrição abaixo continuam valendo.
                </Aviso>
              )}

              <p className={estilos.encerrarNota}>
                A gravação parou agora. Baixe o que precisa antes de sair — o{" "}
                <strong>vídeo existe só nesta aba</strong> e some ao fechar a tela.
              </p>

              {encerrada && <AudioDaEntrevista entrevistaId={encerrada} />}

              <div className={estilos.arquivos}>
                <button
                  type="button"
                  className={estilos.concluir}
                  onClick={() => {
                    const trechos = roteiro.current?.transcricaoBruta() ?? [];
                    const cabecalho = [
                      "TRANSCRIÇÃO BRUTA DA ENTREVISTA",
                      `Gerada em ${new Date().toLocaleString("pt-BR")}`,
                      `${trechos.length} trecho(s) reconhecido(s)`,
                      "",
                      "Esta é a fala como saiu da transcrição automática, na ordem, sem",
                      "passar pelo roteiro. O que está nos campos da entrevista é o que",
                      "o sistema interpretou; isto é o que foi dito.",
                      "",
                      "-".repeat(62),
                      "",
                    ].join("\n");
                    baixarTexto(
                      `Transcrição bruta ${new Date().toLocaleDateString("pt-BR")}.txt`,
                      cabecalho +
                        trechos.map((t) => `[${relogio(t.quando)}] ${t.texto}`).join("\n"),
                    );
                  }}
                >
                  Baixar a transcrição bruta (.txt)
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
                Sair do atendimento
              </button>
            </div>
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
