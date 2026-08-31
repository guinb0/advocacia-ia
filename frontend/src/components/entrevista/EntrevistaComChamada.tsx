"use client";

import { useRef, useState } from "react";
import type { ReactNode } from "react";

import AudioDaEntrevista from "@/components/entrevista/AudioDaEntrevista";
import { Aviso } from "@/components/ui/Basicos";
import PainelChamada from "@/components/chamada/PainelChamada";
import PainelEscuta from "@/components/entrevista/PainelEscuta";
import Roteiro from "@/components/entrevista/Roteiro";
import type { EstadoEscuta, ManipuladorRoteiro } from "@/components/entrevista/Roteiro";
import { lerEntrevista, usarPreAnalise } from "@/lib/preAnalise";
import type { LeituraDaEntrevista } from "@/lib/preAnalise";
import { montarTranscricaoBruta, type TrechoTranscrito } from "@/lib/transcricao";

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
    transcricao: TrechoTranscrito[],
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
    transcricao: TrechoTranscrito[],
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

const CONCLUIR =
  "border-[1.5px] border-acao bg-acao text-papel text-[11px] font-semibold leading-none font-ui " +
  "tracking-[0.1em] uppercase px-4 py-3 cursor-pointer enabled:hover:bg-acao-forte enabled:hover:border-acao-forte " +
  "disabled:opacity-100 disabled:bg-papel-3 disabled:text-tinta-3 disabled:border-borda-forte disabled:cursor-default";
const ENCERRAR_NOTA = "max-w-[46ch] italic font-normal text-[12px] leading-[1.5] font-titulo text-tinta-3";

/* A leitura mostrada na tela, e se ela já cobre a conversa inteira.
 *
 * `provisorio` é a pré-análise adiantada durante a entrevista (ver
 * `lib/preAnalise.ts`): ela aparece no ato do clique para a entrevistadora ter
 * o que ler, e é trocada pela definitiva assim que o fim da conversa é lido. */
type ResultadoFinal = LeituraDaEntrevista & { provisorio: boolean };

function PainelFinal({ resultado, onVoltar, onIrPara, podeComplementar = true }: { resultado: ResultadoFinal; onVoltar: () => void; onIrPara: (id: string) => void; podeComplementar?: boolean }) {
  const { processamento, triagem, recomendacao, avisos, provisorio } = resultado;
  const perguntas = Array.from(new Set([
    ...(processamento.analise?.perguntas_criticas ?? []),
    ...(recomendacao?.analise_comparativa?.perguntas_criticas ?? []),
  ])).slice(0, 8);
  const provas = recomendacao?.analise_comparativa?.provas_prioritarias ?? [];
  const tipo = triagem?.sugestoes[0];
  return (
    <section className="w-full border-l-4 border-tinta bg-papel-2 px-4 py-[14px]" aria-live="polite">
      <strong className="block text-[14px] text-tinta">Revisão da entrevista — o que fazer agora</strong>
      <p className="mt-1 text-xs leading-[1.55] text-tinta-3">
        Leia as sugestões abaixo e faça ao cliente as perguntas que faltarem. A chamada e a gravação continuam ativas.
      </p>
      {/* Dizer que é preliminar não é detalhe: o fim da conversa é onde ficam os
        * valores e o motivo da saída, e uma revisão que parece completa sem eles
        * faz encerrar a entrevista cedo demais. */}
      {provisorio && (
        <p className="mt-2 mb-0 border-l-2 border-atencao pl-[9px] text-[11.5px] leading-[1.5] text-atencao">
          Leitura preliminar, feita durante a entrevista. O trecho final da conversa
          está sendo lido agora e esta revisão será atualizada em instantes.
        </p>
      )}
      {podeComplementar && <button type="button" className={`${CONCLUIR} mt-3`} onClick={onVoltar}>
          Voltar e complementar a entrevista
        </button>}
      <div className="grid grid-cols-2 max-[700px]:grid-cols-1 gap-3 mt-3">
        <div className="border border-borda bg-papel p-3">
          <strong className="text-xs">Tipo provável do caso</strong>
          <p className="my-1 text-sm">{tipo?.nome ?? "Não foi possível classificar com segurança"}</p>
          {triagem && <small className="text-tinta-3">{triagem.motivo}</small>}
        </div>
        <div className="border border-borda bg-papel p-3">
          <strong className="text-xs">Encaminhamento sugerido</strong>
          <p className="my-1 text-sm">
            {recomendacao?.recomendado === "sim" ? "Levar para análise do advogado" :
              recomendacao?.recomendado === "com_ressalva" ? "Levar com ressalvas e completar os dados" :
                recomendacao?.recomendado === "atencao" ? "Não abrir sem revisão do advogado" :
                  "Sem base suficiente para recomendar"}
          </p>
          {recomendacao && <small className="text-tinta-3">{recomendacao.motivo}</small>}
        </div>
      </div>
      {processamento.faltando.length > 0 && (
        <details open className="mt-3"><summary className="cursor-pointer text-xs font-bold">O que ainda não foi perguntado ({processamento.faltando.length})</summary>
          <ul className="mt-2 pl-5 text-xs leading-[1.6]">{processamento.faltando.slice(0, 12).map((p) => <li key={p.pergunta_id}><strong>Pergunte:</strong> “{p.pergunta}”{p.obrigatoria ? " — necessário antes de encerrar" : ""} {podeComplementar && <button type="button" className="ml-2 underline text-acao" onClick={() => onIrPara(p.pergunta_id)}>ir ao campo</button>}</li>)}</ul>
        </details>
      )}
      {processamento.incertas.length > 0 && (
        <details open className="mt-3"><summary className="cursor-pointer text-xs font-bold">O que precisa ser confirmado ({processamento.incertas.length})</summary>
          <ul className="mt-2 pl-5 text-xs leading-[1.6]">{processamento.incertas.slice(0, 10).map((p) => <li key={p.pergunta_id}><strong>Confirme com o cliente:</strong> {p.motivo} {podeComplementar && <button type="button" className="ml-2 underline text-acao" onClick={() => onIrPara(p.pergunta_id)}>ir ao campo</button>}</li>)}</ul>
        </details>
      )}
      {perguntas.length > 0 && (
        <details open className="mt-3"><summary className="cursor-pointer text-xs font-bold">Perguntas jurídicas que podem fortalecer o caso</summary>
          <p className="mt-2 mb-1 text-xs text-tinta-3">Não precisa interpretar juridicamente: leia estas perguntas diretamente para o cliente.</p>
          <ol className="mt-2 pl-5 text-xs leading-[1.6]">{perguntas.map((p) => <li key={p}>“{p}”</li>)}</ol>
        </details>
      )}
      {provas.length > 0 && (
        <details className="mt-3"><summary className="cursor-pointer text-xs font-bold">Documentos e provas a pedir</summary>
          <ul className="mt-2 pl-5 text-xs leading-[1.6]">{provas.slice(0, 8).map((p) => <li key={p.prova}><strong>{p.prova}</strong> — {p.motivo}</li>)}</ul>
        </details>
      )}
      {avisos.map((aviso) => <p key={aviso} className="mt-3 text-xs text-atencao">{aviso}</p>)}
    </section>
  );
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
  const ultimo = useRef<
    [Record<string, string | string[]>, string, string, TrechoTranscrito[]]
  >([{}, "", "", []]);
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
  const [consolidando, setConsolidando] = useState(false);
  const [resultadoFinal, setResultadoFinal] = useState<ResultadoFinal | null>(null);
  /* O painel "A ENTREVISTA ATÉ AQUI" agora mora nesta coluna, embaixo da
   * chamada. O estado que o alimenta nasce no `Roteiro` e chega por `onEscuta`;
   * é `null` enquanto a escuta não abriu. */
  const [escuta, setEscuta] = useState<EstadoEscuta | null>(null);

  /** A transcrição bruta como ela está agora — a mesma que vai para a revisão. */
  const transcricaoAtual = () =>
    roteiro.current?.transcricaoBruta().map((t) => t.texto).join("\n") ?? "";

  /* A revisão adiantada, correndo no fundo enquanto a conversa acontece.
   *
   * Desligada durante a própria revisão e depois do encerramento: as duas
   * disputariam o threadpool do servidor, que é o mesmo que transcreve a fala
   * ao vivo. Nada dela aparece na tela até o clique. */
  const preAnalise = usarPreAnalise({
    lerTranscricao: transcricaoAtual,
    lerRespostas: () => ultimo.current[0],
    ativa: encerrada === null && !fechando,
  });

  const voltarAoRoteiro = () => {
    document.getElementById("roteiro-da-entrevista")?.scrollIntoView({ behavior: "smooth", block: "start" });
  };
  const irParaPergunta = (id: string) => roteiro.current?.irParaPergunta(id);

  return (
    <div className="fixed inset-0 z-40 bg-papel overflow-y-auto px-[22px] pt-[18px] pb-10 max-[1080px]:px-[14px] max-[1080px]:pt-[14px] max-[1080px]:pb-8">
      <div className="flex justify-between items-center gap-4 pb-3 mb-[18px] border-b-[3px] border-double border-borda-forte">
        <span className="text-[11px] font-semibold leading-none font-ui tracking-[0.14em] text-tinta-3">
          ENTREVISTA EM ANDAMENTO
        </span>
        <button
          type="button"
          className="border border-borda-forte bg-transparent text-tinta text-[10px] font-semibold leading-none font-ui tracking-[0.08em] uppercase px-3 py-[9px] cursor-pointer hover:bg-papel-2"
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

      <div className="grid grid-cols-[minmax(0,1fr)_460px] max-[1080px]:grid-cols-[minmax(0,1fr)] gap-6 items-start max-w-[1500px] mx-auto">
        <div className="min-w-0">
          {/* Sem `onConcluir`: o roteiro não fecha mais o atendimento sozinho.
            * Ele só reporta o que foi respondido, e quem encerra é o botão lá
            * embaixo, depois das etapas seguintes. */}
          <Roteiro
            ref={roteiro}
            onEscuta={setEscuta}
            onRespostas={(respostas, relato, entrevistaId) => {
              /* A transcrição BRUTA sobe junto, e é ela que vai para o caso.
               *
               * O `relato` é montado a partir das respostas: diz o que a escuta
               * conseguiu extrair. A auditoria da supervisão precisa do outro —
               * o que foi perguntado e respondido de verdade. Auditar o roteiro
               * preenchido mediria o acerto do reconhecimento de voz, não a
               * condução (ver o cabeçalho de `app/auditoria.py`). */
              const trechos = roteiro.current?.transcricaoBruta() ?? [];
              ultimo.current = [respostas, relato, entrevistaId, trechos];
              onRespostas?.(respostas, relato, entrevistaId, trechos);
            }}
          />

          {encerrada === null && (
            <div className="max-w-[860px] mt-4 mb-5 border-t-[3px] border-double border-borda-forte pt-4 flex items-center flex-wrap gap-3">
              <button
                type="button"
                className={CONCLUIR}
                disabled={fechando}
                onClick={() => document.getElementById("acao-revisar-entrevista")?.click()}
              >
                {fechando ? "Revisando a entrevista…" : resultadoFinal ? "Revisar novamente" : "Revisar entrevista"}
              </button>
              {resultadoFinal && (
                <button
                  type="button"
                  className={CONCLUIR}
                  disabled={fechando}
                  onClick={() => document.getElementById("acao-avancar-finalizacao")?.click()}
                >
                  Avançar para finalizar entrevista
                </button>
              )}
              <span className={ENCERRAR_NOTA}>
                Revise aqui sem sair da entrevista. Você pode voltar ao roteiro ou avançar para finalizar.
              </span>
              {resultadoFinal && (
                <div className="basis-full w-full">
                  <PainelFinal resultado={resultadoFinal} onVoltar={voltarAoRoteiro} onIrPara={irParaPergunta} />
                </div>
              )}
            </div>
          )}

          {/* O atendimento continua aqui embaixo, sem trocar de tela.
            *
            * Na mesma medida do roteiro (860px). Estes painéis foram desenhados
            * para o cartão estreito da tela de casos e não tinham limite de
            * largura própria — soltos aqui, esticavam até o fim da coluna e
            * terminavam num degrau visível em relação às perguntas acima. */}
          <div className="max-w-[860px]">{depois}</div>

          {encerrada === null ? (
            <div className="flex items-center flex-wrap gap-[14px] max-w-[860px] mt-7 mb-2 border-t-[3px] border-double border-borda-forte pt-[18px]">
              <button
                id="acao-revisar-entrevista"
                type="button"
                className={CONCLUIR}
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
                  void (async () => {
                    const transcricao = transcricaoAtual();
                    if (!transcricao.trim()) throw new Error("A conversa ainda não produziu transcrição. Confira o microfone ou preencha os campos manualmente.");

                    /* O que a pré-análise já leu vai para a tela AGORA.
                     *
                     * Ela não preenche o formulário: as respostas que carrega
                     * são as de alguns minutos atrás, e aplicá-las apagaria o
                     * que foi respondido desde então. Campo só a definitiva
                     * mexe, logo abaixo. */
                    const adiantada = preAnalise.obter();
                    const completa = adiantada !== null && adiantada.cobertura === transcricao.length;
                    if (adiantada) setResultadoFinal({ ...adiantada, provisorio: !completa });
                    if (completa) return;

                    setConsolidando(true);
                    const [respostasAtuais, relatoAtual, entrevistaId, trechos] = ultimo.current;
                    const leitura = await lerEntrevista(transcricao, respostasAtuais, (processamento) => {
                      // A revisão não pode viver só numa cópia externa: o roteiro
                      // que permanece na tela precisa exibir a consolidação.
                      roteiro.current?.atualizarRespostas(processamento.respostas);
                      ultimo.current = [processamento.respostas, relatoAtual, entrevistaId, trechos];
                      onRespostas?.(processamento.respostas, relatoAtual, entrevistaId, trechos);
                    });
                    setResultadoFinal({ ...leitura, provisorio: false });
                  })()
                    .catch((e: unknown) => setErroFecho(e instanceof Error ? e.message : "Não foi possível revisar a entrevista."))
                    .finally(() => { setFechando(false); setConsolidando(false); });
                }}
              >
                {fechando ? "Revisando a entrevista…" : resultadoFinal ? "Revisar novamente" : "Revisar entrevista"}
              </button>
              <span className={ENCERRAR_NOTA}>
                A chamada e a gravação continuam enquanto o sistema confere o que faltou e sugere perguntas.
              </span>
              {consolidando && <Aviso tom="neutro" titulo="Lendo o restante da conversa">A revisão já vem adiantada do que foi transcrito durante a entrevista; falta só o trecho final.</Aviso>}
              {erroFecho && <Aviso tom="atencao" titulo="A revisão não foi concluída">{erroFecho}</Aviso>}
              {resultadoFinal && (
                <button
                  id="acao-avancar-finalizacao"
                  type="button"
                  className={CONCLUIR}
                  disabled={fechando}
                  onClick={() => {
                    setFechando(true);
                    setErroFecho(null);
                    void roteiro.current?.encerrarGravacao()
                      .then((id) => setEncerrada(id))
                      .catch((e: unknown) => {
                        setEncerrada("");
                        setErroFecho(e instanceof Error ? e.message : "A gravação não pôde ser fechada.");
                      })
                      .finally(() => setFechando(false));
                  }}
                >
                  Avançar para finalizar entrevista
                </button>
              )}
            </div>
          ) : (
            /* O fecho: a gravação parou e os três arquivos ficam à mão.
             *
             * Vídeo, áudio e transcrição bruta são coisas diferentes e servem a
             * perguntas diferentes — o vídeo prova quem estava na sala, o áudio
             * é a conversa, e a transcrição é o que dá para ler e buscar seis
             * meses depois sem ouvir quarenta minutos. */
            <div className="flex items-start flex-col gap-[14px] max-w-[860px] mt-7 mb-2 border-t-[3px] border-double border-borda-forte pt-[18px]">
              <span className="text-[11px] font-semibold leading-none font-ui tracking-[0.14em] text-ok">
                ATENDIMENTO ENCERRADO
              </span>

              {erroFecho && (
                <Aviso tom="atencao" titulo="A gravação não fechou">
                  {erroFecho} O vídeo e a transcrição abaixo continuam valendo.
                </Aviso>
              )}

              <p className={ENCERRAR_NOTA}>
                A gravação parou agora. Baixe o que precisa antes de sair — o{" "}
                <strong>vídeo existe só nesta aba</strong> e some ao fechar a tela.
              </p>

              {consolidando && <Aviso tom="neutro" titulo="Conferindo a entrevista inteira">Organizando campos, tipo provável, lacunas e próximos passos…</Aviso>}
              {resultadoFinal && <PainelFinal resultado={resultadoFinal} onVoltar={voltarAoRoteiro} onIrPara={irParaPergunta} podeComplementar={false} />}

              {encerrada && <AudioDaEntrevista entrevistaId={encerrada} />}

              <div className="flex items-center flex-wrap gap-[14px]">
                <button
                  type="button"
                  className={CONCLUIR}
                  onClick={() => {
                    /* Mesmo texto que vai gravado no caso — de propósito. Ver
                     * `montarTranscricaoBruta`, em `lib/transcricao.ts`. */
                    baixarTexto(
                      `Transcrição bruta ${new Date().toLocaleDateString("pt-BR")}.txt`,
                      montarTranscricaoBruta(roteiro.current?.transcricaoBruta() ?? []),
                    );
                  }}
                >
                  Baixar a transcrição bruta (.txt)
                </button>
                <span className={ENCERRAR_NOTA}>
                  O vídeo fica no bloco <strong>VÍDEO</strong>, no alto desta tela.
                </span>
              </div>

              <button
                type="button"
                className={CONCLUIR}
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
                Finalizar entrevista
              </button>
            </div>
          )}
        </div>

        <div className="min-w-0 sticky top-[18px] self-start max-h-[calc(100vh-36px)] overflow-y-auto max-[1080px]:order-[-1] max-[1080px]:static max-[1080px]:max-h-none max-[1080px]:overflow-visible">
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

          {/* "A ENTREVISTA ATÉ AQUI" — a transcrição em tempo real, agora abaixo
            * da chamada e não mais ao lado do formulário. A coluna já rola e
            * gruda; o painel só precisa se empilhar. */}
          {escuta && <PainelEscuta {...escuta} />}
        </div>
      </div>
    </div>
  );
}
