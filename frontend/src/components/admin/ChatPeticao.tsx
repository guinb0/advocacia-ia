"use client";

/* O chat da petição — a conversa ancorada ao lado da minuta, dentro do Dossiê.
 *
 * Substitui o que antes eram dois quadrados parados ("Confirmado por documentos" e
 * "Depende de prova ou confirmação") mais três botões: dava para disparar ações e não
 * dava para PERGUNTAR nada. Quem queria entender por que um ponto estava pendente não
 * tinha a quem perguntar; quem queria mudar uma linha da peça tinha de descrever a
 * mudança num campo, sem conversa antes.
 *
 * Três regras moldam o componente:
 *
 * 1. A PEÇA NÃO SAI DA TELA. É coluna à direita, não aba. A resposta cita "o item II dos
 *    pedidos" e ele está ali ao lado, visível.
 * 2. NADA É APLICADO SEM CLIQUE. Toda alteração chega como proposta, com o que vai
 *    acontecer escrito, e vira comparação (antes × depois) antes de virar versão.
 * 3. O QUE VEIO DA WEB TEM CARA DE WEB. Fonte e link, em bloco próprio, nunca com a
 *    mesma aparência do que veio dos autos do caso.
 *
 * E uma regra de uso, vinda da primeira leitura da tela pronta: quem abre isto não sabe
 * o que pode pedir. Por isso o começo da conversa não é um campo vazio com uma frase
 * explicando — são três coisas concretas para clicar, e elas continuam ao alcance como
 * atalhos depois que a conversa começa.
 */

import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";

import { Aviso, Botao, Selo } from "@/components/ui/Basicos";
import VisorEntrega from "@/components/caso/VisorEntrega";
import { baixarArquivoEntrega, enviarDocumentosEmLote } from "@/lib/api";
import {
  DocumentosCitaveis,
  RespostaFormatada,
  dominioDe,
  type DocumentoCitavelMd,
} from "@/components/ui/Markdown";
import estilos from "@/components/admin/ChatPeticao.module.css";
import {
  EVENTO_DO_CHAT,
  abrirChatDaPeticao,
  adicionarContextoAoChat,
  atualizarContextoDoChat,
  criarConversaDoChat,
  excluirConversaDoChat,
  executarAcaoDoChat,
  listarConversasDoChat,
  listarDocumentosDoChat,
  obterContextoDoChat,
  perguntarNoChat,
  registrarEventoNoChat,
  type AcaoProposta,
  type AvisoParaOChat,
  type ConfiancaDaFonte,
  type DocumentoCitavel,
  type FonteDaWeb,
  type MensagemDoChat,
  type ResumoDaConversa,
  type ResumoDoContexto,
} from "@/lib/chatPeticao";

/**
 * O que dá para pedir aqui, em três coisas concretas.
 *
 * `envia: true` manda a pergunta como está — ela se basta. As outras duas ESCREVEM o
 * começo da frase no campo e deixam o cursor no fim: "busque na web" sem o assunto e
 * "altere a peça" sem dizer o quê não são pedidos, e mandá-las prontas gastaria uma
 * volta no modelo só para receber de volta "sobre o quê?".
 */
const ATALHOS: { rotulo: string; dica: string; texto: string; envia: boolean }[] = [
  {
    rotulo: "Entender a peça",
    dica: "O que ainda não tem prova, o que está frágil, por quê",
    texto: "O que nesta petição ainda não tem comprovação documental, e por quê?",
    envia: true,
  },
  {
    rotulo: "Buscar na web",
    dica: "Jurisprudência, súmula, lei — sempre com a fonte e o link",
    texto: "Pesquise na web ",
    envia: false,
  },
  {
    rotulo: "Alterar a petição",
    dica: "Você vê o antes × depois e decide antes de virar versão",
    texto: "Altere a petição: ",
    envia: false,
  },
  {
    rotulo: "Incluir trecho ou print",
    dica: "Um trecho de documento ou um print, na seção que você escolher",
    texto: "Inclua na petição, na seção ",
    envia: false,
  },
];

/** O quarto caminho: existe como link no painel, e aqui vira pergunta. */
const CONFRONTO = "Mostre o confronto entre a entrevista e os documentos.";

interface Props {
  casoId: string;
  /** Recarrega a minuta e o histórico do lado esquerdo: é o que faz a comparação
   *  proposta pelo chat aparecer sobre o documento. */
  aoMudarAPeticao: () => void;
  /** Fecha a gaveta. Em tela larga o painel é coluna fixa e o botão não aparece. */
  aoFechar?: () => void;
  /** Alterna entre a coluna normal e a larga. Quem manda na grade é o `FluxoPeticao`. */
  expandido?: boolean;
  aoAlternarLargura?: () => void;
}

export default function ChatPeticao({
  casoId,
  aoMudarAPeticao,
  aoFechar,
  expandido,
  aoAlternarLargura,
}: Props) {
  const [mensagens, setMensagens] = useState<MensagemDoChat[]>([]);
  const [carregandoHistorico, setCarregandoHistorico] = useState(true);
  const [modeloDisponivel, setModeloDisponivel] = useState(true);
  const [texto, setTexto] = useState("");
  const [parcial, setParcial] = useState("");
  /* Se o modelo começa a responder e depois percebe que precisa consultar algo,
   * preservamos o rascunho, claramente marcado, em vez de fazê-lo sumir. */
  const [rascunhoEmConferencia, setRascunhoEmConferencia] = useState("");
  const parcialNaTela = useRef("");
  const [etapa, setEtapa] = useState("");
  const [enviando, setEnviando] = useState(false);
  const [erro, setErro] = useState("");
  /* O histórico: qual conversa está aberta, quais existem e o que a base do caso já tem.
   * `alvo` é o que se PEDIU abrir (null = a mais recente); vive junto do caso para que
   * trocar de petição nunca herde a conversa escolhida na anterior. */
  const [alvo, setAlvo] = useState<{ caso: string; id: string | null }>({ caso: casoId, id: null });
  const [recarga, setRecarga] = useState(0);
  const [conversaId, setConversaId] = useState("");
  const [conversas, setConversas] = useState<ResumoDaConversa[]>([]);
  const [contexto, setContexto] = useState<ResumoDoContexto | null>(null);
  const [historicoAberto, setHistoricoAberto] = useState(false);
  const [atualizandoBase, setAtualizandoBase] = useState(false);
  const idAlvo = alvo.caso === casoId ? alvo.id : null;
  const [arquivoContexto, setArquivoContexto] = useState<File | null>(null);
  const [relevanciaContexto, setRelevanciaContexto] = useState("");
  const [enviandoContexto, setEnviandoContexto] = useState(false);
  /* Os prints que acabaram de virar anexo do caso, à espera de o advogado dizer em que
   * seção entram. */
  const [enviandoPrint, setEnviandoPrint] = useState(false);
  const [printsAnexados, setPrintsAnexados] = useState<string[]>([]);
  const [previewsPrint, setPreviewsPrint] = useState<Array<{ nome: string; url: string; largura: number }>>([]);
  /* As propostas já decididas nesta sessão. Some o par de botões sem apagar a mensagem:
   * a transcrição precisa continuar mostrando o que foi proposto e aceito. */
  const [decididas, setDecididas] = useState<Record<string, "aceita" | "descartada">>({});
  const [executando, setExecutando] = useState<string | null>(null);
  /* Os anexos que a resposta pode citar. O nome do arquivo (ou o tipo, quando é único)
   * vira link e abre o documento aqui mesmo, no visor do checklist — antes o advogado
   * lia "a CTPS (IMG_4411.jpg)" e tinha de ir ao checklist procurar o arquivo. */
  const [documentos, setDocumentos] = useState<DocumentoCitavel[]>([]);
  const [documentoAberto, setDocumentoAberto] = useState<DocumentoCitavelMd | null>(null);
  /* Quem rolou para cima está LENDO. Empurrar a conversa para o fim a cada pedaço de
   * texto que chega arranca do meio da leitura a resposta anterior, e não há como voltar
   * a ela sem procurar. Enquanto isso, o botão de descer diz que chegou coisa nova. */
  const [preso, setPreso] = useState(true);
  const conversa = useRef<HTMLDivElement>(null);
  const campo = useRef<HTMLTextAreaElement>(null);
  /* De QUAL caso é o que está na tela agora. O Dossiê vive em estado, e não em rota
   * (ver `app/home/home.model.ts`): voltar no navegador para o dossiê de outro caso
   * troca o `casoId` SEM remontar este componente. Sem esta referência, uma resposta
   * ou uma ação pedida no caso anterior voltaria do servidor depois da troca e entraria
   * na transcrição do caso novo. */
  const casoNaTela = useRef(casoId);
  /* E de QUAL conversa do caso. Trocar pelo histórico é como trocar de caso: uma resposta
   * ou uma ação que volte do servidor depois da troca ficou gravada na conversa certa, e
   * não pode aparecer nesta. */
  const conversaNaTela = useRef("");
  /* A pergunta em voo pertence ao caso em que foi feita: trocar de caso a cancela, em
   * vez de deixá-la escrevendo no fluxo de outra conversa. */
  const emVoo = useRef<AbortController | null>(null);
  /* Uma confirmação em andamento por vez. O `disabled` do botão só vale depois do próximo
   * render: dois cliques no mesmo quadro executariam a proposta duas vezes — e uma
   * revisão executada duas vezes substitui a comparação que a primeira abriu. */
  const confirmando = useRef(false);

  /* O que o servidor já executou. Sem isto, o F5 devolvia o botão «Confirmar» a
   * propostas que já tinham sido aplicadas, e um segundo clique as repetia. A prova é a
   * mensagem de sucesso gravada DEPOIS da proposta, com a mesma ação. */
  const executadas = useMemo(() => {
    const saida: Record<string, "aceita"> = {};
    mensagens.forEach((mensagem, indice) => {
      mensagem.acoes.forEach((acao, posicao) => {
        const alvo = acao.pedido || acao.titulo || acao.anexoId || "";
        const feita = mensagens.slice(indice + 1).some((seguinte) => {
          const feito = seguinte.acaoExecutada;
          return (
            !!feito &&
            feito.tipo === acao.tipo &&
            (feito.pedido || feito.titulo || feito.anexoId || "") === alvo
          );
        });
        if (feita) saida[`${mensagem.id}:${posicao}`] = "aceita";
      });
    });
    return saida;
  }, [mensagens]);
  const decisoes = useMemo(() => ({ ...decididas, ...executadas }), [decididas, executadas]);

  const descer = useCallback(() => {
    // `scrollTop` no contêiner, e não `scrollIntoView`: com o painel em coluna sticky, o
    // `scrollIntoView` arrastava a PÁGINA inteira junto, e o documento ao lado saía da
    // vista a cada pedaço de resposta que chegava.
    const alvo = conversa.current;
    if (alvo) alvo.scrollTop = alvo.scrollHeight;
    setPreso(true);
  }, []);

  const ajustarAltura = useCallback(() => {
    const alvo = campo.current;
    if (!alvo) return;
    // Zerar antes de medir: sem isto o `scrollHeight` nunca diminui e o campo fica
    // grande para sempre depois de uma pergunta longa.
    alvo.style.height = "auto";
    alvo.style.height = `${Math.min(alvo.scrollHeight, 168)}px`;
  }, []);

  useEffect(() => {
    let ativo = true;
    /* Zerar ANTES de buscar a conversa nova. A transcrição é renderizada mesmo durante o
     * carregamento, então sem esta limpeza a conversa anterior seguiria na tela sob o aviso
     * "Abrindo a conversa…" — e o pior: as propostas já aceitas ou descartadas lá
     * (`decididas`, que é chave de mensagem) continuariam valendo aqui, além do rascunho no
     * campo e do erro da outra. Vale para trocar de caso E de conversa. */
    casoNaTela.current = casoId;
    conversaNaTela.current = "";
    emVoo.current?.abort();
    emVoo.current = null;
    setMensagens([]);
    setDocumentos([]);
    setDocumentoAberto(null);
    setDecididas({});
    setExecutando(null);
    setTexto("");
    setPrintsAnexados([]);
    setParcial("");
    parcialNaTela.current = "";
    setRascunhoEmConferencia("");
    setEtapa("");
    setEnviando(false);
    setErro("");
    setPreso(true);
    setHistoricoAberto(false);
    setCarregandoHistorico(true);
    void abrirChatDaPeticao(casoId, idAlvo ?? undefined)
      .then((chat) => {
        if (!ativo) return;
        conversaNaTela.current = chat.id;
        setConversaId(chat.id);
        setConversas(chat.conversas);
        setContexto(chat.contexto);
        setMensagens(chat.mensagens);
        setModeloDisponivel(chat.modeloDisponivel);
        setDocumentos(chat.documentos);
      })
      .catch((falha) => {
        if (ativo) setErro(falha instanceof Error ? falha.message : "Não foi possível abrir a conversa.");
      })
      .finally(() => ativo && setCarregandoHistorico(false));
    return () => {
      ativo = false;
    };
  }, [casoId, idAlvo, recarga]);

  /* O histórico e a base do caso mudam a cada resposta: o título nasce da primeira pergunta,
   * a conversa sobe para o topo e o que já foi levantado cresce. */
  const renovarLaterais = useCallback(() => {
    const doCaso = casoId;
    void listarConversasDoChat(doCaso)
      .then((lista) => {
        if (casoNaTela.current === doCaso) setConversas(lista);
      })
      .catch(() => {});
    void obterContextoDoChat(doCaso)
      .then((resumo) => {
        if (casoNaTela.current === doCaso) setContexto(resumo);
      })
      .catch(() => {});
  }, [casoId]);

  /** Relê os anexos: o que foi enviado pelo checklist com a conversa aberta também
   *  precisa virar link. Falhar aqui só deixa a lista como estava. */
  const atualizarDocumentos = useCallback(() => {
    const doCaso = casoId;
    void listarDocumentosDoChat(doCaso)
      .then((lista) => {
        if (casoNaTela.current === doCaso) setDocumentos(lista);
      })
      .catch(() => {});
  }, [casoId]);

  useEffect(() => {
    if (preso) descer();
  }, [mensagens, parcial, etapa, preso, descer]);

  /* O campo acompanha o que se escreve e para de crescer em ~6 linhas. As três linhas
   * fixas de antes roubavam altura da leitura mesmo quando a pergunta tinha cinco
   * palavras — e prendiam o pedido longo numa janelinha com rolagem própria. Rodar isto
   * por efeito, e não só no `onChange`, cobre também o que o código escreve no campo:
   * os atalhos que começam a frase e a limpeza depois do envio. */
  useEffect(ajustarAltura, [texto, ajustarAltura]);

  /* O que os BOTÕES do painel fizeram chega por evento de janela (ver
   * `lib/chatPeticao.avisarChatDaPeticao`). A IA conta na conversa o que mudou — é
   * depois de uma geração que o advogado mais precisa saber o que ficou sem prova. */
  useEffect(() => {
    async function aoAvisar(evento: Event) {
      const { detail } = evento as CustomEvent<AvisoParaOChat>;
      if (!detail || detail.casoId !== casoId) return;
      const daConversa = conversaNaTela.current;
      try {
        const mensagem = await registrarEventoNoChat(casoId, detail.tipo, detail.dados ?? {}, daConversa);
        // A ida ao servidor demora: se o dossiê (ou a conversa) já é outro, a mensagem ficou
        // gravada no lugar certo e só não pode aparecer nesta.
        if (mensagem && casoNaTela.current === casoId && conversaNaTela.current === daConversa) {
          setMensagens((atuais) => [...atuais, mensagem]);
        }
      } catch {
        /* O aviso é complementar: a ação já aconteceu e o painel já a mostrou. Falhar
         * aqui não pode transformar um sucesso em mensagem de erro. */
      }
    }
    window.addEventListener(EVENTO_DO_CHAT, aoAvisar);
    return () => window.removeEventListener(EVENTO_DO_CHAT, aoAvisar);
  }, [casoId]);

  /* A conexão caiu no meio da resposta (rede móvel, tela bloqueada, proxy). O servidor
   * termina de escrever e grava a resposta de qualquer jeito: espera por ela em vez de
   * deixar a pergunta sem retorno — e sem o advogado ter de perguntar tudo de novo. */
  const aguardarResposta = useCallback(async (doCaso: string, daConversa: string) => {
    const continua = () => casoNaTela.current === doCaso && conversaNaTela.current === daConversa;
    setEtapa("A conexão caiu. Buscando a resposta no servidor");
    for (let tentativa = 0; tentativa < 20; tentativa += 1) {
      await new Promise((resolver) => setTimeout(resolver, 3000));
      if (!continua()) return;
      try {
        const chat = await abrirChatDaPeticao(doCaso, daConversa || undefined);
        if (!continua()) return;
        const ultima = chat.mensagens[chat.mensagens.length - 1];
        if (ultima && ultima.papel === "ASSISTANT") {
          setMensagens(chat.mensagens);
          return;
        }
      } catch {
        /* Sem rede ainda: a próxima volta tenta de novo. */
      }
    }
    if (continua()) {
      setErro("A resposta não chegou. Reabra a conversa em instantes — ela fica salva no servidor.");
    }
  }, []);

  const perguntar = useCallback(
    async (pergunta: string) => {
      const limpa = pergunta.trim();
      if (!limpa || enviando) return;
      const controle = new AbortController();
      emVoo.current?.abort();
      emVoo.current = controle;
      const daConversa = conversaNaTela.current;
      /** Esta pergunta ainda é a que está na tela? Deixa de ser quando o caso troca. */
      const ehDaTela = () => emVoo.current === controle;
      setErro("");
      setTexto("");
      setPrintsAnexados([]);
      setParcial("");
      parcialNaTela.current = "";
      setRascunhoEmConferencia("");
      setEtapa("Lendo o caso");
      setEnviando(true);
      setPreso(true);
      try {
        const concluiu = await perguntarNoChat(
          casoId,
          limpa,
          (evento) => {
            // Chegou tarde: o dossiê na tela já é outro. A resposta continua gravada na
            // conversa do caso que a pediu — só não invade a transcrição deste.
            if (!ehDaTela()) return;
            switch (evento.tipo) {
              case "pergunta":
                setMensagens((atuais) => [...atuais, evento.mensagem]);
                break;
              case "etapa":
                setEtapa(evento.texto);
                break;
              case "delta":
                setEtapa("");
                setParcial((anterior) => {
                  const atualizado = anterior + evento.texto;
                  parcialNaTela.current = atualizado;
                  return atualizado;
                });
                break;
              case "recomeco":
                if (parcialNaTela.current.trim()) setRascunhoEmConferencia(parcialNaTela.current);
                parcialNaTela.current = "";
                setParcial("");
                break;
              case "fim":
                setParcial("");
                parcialNaTela.current = "";
                setRascunhoEmConferencia("");
                setEtapa("");
                setMensagens((atuais) => [...atuais, evento.mensagem]);
                atualizarDocumentos();
                renovarLaterais();
                break;
              case "erro":
                setParcial("");
                parcialNaTela.current = "";
                setRascunhoEmConferencia("");
                setEtapa("");
                if (evento.mensagem) setMensagens((atuais) => [...atuais, evento.mensagem!]);
                else setErro(evento.texto);
                break;
            }
          },
          controle.signal,
          daConversa,
        );
        if (!concluiu && ehDaTela()) await aguardarResposta(casoId, daConversa);
      } catch (falha) {
        // O cancelamento pela troca de caso não é falha de ninguém: avisar "a conversa
        // não chegou ao servidor" no caso recém-aberto seria mentira.
        if (ehDaTela()) {
          setErro(
            falha instanceof Error
              ? falha.message
              : "A conversa não chegou ao servidor. Tente de novo.",
          );
        }
      } finally {
        if (ehDaTela()) {
          emVoo.current = null;
          setEnviando(false);
          setEtapa("");
          setParcial("");
          parcialNaTela.current = "";
          setRascunhoEmConferencia("");
        }
      }
    },
    [casoId, enviando, atualizarDocumentos, aguardarResposta, renovarLaterais],
  );

  /** Atalho que não se basta: escreve o começo da frase e devolve o cursor ao campo. */
  function comecarFrase(inicio: string) {
    setTexto(inicio);
    const alvo = campo.current;
    if (!alvo) return;
    alvo.focus();
    // No FIM do texto: o cursor no lugar errado faz a pessoa escrever
    // "Pesquise na webestabilidade acidentária".
    requestAnimationFrame(() => alvo.setSelectionRange(inicio.length, inicio.length));
  }

  function usarAtalho(atalho: (typeof ATALHOS)[number]) {
    if (atalho.envia) void perguntar(atalho.texto);
    else comecarFrase(atalho.texto);
  }

  async function decidir(chave: string, acao: AcaoProposta, aceitar: boolean, generaliza = false) {
    if (!aceitar) {
      setDecididas((atuais) => ({ ...atuais, [chave]: "descartada" }));
      return;
    }
    if (confirmando.current) return;
    confirmando.current = true;
    const doCaso = casoId;
    const daConversa = conversaNaTela.current;
    const continua = () => casoNaTela.current === doCaso && conversaNaTela.current === daConversa;
    setExecutando(chave);
    setErro("");
    try {
      const resultado = await executarAcaoDoChat(doCaso, { ...acao, generaliza }, daConversa);
      // Gerar ou revisar leva tempo: se o dossiê (ou a conversa) na tela já é outro, a ação
      // valeu no lugar certo e nada dela pode aparecer — nem o resultado, nem o recarregamento.
      if (!continua()) return;
      setMensagens((atuais) => [...atuais, resultado.mensagem]);
      // Só uma ação que DEU CERTO fecha o cartão. Marcá-lo «Executada» quando o servidor
      // devolveu falha tirava o botão e deixava o advogado sem como tentar de novo — a
      // mensagem de erro da ação não tem «tentar de novo» — e ele tinha de pedir tudo outra vez.
      if (resultado.ok) setDecididas((atuais) => ({ ...atuais, [chave]: "aceita" }));
      // Mesmo quando a ação falha, o lado esquerdo é recarregado: uma revisão pode ter
      // sido gravada e a falha vir do passo seguinte, e a tela não pode ficar mostrando
      // uma peça mais velha do que a que está no banco.
      aoMudarAPeticao();
    } catch (falha) {
      if (!continua()) return;
      setErro(falha instanceof Error ? falha.message : "A ação não pôde ser executada.");
    } finally {
      // A troca de caso já zerou o `executando`; mexer nele aqui apagaria o indicador de
      // uma ação que esteja rodando no caso agora aberto.
      if (continua()) setExecutando(null);
      confirmando.current = false;
    }
  }

  const conversaVazia = !carregandoHistorico && mensagens.length === 0;
  const conversaAtual = conversas.find((c) => c.id === conversaId);
  const tituloAtual =
    conversaAtual && conversaAtual.perguntas > 0 ? conversaAtual.titulo : "Nova conversa";

  function abrirConversa(id: string) {
    setHistoricoAberto(false);
    if (id === conversaId) return;
    setAlvo({ caso: casoId, id });
  }

  /* Um chat em branco. Se este já está em branco não abre outro: encheria o histórico de
   * conversas vazias a cada clique. */
  async function novaConversa() {
    setHistoricoAberto(false);
    if (conversaAtual && conversaAtual.perguntas === 0 && mensagens.length === 0) {
      campo.current?.focus();
      return;
    }
    try {
      const chat = await criarConversaDoChat(casoId);
      setAlvo({ caso: casoId, id: chat.id });
      requestAnimationFrame(() => campo.current?.focus());
    } catch (falha) {
      setErro(falha instanceof Error ? falha.message : "Não foi possível abrir uma nova conversa.");
    }
  }

  async function excluirConversa(conversa: ResumoDaConversa) {
    if (!window.confirm(`Excluir a conversa «${conversa.titulo}»? Ela some do histórico.`)) return;
    try {
      await excluirConversaDoChat(casoId, conversa.id);
      setConversas((atuais) => atuais.filter((c) => c.id !== conversa.id));
      if (conversa.id === conversaId) {
        // A que estava aberta saiu: cai na mais recente (ou numa em branco). O `recarga` força a
        // releitura mesmo quando o alvo já era «a mais recente».
        setAlvo({ caso: casoId, id: null });
        setRecarga((n) => n + 1);
      }
    } catch (falha) {
      setErro(falha instanceof Error ? falha.message : "Não foi possível excluir a conversa.");
    }
  }

  /* Refaz o levantamento dos documentos. As pesquisas na web continuam guardadas. */
  async function atualizarBase() {
    if (atualizandoBase) return;
    const doCaso = casoId;
    setAtualizandoBase(true);
    try {
      const resumo = await atualizarContextoDoChat(doCaso);
      if (casoNaTela.current === doCaso) setContexto(resumo);
    } catch (falha) {
      if (casoNaTela.current === doCaso) {
        setErro(falha instanceof Error ? falha.message : "Não foi possível atualizar a base do caso.");
      }
    } finally {
      setAtualizandoBase(false);
    }
  }

  /* Print colado (Ctrl+V) ou escolhido no botão: vira ANEXO do caso, e não texto solto.
   * É assim que o chat consegue oferecê-lo na peça — a ferramenta de foto só enxerga o que
   * está nos anexos — e que o print continua disponível no checklist. */
  async function anexarPrint(arquivos: File[]) {
    const imagens = arquivos.filter((arquivo) => arquivo.type.startsWith("image/"));
    if (!imagens.length || enviandoPrint) return;
    const doCaso = casoId;
    setEnviandoPrint(true);
    setErro("");
    try {
      const carimbo = new Date().toISOString().replace(/[-:T]/g, "").slice(0, 14);
      // A captura colada chega sempre como «image.png»: dois prints teriam o MESMO nome e o
      // chat não saberia distinguir qual dos dois o advogado quer.
      const nomeados = imagens.map((arquivo, indice) => {
        if (arquivo.name && !/^image\.(png|jpe?g|gif|webp)$/i.test(arquivo.name)) return arquivo;
        const extensao = (arquivo.type.split("/")[1] || "png").replace("jpeg", "jpg");
        const sufixo = imagens.length > 1 ? `-${indice + 1}` : "";
        return new File([arquivo], `print-${carimbo}${sufixo}.${extensao}`, { type: arquivo.type });
      });
      const resultado = await enviarDocumentosEmLote(doCaso, nomeados);
      if (casoNaTela.current !== doCaso) return;
      const nomes = resultado.recebidos.map((recebido) => recebido.arquivo);
      if (resultado.recusados.length) {
        setErro(
          "Não foi possível anexar: " +
            resultado.recusados.map((recusado) => `${recusado.arquivo} (${recusado.motivo})`).join("; "),
        );
      }
      if (nomes.length) {
        setPrintsAnexados(nomes);
        setPreviewsPrint((atuais) => [
          ...atuais,
          ...nomeados.slice(0, nomes.length).map((arquivo, indice) => ({
            nome: nomes[indice] ?? arquivo.name,
            url: URL.createObjectURL(arquivo),
            largura: 100,
          })),
        ]);
        setTexto((atual) =>
          atual.trim() ? atual : `Inclua o print «${nomes.join("», «")}» na seção `,
        );
        atualizarDocumentos();
        const alvo = campo.current;
        if (alvo) requestAnimationFrame(() => alvo.setSelectionRange(alvo.value.length, alvo.value.length));
        alvo?.focus();
      }
    } catch (falha) {
      if (casoNaTela.current === doCaso) {
        setErro(falha instanceof Error ? falha.message : "Não foi possível anexar o print.");
      }
    } finally {
      if (casoNaTela.current === doCaso) setEnviandoPrint(false);
    }
  }

  async function enviarContexto() {
    if (!arquivoContexto || enviandoContexto) return;
    setEnviandoContexto(true);
    setErro("");
    try {
      const resultado = await adicionarContextoAoChat(casoId, arquivoContexto, relevanciaContexto, conversaNaTela.current);
      setMensagens((atuais) => [...atuais, resultado.mensagem]);
      setArquivoContexto(null);
      setRelevanciaContexto("");
    } catch (falha) {
      setErro(falha instanceof Error ? falha.message : "Não foi possível adicionar o arquivo como contexto.");
    } finally {
      setEnviandoContexto(false);
    }
  }

  return (
    <aside className={estilos.painel} aria-label="Conversa com a IA sobre esta petição">
      {/* Uma linha só. O ícone em quadro e a frase explicativa que moravam aqui comiam
        * altura em TODA a conversa para dizer, o tempo inteiro, algo que só interessa
        * antes da primeira pergunta — e é onde eles estão agora, no convite abaixo. */}
      <header className={estilos.cabecalho}>
        <div className={estilos.identidade}>
          <span className={estilos.marca} aria-hidden>
            <IconeConversa />
          </span>
          <div className={estilos.blocoDoTitulo}>
            <strong className={estilos.titulo} title={tituloAtual}>
              {tituloAtual}
            </strong>
            <span className={estilos.subtitulo}>Conversa sobre a peça</span>
          </div>
        </div>
        <div className={estilos.acoesDoCabecalho}>
          <button
            type="button"
            className={`${estilos.iconeBotao} ${estilos.iconeDestaque}`}
            onClick={() => void novaConversa()}
            disabled={carregandoHistorico}
            aria-label="Nova conversa"
            title="Nova conversa"
          >
            <IconeMais />
          </button>
          <button
            type="button"
            className={`${estilos.iconeBotao} ${historicoAberto ? estilos.iconeAtivo : ""}`}
            onClick={() => setHistoricoAberto((aberto) => !aberto)}
            aria-label="Histórico de conversas"
            aria-expanded={historicoAberto}
            title={`Histórico de conversas${conversas.length ? ` (${conversas.length})` : ""}`}
          >
            <IconeHistorico />
          </button>
          {aoAlternarLargura && (
            <button
              type="button"
              className={`${estilos.iconeBotao} max-lg:hidden`}
              onClick={aoAlternarLargura}
              aria-label={expandido ? "Estreitar a conversa" : "Alargar a conversa"}
              title={
                expandido ? "Estreitar — mais espaço para o documento" : "Alargar a conversa"
              }
            >
              <IconeLargura invertido={expandido} />
            </button>
          )}
          {aoFechar && (
            <button
              type="button"
              className={`${estilos.iconeBotao} lg:hidden`}
              onClick={aoFechar}
              aria-label="Fechar a conversa"
              title="Fechar"
            >
              <IconeFechar />
            </button>
          )}
        </div>
      </header>

      {contexto && !contexto.indisponivel && (
        <div
          className={estilos.contexto}
          title="O que o chat já levantou fica guardado com a petição: ele não relê os documentos nem refaz a pesquisa a cada pergunta."
        >
          <span className={estilos.contextoRotulo}>Base do caso</span>
          <span className={estilos.chip}>
            {contexto.documentosLidos} {contexto.documentosLidos === 1 ? "documento lido" : "documentos lidos"}
          </span>
          {contexto.documentosSemLeitura > 0 && (
            <span className={`${estilos.chip} ${estilos.chipAtencao}`}>
              {contexto.documentosSemLeitura} sem leitura
            </span>
          )}
          {contexto.pesquisas > 0 && (
            <span className={estilos.chip}>
              {contexto.pesquisas} {contexto.pesquisas === 1 ? "pesquisa" : "pesquisas"}
            </span>
          )}
          {contexto.buscas > 0 && (
            <span className={estilos.chip}>
              {contexto.buscas} {contexto.buscas === 1 ? "busca" : "buscas"}
            </span>
          )}
          <button
            type="button"
            className={estilos.atualizarBase}
            onClick={() => void atualizarBase()}
            disabled={atualizandoBase}
            title="Refazer o levantamento dos documentos (as pesquisas na web continuam guardadas)"
          >
            <IconeAtualizar girando={atualizandoBase} />
            {atualizandoBase ? "Atualizando…" : "Atualizar"}
          </button>
        </div>
      )}

      {historicoAberto && (
        <>
          <div className={estilos.fundoDoHistorico} onClick={() => setHistoricoAberto(false)} aria-hidden />
          <div className={estilos.historico} role="menu" aria-label="Histórico de conversas">
            <div className={estilos.historicoTopo}>
              <strong>Conversas desta petição</strong>
              <button type="button" className={estilos.novaNoHistorico} onClick={() => void novaConversa()}>
                + Nova conversa
              </button>
            </div>
            {conversas.length === 0 ? (
              <p className={estilos.vazio}>Nenhuma conversa ainda.</p>
            ) : (
              <ul className={estilos.listaDeConversas}>
                {conversas.map((c) => (
                  <li
                    key={c.id}
                    className={`${estilos.itemDaConversa} ${c.id === conversaId ? estilos.itemAtivo : ""}`}
                  >
                    <button
                      type="button"
                      role="menuitem"
                      className={estilos.itemCorpo}
                      onClick={() => abrirConversa(c.id)}
                    >
                      <span className={estilos.itemTitulo}>
                        {c.perguntas > 0 ? c.titulo : "Nova conversa"}
                      </span>
                      <span className={estilos.itemMeta}>
                        {quando(c.atualizadoEm)} ·{" "}
                        {c.perguntas === 0
                          ? "em branco"
                          : `${c.perguntas} ${c.perguntas === 1 ? "pergunta" : "perguntas"}`}
                      </span>
                    </button>
                    <button
                      type="button"
                      className={estilos.itemExcluir}
                      onClick={() => void excluirConversa(c)}
                      aria-label={`Excluir a conversa ${c.titulo}`}
                      title="Excluir esta conversa"
                    >
                      <IconeLixeira />
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </>
      )}

      <DocumentosCitaveis documentos={documentos} aoAbrir={setDocumentoAberto}>
      <div
        className={estilos.conversa}
        ref={conversa}
        onScroll={(evento) => {
          const alvo = evento.currentTarget;
          // 80px de folga: exigir o fim exato faria o botão piscar durante o streaming,
          // porque cada pedaço de texto muda a altura embaixo do cursor.
          setPreso(alvo.scrollHeight - alvo.scrollTop - alvo.clientHeight < 80);
        }}
      >
        {carregandoHistorico && <p className={estilos.vazio}>Abrindo a conversa deste caso…</p>}

        {!modeloDisponivel && (
          <Aviso tom="atencao" titulo="A conversa está desligada">
            Falta uma chave de modelo no servidor. Os botões de gerar, analisar e revisar
            continuam funcionando normalmente.
          </Aviso>
        )}

        {conversaVazia && modeloDisponivel && (
          <div className={estilos.comecar}>
            <p className={estilos.convite}>Escreva livremente ou escolha uma sugestão</p>
            <p className={estilos.explicacao}>
              O campo abaixo está sempre disponível; estes botões são apenas atalhos. Leio a
              minuta, a entrevista e os documentos deste caso antes de responder.
            </p>
            <div className={estilos.cartoes}>
              {ATALHOS.map((atalho) => (
                <button
                  key={atalho.rotulo}
                  type="button"
                  className={estilos.cartao}
                  onClick={() => usarAtalho(atalho)}
                  disabled={enviando}
                >
                  <strong>{atalho.rotulo}</strong>
                  <span>{atalho.dica}</span>
                </button>
              ))}
            </div>
            <button
              type="button"
              className={`${estilos.sugestao} ${estilos.sugestaoLarga}`}
              onClick={() => void perguntar(CONFRONTO)}
              disabled={enviando}
            >
              Ver o confronto entrevista × documentos
            </button>
            <p className={estilos.rodapeDoConvite}>
              Nada na petição muda sem a sua confirmação — toda alteração passa por uma
              comparação antes × depois.
            </p>
          </div>
        )}

        {mensagens.map((mensagem) =>
          mensagem.papel === "USER" ? (
            <div key={mensagem.id} className={estilos.pergunta}>
              {mensagem.conteudo}
            </div>
          ) : (
            <Resposta
              key={mensagem.id}
              mensagem={mensagem}
              decididas={decisoes}
              executando={executando}
              aoDecidir={decidir}
              aoRepetir={() => void perguntar(mensagem.perguntaOriginal)}
            />
          ),
        )}

        {etapa && (
          <p className={estilos.andamento}>
            <span className={estilos.ponto} aria-hidden />
            {etapa}…
          </p>
        )}

        {rascunhoEmConferencia && (
          <div className={`${estilos.resposta} ${estilos.rascunhoEmConferencia}`}>
            <p className={estilos.avisoRascunho}>Rascunho em conferência</p>
            <RespostaFormatada texto={rascunhoEmConferencia} />
          </div>
        )}

        {parcial && (
          <div className={estilos.resposta}>
            <RespostaFormatada texto={parcial} />
          </div>
        )}

        {enviando && !etapa && !parcial && (
          <p className={estilos.andamento}>
            <span className={estilos.ponto} aria-hidden />
            Escrevendo…
          </p>
        )}

        {erro && <Aviso tom="critico">{erro}</Aviso>}
      </div>
      </DocumentosCitaveis>

      {/* No portal, e acima da gaveta: em tela estreita o chat é gaveta `z-[60]`, e o
        * visor (`z-50`) abriria por baixo dela. */}
      {documentoAberto &&
        createPortal(
          <div className="relative z-[70]">
            <VisorEntrega
              entregaId={documentoAberto.id}
              arquivo={documentoAberto.arquivo}
              onFechar={() => setDocumentoAberto(null)}
            />
          </div>,
          document.body,
        )}

      {!preso && (
        <button type="button" className={estilos.descer} onClick={descer}>
          ↓ Ver o que chegou
        </button>
      )}

      {/* O rodapé da conversa em UMA linha de campo, e não em três blocos empilhados.
        *
        * Antes: chips sempre visíveis + campo de três linhas + botão numa linha própria +
        * legenda de teclas. Quase 190px de altura fixa comidos da leitura, para dizer
        * "Enter envia" a cada rolagem. Agora o campo começa com uma linha e cresce com o
        * que se escreve, e os atalhos recuam assim que há texto — quem já sabe o que
        * pedir não precisa mais deles. */}
      <div className={estilos.composicao}>
        {!conversaVazia && !texto.trim() && (
          <div className={estilos.sugestoes}>
            {ATALHOS.map((atalho) => (
              <button
                key={atalho.rotulo}
                type="button"
                className={estilos.sugestao}
                title={atalho.dica}
                onClick={() => usarAtalho(atalho)}
                disabled={enviando || !modeloDisponivel}
              >
                {atalho.rotulo}
              </button>
            ))}
          </div>
        )}

        <div className="flex flex-wrap items-center gap-2">
          <label className={ESTILO_DO_CHIP} title="Ou cole a imagem direto no campo da conversa (Ctrl+V)">
            <IconeImagem />
            {enviandoPrint ? "Anexando…" : "Enviar print"}
            <input
              className="sr-only"
              type="file"
              accept="image/*"
              multiple
              disabled={enviandoPrint || !modeloDisponivel}
              onChange={(evento) => {
                void anexarPrint(Array.from(evento.target.files ?? []));
                evento.target.value = "";
              }}
            />
          </label>
          <label className={ESTILO_DO_CHIP} title="Material de consulta: não é tratado como prova do caso">
            <IconeClipe />
            Arquivo de contexto
            <input className="sr-only" type="file" accept=".zip,.pdf,.docx,.txt,.md,.csv,.json,.xml,.html,.rtf,.srt,.vtt" onChange={(evento) => setArquivoContexto(evento.target.files?.[0] ?? null)} />
          </label>
          {arquivoContexto && (
            <span className="max-w-[160px] truncate text-xs text-tinta-3" title={arquivoContexto.name}>
              {arquivoContexto.name}
            </span>
          )}
        </div>
        {arquivoContexto && (
          <div className="flex gap-2">
            <input className="campo min-w-0 flex-1 text-xs" value={relevanciaContexto} onChange={(evento) => setRelevanciaContexto(evento.target.value)} placeholder="Por que este arquivo é relevante?" />
            <Botao variante="secundario" pequeno disabled={enviandoContexto} onClick={() => void enviarContexto()}>
              {enviandoContexto ? "Lendo…" : "Adicionar"}
            </Botao>
          </div>
        )}

        {printsAnexados.length > 0 && (
          <div className="mb-2 mt-0 rounded-campo border border-ok-borda bg-ok-claro p-2 text-xs leading-relaxed text-tinta-2">
            <p className="mb-2 mt-0 text-ok">✓ Preview do anexo. Ajuste a largura antes de pedir a inserção:</p>
            <div className="flex flex-wrap gap-3">
              {previewsPrint.map((preview, indice) => (
                <div key={`${preview.nome}-${indice}`} className="min-w-[180px] max-w-full">
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img src={preview.url} alt={preview.nome} style={{ width: `${preview.largura}%` }} className="max-h-64 object-contain border border-borda rounded-campo" />
                  <label className="mt-1 block text-[11px]">Largura {preview.largura}%
                    <input className="ml-2 align-middle" type="range" min="25" max="100" value={preview.largura} onChange={(evento) => setPreviewsPrint((atuais) => atuais.map((item, i) => i === indice ? { ...item, largura: Number(evento.target.value) } : item))} />
                  </label>
                </div>
              ))}
            </div>
            <p className="mb-0 mt-2">Anexado ao caso: {printsAnexados.join(", ")}. Diga em que seção da petição ele entra.</p>
          </div>
        )}

        <div className={estilos.linhaDeEnvio}>
          {/* Sem rótulo visível: o próprio texto de exemplo diz o que se escreve aqui, e
            * uma linha de rótulo acima do campo empurraria a conversa para cima. */}
          <textarea
            ref={campo}
            className={`campo campo--area ${estilos.campoDaPergunta}`}
            aria-label="Pergunta ou pedido sobre esta petição"
            placeholder="Pergunte ou peça uma alteração — Enter envia"
            value={texto}
            rows={1}
            disabled={!modeloDisponivel}
            onChange={(evento) => {
              setTexto(evento.target.value);
              ajustarAltura();
            }}
            onPaste={(evento) => {
              // Só toma o colar quando há IMAGEM: texto colado segue o caminho normal.
              const imagens = Array.from(evento.clipboardData?.files ?? []).filter((arquivo) =>
                arquivo.type.startsWith("image/"),
              );
              if (!imagens.length) return;
              evento.preventDefault();
              void anexarPrint(imagens);
            }}
            onKeyDown={(evento) => {
              // Enter envia, Shift+Enter quebra linha — o hábito de qualquer chat.
              // `isComposing`: o Enter que confirma uma letra acentuada (teclado móvel,
              // acento morto) não é o Enter de enviar — e enviava a pergunta pela metade.
              if (evento.key === "Enter" && !evento.shiftKey && !evento.nativeEvent.isComposing) {
                evento.preventDefault();
                void perguntar(texto);
              }
            }}
          />
          <button
            type="button"
            className={estilos.enviar}
            onClick={() => void perguntar(texto)}
            disabled={enviando || !texto.trim() || !modeloDisponivel}
            aria-label={enviando ? "Enviando a pergunta" : "Enviar a pergunta"}
            title="Enviar · Shift+Enter quebra linha"
          >
            <IconeEnviar />
          </button>
        </div>
      </div>
    </aside>
  );
}

function Resposta({
  mensagem,
  decididas,
  executando,
  aoDecidir,
  aoRepetir,
}: {
  mensagem: MensagemDoChat;
  decididas: Record<string, "aceita" | "descartada">;
  executando: string | null;
  aoDecidir: (chave: string, acao: AcaoProposta, aceitar: boolean, generaliza?: boolean) => void;
  aoRepetir: () => void;
}) {
  if (mensagem.natureza === "ERRO") {
    return (
      <Aviso tom="critico" titulo="Não deu certo">
        <span className="block whitespace-pre-wrap">{mensagem.conteudo}</span>
        {mensagem.podeRepetir && mensagem.perguntaOriginal && (
          <span className="mt-2 block">
            <Botao variante="secundario" pequeno onClick={aoRepetir}>
              Tentar de novo
            </Botao>
          </span>
        )}
      </Aviso>
    );
  }

  const proativa = mensagem.natureza === "EVENTO";
  return (
    <div className={`${estilos.resposta} ${proativa ? estilos.evento : ""}`}>
      {proativa && <span className={estilos.selo}>A IA avisou</span>}
      <RespostaFormatada texto={mensagem.conteudo} />

      {mensagem.fontes.length > 0 && <Fontes fontes={mensagem.fontes} />}

      {mensagem.acoes.map((acao, indice) => {
        const chave = `${mensagem.id}:${indice}`;
        return (
          <PropostaDeAcao
            key={chave}
            acao={acao}
            decisao={decididas[chave]}
            ocupado={executando === chave}
            aoDecidir={(aceitar, generaliza) => aoDecidir(chave, acao, aceitar, generaliza)}
          />
        );
      })}
    </div>
  );
}

/** Como cada camada da hierarquia se apresenta. Palavra + cor, nunca só cor. */
const CAMADAS: Record<ConfiancaDaFonte, { rotulo: string; classe: string }> = {
  OFICIAL: { rotulo: "Oficial", classe: "border-ok bg-ok-claro text-ok" },
  TRIBUNAL: { rotulo: "Tribunal", classe: "border-ok bg-ok-claro text-ok" },
  PUBLICA: { rotulo: "Órgão público", classe: "border-acao-borda bg-acao-clara text-acao" },
  SECUNDARIA: { rotulo: "Não oficial", classe: "border-atencao-borda bg-atencao-claro text-atencao" },
};

/**
 * As fontes da web, na ordem em que o servidor as classificou: oficial primeiro.
 *
 * O aviso do topo muda conforme a busca tenha ou não encontrado norma ou tribunal. Sem
 * ele, uma resposta inteiramente apoiada em portal jurídico chegava com a mesma cara de
 * uma apoiada no Planalto — e é dela que sai o número de súmula que vai para a peça.
 */
function Fontes({ fontes }: { fontes: FonteDaWeb[] }) {
  const oficiais = fontes.filter(
    (f) => f.confianca === "OFICIAL" || f.confianca === "TRIBUNAL",
  ).length;
  return (
    <div className={estilos.fontes}>
      <p className={estilos.tituloDasFontes}>
        Da web — {fontes.length} fonte(s)
        {oficiais > 0 ? `, ${oficiais} oficial(is)` : ", nenhuma oficial"}
      </p>
      {oficiais === 0 && (
        <p className="mb-2 mt-0 text-xs leading-relaxed text-atencao">
          Nenhuma norma no Planalto, decisão no site do tribunal ou órgão público
          sustentou esta busca. Confirme na fonte antes de levar para a peça.
        </p>
      )}
      <ol className={estilos.listaDeFontes}>
        {fontes.map((fonte) => {
          const camada = CAMADAS[fonte.confianca] ?? CAMADAS.SECUNDARIA;
          return (
            <li key={fonte.url}>
              <span className="flex flex-wrap items-baseline gap-x-2">
                <a
                  href={fonte.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-acao underline break-words"
                >
                  {fonte.titulo || dominioDe(fonte.url)}
                </a>
                <span
                  className={`rounded-pill border px-[6px] py-[1px] text-[11px] font-semibold ${camada.classe}`}
                >
                  {camada.rotulo}
                </span>
              </span>
              <span className={estilos.dominio}>{dominioDe(fonte.url)}</span>
            </li>
          );
        })}
      </ol>
    </div>
  );
}

/** Os botões de anexar ao pé do campo: chips discretos, no lugar de links soltos. */
const ESTILO_DO_CHIP =
  "inline-flex cursor-pointer items-center gap-1.5 rounded-pill border border-borda bg-papel-2 px-2.5 py-1 text-xs font-medium text-tinta-2 transition-colors hover:border-acao-borda hover:text-acao";

const ROTULOS: Record<AcaoProposta["tipo"], string> = {
  REVISAR: "Alterar a petição",
  GERAR: "Gerar a petição de novo",
  ANALISAR_DOCUMENTOS: "Reler os documentos",
  PECA_ANEXA: "Redigir outra peça",
  INCLUIR_FOTO: "Incluir foto ou print na petição",
  INCLUIR_TRECHO: "Incluir trecho de documento",
};

/** A foto que vai entrar na peça, para o advogado ver ANTES de confirmar.
 *
 * Busca com o Bearer (`<img src>` direto levaria 401) e solta o object URL ao sair. */
function MiniaturaDaFoto({ anexoId, arquivo }: { anexoId: string; arquivo?: string }) {
  const [url, setUrl] = useState<string | null>(null);
  const [falhou, setFalhou] = useState(false);
  useEffect(() => {
    let ativo = true;
    let criada: string | null = null;
    baixarArquivoEntrega(anexoId)
      .then((blob) => {
        if (!ativo) return;
        criada = URL.createObjectURL(blob);
        setUrl(criada);
      })
      .catch(() => ativo && setFalhou(true));
    return () => {
      ativo = false;
      if (criada) URL.revokeObjectURL(criada);
    };
  }, [anexoId]);
  if (falhou) return <p className="mb-0 mt-2 text-xs text-tinta-3">Não consegui mostrar a foto {arquivo}.</p>;
  if (!url) return <p className="mb-0 mt-2 text-xs text-tinta-3">Carregando a foto…</p>;
  return (
    // eslint-disable-next-line @next/next/no-img-element
    <img
      src={url}
      alt={arquivo ?? "Foto do caso"}
      className="mt-2 max-h-48 max-w-full rounded-campo border border-borda object-contain"
    />
  );
}

/**
 * A proposta, com o que ela faz escrito antes dos botões.
 *
 * O aviso reforçado de `sensivel` não substitui a confirmação — ela é exigida em
 * qualquer caso. Ele existe porque "troque «reclamante» por «autor»" e "aumente o valor
 * para R$ 60.000" chegariam com o mesmo peso visual, e o segundo merece uma leitura
 * mais lenta.
 */
function PropostaDeAcao({
  acao,
  decisao,
  ocupado,
  aoDecidir,
}: {
  acao: AcaoProposta;
  decisao?: "aceita" | "descartada";
  ocupado: boolean;
  aoDecidir: (aceitar: boolean, generaliza?: boolean) => void;
}) {
  const [ensinarIa, setEnsinarIa] = useState(false);
  // O cartão muda de cara conforme o que se decidiu: a cor diz, à distância, se ainda há algo
  // esperando o clique (azul), se pede leitura mais lenta (âmbar) ou se já foi resolvido.
  const tom = decisao === "aceita" ? "aceita" : decisao === "descartada" ? "descartada" : acao.sensivel ? "sensivel" : "pendente";
  const estilo = {
    aceita: { caixa: "border-ok", topo: "bg-ok-claro text-ok" },
    descartada: { caixa: "border-borda opacity-80", topo: "bg-papel-2 text-tinta-3" },
    sensivel: { caixa: "border-atencao-borda", topo: "bg-atencao-claro text-atencao" },
    pendente: { caixa: "border-acao-borda", topo: "bg-acao-clara text-acao" },
  }[tom];
  return (
    <section className={`mt-3 overflow-hidden rounded-campo border bg-papel shadow-sm ${estilo.caixa}`}>
      <div className={`flex flex-wrap items-center justify-between gap-2 px-3 py-2 ${estilo.topo}`}>
        <span className="inline-flex items-center gap-2 text-sm font-semibold">
          <IconeDaAcao tipo={acao.tipo} />
          {ROTULOS[acao.tipo] ?? "Ação"}
        </span>
        {decisao === "aceita" ? (
          <Selo tom="ok" simbolo="✓">Executada</Selo>
        ) : decisao === "descartada" ? (
          <Selo tom="neutro" simbolo="✕">Descartada</Selo>
        ) : acao.sensivel ? (
          <Selo tom="atencao" simbolo="!">Mexe em valor, pedido ou fundamentação</Selo>
        ) : (
          <Selo tom="info" simbolo="✎">Aguardando sua confirmação</Selo>
        )}
      </div>

      <div className="px-3 pb-3 pt-2">
      {acao.pedido && (
        <p className="mb-0 mt-0 text-sm text-tinta-2">
          Pedido: <span className="text-tinta">“{acao.pedido}”</span>
        </p>
      )}
      {acao.tipo === "INCLUIR_FOTO" && acao.anexoId && (
        <>
          <MiniaturaDaFoto anexoId={acao.anexoId} arquivo={acao.arquivo} />
          {acao.arquivo && (
            <div className="mt-1 text-xs">
              <RespostaFormatada texto={`Arquivo: ${acao.arquivo}`} />
            </div>
          )}
          {acao.legenda && (
            <p className="mb-0 mt-1 text-xs italic text-tinta-2">Legenda: {acao.legenda}</p>
          )}
        </>
      )}
      {acao.tipo === "INCLUIR_TRECHO" && acao.trecho && (
        <blockquote className="mb-0 ml-0 mr-0 mt-2 border-0 border-l-4 border-solid border-ok bg-ok-claro px-3 py-2 text-sm leading-relaxed text-tinta">
          “{acao.trecho}”
          {acao.arquivo && (
            <div className="mt-1 text-xs">
              <RespostaFormatada texto={`Fonte: ${acao.arquivo}`} />
            </div>
          )}
        </blockquote>
      )}
      {acao.titulo && acao.tipo === "PECA_ANEXA" && (
        <p className="mb-0 mt-2 text-sm text-tinta-2">Peça: {acao.titulo}</p>
      )}
      {acao.motivo && <p className="mb-0 mt-1 text-sm text-tinta-3">{acao.motivo}</p>}
      {acao.oQueAcontece && (
        <p className="mb-0 mt-2 text-xs leading-relaxed text-tinta-3">{acao.oQueAcontece}</p>
      )}

      {acao.tipo === "REVISAR" && !decisao && (
        <label className="mt-3 flex cursor-pointer items-start gap-2 rounded-campo border border-borda bg-papel-2 p-2 text-xs leading-relaxed text-tinta-2">
          <input
            type="checkbox"
            className="mt-0.5 h-4 w-4 accent-acao"
            checked={ensinarIa}
            onChange={(evento) => setEnsinarIa(evento.target.checked)}
          />
          <span><strong className="text-tinta">Ensinar a IA com esta revisão</strong><br />Use apenas para regra geral do escritório. Nomes, valores, datas e ajustes deste cliente devem ficar desmarcados.</span>
        </label>
      )}

      {!decisao && (
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <Botao variante="primario" disabled={ocupado} carregando={ocupado} onClick={() => aoDecidir(true, ensinarIa)}>
            {!ocupado && <IconeConfirmar />}
            {ocupado ? "Aplicando…" : acao.tipo === "REVISAR" ? "Confirmar alteração" : "Confirmar"}
          </Botao>
          <Botao variante="secundario" disabled={ocupado} onClick={() => aoDecidir(false)}>
            Agora não
          </Botao>
        </div>
      )}
      </div>
    </section>
  );
}

function IconeConfirmar() {
  return (
    <svg className="mr-1.5 inline-block align-[-2px]" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
      <path d="M5 12.5l4.5 4.5L19 7.5" />
    </svg>
  );
}

/** Um ícone por tipo de proposta: o olho reconhece a natureza do cartão antes de ler. */
function IconeDaAcao({ tipo }: { tipo: AcaoProposta["tipo"] }) {
  const caminhos: Record<AcaoProposta["tipo"], ReactNode> = {
    REVISAR: <path d="M12 20h9M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4z" />,
    GERAR: <path d="M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9zM14 3v6h6M9 14h6M9 17h6" />,
    ANALISAR_DOCUMENTOS: <path d="M11 4a7 7 0 1 0 0 14 7 7 0 0 0 0-14zM21 21l-4.3-4.3" />,
    PECA_ANEXA: <path d="M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9zM14 3v6h6M12 12v6M9 15h6" />,
    INCLUIR_FOTO: <path d="M4 5h16a1 1 0 0 1 1 1v12a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V6a1 1 0 0 1 1-1zM8.5 10a1.5 1.5 0 1 0 0-3 1.5 1.5 0 0 0 0 3zM21 16l-5-5-8 8" />,
    INCLUIR_TRECHO: <path d="M7 7h4v4H7zM13 7h4v4h-4zM7 11c0 3 1 5 3 6M13 11c0 3 1 5 3 6" />,
  };
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
      {caminhos[tipo] ?? caminhos.REVISAR}
    </svg>
  );
}

function IconeImagem() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
      <path d="M4 5h16a1 1 0 0 1 1 1v12a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V6a1 1 0 0 1 1-1zM8.5 10a1.5 1.5 0 1 0 0-3 1.5 1.5 0 0 0 0 3zM21 16l-5-5-8 8" />
    </svg>
  );
}

function IconeClipe() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
      <path d="M21 11l-8.6 8.6a5 5 0 0 1-7-7L14 4a3.5 3.5 0 0 1 5 5l-8.6 8.6a2 2 0 0 1-3-3L15 7" />
    </svg>
  );
}

function IconeConversa() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
      <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
    </svg>
  );
}

function IconeEnviar() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
      <path d="M5 12h13M12 5l7 7-7 7" />
    </svg>
  );
}

function IconeMais() {
  return (
    <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
      <path d="M12 5v14M5 12h14" />
    </svg>
  );
}

function IconeHistorico() {
  return (
    <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
      <path d="M3 12a9 9 0 1 0 3-6.7L3 8" />
      <path d="M3 3v5h5M12 7v5l3 2" />
    </svg>
  );
}

function IconeAtualizar({ girando }: { girando?: boolean }) {
  return (
    <svg className={girando ? estilos.girar : undefined} width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
      <path d="M21 12a9 9 0 0 1-15.5 6.2L3 16M3 12a9 9 0 0 1 15.5-6.2L21 8" />
      <path d="M21 3v5h-5M3 21v-5h5" />
    </svg>
  );
}

function IconeLixeira() {
  return (
    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
      <path d="M3 6h18M8 6V4h8v2M6 6l1 14h10l1-14M10 11v5M14 11v5" />
    </svg>
  );
}

/** «hoje 14:32», «ontem», «12/09»: o bastante para reconhecer a conversa no histórico. */
function quando(iso: string): string {
  const data = new Date(iso);
  if (Number.isNaN(data.getTime())) return "";
  const hoje = new Date();
  const mesmoDia = (a: Date, b: Date) => a.toDateString() === b.toDateString();
  const ontem = new Date(hoje);
  ontem.setDate(hoje.getDate() - 1);
  if (mesmoDia(data, hoje)) {
    return `hoje ${data.toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" })}`;
  }
  if (mesmoDia(data, ontem)) return "ontem";
  return data.toLocaleDateString("pt-BR", { day: "2-digit", month: "2-digit" });
}

function IconeFechar() {
  return (
    <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
      <path d="M18 6 6 18M6 6l12 12" />
    </svg>
  );
}

/** Setas para fora (alargar) ou para dentro (estreitar). */
function IconeLargura({ invertido }: { invertido?: boolean }) {
  return (
    <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
      {invertido ? (
        <path d="M13 5h6v6M19 5l-7 7M11 19H5v-6M5 19l7-7" />
      ) : (
        <path d="M19 9V3h-6M13 11l6-6M5 15v6h6M11 13l-6 6" />
      )}
    </svg>
  );
}
