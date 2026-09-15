"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";

import { Aviso } from "@/components/ui/Basicos";
import { BotaoProcesso } from "@/components/ui/BotaoProcesso";
import PainelChamada from "@/components/chamada/PainelChamada";
import PainelEscuta from "@/components/entrevista/PainelEscuta";
import Roteiro from "@/components/entrevista/Roteiro";
import type { EstadoEscuta, ManipuladorRoteiro } from "@/components/entrevista/Roteiro";
import { lerEntrevista, usarPreAnalise } from "@/lib/preAnalise";
import type { LeituraDaEntrevista } from "@/lib/preAnalise";
import { chaveDasRespostas } from "@/lib/roteiroContexto";
import type { ContextoRevisaoRoteiro } from "@/lib/types";
import {
  apagarCopiaTranscricao,
  lerCopiaTranscricao,
  montarTranscricaoBruta,
  urlDoAudio,
  type TrechoTranscrito,
} from "@/lib/transcricao";
import { baixarTexto as baixarArquivoDeTexto } from "@/lib/baixar";
import { enviarGravacaoDrive, guardarGravacaoNoBanco, statusDrive } from "@/lib/api";

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
  /** Publica o snapshot em uso para etapas que sobrevivem ao fechamento. */
  onRoteiroAtivo?: (roteiro: ContextoRevisaoRoteiro["roteiro"] | null) => void;
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
  // Argumentos na ordem inversa da do `lib/baixar` — as chamadas desta tela já
  // passam o nome primeiro, e trocá-las não melhoraria nada.
  baixarArquivoDeTexto(conteudo, nome);
}

const CONCLUIR =
  "border-[1.5px] border-acao bg-acao text-papel text-[11px] font-semibold leading-none font-ui " +
  "tracking-[0.1em] uppercase px-4 py-3 cursor-pointer enabled:hover:bg-acao-forte enabled:hover:border-acao-forte " +
  "disabled:bg-papel-3 disabled:text-tinta-desabilitada disabled:border-borda-forte disabled:cursor-not-allowed";
const ENCERRAR_NOTA = "max-w-[46ch] italic font-normal text-[12px] leading-[1.5] font-titulo text-tinta-3";

/* A leitura mostrada na tela, e se ela já cobre a conversa inteira.
 *
 * `provisorio` é a pré-análise adiantada durante a entrevista (ver
 * `lib/preAnalise.ts`): ela aparece no ato do clique para a entrevistadora ter
 * o que ler, e é trocada pela definitiva assim que o fim da conversa é lido. */
type ResultadoFinal = LeituraDaEntrevista & { provisorio: boolean };

function PainelFinal({ resultado, onVoltar, onIrPara, podeIrPara, podeComplementar = true }: { resultado: ResultadoFinal; onVoltar: () => void; onIrPara: (id: string) => void; podeIrPara: (id: string) => boolean; podeComplementar?: boolean }) {
  const {
    processamento, triagem, recomendacao, avisos, provisorio,
  } = resultado;
  const insights = processamento.insights_entrevista;
  const perguntas = Array.from(new Set([
    ...(insights?.perguntas_especificas ?? []),
    // O RAG cru pode recuperar processos de outro assunto. Só entram perguntas
    // da comparação que passou pelo corte de similaridade da recomendação.
    ...(recomendacao?.analise_comparativa?.perguntas_criticas ?? []),
  ])).filter((pergunta) => !perguntaDeDocumentacao(pergunta)).slice(0, 3);
  const pontosFortes = recomendacao?.analise_comparativa?.pontos_comuns ?? [];
  const pontosFracos = recomendacao?.analise_comparativa?.diferencas_decisivas ?? [];
  const amostra = recomendacao?.estatistica.desfechos_merito;
  const tipo = triagem?.sugestoes[0];
  return (
    <section className="w-full border-l-4 border-tinta bg-papel-2 px-4 py-[14px]" aria-live="polite">
      <strong className="block text-[14px] text-tinta">Revisão da entrevista — o que fazer agora</strong>
      <p className="mt-1 text-xs leading-[1.55] text-tinta-3">
        Só o que precisa ser confirmado com o cliente agora. A chamada e a gravação continuam ativas.
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
      {podeComplementar && (
        <BotaoProcesso variante="primario" className="mt-3" onClick={onVoltar}>
          Voltar e complementar a entrevista
        </BotaoProcesso>
      )}
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
        {amostra && <div className="col-span-2 max-[700px]:col-span-1 border border-borda bg-papel p-3">
          <strong className="text-xs">Amostra de casos semelhantes — não é chance de vitória</strong>
          <p className="my-1 text-sm">
            {amostra.favoraveis} de {amostra.processos} decisões de mérito ({amostra.percentual.toFixed(0)}%)
            foram favoráveis à parte autora.
          </p>
          <small className="text-tinta-3">
            É um retrato dos precedentes recuperados. Provas, fatos e enquadramento do caso ainda precisam da decisão do advogado.
          </small>
        </div>}
      </div>
      {insights && (
        <div className={`mt-3 border-l-[3px] px-3 py-[11px] text-xs leading-[1.6] ${
          insights.foco === "adequado" ? "border-ok bg-papel" : "border-atencao bg-papel-2"
        }`}>
          <strong className="block text-tinta">
            {insights.foco === "fora_do_assunto"
              ? "A conversa fugiu do assunto"
              : insights.foco === "parcial"
                ? "A conversa perdeu foco em alguns pontos"
                : "A conversa permaneceu focada"}
          </strong>
          {insights.diagnostico && <p className="my-1 text-tinta-2">{insights.diagnostico}</p>}
          {insights.desvios.length > 0 && (
            <ul className="mb-0 mt-2 pl-5 text-tinta-2">
              {insights.desvios.map((desvio) => <li key={desvio}>{desvio}</li>)}
            </ul>
          )}
        </div>
      )}
      {processamento.faltando.length > 0 && (
        <details open className="mt-3"><summary className="cursor-pointer text-xs font-bold">O que ainda não foi perguntado ({processamento.faltando.length})</summary>
          <ul className="mt-2 pl-5 text-xs leading-[1.6]">{processamento.faltando.slice(0, 12).map((p) => <li key={p.pergunta_id}><strong>Pergunte:</strong> “{p.pergunta}”{p.obrigatoria ? " — necessário antes de encerrar" : ""} {podeComplementar && podeIrPara(p.pergunta_id) && <button type="button" className="ml-2 underline text-acao" onClick={() => onIrPara(p.pergunta_id)}>ir ao campo</button>}</li>)}</ul>
        </details>
      )}
      {processamento.incertas.length > 0 && (
        <details open className="mt-3"><summary className="cursor-pointer text-xs font-bold">O que precisa ser confirmado ({processamento.incertas.length})</summary>
          <ul className="mt-2 pl-5 text-xs leading-[1.6]">{processamento.incertas.slice(0, 10).map((p) => <li key={p.pergunta_id}><strong>Confirme com o cliente:</strong> {p.motivo} {podeComplementar && podeIrPara(p.pergunta_id) && <button type="button" className="ml-2 underline text-acao" onClick={() => onIrPara(p.pergunta_id)}>ir ao campo</button>}</li>)}</ul>
        </details>
      )}
      {perguntas.length > 0 && (
        <details open className="mt-3"><summary className="cursor-pointer text-xs font-bold">Até 3 perguntas que importam agora</summary>
          <p className="mt-2 mb-1 text-xs text-tinta-3">Nascem de ambiguidades e fatos mencionados, sem repetir o roteiro ou pedir documentos.</p>
          <ol className="mt-2 pl-5 text-xs leading-[1.6]">{perguntas.map((p) => <li key={p}>“{p}”</li>)}</ol>
        </details>
      )}
      {pontosFortes.length > 0 && (
        <details className="mt-3"><summary className="cursor-pointer text-xs font-bold">Pontos fortes sustentados pela amostra</summary>
          <ul className="mt-2 pl-5 text-xs leading-[1.6]">{pontosFortes.slice(0, 6).map((p) => <li key={p.ponto}><strong>{p.ponto}</strong> — {p.impacto}</li>)}</ul>
        </details>
      )}
      {pontosFracos.length > 0 && (
        <details className="mt-3"><summary className="cursor-pointer text-xs font-bold">Pontos fracos ou que exigem confirmação</summary>
          <ul className="mt-2 pl-5 text-xs leading-[1.6]">{pontosFracos.slice(0, 6).map((p) => <li key={p.ponto}><strong>{p.ponto}</strong> — {p.por_que_importa}</li>)}</ul>
        </details>
      )}
      <p className="mt-3 mb-0 border-l-2 border-borda-forte pl-2 text-xs leading-[1.5] text-tinta-3">
        Documentos e provas serão organizados na etapa de documentação, depois de encerrar a entrevista.
      </p>
      {avisos.map((aviso) => <p key={aviso} className="mt-3 text-xs text-atencao">{aviso}</p>)}
    </section>
  );
}

function perguntaDeDocumentacao(texto: string): boolean {
  return /\b(documento|prova|laudo|exame|atestado|carteira|ctps|contracheque|holerite|cat|cnis|ppp)\b/i.test(texto);
}

export default function EntrevistaComChamada({
  onConcluir,
  onFechar,
  onRespostas,
  onRoteiroAtivo,
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
  const [revisadas, setRevisadas] = useState<Record<string, string | string[]> | null>(null);
  const [contextoRoteiro, setContextoRoteiro] = useState<ContextoRevisaoRoteiro | null>(null);
  const publicarRoteiroAtivo = useRef(onRoteiroAtivo);
  publicarRoteiroAtivo.current = onRoteiroAtivo;
  const chaveRoteiro = useRef("");
  const geracaoRevisao = useRef(0);
  const atualizarContextoRoteiro = useCallback((contexto: ContextoRevisaoRoteiro | null) => {
    const proximaChave = contexto?.chave ?? "";
    if (chaveRoteiro.current && chaveRoteiro.current !== proximaChave) {
      geracaoRevisao.current += 1;
      // Resultado e erro pertencem à versão anterior; não podem sobreviver à troca.
      setResultadoFinal(null);
      setRevisadas(null);
      setErroFecho(null);
      setConsolidando(false);
      setFechando(false);
    }
    chaveRoteiro.current = proximaChave;
    setContextoRoteiro(contexto);
    publicarRoteiroAtivo.current?.(contexto?.roteiro ?? null);
  }, []);
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
    contextoRoteiro,
    ativa: encerrada === null && !fechando,
  });

  const salvarTranscricao = (trechos: TrechoTranscrito[]) => {
    const agora = new Date();
    const d2 = (n: number) => String(n).padStart(2, "0");
    const nome =
      `Transcrição completa ${d2(agora.getDate())}-${d2(agora.getMonth() + 1)}-${agora.getFullYear()} ` +
      `${d2(agora.getHours())}h${d2(agora.getMinutes())}.txt`;
    const conteudo = montarTranscricaoBruta(trechos) || "Nenhuma fala foi transcrita neste atendimento.";
    baixarTexto(nome, conteudo);
    apagarCopiaTranscricao();
    void guardarGravacaoNoBanco(
      new Blob([conteudo], { type: "text/plain;charset=utf-8" }),
      nome,
      "transcricao",
      ultimo.current[2],
    ).catch(() => undefined);
    void statusDrive()
      .then((situacao) =>
        situacao.conectado
          ? enviarGravacaoDrive(new Blob([conteudo], { type: "text/plain;charset=utf-8" }), nome)
          : undefined,
      )
      .catch(() => undefined);
  };

  useEffect(() => {
    const copia = lerCopiaTranscricao();
    if (copia.length === 0) return;
    baixarTexto(
      `Transcrição recuperada de atendimento interrompido ${new Date(copia[0].quando).toLocaleString("pt-BR").replace(/[/:]/g, "-")}.txt`,
      montarTranscricaoBruta(copia),
    );
    apagarCopiaTranscricao();
  }, []);

  useEffect(() => {
    const avisar = (evento: BeforeUnloadEvent) => {
      if ((roteiro.current?.transcricaoBruta().length ?? 0) > 0) evento.preventDefault();
    };
    window.addEventListener("beforeunload", avisar);
    return () => window.removeEventListener("beforeunload", avisar);
  }, []);

  const aplicarRevisadas = () => {
    if (!revisadas) return;
    const [respostasAtuais, relato, entrevistaId, trechos] = ultimo.current;
    const combinadas = { ...respostasAtuais, ...revisadas };
    roteiro.current?.atualizarRespostas(revisadas);
    ultimo.current = [combinadas, relato, entrevistaId, trechos];
    onRespostas?.(combinadas, relato, entrevistaId, trechos);
    setRevisadas(null);
  };

  const voltarAoRoteiro = () => {
    document.getElementById("roteiro-da-entrevista")?.scrollIntoView({ behavior: "smooth", block: "start" });
  };
  const idsRenderizaveis = new Set(contextoRoteiro?.ids_renderizaveis ?? []);
  const podeIrParaPergunta = (id: string) => idsRenderizaveis.has(id);
  const irParaPergunta = (id: string) => roteiro.current?.irParaPergunta(id);

  return (
    <div className="fixed inset-0 z-40 overflow-y-auto bg-fundo px-4 pb-10 pt-4 sm:px-5 lg:px-6">
      <div className="sticky top-0 z-30 mx-auto mb-5 flex max-w-[1500px] min-w-0 items-center justify-between gap-4 rounded-cartao border border-borda-forte bg-papel/95 px-4 py-3 shadow-cartao backdrop-blur">
        <div className="min-w-0">
          <span className="block text-[11px] font-semibold leading-none font-ui tracking-[0.14em] text-tinta-3">
            ENTREVISTA EM ANDAMENTO
          </span>
          <strong className="mt-1 block truncate text-sm text-tinta">
            Roteiro, chamada e fechamento no mesmo fluxo
          </strong>
        </div>
        {encerrada === null && !escuta && (
          <button
            type="button"
            className="shrink-0 rounded-campo border border-critico bg-critico px-4 py-[10px] font-ui text-[11px] font-bold uppercase leading-none tracking-[0.08em] text-papel hover:opacity-90"
            onClick={() => roteiro.current?.iniciarTranscricao()}
          >
            Iniciar transcrição
          </button>
        )}
        {escuta && (
          <span className="shrink-0 font-ui text-[11px] font-bold uppercase tracking-[0.08em] text-ok">
            ● Transcrevendo
          </span>
        )}
        <button
          type="button"
          className="shrink-0 rounded-campo border border-borda-forte bg-transparent px-3 py-[9px] font-ui text-[10px] font-semibold uppercase leading-none tracking-[0.08em] text-tinta hover:bg-papel-2"
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
            const trechosAteAqui = roteiro.current?.transcricaoBruta() ?? [];
            if (trechosAteAqui.length > 0) salvarTranscricao(trechosAteAqui);
            onFechar();
          }}
        >
          Fechar sem concluir
        </button>
      </div>

      <div className="mx-auto grid max-w-[1500px] grid-cols-[minmax(0,1fr)_minmax(340px,460px)] items-start gap-5 max-[1080px]:grid-cols-[minmax(0,1fr)]">
        <div className="min-w-0">
          {/* Sem `onConcluir`: o roteiro não fecha mais o atendimento sozinho.
            * Ele só reporta o que foi respondido, e quem encerra é o botão lá
            * embaixo, depois das etapas seguintes. */}
          <Roteiro
            ref={roteiro}
            onEscuta={setEscuta}
            onContextoRevisao={atualizarContextoRoteiro}
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

          {/* O atendimento continua aqui embaixo, sem trocar de tela.
            *
            * Na mesma medida do roteiro (860px). Estes painéis foram desenhados
            * para o cartão estreito da tela de casos e não tinham limite de
            * largura própria — soltos aqui, esticavam até o fim da coluna e
            * terminavam num degrau visível em relação às perguntas acima. */}
          {encerrada !== null && <div id="dados-finais-da-entrevista" className="max-w-[860px]">{depois}</div>}

          {encerrada === null ? (
            <div className="flex items-center flex-wrap gap-[14px] max-w-[860px] mt-7 mb-2 border-t-[3px] border-double border-borda-forte pt-[18px]">
              <BotaoProcesso
                id="acao-revisar-entrevista"
                variante="primario"
                processando={fechando && !resultadoFinal}
                textoProcessando="Revisando a entrevista…"
                dica="Conferindo o que faltou e sugerindo perguntas"
                aguardando={fechando}
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
                  const geracaoDaVez = ++geracaoRevisao.current;
                  void (async () => {
                    const transcricao = transcricaoAtual();
                    if (!transcricao.trim()) throw new Error("A conversa ainda não produziu transcrição. Confira o microfone ou preencha os campos manualmente.");
                    const contextoDaVez = contextoRoteiro;
                    if (!contextoDaVez) {
                      throw new Error("O roteiro ativo ainda não terminou de carregar.");
                    }

                    /* O que a pré-análise já leu vai para a tela AGORA.
                     *
                     * Ela não preenche o formulário: as respostas que carrega
                     * são as de alguns minutos atrás, e aplicá-las apagaria o
                     * que foi respondido desde então. Campo só a definitiva
                     * mexe, logo abaixo. */
                    const [respostasAtuais, relatoAtual, entrevistaId, trechos] = ultimo.current;
                    const chaveRespostasAtuais = chaveDasRespostas(respostasAtuais);
                    const candidata = preAnalise.obter();
                    const adiantada = candidata !== null
                      && (
                        candidata.respostas_entrada_chave === chaveRespostasAtuais
                        || candidata.respostas_saida_chave === chaveRespostasAtuais
                      )
                      ? candidata
                      : null;
                    const completa = adiantada !== null
                      && adiantada.roteiro_chave === contextoDaVez.chave
                      && adiantada.cobertura === transcricao.length;
                    if (adiantada) {
                      setRevisadas(adiantada.processamento.respostas);
                      setResultadoFinal({ ...adiantada, provisorio: !completa });
                    }
                    if (completa) return;

                    setConsolidando(true);
                    const leitura = await lerEntrevista(transcricao, respostasAtuais, contextoDaVez, (processamento) => {
                      if (geracaoRevisao.current !== geracaoDaVez) return;
                      setRevisadas(processamento.respostas);
                    });
                    if (geracaoRevisao.current !== geracaoDaVez) return;
                    setResultadoFinal({ ...leitura, provisorio: false });
                  })()
                    .catch((e: unknown) => {
                      if (geracaoRevisao.current === geracaoDaVez) {
                        setErroFecho(e instanceof Error ? e.message : "Não foi possível revisar a entrevista.");
                      }
                    })
                    .finally(() => {
                      if (geracaoRevisao.current === geracaoDaVez) {
                        setFechando(false);
                        setConsolidando(false);
                      }
                    });
                }}
              >
                {resultadoFinal ? "Revisar novamente" : "Revisar entrevista"}
              </BotaoProcesso>
              <span className={ENCERRAR_NOTA}>
                A chamada e a gravação continuam enquanto o sistema confere o que faltou e sugere perguntas.
              </span>
              {consolidando && <Aviso tom="neutro" titulo="Lendo o restante da conversa">A revisão já vem adiantada do que foi transcrito durante a entrevista; falta só o trecho final.</Aviso>}
              {erroFecho && <Aviso tom="atencao" titulo="A revisão não foi concluída">{erroFecho}</Aviso>}
              {revisadas && (
                <div className="basis-full w-full flex items-center flex-wrap gap-3 border-l-4 border-acao bg-acao-clara px-4 py-3">
                  <span className="text-[13px] leading-[1.5] text-tinta">
                    A revisão encontrou respostas na conversa. Nada foi colocado no roteiro ainda.
                  </span>
                  <BotaoProcesso variante="primario" onClick={aplicarRevisadas}>
                    Informações revisadas — aplicar ao roteiro
                  </BotaoProcesso>
                </div>
              )}
              {resultadoFinal && (
                <div className="basis-full w-full">
                  <PainelFinal resultado={resultadoFinal} onVoltar={voltarAoRoteiro} onIrPara={irParaPergunta} podeIrPara={podeIrParaPergunta} />
                </div>
              )}
              {resultadoFinal && (
                <BotaoProcesso
                  id="acao-avancar-finalizacao"
                  variante="primario"
                  processando={fechando && resultadoFinal !== null}
                  textoProcessando="Fechando a gravação…"
                  aguardando={fechando}
                  onClick={() => {
                    setFechando(true);
                    setErroFecho(null);
                    void roteiro.current?.encerrarGravacao()
                      .then((id) => {
                        setEncerrada(id);
                        window.setTimeout(() => {
                          document.getElementById("dados-finais-da-entrevista")?.scrollIntoView({
                            behavior: "smooth",
                            block: "start",
                          });
                        }, 80);
                      })
                      .catch((e: unknown) => {
                        setEncerrada("");
                        setErroFecho(e instanceof Error ? e.message : "A gravação não pôde ser fechada.");
                      })
                      .finally(() => setFechando(false));
                  }}
                >
                  Avançar para finalizar entrevista
                </BotaoProcesso>
              )}
            </div>
          ) : (
            /* O fecho: as perguntas terminaram, a GRAVAÇÃO NÃO.
             *
             * Esta tela dizia "ATENDIMENTO ENCERRADO / A gravação parou agora" —
             * e era falso. O botão que traz este bloco (`encerrarGravacao`) só
             * devolve o id da entrevista; quem para a captura é
             * `encerrarAtendimento`, no "Finalizar atendimento" mais abaixo. É de propósito:
             * as etapas que aparecem aqui (dados finais, avaliação, contrato e a
             * conversa sobre os DOCUMENTOS) precisam entrar no arquivo.
             *
             * O texto errado tinha consequência: convidava a baixar e sair no
             * meio, com metade do atendimento ainda por gravar.
             *
             * Vídeo, áudio e transcrição bruta são coisas diferentes e servem a
             * perguntas diferentes — o vídeo prova quem estava na sala, o áudio
             * é a conversa, e a transcrição é o que dá para ler e buscar seis
             * meses depois sem ouvir quarenta minutos. */
            <div className="flex items-start flex-col gap-[14px] max-w-[860px] mt-7 mb-2 border-t-[3px] border-double border-borda-forte pt-[18px]">
              <span className="text-[11px] font-semibold leading-none font-ui tracking-[0.14em] text-atencao">
                PERGUNTAS ENCERRADAS — GRAVAÇÃO AINDA CORRENDO
              </span>

              {erroFecho && (
                <Aviso tom="atencao" titulo="A gravação não fechou">
                  {erroFecho} O vídeo e a transcrição abaixo continuam valendo.
                </Aviso>
              )}

              <p className={ENCERRAR_NOTA}>
                A gravação e a transcrição <strong>continuam correndo</strong> e só param em
                “Finalizar atendimento” — crie o caso acima e mande o link e a senha ao cliente
                antes. No encerramento o{" "}
                <strong>vídeo é baixado sozinho</strong>; ele existe só nesta aba e some ao fechar a tela.
              </p>

              <BotaoProcesso
                id="acao-criar-caso"
                variante="primario"
                onClick={() => {
                  if (
                    !window.confirm(
                      (roteiro.current?.temVideoPendente()
                        ? "O vídeo gravado será baixado agora, neste computador. "
                        : "") +
                        "A transcrição completa da conversa será baixada. Finalizar o atendimento encerra a gravação e desliga a chamada. Continuar?",
                    )
                  ) {
                    return;
                  }
                  void roteiro.current?.encerrarAtendimento().finally(() => {
                    /* A transcrição é relida AGORA, e não tirada de
                     * `ultimo.current`: o encerramento acabou de acrescentar a
                     * cauda da conversa (ver `onCauda`), e o snapshot foi tirado
                     * antes dela. Era o fim do atendimento que não chegava ao
                     * caso mesmo depois de ter sido transcrito. */
                    const [respostas, relato, entrevistaId] = ultimo.current;
                    const trechos = roteiro.current?.transcricaoBruta() ?? ultimo.current[3];
                    ultimo.current = [respostas, relato, entrevistaId, trechos];
                    salvarTranscricao(trechos);
                    if (entrevistaId) {
                      void fetch(urlDoAudio(entrevistaId))
                        .then((resposta) => (resposta.ok ? resposta.blob() : null))
                        .then((audio) =>
                          audio ? guardarGravacaoNoBanco(audio, `Audio da entrevista ${entrevistaId}.m4a`, "audio", entrevistaId) : undefined,
                        )
                        .catch(() => undefined);
                    }
                    onConcluir(respostas, relato, entrevistaId, trechos);
                  });
                }}
              >
                Finalizar atendimento e baixar gravação e transcrição
              </BotaoProcesso>

              {consolidando && <Aviso tom="neutro" titulo="Conferindo a entrevista inteira">Organizando campos, tipo provável, lacunas e próximos passos…</Aviso>}
              {resultadoFinal && <PainelFinal resultado={resultadoFinal} onVoltar={voltarAoRoteiro} onIrPara={irParaPergunta} podeIrPara={podeIrParaPergunta} podeComplementar={false} />}

              <span className={ENCERRAR_NOTA}>
                A transcrição de <strong>tudo que foi falado</strong>, do início ao fim, é baixada
                automaticamente ao finalizar. Se a página fechar antes, ela é baixada ao abrir o
                sistema de novo.
              </span>

            </div>
          )}
        </div>

        <div className="min-w-0 sticky top-[86px] self-start max-h-[calc(100vh-104px)] overflow-y-auto rounded-cartao border border-borda-forte bg-papel p-3 shadow-cartao max-[1080px]:order-[-1] max-[1080px]:static max-[1080px]:max-h-none max-[1080px]:overflow-visible">
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
