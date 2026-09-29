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
import type {
  ContextoRevisaoRoteiro,
  Estrategia,
  PerguntaPendente,
  ProcessamentoEntrevista,
  RoteiroCompleto,
} from "@/lib/types";
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
/* Exportado porque o relato COLADO passa pela mesma leitura.
 *
 * A entrevista guiada e o .txt trazido de fora terminam na mesma pergunta — o
 * que a conversa trouxe, o que faltou, que ação é e o que os precedentes dizem.
 * Um segundo painel para responder isso divergiria do primeiro no primeiro
 * ajuste; é o mesmo componente, alimentado pela mesma `lerEntrevista`. */
export type ResultadoFinal = LeituraDaEntrevista & { provisorio: boolean };

/* O tipo provável do caso, como a triagem o leu.
 *
 * Só as três primeiras sugestões: o ranking tem cauda longa e as últimas são
 * ruído de pontuação. `confiante` é o que decide o tom — a triagem sabe quando
 * não sabe (duas categorias empatadas, sinal fraco), e esconder essa dúvida é
 * pior que não sugerir nada: errar a categoria erra o checklist inteiro e o
 * sistema passa a cobrar documentos que a ação não usa. */
function TipoProvavel({ triagem }: { triagem: ResultadoFinal["triagem"] }) {
  if (!triagem || triagem.sugestoes.length === 0) return null;
  const principais = triagem.sugestoes.slice(0, 3);
  return (
    <details open className="mt-3">
      <summary className="cursor-pointer text-xs font-bold">
        Tipo provável do caso
        {!triagem.confiante && <span className="ml-2 font-semibold text-atencao">a confirmar</span>}
      </summary>
      <ul className="mt-2 pl-5 text-xs leading-[1.6]">
        {principais.map((s) => (
          <li key={s.codigo}>
            <strong>{s.nome}</strong>{" "}
            <span className="text-tinta-3 tabular-nums">({Math.round(s.confianca * 100)}%)</span>
            {s.evidencias.length > 0 && (
              <span className="text-tinta-3"> — “{s.evidencias.slice(0, 2).join("”; “")}”</span>
            )}
          </li>
        ))}
      </ul>
      {!triagem.confiante && triagem.motivo && (
        <p className="mt-2 mb-0 text-[11.5px] leading-[1.5] text-atencao">{triagem.motivo}</p>
      )}
      {/* Duas ações possíveis não é detalhe de classificação: é dinheiro e prazo
          diferentes, e quem decide precisa ver isso antes de fechar o caso. */}
      {triagem.concorrentes && (
        <p className="mt-2 mb-0 text-[11.5px] leading-[1.5] text-atencao">
          O relato traz doença crônica <strong>e</strong> acidente súbito — podem ser duas ações.
        </p>
      )}
      {triagem.divergiu && (
        <p className="mt-2 mb-0 text-[11.5px] leading-[1.5] text-tinta-3">
          As duas leituras (modelo e termos) discordaram: confira a categoria à mão.
        </p>
      )}
    </details>
  );
}

/* Como a ENTREVISTA foi conduzida — não o caso, a conversa.
 *
 * É a única parte da análise que fala com quem está conduzindo, e enquanto dá
 * para consertar: o cliente ainda está na sala. "Fora do assunto" com uma
 * pergunta pronta ao lado vale mais que qualquer leitura de mérito depois. */
function LeituraDaConducao({ insights }: { insights: ProcessamentoEntrevista["insights_entrevista"] }) {
  if (!insights) return null;
  const tom =
    insights.foco === "adequado" ? "text-ok" : insights.foco === "parcial" ? "text-atencao" : "text-critico";
  const rotulo =
    insights.foco === "adequado"
      ? "no assunto"
      : insights.foco === "parcial"
        ? "parcialmente no assunto"
        : "fora do assunto";
  return (
    <details open={insights.foco !== "adequado"} className="mt-3">
      <summary className="cursor-pointer text-xs font-bold">
        Como a entrevista foi conduzida <span className={`font-semibold ${tom}`}>— {rotulo}</span>
      </summary>
      {insights.diagnostico && (
        <p className="mt-2 mb-0 text-xs leading-[1.6] text-tinta-2">{insights.diagnostico}</p>
      )}
      {insights.desvios.length > 0 && (
        <ul className="mt-2 pl-5 text-xs leading-[1.6] text-tinta-3">
          {insights.desvios.map((d) => <li key={d}>{d}</li>)}
        </ul>
      )}
      {insights.perguntas_especificas.length > 0 && (
        <>
          <strong className="mt-3 block text-xs">Ainda dá para perguntar</strong>
          <ul className="mt-1 pl-5 text-xs leading-[1.6]">
            {insights.perguntas_especificas.map((p) => (
              <li key={p}><strong>Pergunte:</strong> “{p}”</li>
            ))}
          </ul>
        </>
      )}
    </details>
  );
}

/* O que processos semelhantes mostraram, e o cuidado que isso exige.
 *
 * Fechado por padrão, de propósito: é leitura de mérito, e a tela existe para
 * fechar a ENTREVISTA. Quem quer ler, abre.
 *
 * O `aviso` e a `metodologia` do backend vão junto e não são decorativos: isto
 * é amostra vetorial de processos parecidos, estatística descritiva do que já
 * foi decidido — não previsão de êxito deste caso. Mostrar percentual sem o
 * critério ao lado é o caminho curto para alguém prometer resultado ao cliente. */
function LeituraPorPrecedentes({ analise }: { analise: Estrategia | null }) {
  if (!analise) return null;
  const merito = analise.estatisticas?.desfechos_merito;
  return (
    <details className="mt-3">
      <summary className="cursor-pointer text-xs font-bold">
        O que processos semelhantes mostram
        {analise.estatisticas?.processos_analisados ? (
          <span className="ml-2 font-normal text-tinta-3 tabular-nums">
            ({analise.estatisticas.processos_analisados} analisados)
          </span>
        ) : null}
      </summary>

      {analise.resumo && (
        <p className="mt-2 mb-0 border-l-4 border-acao bg-acao-clara px-3 py-2 text-xs leading-[1.6]">
          {analise.resumo}
        </p>
      )}

      {merito && merito.processos > 0 && (
        <p className="mt-2 mb-0 text-[11.5px] leading-[1.5] text-tinta-3 tabular-nums">
          {merito.favoraveis} de {merito.processos} com mérito julgado ({merito.percentual}%) — {merito.criterio}
        </p>
      )}

      {analise.acoes.length > 0 && (
        <>
          <strong className="mt-3 block text-xs">O que costuma sustentar</strong>
          <ul className="mt-1 pl-5 text-xs leading-[1.6]">
            {analise.acoes.map((a, i) => (
              <li key={i}>
                {a.acao}
                {a.porque && <span className="text-tinta-3"> — {a.porque}</span>}
                {a.contrapontos && <span className="text-atencao"> Contraponto: {a.contrapontos}</span>}
              </li>
            ))}
          </ul>
        </>
      )}

      {analise.riscos.length > 0 && (
        <>
          <strong className="mt-3 block text-xs text-atencao">Riscos apontados</strong>
          <ul className="mt-1 pl-5 text-xs leading-[1.6]">
            {analise.riscos.map((r, i) => (
              <li key={i}>
                {r.risco}
                {r.contrapontos && <span className="text-tinta-3"> — {r.contrapontos}</span>}
              </li>
            ))}
          </ul>
        </>
      )}

      {analise.perguntas_criticas && analise.perguntas_criticas.length > 0 && (
        <>
          <strong className="mt-3 block text-xs">Perguntas que os precedentes sugerem</strong>
          <ul className="mt-1 pl-5 text-xs leading-[1.6]">
            {analise.perguntas_criticas.map((p) => <li key={p}><strong>Pergunte:</strong> “{p}”</li>)}
          </ul>
        </>
      )}

      {analise.lacunas.length > 0 && (
        <>
          <strong className="mt-3 block text-xs">Provas que costumam faltar</strong>
          <ul className="mt-1 pl-5 text-xs leading-[1.6]">
            {analise.lacunas.map((l) => <li key={l}>{l}</li>)}
          </ul>
        </>
      )}

      {(analise.aviso || analise.metodologia) && (
        <p className="mt-3 mb-0 border-t border-borda pt-2 text-[11px] leading-[1.5] text-tinta-3">
          {analise.aviso} {analise.metodologia}
        </p>
      )}
    </details>
  );
}

/* A recomendação de triagem: vale abrir o caso?
 *
 * Decisão reversível, e o texto diz isso — a rota que a produz é explícita ao
 * separar triagem de previsão de êxito (`/api/entrevista/recomendacao`). O que
 * mais importa aqui não é o veredito e sim `lacunas_obrigatorias`: o que falta
 * conseguir ANTES de aceitar, que ainda dá para pedir com o cliente na sala. */
function RecomendacaoDeTriagem({ recomendacao }: { recomendacao: ResultadoFinal["recomendacao"] }) {
  if (!recomendacao) return null;
  const tom: Record<string, string> = {
    sim: "text-ok",
    com_ressalva: "text-atencao",
    atencao: "text-critico",
    indefinido: "text-tinta-3",
  };
  const rotulo: Record<string, string> = {
    sim: "vale abrir",
    com_ressalva: "vale abrir, com ressalva",
    atencao: "atenção antes de aceitar",
    indefinido: "sem sinal suficiente",
  };
  return (
    <details open={recomendacao.lacunas_obrigatorias.length > 0} className="mt-3">
      <summary className="cursor-pointer text-xs font-bold">
        Triagem do caso{" "}
        <span className={`font-semibold ${tom[recomendacao.recomendado]}`}>
          — {rotulo[recomendacao.recomendado]}
        </span>
      </summary>
      {recomendacao.motivo && (
        <p className="mt-2 mb-0 text-xs leading-[1.6] text-tinta-2">{recomendacao.motivo}</p>
      )}
      {recomendacao.lacunas_obrigatorias.length > 0 && (
        <>
          <strong className="mt-3 block text-xs">Conseguir antes de aceitar</strong>
          <ul className="mt-1 pl-5 text-xs leading-[1.6]">
            {recomendacao.lacunas_obrigatorias.map((l) => <li key={l}>{l}</li>)}
          </ul>
        </>
      )}
      {!recomendacao.com_precedentes && (
        <p className="mt-2 mb-0 text-[11.5px] leading-[1.5] text-atencao">
          Sem a base de precedentes: esta é a leitura do modelo sobre o relato, e não o que
          processos semelhantes mostram.
        </p>
      )}
      <p className="mt-3 mb-0 border-t border-borda pt-2 text-[11px] leading-[1.5] text-tinta-3">
        Decisão de triagem, reversível — não é previsão de êxito.
        {recomendacao.aviso ? ` ${recomendacao.aviso}` : ""}
      </p>
    </details>
  );
}

/* A QUALIFICAÇÃO NÃO ENTRA NA CONFERÊNCIA — ela é etapa DEPOIS da entrevista.
 *
 * Nome, CPF, estado civil, UF e município são digitados fora da conversa (é o
 * que `escuta.DADOS_DIGITADOS` fixa do lado do servidor), e o bloco de
 * qualificação inteiro sai da entrevista por `delegado_a` — hoje ele é de outra
 * equipe, e o próprio backend tem um `IDS_QUALIFICACAO_POS_ENTREVISTA` com esse
 * nome. Listar esses campos aqui como "ainda não perguntado" enchia a
 * conferência de pendência que ninguém ia resolver com o cliente na linha, e
 * empurrava para baixo o que de fato importa: o que a pessoa contou e o que
 * ficou faltando DO CASO.
 *
 * O filtro sai do roteiro em uso, e não de uma lista de nomes de campo escrita
 * aqui: roteiro importado de outro escritório nomeia "cpf" como quiser, e a
 * regra que vale é a mesma do servidor — bloco delegado, campo com dígito
 * verificador, ou dado digitado por regra. */
const DADOS_DIGITADOS = new Set(["nome", "cpf", "estado_civil", "uf", "municipio"]);

function idsDeQualificacao(roteiro: RoteiroCompleto | null): Set<string> {
  const ids = new Set(DADOS_DIGITADOS);
  for (const bloco of roteiro?.blocos ?? []) {
    for (const pergunta of bloco.perguntas) {
      if (bloco.delegado_a || pergunta.validacao) ids.add(pergunta.id);
    }
  }
  return ids;
}

function semQualificacao(itens: PerguntaPendente[], ids: Set<string>): PerguntaPendente[] {
  return itens.filter((p) => !ids.has(p.pergunta_id));
}

export function PainelFinal({ resultado, roteiro, onVoltar, onIrPara, podeIrPara, podeComplementar = true }: { resultado: ResultadoFinal; roteiro: RoteiroCompleto | null; onVoltar: () => void; onIrPara: (id: string) => void; podeIrPara: (id: string) => boolean; podeComplementar?: boolean }) {
  const { processamento, avisos, provisorio } = resultado;
  const qualificacao = idsDeQualificacao(roteiro);
  const faltando = semQualificacao(processamento.faltando, qualificacao);
  const incertas = processamento.incertas.filter((p) => !qualificacao.has(p.pergunta_id));
  return (
    <section className="w-full border-l-4 border-tinta bg-papel-2 px-4 py-[14px]" aria-live="polite">
      <strong className="block text-[14px] text-tinta">Leitura da entrevista</strong>
      <p className="mt-1 text-xs leading-[1.55] text-tinta-3">
        O que a conversa trouxe do caso, o que ficou faltando e o que processos semelhantes
        mostram. A qualificação (nome, CPF, endereço) é etapa posterior e não entra aqui.
        A chamada e a gravação continuam ativas.
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

      {/* A condução vem primeiro porque é a única parte que ainda dá para
        * consertar: o cliente está na sala. O resto é leitura do caso. */}
      <LeituraDaConducao insights={processamento.insights_entrevista} />

      {faltando.length === 0 && incertas.length === 0 && (
        <p className="mt-3 mb-0 border-l-[3px] border-ok bg-papel px-3 py-[11px] text-xs font-semibold text-ok">
          A conversa cobriu o que o roteiro pede sobre o caso.
        </p>
      )}
      {faltando.length > 0 && (
        <details open className="mt-3"><summary className="cursor-pointer text-xs font-bold">Sobre o caso, ainda sem resposta ({faltando.length})</summary>
          <ul className="mt-2 pl-5 text-xs leading-[1.6]">{faltando.map((p) => <li key={p.pergunta_id}><strong>Pergunte:</strong> “{p.pergunta}”{p.obrigatoria ? " — necessário antes de encerrar" : ""} {podeComplementar && podeIrPara(p.pergunta_id) && <button type="button" className="ml-2 underline text-acao" onClick={() => onIrPara(p.pergunta_id)}>ir ao campo</button>}</li>)}</ul>
        </details>
      )}
      {incertas.length > 0 && (
        <details open className="mt-3"><summary className="cursor-pointer text-xs font-bold">O que precisa ser confirmado ({incertas.length})</summary>
          <ul className="mt-2 pl-5 text-xs leading-[1.6]">{incertas.slice(0, 10).map((p) => <li key={p.pergunta_id}><strong>Confirme com o cliente:</strong> {p.motivo} {podeComplementar && podeIrPara(p.pergunta_id) && <button type="button" className="ml-2 underline text-acao" onClick={() => onIrPara(p.pergunta_id)}>ir ao campo</button>}</li>)}</ul>
        </details>
      )}

      {/* Daqui para baixo, a leitura do caso: era tudo calculado a cada passada
        * — três chamadas por vez, durante a entrevista inteira — e nada disso
        * chegava à tela. */}
      <TipoProvavel triagem={resultado.triagem} />
      <LeituraPorPrecedentes analise={processamento.analise} />
      <RecomendacaoDeTriagem recomendacao={resultado.recomendacao} />

      {avisos.map((aviso) => <p key={aviso} className="mt-3 text-xs text-atencao">{aviso}</p>)}
    </section>
  );
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

      {/* A coluna da chamada cresceu de 340–460px para 440–620px.
        *
        * O roteiro à esquerda tem medida fixa de leitura (860px) e não usava a
        * folga: numa tela de 1500px sobrava espaço vazio entre as duas colunas
        * enquanto a chamada ficava espremida. Quem conduz passa a entrevista
        * inteira olhando para o rosto do entrevistado, não para o formulário —
        * a coluna da direita é que merece a largura excedente.
        *
        * O ponto de empilhamento sobe de 1080px para 1240px: com a coluna maior,
        * entre 1080 e 1240 o roteiro ficava abaixo da medida legível. */}
      <div className="mx-auto grid max-w-[1500px] grid-cols-[minmax(0,1fr)_minmax(440px,620px)] items-start gap-5 max-[1240px]:grid-cols-[minmax(0,1fr)]">
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
                  <PainelFinal resultado={resultadoFinal} roteiro={contextoRoteiro?.roteiro ?? null} onVoltar={voltarAoRoteiro} onIrPara={irParaPergunta} podeIrPara={podeIrParaPergunta} />
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
              {resultadoFinal && <PainelFinal resultado={resultadoFinal} roteiro={contextoRoteiro?.roteiro ?? null} onVoltar={voltarAoRoteiro} onIrPara={irParaPergunta} podeIrPara={podeIrParaPergunta} podeComplementar={false} />}

              <span className={ENCERRAR_NOTA}>
                A transcrição de <strong>tudo que foi falado</strong>, do início ao fim, é baixada
                automaticamente ao finalizar. Se a página fechar antes, ela é baixada ao abrir o
                sistema de novo.
              </span>

            </div>
          )}
        </div>

        <div className="min-w-0 sticky top-[86px] self-start max-h-[calc(100vh-104px)] overflow-y-auto rounded-cartao border border-borda-forte bg-papel p-3 shadow-cartao max-[1240px]:order-[-1] max-[1240px]:static max-[1240px]:max-h-none max-[1240px]:overflow-visible">
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
