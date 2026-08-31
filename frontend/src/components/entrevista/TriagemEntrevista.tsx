"use client";

import { useEffect, useRef, useState } from "react";

import {
  analisarEstrategia,
  gravarEntrevistaAoVivo,
  listarAssinaturas,
  triarEntrevista,
  vincularAssinaturaAoCaso,
} from "@/lib/api";
import {
  CapturaEntrevista,
  montarTranscricaoBruta,
  type EstadoCaptura,
  type TrechoTranscrito,
} from "@/lib/transcricao";
import type { CasoCriado, Categoria, Estrategia, Triagem } from "@/lib/types";
import CasoEDocumentos from "@/components/caso/CasoEDocumentos";
import { useChamada } from "@/lib/ChamadaContexto";
import AudioDaEntrevista from "@/components/entrevista/AudioDaEntrevista";
import AvaliacaoGoogle from "@/components/contrato/AvaliacaoGoogle";
import RespostasDoRoteiro from "@/components/entrevista/RespostasDoRoteiro";
import { Aviso, Botao, Campo, RotuloCampo, Selo } from "@/components/ui/Basicos";
import EntrevistaComChamada from "@/components/entrevista/EntrevistaComChamada";
import PainelContrato from "@/components/contrato/PainelContrato";
import PainelChamada from "@/components/chamada/PainelChamada";

const OPCAO_BASE =
  "flex gap-3 items-start w-full px-[14px] py-3 border-none border-b border-borda border-l-4 bg-transparent " +
  "text-inherit [font:inherit] text-left cursor-pointer transition-[background-color] duration-[120ms] ease-[ease]";
const OPCAO_RESTING = "border-l-transparent hover:bg-papel-3";
const OPCAO_ESCOLHIDA = "border-l-ok bg-ok-claro";
const ESTADO_TEXTO = "text-tinta-3 text-xs leading-[1.55]";

/* Painel de insights de processos semelhantes: cartões de métrica + faixas de
 * dado + duas colunas de listas — classes reaproveitadas entre os vários
 * blocos de dados e listas deste painel. */
const METRICAS = "grid grid-cols-2 max-[700px]:grid-cols-1 gap-[10px]";
const METRICA_CARTAO = "p-[12px_14px] border border-borda rounded-campo bg-papel";
const METRICA_VALOR = "block text-tinta font-titulo text-lg font-semibold tabular-nums";
const METRICA_ROTULO = "block mt-[3px] text-tinta-3 text-xs leading-[1.4]";
const FAIXA_DADOS = "py-[11px] border-b border-borda";
const FAIXA_TITULO = "m-0 mb-[5px] text-tinta font-ui text-xs font-bold";
const FAIXA_TEXTO = "m-0 text-tinta-2 text-xs leading-[1.55]";
const COLUNAS_INSIGHTS = "grid grid-cols-2 max-[700px]:grid-cols-1 gap-[22px] mt-4";
const LISTA_INSIGHT = "m-0 pl-[18px]";
const ITEM_INSIGHT = "mb-2 text-tinta-2 text-xs leading-[1.55]";
const PRECEDENTES = "mt-[14px] pt-3 border-t border-borda";

/* Lê a entrevista e sugere a categoria — mas quem escolhe é o advogado.
 *
 * A sugestão nunca é aplicada sozinha: categoria errada é checklist errado, e o
 * escritório passaria a cobrar do cliente documentos que a ação não usa e a
 * ignorar os que ela exige. Por isso cada opção mostra o trecho do relato que a
 * sustentou, e a lista inteira fica clicável, não só a primeira. */
export default function TriagemEntrevista({
  onEscolher,
  onAtendimento,
  categorias,
  onCriarCaso,
  onAbrirDossie,
  onAbrirAnalises,
}: {
  /** Tipos de ação, para criar o caso sem sair do atendimento. */
  categorias: Categoria[];
  /** Cria o caso e devolve o portal do cliente (link + senha). */
  onCriarCaso: (
    cliente: string,
    categoria: string,
    observacao?: string,
    /** O WhatsApp da entrevista, para o caso já nascer com ele. */
    telefone?: string,
  ) => Promise<CasoCriado>;
  /** Sai da entrevista direto para a visão completa do caso recém-criado. */
  onAbrirDossie?: (casoId: string) => void;
  onAbrirAnalises?: (casoId: string) => void;
  /** Aplica a categoria (e o nome do cliente, se a entrevista trouxer). */
  onEscolher: (categoria: string, cliente?: string) => void;
  /** Em que ponto o atendimento está. A tela ao redor usa isto para tirar do
   *  caminho o que não é deste cliente (a lista de casos antigos) e para saber
   *  quando pode mostrar a chamada — durante a entrevista ela já está na
   *  coluna da direita, e desenhá-la duas vezes decodificaria o mesmo vídeo em
   *  dois lugares. */
  onAtendimento?: (fase: "nenhum" | "entrevista" | "pos-entrevista") => void;
}) {
  const [texto, setTexto] = useState("");
  const [mostrarRoteiro, setMostrarRoteiro] = useState(false);
  /* A qualificação fica guardada depois que a entrevista fecha: é ela que
   * preenche o contrato, e o relato corrido já não a tem em campos separados. */
  const [qualificacao, setQualificacao] = useState<Record<string, string | string[]> | null>(
    null,
  );
  /* O áudio sobrevive à tela em que foi gravado — pelo mesmo motivo da
   * qualificação. Sem guardar o id aqui, o arquivo continuaria no disco e
   * ninguém teria como pedi-lo: o nome dele é um uuid. */
  const [audioEntrevista, setAudioEntrevista] = useState("");
  /* A etapa do Google Meu Negócio, marcada pelo atendente. Fica AQUI e não na
   * caixa dela: voltar ao roteiro desmonta a caixa, e a marcação sumiria junto
   * — dando a etapa por pendente depois de ela ter sido cumprida. */
  const [avaliacaoConcluida, setAvaliacaoConcluida] = useState(false);
  /* A conversa como o Whisper a ouviu, guardada aqui pelo mesmo motivo da
   * qualificação: ela sobrevive ao fechamento da tela da entrevista, e é o que
   * vai para o caso. Sem isto, a entrevista conduzida pelo roteiro morria com a
   * aba e a supervisão nunca a via (ver `app/supervisao.py`). */
  const [transcricao, setTranscricao] = useState<TrechoTranscrito[]>([]);
  /* O caso, depois de criado aqui embaixo. Guardado para o encerramento poder
   * regravar a transcrição completa: o caso nasce NO MEIO do atendimento, e o
   * fechamento do roteiro — inclusive o pedido da avaliação — vem depois dele. */
  const [casoCriado, setCasoCriado] = useState("");
  /* O atendimento foi ENCERRADO no botão do fim — diferente de "fechei a tela".
   *
   * Encerrado, as etapas não se repetem aqui embaixo: elas já foram feitas lá
   * dentro, e vê-las de novo, zeradas, faz o atendente achar que perdeu tudo.
   * O que fica é o resumo e o próximo passo, que é criar o caso. */
  const [encerrado, setEncerrado] = useState(false);
  const [resultado, setResultado] = useState<Triagem | null>(null);
  const [escolhida, setEscolhida] = useState<string | null>(null);
  const [analisando, setAnalisando] = useState(false);
  const [analisandoEstrategia, setAnalisandoEstrategia] = useState(false);
  const [estrategia, setEstrategia] = useState<Estrategia | null>(null);
  const [erroEstrategia, setErroEstrategia] = useState<string | null>(null);
  const [erro, setErro] = useState<string | null>(null);
  const [arrastandoArquivo, setArrastandoArquivo] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  /* -------- atendimento iniciado por um .txt de transcrição --------
   *
   * O upload do .txt deixou de ser só uma validação: ele agora ABRE um
   * atendimento. A IA avalia e recomenda a ação, a gravação do áudio começa na
   * hora (é o atendimento presencial/telefônico que segue o relato), e o
   * advogado confirma nome e CPF para o caso nascer — daí em diante o processo
   * é o mesmo do ao vivo (portal + checklist, em `CasoEDocumentos`). */
  const [atendimentoTxt, setAtendimentoTxt] = useState(false);
  const [nomeTxt, setNomeTxt] = useState("");
  const [cpfTxt, setCpfTxt] = useState("");
  const [categoriaTxt, setCategoriaTxt] = useState("");
  const [entrevistaIdTxt, setEntrevistaIdTxt] = useState("");
  const [gravacaoEstado, setGravacaoEstado] = useState<EstadoCaptura>("sem-audio");
  const [gravacaoAviso, setGravacaoAviso] = useState<string | null>(null);
  const [casoTxtId, setCasoTxtId] = useState("");
  const [encerrandoTxt, setEncerrandoTxt] = useState(false);
  const capturaTxtRef = useRef<CapturaEntrevista | null>(null);
  const trechosTxtRef = useRef<TrechoTranscrito[]>([]);
  // A chamada vive na raiz do app; aqui ela serve para a última etapa saber se
  // ainda há cliente na linha, e para oferecer o desligar sem sair da tela.
  const chamada = useChamada();

  /* Avisa a tela de fora em que ponto este atendimento está.
   *
   * O pós-entrevista (avaliação, relatório, contrato) é a MESMA sessão da
   * entrevista, com o cliente ainda na linha — por isso ele também conta como
   * atendimento em curso, e não como "voltou para a tela de casos". */
  const fase = mostrarRoteiro
    ? "entrevista"
    : qualificacao !== null && !encerrado
      ? "pos-entrevista"
      : "nenhum";
  const avisar = useRef(onAtendimento);
  avisar.current = onAtendimento;
  useEffect(() => {
    avisar.current?.(fase);
  }, [fase]);

  /* Manda a entrevista conduzida para o caso.
   *
   * Chamada duas vezes por atendimento — ao criar o caso e ao encerrar — e a
   * rota é PUT justamente por isso: `gravacao_id` é a chave, e a segunda
   * chamada REESCREVE a primeira em vez de criar outra entrevista. Sem isso, a
   * supervisão contaria o dobro do trabalho de quem conduziu.
   *
   * Falhar aqui NÃO pode desfazer o atendimento: o caso foi criado, o cliente
   * está na linha, e os documentos chegam do mesmo jeito. O que se perde é o
   * registro para a supervisão — grave, mas não na frente do cliente. */
  async function guardarEntrevista(
    casoId: string,
    trechos: TrechoTranscrito[],
    gravacaoId: string,
    concluida: boolean,
  ) {
    if (!casoId || !gravacaoId) return;
    try {
      await gravarEntrevistaAoVivo(casoId, {
        gravacao_id: gravacaoId,
        texto: montarTranscricaoBruta(trechos),
        realizada_em: new Date().toISOString().slice(0, 10),
        avaliacao_google: avaliacaoConcluida,
        concluida,
      });
    } catch (e) {
      console.error("Não foi possível guardar a entrevista no caso.", e);
    }
  }

  /* Liga o microfone e começa a gravar assim que o .txt é analisado.
   *
   * Chamado de dentro do gesto do usuário (o clique que escolheu o arquivo),
   * então o navegador concede o microfone sem bloquear o `getUserMedia`. Se
   * ainda assim falhar, o atendimento segue: o caso pode ser criado sem áudio —
   * só a gravação fica indisponível, e a tela diz isso. */
  async function iniciarGravacaoTxt() {
    if (capturaTxtRef.current) return;
    trechosTxtRef.current = [];
    const captura = new CapturaEntrevista({
      onTrecho: (texto) => {
        trechosTxtRef.current = [...trechosTxtRef.current, { quando: Date.now(), texto }];
      },
      onEstado: setGravacaoEstado,
      onAviso: setGravacaoAviso,
      onErro: setGravacaoAviso,
    });
    capturaTxtRef.current = captura;
    setEntrevistaIdTxt(captura.entrevistaId);
    setGravacaoAviso(null);
    try {
      await captura.selecionarAudio();
      await captura.iniciarEntrevista();
    } catch {
      setGravacaoAviso(
        "Não consegui ligar o microfone. O caso pode ser criado assim mesmo; a gravação do áudio fica indisponível.",
      );
      setGravacaoEstado("sem-audio");
    }
  }

  /* Encerra a gravação do atendimento por .txt e regrava a transcrição completa
   * no caso, agora marcada como concluída. Espelha o encerramento do ao vivo. */
  async function encerrarGravacaoTxt() {
    const captura = capturaTxtRef.current;
    if (!captura) return;
    setEncerrandoTxt(true);
    try {
      captura.finalizarResposta();
      await captura.encerrarGravacao();
      captura.encerrar();
      capturaTxtRef.current = null;
      setGravacaoEstado("sem-audio");
      // Deixa o áudio disponível para conferência, como no fim da entrevista.
      if (entrevistaIdTxt) setAudioEntrevista(entrevistaIdTxt);
      if (casoTxtId) {
        await guardarEntrevista(casoTxtId, trechosTxtRef.current, entrevistaIdTxt, true);
      }
    } finally {
      setEncerrandoTxt(false);
    }
  }

  /* Fecha a captura se a tela sair no meio: microfone aberto sem ninguém para
   * fechá-lo fica com o indicador do navegador aceso e a trilha viva. */
  useEffect(() => {
    return () => {
      capturaTxtRef.current?.encerrar();
      capturaTxtRef.current = null;
    };
  }, []);

  async function analisar(arquivo?: File) {
    if (!arquivo && !texto.trim()) return;
    setAnalisando(true);
    setAnalisandoEstrategia(true);
    setErro(null);
    setErroEstrategia(null);
    setEstrategia(null);
    setEscolhida(null);
    try {
      const r = await triarEntrevista(texto, arquivo);
      setResultado(r);
      const relato = r.texto_extraido || texto;
      if (arquivo && relato) setTexto(relato);
      void analisarEstrategia(relato)
        .then(setEstrategia)
        .catch((e: unknown) =>
          setErroEstrategia(
            e instanceof Error ? e.message : "Não foi possível consultar os processos semelhantes.",
          ),
        )
        .finally(() => setAnalisandoEstrategia(false));
      // Confiante aplica direto; ambíguo espera o clique.
      if (r.confiante && r.sugestoes[0]) {
        setEscolhida(r.sugestoes[0].codigo);
        onEscolher(r.sugestoes[0].codigo, r.dados.cliente);
      } else if (r.dados.cliente) {
        onEscolher("", r.dados.cliente);
      }
      /* O .txt não para na avaliação: ele abre o atendimento.
       *
       * A IA já avaliou e recomendou acima; agora começa a gravação e sobe o
       * formulário de nome/CPF para o caso nascer. A recomendação entra
       * pré-selecionada (a primeira sugestão, ou a primeira categoria ativa),
       * mas o advogado pode trocar antes de criar. O relato colado continua
       * sendo só validação — quem inicia o atendimento é o arquivo. */
      if (arquivo) {
        setNomeTxt(r.dados.cliente ?? "");
        setCpfTxt(r.dados.cpf ?? "");
        setCategoriaTxt(r.sugestoes[0]?.codigo ?? categorias[0]?.codigo ?? "");
        setCasoTxtId("");
        setAtendimentoTxt(true);
        void iniciarGravacaoTxt();
      }
    } catch (e) {
      setErro(e instanceof Error ? e.message : "Não foi possível analisar a entrevista.");
      setResultado(null);
      setAnalisandoEstrategia(false);
    } finally {
      setAnalisando(false);
    }
  }

  /* As etapas que vêm DEPOIS das perguntas — avaliação, relatório, documentos.
   *
   * Elas são as mesmas dentro e fora da tela da entrevista, e é por isso que
   * moram numa variável: o escritório pediu "tudo numa paulada só", então
   * durante a entrevista elas ficam logo abaixo do roteiro, na mesma rolagem, e
   * depois de fechada continuam aqui na tela de casos. Duplicar o bloco faria
   * as duas cópias divergirem no primeiro ajuste. */
  const etapasDoAtendimento = qualificacao && (
    <>
      <AvaliacaoGoogle
        concluida={avaliacaoConcluida}
        onConcluir={setAvaliacaoConcluida}
        telefone={String(qualificacao.telefone ?? "")}
      />
      <PainelContrato respostas={qualificacao} />

      {/* O roteiro inteiro com o que foi respondido, para conferir antes de o
        * cliente desligar. Vem DEPOIS do contrato de propósito: quem chegou até
        * aqui já fechou o atendimento, e o que resta é revisar — o que ficou em
        * branco ainda dá para colher com ele na linha. */}
      {/* `aberto` aqui, recolhido no `Roteiro`: são momentos diferentes. Lá a
        * entrevista ainda corre e a lista disputaria a atenção; aqui o
        * atendimento já fechou e conferir É o trabalho. */}
      <RespostasDoRoteiro respostas={qualificacao} aberto />

      {/* E o caso nasce aqui, na mesma rolagem: o portal abre com o cliente
        * ainda na linha, e o checklist recebe o que ele já tem em mãos. */}
      <CasoEDocumentos
        cliente={String(qualificacao.nome ?? "")}
        entrevistaId={audioEntrevista}
        onCasoCriado={async (casoId) => {
          setCasoCriado(casoId);
          // Grava já, sem esperar o encerramento: se a aba morrer daqui para a
          // frente, a entrevista conduzida até aqui não se perde.
          await guardarEntrevista(casoId, transcricao, audioEntrevista, encerrado);
          const nome = String(qualificacao.nome ?? "");
          const cpf = String(qualificacao.cpf ?? "");
          if (nome && cpf) {
            // O caso já existe neste ponto. Uma indisponibilidade momentânea da
            // assinatura não pode fazer a tela alegar que a criação falhou.
            try {
              const existentes = await listarAssinaturas({ cliente: nome, cpf });
              await Promise.allSettled(
                existentes.map((item) => vincularAssinaturaAoCaso(item.id, casoId)),
              );
            } catch {
              // A listagem de assinaturas retoma o vínculo na próxima abertura.
            }
          }
        }}
        categorias={categorias}
        sugerida={escolhida ?? undefined}
        /* O telefone entra AQUI, e não dentro do `CasoEDocumentos`: quem tem
          * as respostas da entrevista é esta tela. Sem ele o caso nasce sem
          * número e a cobrança de documentos abre com o campo em branco,
          * pedindo o que o cliente já ditou (ver `telefone_do_caso`). */
        onCriar={(nome, categoria) =>
          onCriarCaso(nome, categoria, "", String(qualificacao.telefone ?? ""))
        }
        onAbrirDossie={onAbrirDossie}
        onAbrirAnalises={onAbrirAnalises}
        emChamada={chamada.estado !== "fora" && chamada.estado !== "encerrada"}
        onEncerrarChamada={chamada.desligar}
      />
    </>
  );

  /* Como desenhar o estado da gravação do atendimento por .txt. `sem-audio`
   * cobre tanto "nunca ligou" quanto "já encerrou": o texto se resolve pelo
   * aviso, quando há um. */
  const gravInfo = (
    {
      gravando: { tom: "ok", titulo: "Gravando o atendimento" },
      capturando: { tom: "info", titulo: "Microfone ligado — aguardando fala" },
      pausado: { tom: "info", titulo: "Gravação pausada" },
      recuperando: { tom: "atencao", titulo: "Reconectando o microfone…" },
      "sem-audio": { tom: "neutro", titulo: "Gravação encerrada" },
    } as const
  )[gravacaoEstado];

  return (
    <section className="mb-5 min-w-0 overflow-hidden rounded-cartao border border-borda-forte bg-papel shadow-cartao">
      <header className="border-b border-borda bg-papel-2 px-4 py-4 sm:px-5">
        <div className="flex min-w-0 flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
          <div className="min-w-0">
            <span className="block text-[11px] font-bold uppercase tracking-[0.12em] text-tinta-3">
              Atendimento
            </span>
            <h2 className="mt-1 truncate text-xl font-semibold leading-[1.15] text-tinta">
              Entrevista guiada
            </h2>
            <p className="mt-2 max-w-[76ch] text-sm leading-[1.55] text-tinta-2">
              Conduza o relato, valide a ação cabível e crie o caso sem sair do atendimento.
            </p>
          </div>

          <div className="flex min-w-0 flex-wrap gap-2">
            <Selo tom={mostrarRoteiro ? "info" : qualificacao ? "ok" : "neutro"}>
              Roteiro
            </Selo>
            <Selo tom={resultado ? "ok" : analisando ? "info" : "neutro"}>
              Validação
            </Selo>
            <Selo tom={casoCriado || casoTxtId ? "ok" : "neutro"}>
              Caso
            </Selo>
          </div>
        </div>
      </header>

      <div className="min-w-0 p-4 sm:p-5">
      {mostrarRoteiro ? (
        <EntrevistaComChamada
          /* As respostas sobem a cada mudança: é o que deixa as etapas abaixo
           * do roteiro prontas antes de a entrevista fechar. O relato e o id do
           * áudio vêm junto, pelos mesmos motivos de sempre. */
          onRespostas={(respostas, relato, entrevistaId, trechos) => {
            setTexto(relato);
            setQualificacao(respostas);
            setAudioEntrevista(entrevistaId);
            setTranscricao(trechos);
          }}
          onConcluir={(respostas, relato, entrevistaId, trechos) => {
            /* Finalizar é diferente de apenas avançar para documentação.
             * A tela prometia "chamada desligada", mas só escondia o roteiro:
             * o provedor global continuava conectado e remontava o vídeo, em
             * largura total, embaixo do formulário genérico. */
            chamada.desligar();
            setTexto(relato);
            setQualificacao(respostas);
            setAudioEntrevista(entrevistaId);
            setTranscricao(trechos);
            setMostrarRoteiro(false);
            setEncerrado(true);
            // Encerrou com o caso já criado: regrava a conversa inteira, agora
            // com o fechamento do roteiro dentro dela, e libera a leitura do
            // agente. Sem caso ainda, quem grava é a criação dele, logo abaixo.
            if (casoCriado) {
              void guardarEntrevista(casoCriado, trechos, entrevistaId, true);
            }
          }}
          onFechar={() => setMostrarRoteiro(false)}
          depois={etapasDoAtendimento}
        />
      ) : (
        <Botao
          variante="secundario"
          className="mb-[14px]"
          onClick={() => {
            // Voltar é continuar: o atendimento deixa de estar encerrado e as
            // etapas voltam a ficar à mão, dentro e fora da tela.
            setEncerrado(false);
            setMostrarRoteiro(true);
          }}
        >
          {qualificacao ? "Voltar ao roteiro" : "Começar entrevista guiada"}
        </Botao>
      )}

      {/* O áudio do que acabou de ser conduzido, antes do contrato: quem sai da
        * entrevista costuma querer conferir uma fala antes de seguir. */}
      {!mostrarRoteiro && audioEntrevista && (
        <AudioDaEntrevista entrevistaId={audioEntrevista} />
      )}

      {/* Encerrado o atendimento, as etapas NÃO se repetem.
        *
        * Elas foram feitas lá dentro, na mesma rolagem da entrevista; mostrá-las
        * de novo, zeradas, faz o atendente achar que perdeu o que já tinha feito
        * — foi o que aconteceu. Fica o resumo e o próximo passo. */}
      {encerrado && !mostrarRoteiro && (
        <div className="mt-5 border-l-[3px] border-ok px-[14px] py-3 bg-papel-2 max-w-[74ch] font-normal text-[12.5px] leading-[1.6] font-ui">
          <strong>Atendimento encerrado.</strong> A gravação foi fechada e a chamada,
          desligada.{" "}
          {avaliacaoConcluida
            ? "A avaliação no Google ficou marcada como concluída."
            : "A avaliação no Google ficou EM ABERTO — se o cliente ainda está na linha, volte ao roteiro."}{" "}
          Agora crie o caso abaixo: é ele que abre o checklist e o portal para o cliente
          enviar os documentos.
        </div>
      )}

      {/* Fechou a tela sem encerrar (ou voltou para continuar): as etapas seguem
        * aqui, porque continuam por fazer. */}
      {!encerrado && !mostrarRoteiro && etapasDoAtendimento}

      {/* O importador abaixo também serve para análise avulsa, antes de começar
        * uma entrevista. Depois de FINALIZAR, porém, a conversa já foi lida em
        * duas etapas e revisada dentro do roteiro. Mostrá-lo novamente fazia a
        * tela parecer ter voltado ao início e convidava a analisar tudo duas
        * vezes. */}
      {!encerrado && (
        <>
          <span className="block mb-1 text-tinta text-sm font-bold">Validação após a entrevista — quais ações cabem</span>
          <p className="mb-3 mt-0 max-w-[64ch] text-tinta-3 text-xs leading-[1.55]">
            Analise o relato antes de pedir a avaliação ao cliente. O sistema sugere as ações cabíveis,
            mostra o que sustenta cada uma e compara o caso com a base vetorial. A decisão final é da equipe jurídica.
          </p>

          <div
        className={`rounded-campo border-2 border-dashed p-3 transition-colors ${
          arrastandoArquivo ? "border-tinta bg-papel-2" : "border-transparent"
        }`}
        onDragEnter={(evento) => {
          evento.preventDefault();
          setArrastandoArquivo(true);
        }}
        onDragOver={(evento) => {
          evento.preventDefault();
          evento.dataTransfer.dropEffect = "copy";
        }}
        onDragLeave={(evento) => {
          if (!evento.currentTarget.contains(evento.relatedTarget as Node | null)) {
            setArrastandoArquivo(false);
          }
        }}
        onDrop={(evento) => {
          evento.preventDefault();
          setArrastandoArquivo(false);
          const arquivo = evento.dataTransfer.files?.[0];
          if (arquivo && !analisando) void analisar(arquivo);
        }}
      >
        <RotuloCampo htmlFor="relato-entrevista">Colar entrevista ou arrastar um arquivo</RotuloCampo>
        <Campo
          area
          id="relato-entrevista"
          value={texto}
          onChange={(e) => setTexto(e.target.value)}
          placeholder={
            arrastandoArquivo
              ? "Solte o arquivo aqui"
              : "Cole o relato ou arraste para cá um arquivo que contenha texto…"
          }
        />

      <div className="flex gap-[10px] items-center flex-wrap mt-3">
        <Botao variante="secundario" onClick={() => void analisar()} disabled={analisando || !texto.trim()}>
          {analisando ? "Analisando…" : "Analisar o relato"}
        </Botao>

        <Botao variante="discreto" pequeno onClick={() => inputRef.current?.click()} disabled={analisando}>
          Escolher arquivo com texto
        </Botao>

        <input
          ref={inputRef}
          type="file"
          hidden
          onChange={(e) => {
            const f = e.target.files?.[0];
            if (f) void analisar(f);
            e.target.value = "";
          }}
        />

        {texto.trim() && (
          <span className="ml-auto text-tinta-3 text-xs tabular-nums">{texto.trim().length} caracteres</span>
        )}
      </div>
      <p className="mb-0 mt-2 text-[11px] leading-[1.5] text-tinta-3">
        Aceita texto simples, DOCX, PDF com texto, CSV, JSON, XML, HTML, RTF, legendas e outras extensões cujo conteúdo seja textual.
      </p>
          </div>

          {erro && (
            <div className="mt-3">
              <Aviso tom="critico" titulo="Não foi possível analisar">
                {erro}
              </Aviso>
            </div>
          )}
        </>
      )}

      {resultado && (
        <div className="mt-4 pt-[14px] border-t border-borda">
          <Aviso
            tom={resultado.confiante ? "ok" : "atencao"}
            titulo={
              resultado.confiante
                ? "Sugestão com boa margem de acerto"
                : "Sugestão incerta — confira antes de aceitar"
            }
          >
            {resultado.motivo}
            {resultado.concorrentes && (
              <span className="block mt-[6px] text-xs leading-[1.5]">
                O relato traz um quadro crônico e um acidente ao mesmo tempo. Pode ser mais de uma
                ação — vale abrir os dois casos.
              </span>
            )}
            {resultado.metodo === "pistas" && (
              <span className="block mt-[6px] text-xs leading-[1.5]">
                A classificação saiu de termos encontrados no texto, sem a leitura por
                inteligência artificial, e por isso erra mais.
              </span>
            )}
          </Aviso>

          {resultado.sugestoes.length === 0 ? (
            <p className="py-3 text-tinta-3 text-sm leading-[1.6]">
              Nenhuma sugestão. Escolha o tipo de ação no campo abaixo.
            </p>
          ) : (
            <ul className="list-none mt-3 mb-0 p-0 border border-borda rounded-campo bg-papel overflow-hidden">
              {resultado.sugestoes.map((s, i) => (
                <li key={s.codigo} className="last:[&>button]:border-b-0">
                  <button
                    type="button"
                    className={`${OPCAO_BASE} ${escolhida === s.codigo ? OPCAO_ESCOLHIDA : OPCAO_RESTING}`}
                    onClick={() => {
                      setEscolhida(s.codigo);
                      onEscolher(s.codigo, resultado.dados.cliente);
                    }}
                    aria-pressed={escolhida === s.codigo}
                  >
                    <span className="flex-none w-6 text-tinta-3 font-codigo text-xs tabular-nums pt-[3px]">
                      {i + 1}º
                    </span>
                    <span className="flex-1 min-w-0">
                      <span className="flex items-center gap-2 flex-wrap text-tinta text-base font-semibold">
                        {s.nome}
                        {escolhida === s.codigo && (
                          <Selo tom="ok" simbolo="✓">
                            escolhida
                          </Selo>
                        )}
                      </span>
                      {s.evidencias.slice(0, 2).map((ev, k) => (
                        <span
                          key={k}
                          className="block mt-1 text-tinta-2 text-xs italic leading-[1.5] [overflow-wrap:anywhere]"
                        >
                          “{ev}”
                        </span>
                      ))}
                    </span>
                    <span className="flex-none pt-[3px] text-tinta-3 text-xs tabular-nums whitespace-nowrap">
                      {s.pontos} {s.pontos === 1 ? "ponto" : "pontos"}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      {/* O atendimento que o .txt abriu: gravação em curso + criação do caso.
        *
        * Fica logo abaixo da recomendação — a ordem que o escritório pediu:
        * a IA avalia, diz qual ação recomenda e por quê, a gravação começa e o
        * caso nasce com nome e CPF confirmados. Daí em diante é `CasoEDocumentos`,
        * o mesmo do ao vivo (portal + checklist). */}
      {atendimentoTxt && (
        <div className="mt-4 pt-[14px] border-t border-borda">
          <span className="block mb-1 text-tinta text-sm font-bold">Abrir o atendimento</span>
          <p className="mb-3 mt-0 max-w-[64ch] text-tinta-3 text-xs leading-[1.55]">
            A recomendação acima já está pré-selecionada. A gravação do áudio começou —
            confirme o nome e o CPF do cliente para criar o caso e seguir com o portal e o
            checklist.
          </p>

          <div className="mb-3">
            <Aviso tom={gravInfo.tom} titulo={gravInfo.titulo}>
              {gravacaoAviso || "O áudio e a transcrição deste atendimento estão sendo guardados."}
            </Aviso>
          </div>

          <div className="sticky top-3 z-20 mb-4 max-w-[680px] shadow-[0_10px_30px_rgba(15,23,42,0.16)]">
            <PainelChamada
              modo="documentos"
              onFaixaRemota={(trilha) => {
                const captura = capturaTxtRef.current;
                if (captura) void captura.usarTrilha(trilha);
              }}
            />
          </div>

          <CasoEDocumentos
            editavel
            cliente={nomeTxt}
            onCliente={setNomeTxt}
            cpf={cpfTxt}
            onCpf={setCpfTxt}
            sugerida={categoriaTxt}
            onCategoria={setCategoriaTxt}
            categorias={categorias}
            entrevistaId={entrevistaIdTxt}
            onCriar={onCriarCaso}
            onCasoCriado={async (casoId) => {
              setCasoTxtId(casoId);
              setCasoCriado(casoId);
              // Grava já, ainda sem encerrar: se a aba morrer, o que foi
              // transcrito até aqui não se perde. O encerramento regrava com
              // `concluida`.
              await guardarEntrevista(casoId, trechosTxtRef.current, entrevistaIdTxt, false);
              if (nomeTxt && cpfTxt) {
                try {
                  const existentes = await listarAssinaturas({ cliente: nomeTxt, cpf: cpfTxt });
                  await Promise.allSettled(
                    existentes.map((item) => vincularAssinaturaAoCaso(item.id, casoId)),
                  );
                } catch {
                  // A listagem de assinaturas retoma o vínculo na próxima abertura.
                }
              }
            }}
            onAbrirDossie={onAbrirDossie}
            onAbrirAnalises={onAbrirAnalises}
            emChamada={chamada.estado !== "fora" && chamada.estado !== "encerrada"}
            onEncerrarChamada={chamada.desligar}
          />

          {casoTxtId && gravacaoEstado !== "sem-audio" && (
            <Botao
              variante="secundario"
              className="mt-3"
              disabled={encerrandoTxt}
              onClick={() => void encerrarGravacaoTxt()}
            >
              {encerrandoTxt ? "Encerrando a gravação…" : "Encerrar a gravação do atendimento"}
            </Botao>
          )}
        </div>
      )}

      {(analisandoEstrategia || estrategia || erroEstrategia) && (
        <section className="mt-[18px] pt-4 border-t border-borda" aria-live="polite">
          <div className="flex justify-between items-baseline gap-3 flex-wrap">
            <span className="block mb-1 text-tinta text-sm font-bold">O que dizem processos semelhantes</span>
            {analisandoEstrategia && <span className={ESTADO_TEXTO}>Buscando semelhantes…</span>}
          </div>

          {erroEstrategia && !analisandoEstrategia && <p className={ESTADO_TEXTO}>{erroEstrategia}</p>}

          {estrategia && (
            <>
              <p className="my-[6px] mb-[14px] text-tinta font-titulo text-md leading-[1.5]">
                {estrategia.resumo}
              </p>

              <div className={METRICAS}>
                <div className={METRICA_CARTAO}>
                  <strong className={METRICA_VALOR}>{estrategia.estatisticas.processos_analisados}</strong>
                  <span className={METRICA_ROTULO}>processos semelhantes</span>
                </div>
                <div className={METRICA_CARTAO}>
                  <strong className={METRICA_VALOR}>{estrategia.estatisticas.desfechos_merito.percentual}%</strong>
                  <span className={METRICA_ROTULO}>procedente ou parcial entre casos julgados no mérito</span>
                </div>
              </div>

              {estrategia.estatisticas.resultados.length > 0 && (
                <div className={FAIXA_DADOS}>
                  <h4 className={FAIXA_TITULO}>Desfechos na amostra</h4>
                  <p className={FAIXA_TEXTO}>{estrategia.estatisticas.resultados.map((i) => `${i.nome}: ${i.quantidade} (${i.percentual}%)`).join(" · ")}</p>
                </div>
              )}

              {estrategia.estatisticas.varas.length > 0 && (
                <div className={FAIXA_DADOS}>
                  <h4 className={FAIXA_TITULO}>Varas mais presentes</h4>
                  <p className={FAIXA_TEXTO}>{estrategia.estatisticas.varas.slice(0, 4).map((i) => `${i.nome} (${i.quantidade})`).join(" · ")}</p>
                </div>
              )}

              {estrategia.estatisticas.magistrados.length > 0 && (
                <div className={FAIXA_DADOS}>
                  <h4 className={FAIXA_TITULO}>Magistrados identificados nos documentos</h4>
                  <p className={FAIXA_TEXTO}>{estrategia.estatisticas.magistrados.slice(0, 4).map((i) => `${i.nome} (${i.quantidade})`).join(" · ")}</p>
                </div>
              )}

              <div className={COLUNAS_INSIGHTS}>
                <div>
                  <h4 className={FAIXA_TITULO}>Próximas ações sugeridas</h4>
                  <ul className={LISTA_INSIGHT}>{estrategia.acoes.map((item, i) => <li key={i} className={ITEM_INSIGHT}><strong className="text-tinta">{item.acao} {item.forca && `· força ${item.forca}`}</strong><span className="block text-tinta-3">{item.porque} {item.aplicabilidade && ` Aplicável porque: ${item.aplicabilidade}`} {item.contrapontos && ` Contraponto: ${item.contrapontos}`} {item.precedentes.join(", ")}</span></li>)}</ul>
                </div>
                <div>
                  <h4 className={FAIXA_TITULO}>Riscos e pontos a confirmar</h4>
                  <ul className={LISTA_INSIGHT}>
                    {estrategia.riscos.map((item, i) => <li key={`r-${i}`} className={ITEM_INSIGHT}><strong className="text-tinta">{item.risco} {item.forca && `· força ${item.forca}`}</strong><span className="block text-tinta-3">{item.aplicabilidade && `Aplicável porque: ${item.aplicabilidade}. `}{item.contrapontos && `Contraponto: ${item.contrapontos}. `}{item.precedentes.join(", ")}</span></li>)}
                    {estrategia.lacunas.map((item, i) => <li key={`l-${i}`} className={ITEM_INSIGHT}>{item}</li>)}
                  </ul>
                </div>
              </div>

              {!!estrategia.divergencias?.length && (
                <div className={FAIXA_DADOS}>
                  <h4 className={FAIXA_TITULO}>Divergências entre os processos</h4>
                  <p className={FAIXA_TEXTO}>{estrategia.divergencias.map((d) => `${d.ponto} (favoráveis: ${d.precedentes_favoraveis.join(", ") || "—"}; contrários: ${d.precedentes_contrarios.join(", ") || "—"})`).join(" · ")}</p>
                </div>
              )}

              {!!estrategia.perguntas_criticas?.length && (
                <div className={FAIXA_DADOS}>
                  <h4 className={FAIXA_TITULO}>Perguntas críticas para a entrevista</h4>
                  <p className={FAIXA_TEXTO}>{estrategia.perguntas_criticas.join(" · ")}</p>
                </div>
              )}

              <details className={PRECEDENTES}>
                <summary className="text-acao text-sm font-semibold cursor-pointer">Ver processos usados como referência</summary>
                <ul className={LISTA_INSIGHT}>{estrategia.precedentes.map((p) => <li key={p.indice} className={ITEM_INSIGHT}><strong className="text-tinta">{p.indice}</strong> {p.processo || "processo não informado"} · {p.resultado || "sem desfecho"}{p.vara ? ` · ${p.vara}` : ""}</li>)}</ul>
              </details>
              <p className={`${ESTADO_TEXTO} mt-3`}>{estrategia.estatisticas.aviso} Similaridade mediana: {estrategia.estatisticas.similaridade_amostra.mediana}.</p>
            </>
          )}
        </section>
      )}

      </div>
    </section>
  );
}
