"use client";

/**
 * Análise + petição local (DeepSeek) — entrevista + OCR, sem agente.
 * O botão principal fica no cabeçalho do dossiê; aqui só resultado e edição.
 */

import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";

import { BookOpenCheck, FilePenLine, GitCompareArrows, Globe, Maximize2, Mic, MicOff, Minimize2, Search } from "lucide-react";

import { Aviso, Botao, Cartao, RotuloCampo, Campo, Selo } from "@/components/ui/Basicos";
import ChatPeticao from "@/components/admin/ChatPeticao";
import { RespostaFormatada, dominioDe } from "@/components/ui/Markdown";
import { alinharSecoes, indicesAlterados, type LinhaComparacao } from "@/lib/diffPeticao";
import { BotaoProcesso } from "@/components/ui/BotaoProcesso";
import {
  baixarArquivoDaPeticao,
  aceitarRevisaoPendente,
  buscarPeticao,
  descartarRevisaoPendente,
  estadoPeticaoFluxo,
  gerarAnaliseEPeticao,
  historicoDePeticao,
  revisarPeticaoComPrompt,
  salvarRascunhoPeticao,
  type EstadoPeticaoFluxo,
  type HistoricoDePeticao,
  gerarPecaAnexa,
  listarPecasAnexas,
  type PecaAnexa,
  type Peticao,
  pesquisarNaWeb,
  type ResultadoPesquisaWeb,
  type RevisaoRegistrada,
  type SecaoPeticao,
} from "@/lib/agente";
import { avisarChatDaPeticao } from "@/lib/chatPeticao";
import { baixarArquivo } from "@/lib/baixar";
import { useEdicaoAutoSalva, type SituacaoDoSalvamento } from "@/lib/useEdicaoAutoSalva";
import {
  BarraDeFormatacao,
  CampoDeTitulo,
  CampoDoDocumento,
  LARGURA_UTIL_CM,
  ReguaDeTabulacao,
  useSelecaoFormatada,
} from "@/components/admin/EditorDoDocumento";
import { semMarcacao } from "@/lib/formatacaoPeticao";


const TITULO = "font-ui text-lg font-semibold m-0";
const SUB = "text-sm leading-relaxed text-tinta-3 m-0";
const TEXTO = "text-sm leading-relaxed text-tinta-2 m-0";

export type ControlesGeracaoPeticao = {
  gerar: () => void;
  ocupado: boolean;
  podeGerar: boolean;
  rotulo: string;
  /* O botão de gerar mora no cabeçalho do dossiê, longe deste cartão: sem o
   * resultado aqui, quem clicava lá em cima não via nem o erro nem o fim. */
  erro: string | null;
  concluido: string | null;
};

type AcaoPeticao = "gerar" | "salvar" | "revisar";
/** Resultado da última ação, com a ação que o produziu — cada um aparece junto do próprio botão. */
type Retorno = { acao: AcaoPeticao; texto: string } | null;

type Props = {
  casoId: string;
  temEntrevista: boolean;
  onControlesGeracao?: (controles: ControlesGeracaoPeticao) => void;
};

export default function FluxoPeticao({ casoId, temEntrevista, onControlesGeracao }: Props) {
  const [estado, setEstado] = useState<EstadoPeticaoFluxo | null>(null);
  const [peticao, setPeticao] = useState<Peticao | null>(null);
  const [ocupado, setOcupado] = useState(false);
  /** Qual formato está sendo salvo: cada botão de download mostra só o próprio andamento. */
  const [salvandoComo, setSalvandoComo] = useState<"docx" | "pdf" | null>(null);
  const salvando = salvandoComo !== null;
  const [erro, setErro] = useState<Retorno>(null);
  const [concluido, setConcluido] = useState<Retorno>(null);

  // Revisão por prompt — issue "Permitir alteração da petição por prompt com
  // rastreabilidade". `historico` fica separado de `peticao` porque uma falha
  // ao carregar o histórico não pode esconder a petição, que é o que importa
  // primeiro.
  const [promptRevisao, setPromptRevisao] = useState("");
  /* Marcado por padrão: a crítica quase sempre é uma lição do escritório, e é
   * dela que a IA aprende. Desmarcar é o que impede um ajuste pontual — "troque
   * o nome do cliente" — de virar regra de todas as petições da categoria. */
  const [ensinarIA, setEnsinarIA] = useState(true);
  const [revisando, setRevisando] = useState(false);
  const [historico, setHistorico] = useState<HistoricoDePeticao | null>(null);
  const [mostrarHistorico, setMostrarHistorico] = useState(false);
  const [avisoRevisao, setAvisoRevisao] = useState<string | null>(null);
  const [ouvindoRevisao, setOuvindoRevisao] = useState(false);
  const reconhecimentoRevisao = useRef<SpeechRecognition | null>(null);

  const alternarMicrofoneRevisao = useCallback(() => {
    if (ouvindoRevisao) {
      reconhecimentoRevisao.current?.stop();
      return;
    }
    const Speech = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!Speech) {
      setAvisoRevisao("Seu navegador não oferece transcrição por voz. Use Chrome ou Edge, ou digite o pedido.");
      return;
    }
    const reconhecimento = new Speech();
    reconhecimento.lang = "pt-BR";
    reconhecimento.continuous = true;
    reconhecimento.interimResults = true;
    reconhecimento.onresult = (evento) => {
      let final = "";
      for (let i = evento.resultIndex; i < evento.results.length; i += 1) {
        if (evento.results[i].isFinal) final += evento.results[i][0].transcript;
      }
      if (final.trim()) setPromptRevisao((atual) => `${atual}${atual.trim() ? " " : ""}${final.trim()}`);
    };
    reconhecimento.onerror = () => {
      setOuvindoRevisao(false);
      setAvisoRevisao("Não consegui transcrever o áudio. Verifique a permissão do microfone e tente novamente.");
    };
    reconhecimento.onend = () => setOuvindoRevisao(false);
    reconhecimentoRevisao.current = reconhecimento;
    reconhecimento.start();
    setAvisoRevisao(null);
    setOuvindoRevisao(true);
  }, [ouvindoRevisao]);

  useEffect(() => () => reconhecimentoRevisao.current?.stop(), []);

  const recarregar = useCallback(async () => {
    try {
      const dados = await estadoPeticaoFluxo(casoId);
      setEstado(dados);
      if (dados.peticao_pronta) {
        const pronta = await buscarPeticao(casoId, "local");
        setPeticao(pronta);
        try {
          setHistorico(await historicoDePeticao(casoId, "local"));
        } catch {
          /* rastreabilidade é complementar — a petição continua utilizável sem ela */
        }
      }
    } catch {
      /* primeiro uso */
    }
  }, [casoId]);

  useEffect(() => {
    void recarregar();
  }, [recarregar]);

  /* Cada pausa na digitação grava — antes só o botão "Salvar e baixar" levava a
   * edição ao banco, e quem saía da tela sem clicar perdia o que escreveu. */
  const autoSalvo = useEdicaoAutoSalva({
    chave: peticao?.id ?? null,
    secoes: peticao?.sections,
    titulo: peticao?.title,
    salvar: (pecaId, envio) =>
      salvarRascunhoPeticao(casoId, pecaId, envio.secoes, envio.titulo),
    onSalvo: (atualizada) => {
      setPeticao(atualizada);
      historicoDePeticao(casoId, "local").then(setHistorico, () => undefined);
    },
  });
  const edicao = autoSalvo.edicao;

  const gerar = useCallback(async () => {
    // A minuta já salva é carregada ao voltar ao dossiê. Nunca mande outra
    // chamada ao modelo por engano: gerar de novo custa token e sobrescreve a
    // versão em trabalho; a decisão precisa ser explícita.
    if (
      peticao &&
      !window.confirm(
        "Já existe uma minuta salva para este caso. Gerar novamente usa tokens e cria uma nova versão. Continuar?",
      )
    ) {
      return;
    }
    setErro(null);
    setConcluido(null);
    setOcupado(true);
    try {
      const resultado = await gerarAnaliseEPeticao(casoId);
      if (resultado.peticao) {
        setPeticao(resultado.peticao);
        if (resultado.analise) {
          setEstado((atual) => ({ ...(atual ?? {}), analise: resultado.analise }));
        }
        await recarregar();
        const arquivo = await baixarArquivoDaPeticao(casoId, "local", "docx");
        baixarArquivo(arquivo, `Peticao inicial - v${resultado.peticao.version}.docx`);
        setConcluido({
          acao: "gerar",
          texto: `Petição gerada (versão ${resultado.peticao.version}) e .docx baixado.`,
        });
        /* A IA conta no chat o que saiu — versão nova, o que ficou sem comprovação.
         * Sem isto, a conversa ao lado continuaria falando da peça anterior como se
         * nada tivesse acontecido, que é justamente quando o advogado mais precisa
         * saber o que mudou. */
        avisarChatDaPeticao(casoId, "peticao_gerada", { versao: resultado.peticao.version });
      }
    } catch (e) {
      const texto = e instanceof Error ? e.message : "Falha ao gerar a petição.";
      setErro({ acao: "gerar", texto });
      avisarChatDaPeticao(casoId, "falha", { acao: "Gerar a petição", erro: texto });
    } finally {
      setOcupado(false);
    }
  }, [casoId, peticao, recarregar]);

  const semEntrevista = !temEntrevista && !estado?.entrevista?.texto;
  const rotuloGerar = ocupado
    ? "Analisando e redigindo…"
    : peticao
      ? "Gerar de novo"
      : "Gerar análise e petição";

  const erroGerar = erro?.acao === "gerar" ? erro.texto : null;
  const concluidoGerar = concluido?.acao === "gerar" ? concluido.texto : null;

  useEffect(() => {
    onControlesGeracao?.({
      gerar: () => void gerar(),
      ocupado,
      // A API valida a transcrição real. Não bloqueie o botão por metadados
      // incompletos do dossiê (casos antigos podem ter texto e `caracteres` zerado).
      podeGerar: true,
      rotulo: rotuloGerar,
      erro: erroGerar,
      concluido: concluidoGerar,
    });
  }, [onControlesGeracao, gerar, ocupado, semEntrevista, rotuloGerar, erroGerar, concluidoGerar]);

  async function salvar(baixarPdf = false) {
    if (!peticao) return;
    const formato = baixarPdf ? "pdf" : "docx";
    setSalvandoComo(formato);
    setErro(null);
    setConcluido(null);
    try {
      await autoSalvo.descarregar();
      const atualizada = await salvarRascunhoPeticao(
        casoId,
        peticao.id,
        secoesDaTela(peticao.sections, edicao, autoSalvo.rotulos),
        autoSalvo.titulo,
      );
      setPeticao(atualizada);
      const arquivo = await baixarArquivoDaPeticao(casoId, peticao.id, formato);
      baixarArquivo(arquivo, `Peticao inicial - v${atualizada.version}.${formato}`);
      setConcluido({ acao: "salvar", texto: `Versão ${atualizada.version} salva e .${formato} baixado.` });
      avisarChatDaPeticao(casoId, "versao_salva", { formato, versao: atualizada.version });
    } catch (e) {
      const texto = e instanceof Error ? e.message : "Não foi possível salvar.";
      setErro({ acao: "salvar", texto });
      avisarChatDaPeticao(casoId, "falha", { acao: "Salvar a petição", erro: texto });
    } finally {
      setSalvandoComo(null);
    }
  }

  async function revisar() {
    if (!peticao || !promptRevisao.trim()) return;
    setRevisando(true);
    setErro(null);
    setConcluido(null);
    setAvisoRevisao(null);
    try {
      await autoSalvo.descarregar();
      const secoesAtuais = peticao.sections ?? [];
      if (haEdicaoNaTela(secoesAtuais, edicao, autoSalvo.rotulos)) {
        await salvarRascunhoPeticao(
          casoId,
          peticao.id,
          secoesDaTela(secoesAtuais, edicao, autoSalvo.rotulos),
        );
      }
      const resultado = await revisarPeticaoComPrompt(
        casoId,
        peticao.id,
        promptRevisao.trim(),
        ensinarIA,
      );
      setPeticao(resultado.peticao);
      setPromptRevisao("");
      const revisao = resultado.peticao.revisao ?? resultado.revisao;
      const alteradas = revisao?.alteradas ?? [];
      setConcluido({
        acao: "revisar",
        texto: `Revisão concluída — compare a candidata antes de aceitar. A peça oficial permanece na versão ${resultado.peticao.version}${
          alteradas.length ? `. Seções alteradas: ${alteradas.join(", ")}` : ""
        }.`,
      });
      if (revisao?.alterou === false) {
        setConcluido({
          acao: "revisar",
          texto: "A IA não identificou uma alteração segura; nenhuma versão nova foi criada.",
        });
      }
      if (revisao?.atendeu === false) {
        setAvisoRevisao(
          `A conferência automática indica que pode faltar: ${revisao.faltou || "parte do pedido"}. Confira o texto e peça de novo se precisar.`,
        );
      }
      if ((revisao?.perguntas ?? []).length > 0) {
        setAvisoRevisao(`A IA precisa confirmar: ${revisao!.perguntas!.join(" · ")}`);
      }
      if (resultado.peticao.revisao_pendente) {
        avisarChatDaPeticao(casoId, "revisao_proposta", {
          pedido: promptRevisao.trim(),
          alteradas,
        });
      }
      await recarregar();
      // `recarregar` lê a versão persistida; numa revisão sem alteração ela não
      // contém o aviso/perguntas retornados pela IA. Reaplica o resultado da
      // chamada depois da leitura para que a tela não perca esse retorno.
      setPeticao(resultado.peticao);
    } catch (e) {
      const texto = e instanceof Error ? e.message : "Não foi possível aplicar a revisão.";
      setErro({ acao: "revisar", texto });
      avisarChatDaPeticao(casoId, "falha", { acao: "Revisar a petição", erro: texto });
    } finally {
      setRevisando(false);
    }
  }

  async function decidirRevisao(aceitar: boolean) {
    const candidata = peticao?.revisao_pendente;
    if (!peticao || !candidata) return;
    // Gravar a digitação pendente agora descartaria a candidata no servidor
    // (edição manual muda a versão-base) — a decisão sobre ela vem primeiro.
    autoSalvo.substituir(peticao.sections);
    setRevisando(true);
    setErro(null);
    try {
      const resultado = aceitar
        ? await aceitarRevisaoPendente(casoId, candidata.id)
        : await descartarRevisaoPendente(casoId, candidata.id);
      setPeticao(resultado.peticao);
      autoSalvo.substituir(resultado.peticao.sections);
      setConcluido({ acao: "revisar", texto: aceitar ? "Revisão aceita e gravada como nova versão." : "Revisão descartada; a peça original foi preservada." });
      avisarChatDaPeticao(casoId, aceitar ? "revisao_aceita" : "revisao_descartada", {
        pedido: candidata.prompt ?? "",
      });
      await recarregar();
    } catch (e) {
      setErro({ acao: "revisar", texto: e instanceof Error ? e.message : "Não foi possível concluir a revisão." });
    } finally {
      setRevisando(false);
    }
  }

  const analise = estado?.analise;
  /* As outras peças do caso, e o que está sendo redigido ou baixado agora.
   *
   * Ficam fora de `peticao` de propósito: a petição inicial tem versão, histórico
   * e aprovação; estas são peças irmãs, e misturá-las no mesmo estado faria uma
   * falha ao listá-las esconder a minuta, que é o que importa primeiro. */
  const [anexas, setAnexas] = useState<PecaAnexa[]>([]);
  const [maximoAnexas, setMaximoAnexas] = useState(3);
  const [gerandoAnexa, setGerandoAnexa] = useState<string | null>(null);
  const [baixandoAnexa, setBaixandoAnexa] = useState<string | null>(null);
  const [erroAnexa, setErroAnexa] = useState<string | null>(null);

  const sugestoes = analise?.acoes_sugeridas ?? [];

  const recarregarAnexas = useCallback(async () => {
    try {
      const dados = await listarPecasAnexas(casoId);
      setAnexas(dados.anexas);
      setMaximoAnexas(dados.maximo);
    } catch {
      /* a lista é complementar — a minuta principal continua utilizável sem ela */
    }
  }, [casoId]);

  useEffect(() => {
    void recarregarAnexas();
  }, [recarregarAnexas]);

  async function gerarAnexa(acao: { titulo: string; motivo?: string; pedidos?: string[] }) {
    setErroAnexa(null);
    setGerandoAnexa(acao.titulo);
    try {
      await gerarPecaAnexa(casoId, acao);
      await recarregarAnexas();
      avisarChatDaPeticao(casoId, "peca_anexa_gerada", { titulo: acao.titulo });
    } catch (e) {
      const texto = e instanceof Error ? e.message : "Não foi possível gerar esta peça.";
      setErroAnexa(texto);
      avisarChatDaPeticao(casoId, "falha", { acao: `Redigir «${acao.titulo}»`, erro: texto });
    } finally {
      setGerandoAnexa(null);
    }
  }

  async function baixarAnexa(peca: PecaAnexa, formato: "docx" | "pdf") {
    setErroAnexa(null);
    setBaixandoAnexa(`${peca.id}:${formato}`);
    try {
      const arquivo = await baixarArquivoDaPeticao(casoId, peca.id, formato);
      baixarArquivo(arquivo, `${peca.titulo}.${formato}`);
    } catch (e) {
      setErroAnexa(e instanceof Error ? e.message : "Não foi possível baixar esta peça.");
    } finally {
      setBaixandoAnexa(null);
    }
  }

  /* Edição de uma peça anexa — a segunda petição sugerida em diante só dava
   * para baixar, não para editar como a inicial (a API não sabia distinguir
   * "petição inicial" de "peça anexa" nas rotas de leitura/rascunho). Reaproveita
   * `buscarPeticao`/`salvarRascunhoPeticao`, que já são genéricas por `pecaId`. */
  const [anexaAberta, setAnexaAberta] = useState<string | null>(null);
  const [peticaoAnexa, setPeticaoAnexa] = useState<Peticao | null>(null);
  const [carregandoAnexa, setCarregandoAnexa] = useState(false);
  /* Revisão por prompt — recurso opcional, oferecido para a peça anexa com a
   * mesma qualidade da petição inicial; sem "ensinar a IA" nem versão anterior
   * guardada, porque a anexa já não tem histórico nem para "gerar de novo"
   * (ver `app/peticao_local.revisar_anexa_com_prompt`). */
  const [promptRevisaoAnexa, setPromptRevisaoAnexa] = useState("");
  const [revisandoAnexa, setRevisandoAnexa] = useState(false);
  const [retornoAnexa, setRetornoAnexa] = useState<{ tom: "ok" | "atencao"; texto: string } | null>(null);
  const [historicoAnexa, setHistoricoAnexa] = useState<HistoricoDePeticao | null>(null);
  const [mostrarHistoricoAnexa, setMostrarHistoricoAnexa] = useState(false);
  const autoSalvoAnexa = useEdicaoAutoSalva({
    chave: peticaoAnexa?.id ?? null,
    secoes: peticaoAnexa?.sections,
    titulo: peticaoAnexa?.title,
    salvar: (pecaId, envio) =>
      salvarRascunhoPeticao(casoId, pecaId, envio.secoes, envio.titulo),
    onSalvo: (atualizada, pecaId) => {
      setPeticaoAnexa(atualizada);
      historicoDePeticao(casoId, pecaId).then(setHistoricoAnexa, () => undefined);
      void recarregarAnexas();
    },
  });
  const edicaoAnexa = autoSalvoAnexa.edicao;

  async function carregarHistoricoAnexa(pecaId: string) {
    try {
      setHistoricoAnexa(await historicoDePeticao(casoId, pecaId));
    } catch {
      setHistoricoAnexa(null);
    }
  }

  async function alternarEdicaoAnexa(peca: PecaAnexa) {
    if (anexaAberta === peca.id) {
      setAnexaAberta(null);
      setPeticaoAnexa(null);
      setPromptRevisaoAnexa("");
      setRetornoAnexa(null);
      setHistoricoAnexa(null);
      return;
    }
    setRetornoAnexa(null);
    void carregarHistoricoAnexa(peca.id);
    setErroAnexa(null);
    setAnexaAberta(peca.id);
    setPromptRevisaoAnexa("");
    setCarregandoAnexa(true);
    try {
      const dados = await buscarPeticao(casoId, peca.id);
      setPeticaoAnexa(dados);
    } catch (e) {
      setErroAnexa(e instanceof Error ? e.message : "Não foi possível abrir esta peça para edição.");
      setAnexaAberta(null);
    } finally {
      setCarregandoAnexa(false);
    }
  }

  async function revisarEdicaoAnexa() {
    if (!peticaoAnexa || !promptRevisaoAnexa.trim()) return;
    setErroAnexa(null);
    setRetornoAnexa(null);
    setRevisandoAnexa(true);
    try {
      await autoSalvoAnexa.descarregar();
      const secoesAtuais = peticaoAnexa.sections ?? [];
      if (haEdicaoNaTela(secoesAtuais, edicaoAnexa, autoSalvoAnexa.rotulos)) {
        await salvarRascunhoPeticao(
          casoId,
          peticaoAnexa.id,
          secoesDaTela(secoesAtuais, edicaoAnexa, autoSalvoAnexa.rotulos),
        );
      }
      const resultado = await revisarPeticaoComPrompt(
        casoId,
        peticaoAnexa.id,
        promptRevisaoAnexa.trim(),
        false,
      );
      setPeticaoAnexa(resultado.peticao);
      autoSalvoAnexa.substituir(resultado.peticao.sections);
      setPromptRevisaoAnexa("");
      const revisao = resultado.peticao.revisao ?? resultado.revisao;
      const alteradas = revisao?.alteradas ?? [];
      setRetornoAnexa(
        revisao?.alterou === false
          ? {
              tom: "atencao",
              texto: `Nenhuma versão nova foi criada. ${
                (revisao.perguntas ?? []).join(" · ") || "A IA não identificou uma alteração segura."
              }`,
            }
          : revisao?.atendeu === false
          ? {
              tom: "atencao",
              texto: `Revisão aplicada, mas a conferência automática indica que pode faltar: ${revisao.faltou || "parte do pedido"}. Confira o texto.`,
            }
          : {
              tom: "ok",
              texto: `Revisão aplicada${alteradas.length ? ` em: ${alteradas.join(", ")}` : ""}. A versão anterior ficou no histórico desta peça.`,
            },
      );
      await Promise.all([recarregarAnexas(), carregarHistoricoAnexa(peticaoAnexa.id)]);
    } catch (e) {
      setErroAnexa(e instanceof Error ? e.message : "Não foi possível aplicar a revisão nesta peça.");
    } finally {
      setRevisandoAnexa(false);
    }
  }

  const prep = estado?.preparacao;
  /* Só vale abaixo de `lg`: acima disso a conversa é coluna e está sempre à vista. */
  const [gaveta, setGaveta] = useState(false);
  /* A conversa larga: quem está PEDINDO alterações passa mais tempo lendo a resposta
   * do que a peça, e uma coluna estreita transforma cada parágrafo em vinte linhas.
   * A escolha fica com o advogado porque ela muda ao longo do mesmo trabalho. */
  const [chatLargo, setChatLargo] = useState(false);

  /* SPLIT VIEW: o documento à esquerda, a conversa à direita.
   *
   * A peça não pode sair da tela enquanto se fala dela. Numa aba, a resposta que cita
   * "o item II dos pedidos" aponta para algo que o advogado não está mais vendo — o
   * mesmo defeito que o ajudante do caso já corrigiu uma vez. Abaixo de `lg` não há
   * largura para as duas colunas: aí a conversa vira gaveta, e o documento continua
   * com a página inteira. */
  return (
    <div
      className={`grid gap-4 lg:items-start ${
        chatLargo
          ? "lg:grid-cols-[minmax(0,1fr)_minmax(32rem,40rem)]"
          : "lg:grid-cols-[minmax(0,1fr)_minmax(25rem,29rem)]"
      }`}
    >
      <Cartao className="grid min-w-0 gap-4">
        <header className="grid gap-2">
          {/* O mesmo `gerar` do botão do cabeçalho do dossiê, repetido aqui: quem
            * chegou a este cartão rolando a página não precisa voltar ao topo. O erro
            * já aparece no Aviso logo abaixo, então o botão só mostra o concluído. */}
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h2 className={TITULO}>Análise e petição</h2>
            <BotaoProcesso
              variante="primario"
              pequeno
              processando={ocupado}
              dica="Cruzando entrevista e documentos e redigindo a petição"
              aguardando={salvando || revisando}
              concluido={concluidoGerar}
              onClick={() => void gerar()}
            >
              {rotuloGerar}
            </BotaoProcesso>
          </div>
          <p className={SUB}>
            Cruza a entrevista com os documentos lidos por OCR e redige a petição inicial com
            DeepSeek.
          </p>
        </header>

        {semEntrevista && (
          <Aviso tom="atencao" titulo="Falta a entrevista">
            Este caso ainda não tem transcrição do atendimento.
          </Aviso>
        )}

        {/* O erro de gerar aparece também aqui, além do botão do cabeçalho: quem já
          * rolou até este cartão não vê mais o topo. Salvar e revisar mostram o
          * próprio resultado junto dos seus botões. */}
        {erro?.acao === "gerar" && (
          <Aviso tom="critico" titulo="A petição não foi gerada">
            {erro.texto}
          </Aviso>
        )}

        {prep && (
          <div className="grid grid-cols-2 gap-2 text-xs text-tinta-3">
            <div className="border border-borda p-2 bg-papel-2">
              <strong className="block text-tinta-2">{prep.documentos_lidos ?? 0}</strong>
              docs com texto OCR
            </div>
            <div className="border border-borda p-2 bg-papel-2">
              <strong className="block text-tinta-2">
                {prep.checklist_entregues ?? 0}/{prep.checklist_obrigatorios ?? "?"}
              </strong>
              checklist obrigatório
            </div>
          </div>
        )}

        {analise && (
          <section className="grid gap-3 border border-borda bg-papel p-4">
            <div><h3 className="text-sm font-semibold m-0">Leitura rápida do caso</h3><p className="mt-1 text-sm leading-relaxed text-tinta-2">{analise.resumo}</p></div>
            <div className="grid gap-2 sm:grid-cols-2">
              <ResumoAnalise titulo="✓ Confirmado por documentos" tom="ok" itens={analise.fatos_confirmados ?? []} vazio="Ainda não há confirmação documental destacada." />
              <ResumoAnalise titulo="? Depende de prova ou confirmação" tom="atencao" itens={[...(analise.fatos_so_na_entrevista ?? []), ...(analise.lacunas ?? [])]} vazio="Nenhuma pendência relevante apontada." />
            </div>
            {analise.cruzamento_entrevista_documentos && <details className="text-sm text-tinta-2"><summary className="cursor-pointer font-semibold">Ver confronto completo: entrevista × documentos</summary><p className="mt-2 leading-relaxed">{analise.cruzamento_entrevista_documentos}</p></details>}
          </section>
        )}

        {peticao && (
          <section className="grid gap-3 border border-borda p-4 bg-papel-2">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div className="grid gap-0.5">
                <h3 className="text-sm font-semibold m-0">
                  Petição inicial — versão {peticao.version}
                </h3>
                <IndicadorDeSalvamento
                  situacao={autoSalvo.situacao}
                  salvoEm={autoSalvo.salvoEm}
                  erro={autoSalvo.erro}
                  onTentarDeNovo={() => void autoSalvo.descarregar().catch(() => undefined)}
                />
              </div>
              <div className="flex gap-2 flex-wrap">
                {/* O botão de mostrar/ocultar prévia saiu junto com a segunda
                    coluna: não há mais duas visões do mesmo texto para alternar. */}
                <BotaoProcesso
                  variante="secundario"
                  pequeno
                  processando={salvandoComo === "docx"}
                  textoProcessando="Salvando…"
                  aguardando={ocupado || salvandoComo === "pdf"}
                  onClick={() => salvar(false)}
                >
                  Salvar e baixar .docx
                </BotaoProcesso>
                <BotaoProcesso
                  variante="texto"
                  pequeno
                  processando={salvandoComo === "pdf"}
                  textoProcessando="Gerando o PDF…"
                  aguardando={ocupado || salvandoComo === "docx"}
                  onClick={() => salvar(true)}
                >
                  Baixar PDF
                </BotaoProcesso>
              </div>
            </div>

            {erro?.acao === "salvar" && (
              <Aviso tom="critico" titulo="Não foi possível salvar">
                {erro.texto}
              </Aviso>
            )}
            {concluido?.acao === "salvar" && <Aviso tom="ok">{concluido.texto}</Aviso>}

            {(peticao.readiness?.pendencias ?? []).length > 0 && (
              <Aviso tom="atencao" titulo="Pontos sem comprovação documental">
                Revise a minuta antes de protocolar.
              </Aviso>
            )}

            {historico && (historico.criticas.length > 0 || historico.versoes.length > 0) && (
              <HistoricoDeCriticas
                historico={historico}
                aberto={mostrarHistorico}
                onAlternar={() => setMostrarHistorico((atual) => !atual)}
              />
            )}

            {/* UMA COLUNA SÓ — o documento é o próprio editor.
              *
              * Havia duas: os campos crus à esquerda e a prévia à direita. O mesmo
              * texto ocupava a tela duas vezes, e a página ficava tão alta que
              * rolar virava o trabalho principal. Agora se escreve onde se lê. */}
            <PreviaPeticao
              titulo={autoSalvo.titulo || peticao.title}
              secoes={peticao.sections ?? []}
              edicao={edicao}
              rotulos={autoSalvo.rotulos}
              onEditar={autoSalvo.editar}
              onEditarRotulo={autoSalvo.editarRotulo}
              onEditarTitulo={autoSalvo.editarTitulo}
            />

            {peticao.revisao_pendente && (
              <ComparacaoRevisao
                anterior={peticao.sections ?? []}
                candidata={peticao.revisao_pendente.sections}
                revisando={revisando}
                onAceitar={() => void decidirRevisao(true)}
                onDescartar={() => void decidirRevisao(false)}
              />
            )}

            {/* AS MESMAS FERRAMENTAS DE ANTES, agora recolhidas.
            *
            * O chat ao lado faz as duas coisas em linguagem natural — "reescreve o item
            * II com tom mais técnico", "procura súmula sobre isso" —, mas nenhuma delas
            * foi removida: quem já trabalha com o campo de revisão continua com ele, e a
            * pesquisa avulsa segue servindo a quem não quer abrir conversa. Recolhidas
            * porque duas caixas grandes repetindo o que a coluna da direita faz
            * empurravam a peça para fora da primeira tela. */}
          <details className="rounded-cartao border border-borda bg-papel-2 p-3">
            <summary className="cursor-pointer text-sm font-semibold text-tinta-2">
              Ferramentas fora do chat: revisão por prompt e pesquisa na web
            </summary>
            <div className="grid gap-3 pt-3">
              {/* A revisão por prompt vem DEPOIS do texto: ela age sobre o que está
                  * escrito, e pedir a mudança antes de ver a peça invertia a leitura —
                  * o advogado abria a tela num campo em branco e precisava rolar para
                  * descobrir o que iria alterar. */}
                <CartaoFerramenta
                  tipo="revisao"
                  icone={<FilePenLine size={18} aria-hidden />}
                  titulo="Pedir uma revisão por prompt"
                  descricao={
                    <>
                      Descreva o que deve mudar (ex.: &quot;separe dano moral do material nos
                      pedidos&quot;). A IA gera uma nova versão completa para comparação. A versão
                      atual só muda depois que você aceitar a revisão.
                    </>
                  }
                  selo={<Selo tom="info" simbolo="✎">Altera a petição após aceite</Selo>}
                >
                  <RotuloCampo htmlFor="prompt-revisao" className="sr-only">
                    O que deve mudar nesta petição
                  </RotuloCampo>
                  <Campo
                    area
                    id="prompt-revisao"
                    value={promptRevisao}
                    onChange={(e) => setPromptRevisao(e.target.value)}
                    rows={3}
                    placeholder="O que deve mudar nesta petição?"
                  />
                  <div className="flex flex-wrap items-center gap-2">
                    <Botao variante="secundario" pequeno onClick={alternarMicrofoneRevisao}>
                      {ouvindoRevisao ? <MicOff size={14} aria-hidden /> : <Mic size={14} aria-hidden />}
                      {ouvindoRevisao ? "Parar transcrição" : "Falar pedido"}
                    </Botao>
                    {ouvindoRevisao && (
                      <Selo tom="critico" simbolo="●">Ouvindo — fale a alteração</Selo>
                    )}
                  </div>
                  <label className="flex items-start gap-2 rounded-campo border border-borda bg-papel-2 p-2 text-xs text-tinta-2 cursor-pointer">
                    <input
                      type="checkbox"
                      className="mt-[2px]"
                      checked={ensinarIA}
                      onChange={(e) => setEnsinarIA(e.target.checked)}
                    />
                    <span>
                      Ensinar a IA com esta correção
                      <span className="block text-tinta-3">
                        Marcado, ela passa a valer para as próximas petições desta mesma
                        categoria de caso. Desmarque quando o ajuste for só deste cliente
                        (um nome, um valor, uma data) — a correção continua no histórico
                        deste caso de qualquer jeito.
                      </span>
                    </span>
                  </label>
                  <div>
                    <BotaoProcesso
                      variante="secundario"
                      pequeno
                      processando={revisando}
                      textoProcessando="Aplicando a revisão…"
                      pendencia={promptRevisao.trim() ? null : "Descreva acima o que deve mudar."}
                      aguardando={salvando || ocupado}
                      erro={erro?.acao === "revisar" ? erro.texto : null}
                      concluido={concluido?.acao === "revisar" ? concluido.texto : null}
                      onClick={revisar}
                    >
                      Aplicar revisão
                    </BotaoProcesso>
                  </div>
                  {avisoRevisao && (
                    <Aviso tom="atencao" titulo="Confira a revisão">
                      {avisoRevisao}
                    </Aviso>
                  )}
                </CartaoFerramenta>

                <PesquisaWeb />
            </div>
          </details>
          </section>
        )}

        {/* ------------------------------------------------- outras peças do caso
          *
          * O escritório quer poder levar DUAS ações do mesmo acidente sem redigir a
          * segunda à mão. Até aqui isto não existia: o banco guardava uma peça por
          * caso (a chave de `peticoes_locais` é o `caso_id`), então gerar a segunda
          * apagaria a primeira. Agora elas moram em `peticoes_anexas` e a petição
          * inicial não é tocada.
          *
          * O bloco aparece SEMPRE que há minuta, mesmo sem sugestão nenhuma. Antes
          * ele só existia com a lista cheia — e quem abria a tela sem sugestão não
          * tinha como saber que a funcionalidade existia. */}
        {peticao && (
          <section className="grid gap-3 border border-acao-borda bg-acao-clara p-4">
            <div>
              <h3 className="m-0 text-sm font-semibold text-tinta">Outras peças deste caso</h3>
              <p className="mt-1 text-sm text-tinta-2">
                Ações possíveis a partir da mesma entrevista e dos mesmos documentos. Gerar uma
                delas <strong>não altera a petição inicial</strong> acima — cada peça sai com os
                pedidos próprios dela, para conferir e baixar.
              </p>
            </div>

            {erroAnexa && (
              <Aviso tom="critico" titulo="A peça não foi gerada">
                {erroAnexa}
              </Aviso>
            )}

            {sugestoes.length > 0 ? (
              <ul className="m-0 grid list-none gap-2 p-0">
                {sugestoes.map((acao, indice) => {
                  const jaGerada = anexas.find((p) => p.titulo === acao.titulo);
                  return (
                    <li key={`${acao.titulo}-${indice}`} className="border border-borda bg-papel p-3">
                      <div className="flex flex-wrap items-center justify-between gap-2">
                        <strong className="text-sm text-tinta">{acao.titulo}</strong>
                        <span className="rounded-pill border border-acao-borda px-2 py-0.5 text-xs text-acao">
                          {acao.prioridade === "principal"
                            ? "prioritária"
                            : acao.prioridade === "alternativa"
                              ? "alternativa"
                              : "avaliar"}
                        </span>
                      </div>
                      <p className="mb-0 mt-2 text-sm text-tinta-2">{acao.motivo}</p>
                      {acao.pedidos.length > 0 && (
                        <p className="mb-0 mt-2 text-xs text-tinta-3">
                          Pedidos possíveis: {acao.pedidos.join("; ")}
                        </p>
                      )}
                      <div className="mt-3 flex flex-wrap items-center gap-2">
                        <BotaoProcesso
                          variante={jaGerada ? "secundario" : "primario"}
                          pequeno
                          processando={gerandoAnexa === acao.titulo}
                          textoProcessando="Redigindo a peça…"
                          aguardando={ocupado || (gerandoAnexa !== null && gerandoAnexa !== acao.titulo)}
                          onClick={() => gerarAnexa(acao)}
                        >
                          {jaGerada ? "Redigir de novo" : "Gerar esta peça"}
                        </BotaoProcesso>
                        {jaGerada && (
                          <span className="text-xs text-tinta-3">
                            Já redigida — redigir de novo substitui o texto atual e guarda a versão
                            anterior no histórico da peça.
                          </span>
                        )}
                      </div>
                    </li>
                  );
                })}
              </ul>
            ) : (
              <p className="m-0 text-sm text-tinta-3">
                A análise desta minuta não apontou outra ação cabível a partir deste material.
                Novas sugestões aparecem aqui quando a petição é gerada de novo — normalmente
                depois de entrar documento novo no caso.
              </p>
            )}

            {anexas.length > 0 && (
              <div className="grid gap-2 border-t border-acao-borda pt-3">
                <h4 className="m-0 text-xs font-semibold uppercase tracking-[0.1em] text-tinta-3">
                  Peças já redigidas ({anexas.length} de {maximoAnexas})
                </h4>
                <ul className="m-0 grid list-none gap-2 p-0">
                  {anexas.map((peca) => (
                    <li key={peca.id} className="border border-borda bg-papel p-3">
                      <div className="flex flex-wrap items-start justify-between gap-2">
                        <div className="min-w-0">
                          <strong className="text-sm text-tinta">{peca.titulo}</strong>
                          <p className="mb-0 mt-1 text-xs text-tinta-3">
                            {peca.secoes} seções
                            {peca.gerada_por ? ` · por ${peca.gerada_por}` : ""}
                            {peca.atualizado_em
                              ? ` · ${new Date(peca.atualizado_em).toLocaleString("pt-BR")}`
                              : ""}
                          </p>
                        </div>
                        <div className="flex flex-wrap gap-2">
                          <BotaoProcesso
                            variante={anexaAberta === peca.id ? "secundario" : "primario"}
                            pequeno
                            processando={carregandoAnexa && anexaAberta === peca.id}
                            textoProcessando="Abrindo…"
                            onClick={() => alternarEdicaoAnexa(peca)}
                          >
                            {anexaAberta === peca.id ? "Fechar edição" : "Editar"}
                          </BotaoProcesso>
                          <BotaoProcesso
                            variante="secundario"
                            pequeno
                            processando={baixandoAnexa === `${peca.id}:docx`}
                            textoProcessando="Baixando…"
                            onClick={() => baixarAnexa(peca, "docx")}
                          >
                            .docx
                          </BotaoProcesso>
                          <BotaoProcesso
                            variante="texto"
                            pequeno
                            processando={baixandoAnexa === `${peca.id}:pdf`}
                            textoProcessando="Gerando o PDF…"
                            onClick={() => baixarAnexa(peca, "pdf")}
                          >
                            PDF
                          </BotaoProcesso>
                        </div>
                      </div>
                      {peca.pendencias.length > 0 && (
                        <p className="mb-0 mt-2 text-xs text-atencao">
                          Pendente nesta peça: {peca.pendencias.join("; ")}
                        </p>
                      )}

                      {anexaAberta === peca.id && peticaoAnexa && (
                        <div className="mt-3 grid gap-3 border-t border-borda pt-3">
                          {/* Mesma mudança da petição inicial: a peça anexa também
                            * deixou de ter campo cru de um lado e prévia do outro. */}
                          <div className="grid gap-3">
                            <PreviaPeticao
                              titulo={autoSalvoAnexa.titulo || peticaoAnexa.title}
                              secoes={peticaoAnexa.sections ?? []}
                              edicao={edicaoAnexa}
                              rotulos={autoSalvoAnexa.rotulos}
                              onEditar={autoSalvoAnexa.editar}
                              onEditarRotulo={autoSalvoAnexa.editarRotulo}
                              onEditarTitulo={autoSalvoAnexa.editarTitulo}
                            />
                            <IndicadorDeSalvamento
                              situacao={autoSalvoAnexa.situacao}
                              salvoEm={autoSalvoAnexa.salvoEm}
                              erro={autoSalvoAnexa.erro}
                              onTentarDeNovo={() => void autoSalvoAnexa.descarregar().catch(() => undefined)}
                            />
                          </div>

                          {historicoAnexa && historicoAnexa.versoes.length > 0 && (
                            <HistoricoDeCriticas
                              historico={historicoAnexa}
                              aberto={mostrarHistoricoAnexa}
                              onAlternar={() => setMostrarHistoricoAnexa((atual) => !atual)}
                            />
                          )}

                          <CartaoFerramenta
                            tipo="revisao"
                            icone={<FilePenLine size={18} aria-hidden />}
                            titulo="Pedir uma revisão por prompt (opcional)"
                            descricao={
                              <>
                                Descreva o que deve mudar nesta peça. A IA aplica só o que você
                                pedir, confere o resultado e preserva o resto do texto. A versão
                                atual fica guardada no histórico desta peça.
                              </>
                            }
                            selo={<Selo tom="info" simbolo="✎">Altera esta peça</Selo>}
                          >
                            <RotuloCampo htmlFor={`anexa-${peca.id}-prompt-revisao`} className="sr-only">
                              O que deve mudar nesta peça
                            </RotuloCampo>
                            <Campo
                              area
                              id={`anexa-${peca.id}-prompt-revisao`}
                              value={promptRevisaoAnexa}
                              onChange={(e) => setPromptRevisaoAnexa(e.target.value)}
                              rows={3}
                              placeholder="O que deve mudar nesta peça?"
                            />
                            <div>
                              <BotaoProcesso
                                variante="secundario"
                                pequeno
                                processando={revisandoAnexa}
                                textoProcessando="Aplicando a revisão…"
                                pendencia={promptRevisaoAnexa.trim() ? null : "Descreva acima o que deve mudar."}
                                onClick={revisarEdicaoAnexa}
                              >
                                Aplicar revisão
                              </BotaoProcesso>
                            </div>
                            {retornoAnexa && (
                              <Aviso tom={retornoAnexa.tom} titulo={retornoAnexa.tom === "ok" ? undefined : "Confira a revisão"}>
                                {retornoAnexa.texto}
                              </Aviso>
                            )}
                          </CartaoFerramenta>
                        </div>
                      )}
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </section>
        )}

        {peticao?.jurimetria && <ModuloJurimetria dados={peticao.jurimetria} />}
      </Cartao>

      {/* UM só ChatPeticao, sempre montado.
        *
        * Montar um para a coluna e outro para a gaveta duplicaria a escuta dos avisos
        * do painel (`avisarChatDaPeticao`) e a mensagem da IA entraria duas vezes na
        * transcrição. Aqui só a moldura muda: coluna fixa em tela larga, gaveta
        * sobreposta abaixo dela. */}
      <div
        className={`min-w-0 lg:sticky lg:top-2 lg:block lg:h-[calc(100dvh-4.8rem)] ${
          gaveta
            ? "max-lg:fixed max-lg:inset-y-0 max-lg:right-0 max-lg:z-[60] max-lg:w-[min(100vw,26rem)] max-lg:shadow-modal"
            : "max-lg:hidden"
        }`}
      >
        <ChatPeticao
          casoId={casoId}
          aoMudarAPeticao={() => void recarregar()}
          aoFechar={() => setGaveta(false)}
          expandido={chatLargo}
          aoAlternarLargura={() => setChatLargo((atual) => !atual)}
        />
      </div>

      {gaveta && (
        <button
          type="button"
          aria-label="Fechar a conversa"
          className="fixed inset-0 z-[55] cursor-pointer border-0 bg-black/35 p-0 lg:hidden"
          onClick={() => setGaveta(false)}
        />
      )}

      {!gaveta && (
        <button
          type="button"
          className="botao botao--primario fixed bottom-4 right-4 z-50 shadow-modal lg:hidden"
          onClick={() => setGaveta(true)}
        >
          Falar com a IA
        </button>
      )}
    </div>
  );
}

/**
 * O DOCUMENTO É O EDITOR.
 *
 * Isto já foi só a prévia: havia os campos crus de um lado e esta leitura do
 * outro, as duas sobre o mesmo estado `edicao`. Escrever num lugar e conferir
 * noutro dobrava o que havia na tela e alongava a página a ponto de rolar virar
 * o trabalho principal — foi a queixa que originou esta mudança.
 *
 * Agora cada seção é um campo com a tipografia da peça. O estado continua sendo
 * o mesmo `edicao`, então salvar, revisar por prompt e baixar .docx/PDF não
 * mudaram de caminho — nenhuma dessas ações sabe que a tela mudou.
 */
/** Onde está a edição: gravada, esperando a pausa, gravando ou com falha. */
function IndicadorDeSalvamento({
  situacao,
  salvoEm,
  erro,
  onTentarDeNovo,
}: {
  situacao: SituacaoDoSalvamento;
  salvoEm: Date | null;
  erro: string | null;
  onTentarDeNovo: () => void;
}) {
  if (situacao === "erro") {
    return (
      <p className="m-0 text-xs text-critico" role="status">
        Não foi possível salvar automaticamente{erro ? `: ${erro}` : ""}. Tentando de novo…{" "}
        <button
          type="button"
          className="bg-transparent border-0 p-0 underline cursor-pointer text-inherit"
          onClick={onTentarDeNovo}
        >
          Tentar agora
        </button>
      </p>
    );
  }
  const texto =
    situacao === "salvando"
      ? "Salvando…"
      : situacao === "pendente"
        ? "Alterações não salvas…"
        : salvoEm
          ? `Salvo automaticamente às ${salvoEm.toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" })}`
          : "As alterações são salvas automaticamente";
  return (
    <p className="m-0 text-xs text-tinta-3" role="status" aria-live="polite">
      {texto}
    </p>
  );
}

/** Largura da folha A4 em pixels CSS: 21 cm a 96 dpi. */
const LARGURA_DA_FOLHA_PX = (21 / 2.54) * 96;

/**
 * Quanto a folha precisa encolher para caber na coluna do documento.
 *
 * A peça é desenhada em centímetros de verdade — é o que faz a régua valer. Só
 * que com a conversa aberta ao lado não sobram 21 cm de tela, e uma folha em
 * medida fixa não encolhe: ela vira a largura MÍNIMA da coluna e empurra o
 * layout, que foi o documento passando por baixo do painel do chat.
 *
 * A saída é medir o espaço e escalar a folha inteira, em vez de estreitá-la:
 * estreitar mudaria onde a linha quebra, e a prévia deixaria de ser a página.
 */
function useEscalaDaFolha() {
  const moldura = useRef<HTMLDivElement>(null);
  const [escala, setEscala] = useState(1);

  useEffect(() => {
    const alvo = moldura.current;
    if (!alvo || typeof ResizeObserver === "undefined") return;
    const observador = new ResizeObserver(([entrada]) => {
      const largura = entrada.contentRect.width;
      if (!largura) return;
      // Nunca AUMENTA: a peça em tela larga fica no tamanho do papel, e não
      // esticada até a borda do monitor.
      setEscala(Math.min(1, largura / LARGURA_DA_FOLHA_PX));
    });
    observador.observe(alvo);
    return () => observador.disconnect();
  }, []);

  return { moldura, escala };
}

/** A peça como está na tela — para as gravações explícitas (salvar e baixar,
 *  revisar por prompt), que mandam a peça inteira em vez de só o pendente. */
function secoesDaTela(
  secoes: SecaoPeticao[] | undefined,
  edicao: Record<string, string>,
  rotulos: Record<string, string>,
): { code: string; content: string; label: string }[] {
  return (secoes ?? []).map((s) => ({
    code: s.code,
    content: edicao[s.code] ?? s.content,
    label: rotulos[s.code] ?? s.label,
  }));
}

/** Há algo na tela que o servidor ainda não tem — texto ou título de tópico. */
function haEdicaoNaTela(
  secoes: SecaoPeticao[],
  edicao: Record<string, string>,
  rotulos: Record<string, string>,
): boolean {
  return secoes.some(
    (s) => (edicao[s.code] ?? s.content) !== s.content || (rotulos[s.code] ?? s.label) !== s.label,
  );
}

function PreviaPeticao({
  titulo,
  secoes,
  edicao,
  rotulos,
  onEditar,
  onEditarRotulo,
  onEditarTitulo,
}: {
  titulo: string;
  secoes: SecaoPeticao[];
  edicao: Record<string, string>;
  /** O título de cada tópico, por código de seção, como está na tela. */
  rotulos: Record<string, string>;
  onEditar: (codigo: string, valor: string) => void;
  onEditarRotulo: (codigo: string, valor: string) => void;
  onEditarTitulo: (valor: string) => void;
}) {
  /* Uma barra só, no topo do documento, agindo sobre a seção em foco — como em
     qualquer editor de texto. Barra por seção repetiria os mesmos oito botões
     uma dúzia de vezes dentro da peça. */
  const [campoAtivo, setCampoAtivo] = useState<HTMLDivElement | null>(null);
  const selecao = useSelecaoFormatada(campoAtivo);
  const { moldura, escala } = useEscalaDaFolha();

  const aplicar = useCallback(
    (acao: (raiz: HTMLElement) => void) => {
      if (!campoAtivo) return;
      campoAtivo.focus();
      // `styleWithCSS`: sem isto o navegador escreve `<font color=…>`, marcação
      // que o leitor de formatação não reconhece e que se perderia ao salvar.
      document.execCommand("styleWithCSS", false, "true");
      acao(campoAtivo);
      // `execCommand` não dispara `input` em todos os navegadores; sem este
      // aviso a formatação aplicada pela barra não chegaria ao salvamento.
      campoAtivo.dispatchEvent(new Event("input", { bubbles: true }));
    },
    [campoAtivo],
  );

  return (
    /* `min-w-0`: sem isto a folha de 21 cm vira a largura MÍNIMA da coluna, e a
       coluna do documento cresce por cima da conversa ao lado — a peça passava
       por baixo do painel do chat. Item de grade não encolhe abaixo do próprio
       conteúdo a não ser que se mande. */
    <div className="grid min-w-0 gap-2" ref={moldura}>
      {/* A barra fica FORA da folha e ocupa a coluna inteira: ela é controle, não
          documento. Dentro da folha ela disputava os 16 cm da mancha de texto com
          o documento, quebrava em duas fileiras e encolhia junto com a página. */}
      <BarraDeFormatacao ativo={selecao} aoAplicar={aplicar} />

      {/* A régua também fica fora — pelo mesmo motivo, e para os marcadores não
          encolherem com a página até virarem alvos de dois pixels. Mas ela é
          alinhada com a mancha de texto: a caixa abaixo tem a largura e a margem
          da folha JÁ ESCALADAS, de modo que o zero da régua cai exatamente sobre
          a primeira letra do parágrafo. */}
      <div className="mx-auto" style={{ width: `${21 * escala}cm`, maxWidth: "100%" }}>
        <div style={{ marginLeft: `${3 * escala}cm`, width: `${LARGURA_UTIL_CM * escala}cm` }}>
          <ReguaDeTabulacao ativo={selecao} aoAplicar={aplicar} />
        </div>
      </div>

      {/* Sem `max-h`/`overflow` e sem `sticky`: o documento rola com a página,
          que é o que se espera de um texto que se está escrevendo.

          A LARGURA É A DO PAPEL, não um número redondo de pixels. A folha tem
          21 cm (A4) e as margens do modelo do escritório, então a mancha de
          texto mede exatamente os `LARGURA_UTIL_CM` da régua: 2 cm arrastados
          ali são os 2 cm que o Word vai mostrar. Com a caixa em pixels
          arbitrários, a régua seria um desenho bonito e mentiroso.

          A fonte segue o mesmo raciocínio — 12 pt e entrelinha 1,5, como em
          `CONFIGURACAO_VISUAL_PADRAO` —, de modo que a linha quebra na tela
          onde quebra no papel.

          `zoom` para caber, e não uma largura menor: com a conversa aberta não há
          21 cm de tela, e estreitar a folha faria a linha quebrar num lugar que o
          papel não quebra. O `zoom` diminui a folha INTEIRA — margens, letra e
          recuos na mesma proporção —, então o que se vê continua sendo a página,
          só que de mais longe. É `zoom` e não `transform: scale` porque o `zoom`
          é layout de verdade: a folha ocupa o espaço que aparenta ocupar, em vez
          de deixar um buraco do tamanho original embaixo. */}
      <div
        className="mx-auto w-[21cm] font-titulo text-[12pt] leading-[1.5] border border-borda-forte bg-papel shadow-sm pl-[3cm] pr-[1.89cm] py-12"
        style={{ zoom: escala }}
      >
        <h1 className="mb-10">
          <CampoDeTitulo
            valor={titulo}
            rotulo="Nome da peça"
            centralizado
            onEditar={onEditarTitulo}
          />
        </h1>
        <div className="grid gap-6">
          {secoes.map((secao) => (
            <section key={secao.code} className="grid gap-3">
              {/* HEADING, VALUE e CLOSING não têm título NA PEÇA — o endereçamento,
                  o valor da causa e o fecho entram como frase solta (ver o
                  `montar_docx`). Editar um rótulo que o .docx ignora seria
                  prometer uma mudança que não aparece no documento. */}
              {!["HEADING", "VALUE", "CLOSING"].includes(secao.code) && (
                <h2>
                  <CampoDeTitulo
                    valor={rotulos[secao.code] ?? secao.label}
                    rotulo={`Título do tópico ${secao.label || secao.code}`}
                    onEditar={(valor) => onEditarRotulo(secao.code, valor)}
                  />
                </h2>
              )}
              <CampoDoDocumento
                valor={edicao[secao.code] ?? secao.content}
                rotulo={rotulos[secao.code] || secao.label || secao.code}
                formato={secao.code === "CLOSING" ? "fechamento" : secao.code === "HEADING" ? "enderecamento" : "corpo"}
                onEditar={(valor) => onEditar(secao.code, valor)}
                onFoco={setCampoAtivo}
              />
            </section>
          ))}
        </div>
      </div>
    </div>
  );
}

/**
 * A rastreabilidade que a issue pede: quem pediu cada revisão, quando, sobre
 * qual versão — visível, não só guardada no banco. Fechado por padrão porque
 * a maioria das visitas à tela não precisa dela; abre com um clique quando
 * alguém precisa auditar o que mudou e por quê.
 */
function rotuloDaRevisao(revisao?: RevisaoRegistrada | null): string {
  if (!revisao) return "gerada pela IA";
  if (revisao.tipo === "prompt") return "revisão por prompt";
  if (revisao.tipo === "manual") return "edição manual";
  return "redigida pela IA";
}

function HistoricoDeCriticas({
  historico,
  aberto,
  onAlternar,
}: {
  historico: HistoricoDePeticao;
  aberto: boolean;
  onAlternar: () => void;
}) {
  const versoes = [...historico.versoes].reverse();
  return (
    <div className="grid gap-2 border border-borda p-3 bg-papel">
      <button
        type="button"
        className="flex items-center justify-between gap-2 text-left text-xs font-semibold text-tinta-3 uppercase tracking-wide bg-transparent border-0 p-0 cursor-pointer"
        onClick={onAlternar}
      >
        <span>
          Histórico de edições ({historico.versoes.length}{" "}
          {historico.versoes.length === 1 ? "versão anterior" : "versões anteriores"}
          {historico.criticas.length > 0
            ? ` · ${historico.criticas.length} ${historico.criticas.length === 1 ? "crítica" : "críticas"}`
            : ""}
          )
        </span>
        <span aria-hidden>{aberto ? "▲" : "▼"}</span>
      </button>
      {aberto && versoes.length > 0 && (
        <ul className="grid gap-3 m-0 p-0 list-none">
          {versoes.map((versao) => {
            const revisao = versao.dados?.revisao;
            return (
              <li key={versao.versao} className="grid gap-1 border-l-2 border-borda pl-3">
                <div className="flex flex-wrap items-baseline gap-x-2 text-xs text-tinta-3">
                  <strong className="text-tinta-2">Versão {versao.versao}</strong>
                  <span>{rotuloDaRevisao(revisao)}</span>
                  {revisao?.usuario && <span>por {revisao.usuario}</span>}
                  <span>{new Date(revisao?.em || versao.criado_em).toLocaleString("pt-BR")}</span>
                </div>
                {revisao?.prompt && (
                  <p className="text-sm text-tinta-2 m-0 whitespace-pre-wrap">“{revisao.prompt}”</p>
                )}
                {(revisao?.alteradas ?? []).length > 0 && (
                  <p className="text-xs text-tinta-3 m-0">
                    Seções alteradas: {(revisao?.alteradas ?? []).join(", ")}
                  </p>
                )}
              </li>
            );
          })}
        </ul>
      )}
      {aberto && historico.criticas.length > 0 && (
        <ul className="grid gap-3 m-0 p-0 list-none">
          <li className="text-xs font-semibold text-tinta-3 uppercase tracking-wide">Críticas registradas</li>
          {[...historico.criticas].reverse().map((critica) => (
            <li key={critica.id} className="grid gap-1 border-l-2 border-borda pl-3">
              <div className="flex flex-wrap items-baseline gap-x-2 text-xs text-tinta-3">
                <strong className="text-tinta-2">{critica.usuario || "usuário não identificado"}</strong>
                <span>
                  v{critica.versao_origem} → v{critica.versao_resultado}
                </span>
                <span>{new Date(critica.criado_em).toLocaleString("pt-BR")}</span>
                {/* Qual crítica está ensinando a IA e qual valeu só aqui — sem
                  * isto não há como saber por que a próxima petição saiu
                  * diferente. */}
                <span
                  className={
                    critica.generaliza === false
                      ? "text-tinta-3"
                      : "text-ok font-semibold"
                  }
                  title={
                    critica.generaliza === false
                      ? "Valeu só neste caso — não instrui as próximas petições."
                      : "Esta correção instrui as próximas petições desta categoria."
                  }
                >
                  {critica.generaliza === false ? "só neste caso" : "ensina a IA"}
                </span>
              </div>
              <p className="text-sm text-tinta-2 m-0 whitespace-pre-wrap">{critica.prompt}</p>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function ModuloJurimetria({
  dados,
}: {
  dados: NonNullable<Peticao["jurimetria"]>;
}) {
  if (!dados.disponivel) {
    return (
      <section className="grid gap-3 border border-borda p-4 bg-papel">
        <h3 className="text-sm font-semibold m-0">Jurimetria da minuta</h3>
        <Aviso tom="atencao">{dados.aviso || "Base de processos indisponível."}</Aviso>
      </section>
    );
  }

  const estatisticas = dados.estatisticas;
  const merito = estatisticas?.desfechos_merito;
  const similaridade = estatisticas?.similaridade_amostra;
  return (
    <section className="grid gap-4 border border-borda p-4 bg-papel">
      <header className="grid gap-1">
        <h3 className="text-sm font-semibold m-0">Jurimetria da minuta</h3>
        <p className={SUB}>
          Busca vetorial pelos embeddings do acervo do Advocacia IA. Módulo interno de apoio
          à decisão; não integra o texto nem o arquivo da petição.
        </p>
        {dados.jurisdicao && (
          <p className="text-xs text-tinta-3 m-0">
            Focada em <strong className="text-tinta-2">{dados.jurisdicao}</strong>.
          </p>
        )}
      </header>

      {estatisticas && (
        <div className="grid grid-cols-2 md:grid-cols-3 gap-2 text-xs text-tinta-3">
          <div className="border border-borda p-2 bg-papel-2">
            <strong className="block text-tinta-2">{estatisticas.processos_analisados}</strong>
            processos semelhantes
          </div>
          <div className="border border-borda p-2 bg-papel-2">
            <strong className="block text-tinta-2">
              {merito ? `${merito.favoraveis}/${merito.processos} (${merito.percentual.toLocaleString("pt-BR")}%)` : "—"}
            </strong>
            favoráveis no mérito
          </div>
          <div className="border border-borda p-2 bg-papel-2">
            <strong className="block text-tinta-2">
              {similaridade ? similaridade.mediana.toFixed(3) : "—"}
            </strong>
            similaridade mediana
          </div>
        </div>
      )}

      {dados.sintese && <p className={TEXTO}>{dados.sintese}</p>}
      {(dados.fundamentos ?? []).length > 0 && (
        <ListaJurimetria
          titulo="Fundamentos que orientaram a análise"
          itens={(dados.fundamentos ?? []).map((item) => ({
            titulo: item.ponto || "Fundamento",
            detalhe: item.impacto || "",
            refs: item.processos,
          }))}
        />
      )}
      {(dados.riscos ?? []).length > 0 && (
        <ListaJurimetria
          titulo="Riscos e distinções"
          itens={(dados.riscos ?? []).map((item) => ({
            titulo: item.ponto || "Risco",
            detalhe: item.distincao || "",
            refs: item.processos,
          }))}
        />
      )}

      {(dados.precedentes ?? []).length > 0 && (
        <div className="grid gap-2">
          <h4 className="text-xs font-semibold text-tinta-3 m-0">Decisões consultadas</h4>
          <ul className="grid gap-2 list-none p-0 m-0">
            {(dados.precedentes ?? []).map((item) => (
              <li key={item.indice} className="text-xs text-tinta-2 border-l-2 border-borda pl-3">
                <strong>
                  [{item.indice}] Processo {item.processo_formatado || item.processo || "não informado"}
                </strong>
                {` — ${item.resultado || "desfecho não informado"}; ${item.vara || "órgão não informado"}`}
                {typeof item.similaridade === "number" ? `; similaridade ${item.similaridade.toFixed(3)}` : ""}
                {/* O link vai para a consulta processual do PRÓPRIO tribunal, montada
                  * a partir do número CNJ (ver `tribunais.link_do_processo`). Dizer
                  * qual tribunal antes do clique evita a surpresa de cair num TRT
                  * que o advogado não esperava. */}
                {item.url && (
                  <>
                    {" — "}
                    <a className="text-acao underline" href={item.url} target="_blank" rel="noreferrer">
                      abrir processo{item.tribunal ? ` no ${item.tribunal}` : ""}
                    </a>
                  </>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}

      <p className="text-xs text-tinta-3 m-0">{dados.aviso}</p>
    </section>
  );
}

function ListaJurimetria({
  titulo,
  itens,
}: {
  titulo: string;
  itens: Array<{ titulo: string; detalhe: string; refs: string[] }>;
}) {
  return (
    <div className="grid gap-2">
      <h4 className="text-xs font-semibold text-tinta-3 m-0">{titulo}</h4>
      <ul className="grid gap-2 m-0 pl-4 text-xs text-tinta-2">
        {itens.map((item, indice) => (
          <li key={`${item.titulo}-${indice}`}>
            <strong>{item.titulo}</strong>{item.detalhe ? ` — ${item.detalhe}` : ""}{" "}
            <span className="text-tinta-3">[{item.refs.join(", ")}]</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

function ListaRotulo({ titulo, itens }: { titulo: string; itens: string[] }) {
  return (
    <div>
      <p className="text-xs font-semibold text-tinta-3 m-0 mb-1">{titulo}</p>
      <ul className="text-xs text-tinta-2 m-0 pl-4">
        {itens.map((item) => (
          <li key={item}>{item}</li>
        ))}
      </ul>
    </div>
  );
}

function ResumoAnalise({ titulo, tom, itens, vazio }: { titulo: string; tom: "ok" | "atencao"; itens: string[]; vazio: string }) {
  const unicos = [...new Set(itens.filter(Boolean))];
  return <div className={`rounded-campo border p-3 ${tom === "ok" ? "border-ok bg-ok-claro" : "border-atencao bg-atencao-claro"}`}>
    <p className="m-0 text-xs font-bold text-tinta">{titulo} <span className="font-normal text-tinta-3">({unicos.length})</span></p>
    {unicos.length ? <ul className="mt-2 mb-0 grid gap-1 pl-4 text-xs leading-relaxed text-tinta-2">{unicos.slice(0, 5).map((item) => <li key={item}>{item}</li>)}</ul> : <p className="mt-2 mb-0 text-xs text-tinta-3">{vazio}</p>}
    {unicos.length > 5 && <p className="mt-2 mb-0 text-xs text-tinta-3">+ {unicos.length - 5} outros pontos</p>}
  </div>;
}

/**
 * Moldura dos cards de ferramenta abaixo da petição — revisão por prompt e
 * pesquisa na web.
 *
 * Os dois eram caixas cinzas iguais, só com rótulo: não dava para saber de
 * relance qual mexe na peça e qual só consulta. Agora cada um tem ícone, faixa
 * lateral e selo próprios (símbolo + palavra, nunca só cor): a revisão usa a
 * cor de ação — ela altera a petição —; a pesquisa usa o ouro da marca, que não
 * é cor de estado e não compete com o botão principal.
 */
function CartaoFerramenta({
  tipo,
  icone,
  titulo,
  descricao,
  selo,
  children,
}: {
  tipo: "revisao" | "pesquisa";
  icone: ReactNode;
  titulo: string;
  descricao: ReactNode;
  selo?: ReactNode;
  children: ReactNode;
}) {
  const visual =
    tipo === "revisao"
      ? { faixa: "border-l-acao", icone: "bg-acao-clara text-acao border-acao-borda" }
      : { faixa: "border-l-marca-ouro", icone: "bg-marca-ouro-claro text-tinta border-borda-forte" };
  return (
    <section
      className={`grid gap-3 rounded-cartao border border-borda-forte border-l-4 bg-papel p-4 shadow-cartao ${visual.faixa}`}
    >
      <header className="flex flex-wrap items-start justify-between gap-2">
        <div className="flex min-w-0 items-start gap-3">
          <span
            className={`flex h-9 w-9 flex-none items-center justify-center rounded-campo border ${visual.icone}`}
          >
            {icone}
          </span>
          <div className="min-w-0">
            <h3 className="m-0 font-ui text-base font-semibold text-tinta">{titulo}</h3>
            <p className="mt-1 mb-0 text-xs leading-relaxed text-tinta-3">{descricao}</p>
          </div>
        </div>
        {selo}
      </header>
      {children}
    </section>
  );
}

/**
 * Dúvida rápida pesquisada na web, sem sair da petição.
 *
 * Fica abaixo da revisão por prompt, mas é independente dela: não altera a
 * peça, não entra no dossiê e não é gravada. As perguntas da sessão ficam só
 * aqui, na tela, com as fontes à vista — a resposta vem da internet e o
 * advogado precisa conferir antes de usar (ver `app/pesquisa_web.py`).
 */
function PesquisaWeb() {
  const [pergunta, setPergunta] = useState("");
  const [pesquisando, setPesquisando] = useState(false);
  const [erro, setErro] = useState<string | null>(null);
  const [resultados, setResultados] = useState<ResultadoPesquisaWeb[]>([]);

  async function pesquisar() {
    const texto = pergunta.trim();
    if (!texto || pesquisando) return;
    setPesquisando(true);
    setErro(null);
    try {
      const resultado = await pesquisarNaWeb(texto);
      setResultados((atuais) => [resultado, ...atuais]);
      setPergunta("");
    } catch (e) {
      setErro(e instanceof Error ? e.message : "Não foi possível pesquisar agora.");
    } finally {
      setPesquisando(false);
    }
  }

  return (
    <CartaoFerramenta
      tipo="pesquisa"
      icone={<Globe size={18} aria-hidden />}
      titulo="Tirar uma dúvida na web"
      descricao={
        <>
          Pesquisa na internet e responde com as fontes (ex.: &quot;prazo prescricional de
          acidente de trabalho no TST&quot;). Ctrl+Enter também pesquisa.
        </>
      }
      selo={<Selo tom="neutro" simbolo="i">Só consulta · não altera a petição</Selo>}
    >
      <RotuloCampo htmlFor="pesquisa-web" className="sr-only">
        O que você quer pesquisar
      </RotuloCampo>
      <Campo
        area
        id="pesquisa-web"
        value={pergunta}
        onChange={(e) => setPergunta(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
            e.preventDefault();
            void pesquisar();
          }
        }}
        rows={2}
        className="min-h-[72px]"
        maxLength={1000}
        placeholder="O que você quer pesquisar?"
      />
      <div>
        <BotaoProcesso
          variante="secundario"
          pequeno
          processando={pesquisando}
          textoProcessando="Pesquisando na web…"
          dica="Buscando fontes e redigindo a resposta"
          pendencia={pergunta.trim() ? null : "Escreva acima a sua dúvida."}
          erro={erro}
          onClick={pesquisar}
        >
          <Search size={14} aria-hidden />
          Pesquisar
        </BotaoProcesso>
      </div>

      {resultados.length > 0 && (
        <div className="grid gap-3">
          {resultados.map((resultado, indice) => (
            <ResultadoDaPesquisa
              key={`${resultados.length - indice}-${resultado.pergunta}`}
              resultado={resultado}
              maisRecente={indice === 0}
            />
          ))}
        </div>
      )}
    </CartaoFerramenta>
  );
}

function ResultadoDaPesquisa({
  resultado,
  maisRecente,
}: {
  resultado: ResultadoPesquisaWeb;
  maisRecente: boolean;
}) {
  const semFontes = resultado.fontes.length === 0;
  return (
    <article className="overflow-hidden rounded-campo border border-borda-forte bg-papel">
      <header className="flex flex-wrap items-start justify-between gap-2 border-b border-borda bg-papel-2 px-3 py-2">
        <div className="min-w-0">
          <p className="m-0 text-xs font-semibold text-tinta-3">Pergunta</p>
          <p className="m-0 text-sm font-semibold text-tinta break-words">{resultado.pergunta}</p>
        </div>
        <div className="flex flex-wrap gap-1">
          {maisRecente && <Selo tom="info" simbolo="→">Mais recente</Selo>}
          {semFontes ? (
            <Selo tom="atencao" simbolo="!">Sem fontes</Selo>
          ) : (
            <Selo tom="ok" simbolo="✓">{resultado.fontes.length} fonte(s)</Selo>
          )}
        </div>
      </header>

      <div className="px-3 py-3">
        <RespostaFormatada texto={resultado.resposta} />
      </div>

      {!semFontes && (
        <details className="border-t border-borda px-3 py-2 text-xs text-tinta-2">
          <summary className="flex cursor-pointer items-center gap-2 font-semibold text-tinta">
            <BookOpenCheck size={14} aria-hidden />
            Ver fontes consultadas ({resultado.fontes.length})
          </summary>
          <ol className="mt-2 mb-1 grid list-none gap-2 pl-0">
            {resultado.fontes.map((fonte, i) => (
              <li key={fonte.url} className="grid grid-cols-[auto_1fr] gap-2 rounded-campo bg-papel-2 p-2">
                <span className="flex h-5 w-5 items-center justify-center rounded-pill bg-acao-clara text-xs font-bold text-acao">
                  {i + 1}
                </span>
                <span className="min-w-0">
                  <a
                    href={fonte.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="font-semibold text-acao underline break-words"
                  >
                    {fonte.titulo || dominioDe(fonte.url)}
                  </a>
                  <span className="block text-tinta-3">{dominioDe(fonte.url)}</span>
                  {fonte.trecho && <span className="mt-1 block leading-relaxed">{fonte.trecho}</span>}
                </span>
              </li>
            ))}
          </ol>
        </details>
      )}

      <p className="m-0 flex items-start gap-2 border-t border-atencao-borda bg-atencao-claro px-3 py-2 text-xs text-atencao">
        <span aria-hidden className="font-bold">!</span>
        {semFontes
          ? "A pesquisa não devolveu fontes — trate a resposta com cautela."
          : "Conteúdo da internet: confira as fontes antes de usar na petição."}
      </p>
    </article>
  );
}

function ComparacaoRevisao({
  anterior, candidata, revisando, onAceitar, onDescartar,
}: {
  anterior: SecaoPeticao[]; candidata: SecaoPeticao[]; revisando: boolean;
  onAceitar: () => void; onDescartar: () => void;
}) {
  const comparacaoRef = useRef<HTMLElement>(null);
  // Tela cheia: com a peça dividida ao meio, cada coluna fica estreita demais
  // para o advogado achar a alteração num parágrafo longo.
  const [expandido, setExpandido] = useState(false);
  // Uma seção pode trocar de código/posição numa revisão. A linha preserva o par
  // achado por conteúdo antes de cair no código, portanto texto idêntico não vira
  // duas seções inteiras em vermelho e verde.
  const linhas = alinharSecoes(anterior, candidata);
  const mudancas = linhas.filter((linha) => linha.antes.content !== linha.depois.content).length;
  useEffect(() => {
    // Ao chegar a candidata (ou ao expandir), o advogado não precisa procurar a
    // alteração numa peça longa. O primeiro trecho marcado (vermelho ou verde)
    // vira o ponto de entrada; `scrollIntoView` também ajusta a coluna rolável.
    const primeiro = comparacaoRef.current?.querySelector<HTMLElement>("[data-revisao-alteracao='true']");
    if (!primeiro) return;
    const quadro = window.requestAnimationFrame(() => {
      primeiro.scrollIntoView({ behavior: "smooth", block: "center", inline: "nearest" });
      primeiro.focus({ preventScroll: true });
    });
    return () => window.cancelAnimationFrame(quadro);
  }, [anterior, candidata, expandido]);
  useEffect(() => {
    if (!expandido) return;
    const fecharComEsc = (e: KeyboardEvent) => { if (e.key === "Escape") setExpandido(false); };
    const overflowAnterior = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    window.addEventListener("keydown", fecharComEsc);
    return () => {
      document.body.style.overflow = overflowAnterior;
      window.removeEventListener("keydown", fecharComEsc);
    };
  }, [expandido]);
  return (
    <section
      ref={comparacaoRef}
      role={expandido ? "dialog" : undefined}
      aria-modal={expandido || undefined}
      aria-label={expandido ? "Revisão pendente em tela cheia" : undefined}
      className={expandido
        ? "fixed inset-0 z-50 grid grid-rows-[auto_auto_minmax(0,1fr)_auto] gap-3 bg-papel p-4 sm:p-6"
        : "grid gap-3 rounded-cartao border border-atencao-borda border-l-4 border-l-atencao-marca bg-papel p-4 shadow-cartao-forte"}
    >
      <header className="flex flex-wrap items-start justify-between gap-2">
        <div className="flex min-w-0 items-start gap-3">
          <span className="flex h-9 w-9 flex-none items-center justify-center rounded-campo border border-atencao-borda bg-atencao-claro text-atencao">
            <GitCompareArrows size={18} aria-hidden />
          </span>
          <div className="min-w-0">
            <h3 className={TITULO}>Revisão pendente</h3>
            <p className={SUB}>Compare a peça completa antes de aceitar.</p>
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-1">
          <Selo tom="atencao" simbolo="!">Aguardando sua decisão</Selo>
          <Selo tom="info" simbolo="✎">{mudancas} seção(ões) alterada(s)</Selo>
        </div>
      </header>
      <div className="flex flex-wrap items-center justify-between gap-2 rounded-campo bg-papel-2 px-3 py-2 text-xs text-tinta-2">
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1">
          <span className="font-semibold text-tinta">Como ler:</span>
          <span><span className="bg-red-100 px-1 text-red-900 line-through">vermelho</span> foi apagado</span>
          <span><span className="bg-green-100 px-1 text-green-900">verde</span> foi adicionado</span>
          <span className="text-tinta-3">A peça oficial continua preservada até você aceitar.</span>
        </div>
        <button
          type="button"
          onClick={() => setExpandido((v) => !v)}
          aria-pressed={expandido}
          className="inline-flex items-center gap-2 rounded-campo border border-borda-campo bg-papel px-4 py-2 text-sm font-semibold text-tinta shadow-sm transition hover:bg-papel-2 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2"
        >
          {expandido ? <Minimize2 size={18} aria-hidden /> : <Maximize2 size={18} aria-hidden />}
          {expandido ? "Sair da tela cheia" : "Expandir comparação"}
        </button>
      </div>
      <div className={`grid min-h-0 grid-cols-2 gap-3 max-[760px]:grid-cols-1 ${expandido ? "max-[760px]:overflow-auto" : ""}`}>
        <ColunaComparacao titulo="Versão anterior" linhas={linhas} tipo="antes" expandido={expandido} />
        <ColunaComparacao titulo="Nova versão" linhas={linhas} tipo="depois" expandido={expandido} />
      </div>
      <div className="flex flex-wrap justify-end gap-2 border-t border-borda pt-3">
        <Botao variante="secundario" pequeno disabled={revisando} onClick={onDescartar}>✕ Descartar revisão</Botao>
        <Botao variante="primario" pequeno disabled={revisando} onClick={onAceitar}>{revisando ? "Salvando…" : "✓ Aceitar revisão"}</Botao>
      </div>
    </section>
  );
}

function ColunaComparacao({ titulo, linhas, tipo, expandido }: { titulo: string; linhas: LinhaComparacao[]; tipo: "antes" | "depois"; expandido: boolean }) {
  return <article className={`min-w-0 overflow-auto rounded-campo border border-borda border-t-4 bg-papel-2 ${expandido ? "h-full min-h-0 p-5" : "max-h-[70vh] p-3"} ${tipo === "antes" ? "border-t-red-500" : "border-t-ok"}`}>
    <h4 className="sticky top-0 z-[1] mb-2 flex items-center justify-between gap-2 bg-papel-2 py-1 text-sm font-semibold text-tinta">
      {titulo}
      {tipo === "antes" ? <Selo tom="neutro" simbolo="↺">Atual</Selo> : <Selo tom="ok" simbolo="✓">Proposta da IA</Selo>}
    </h4>
    {linhas.map((linha, i) => {
      const secao = tipo === "antes" ? linha.antes : linha.depois;
      const oposta = tipo === "antes" ? linha.depois : linha.antes;
      return <div key={`${linha.antes.code}:${linha.depois.code}-${i}`} className={`mb-4 whitespace-pre-wrap leading-relaxed text-tinta ${expandido ? "text-base" : "text-sm"}`}>
      <p className="mb-1 font-semibold">{secao.label}</p>
      {/* Sem as marcações: aqui se compara o que a peça DIZ. Formatação virando
          palavra alterada esconderia a mudança de texto que importa. */}
      <TextoComDiff texto={semMarcacao(secao.content)} outro={semMarcacao(oposta.content)} tipo={tipo} />
    </div>;
    })}
  </article>;
}

function TextoComDiff({ texto, outro, tipo }: { texto: string; outro: string; tipo: "antes" | "depois" }) {
  if (texto === outro) return <>{texto}</>;
  const palavras = texto.split(/(\s+)/);
  const alteradas = indicesAlterados(texto, outro);
  let indicePalavra = 0;
  return <>{palavras.map((palavra, i) => {
    const ehPalavra = Boolean(palavra.trim());
    const mudou = ehPalavra && alteradas.has(indicePalavra);
    if (ehPalavra) indicePalavra += 1;
    return <span
      key={i}
      data-revisao-alteracao={mudou ? "true" : undefined}
      tabIndex={mudou ? -1 : undefined}
      className={mudou ? tipo === "antes" ? "bg-red-100 text-red-900 line-through" : "bg-green-100 text-green-900" : undefined}
    >{palavra}</span>;
  })}</>;
}
