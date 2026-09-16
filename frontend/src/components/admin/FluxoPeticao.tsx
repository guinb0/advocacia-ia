"use client";

/**
 * Análise + petição local (DeepSeek) — entrevista + OCR, sem agente.
 * O botão principal fica no cabeçalho do dossiê; aqui só resultado e edição.
 */

import { useCallback, useEffect, useRef, useState } from "react";

import { Aviso, Botao, Cartao, RotuloCampo, Campo } from "@/components/ui/Basicos";
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
  type RevisaoRegistrada,
  type SecaoPeticao,
} from "@/lib/agente";
import { baixarArquivo } from "@/lib/baixar";


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
  const [edicao, setEdicao] = useState<Record<string, string>>({});
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

  useEffect(() => {
    if (!peticao?.sections) return;
    setEdicao(Object.fromEntries(peticao.sections.map((s) => [s.code, s.content])));
  }, [peticao?.id, peticao?.sections]);

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
      }
    } catch (e) {
      setErro({ acao: "gerar", texto: e instanceof Error ? e.message : "Falha ao gerar a petição." });
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
      const secoes = (peticao.sections ?? []).map((s) => ({
        code: s.code,
        content: edicao[s.code] ?? s.content,
      }));
      const atualizada = await salvarRascunhoPeticao(casoId, peticao.id, secoes);
      setPeticao(atualizada);
      const arquivo = await baixarArquivoDaPeticao(casoId, peticao.id, formato);
      baixarArquivo(arquivo, `Peticao inicial - v${atualizada.version}.${formato}`);
      setConcluido({ acao: "salvar", texto: `Versão ${atualizada.version} salva e .${formato} baixado.` });
    } catch (e) {
      setErro({ acao: "salvar", texto: e instanceof Error ? e.message : "Não foi possível salvar." });
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
      const secoesAtuais = peticao.sections ?? [];
      if (secoesAtuais.some((s) => (edicao[s.code] ?? s.content) !== s.content)) {
        await salvarRascunhoPeticao(
          casoId,
          peticao.id,
          secoesAtuais.map((s) => ({ code: s.code, content: edicao[s.code] ?? s.content })),
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
      await recarregar();
      // `recarregar` lê a versão persistida; numa revisão sem alteração ela não
      // contém o aviso/perguntas retornados pela IA. Reaplica o resultado da
      // chamada depois da leitura para que a tela não perca esse retorno.
      setPeticao(resultado.peticao);
    } catch (e) {
      setErro({
        acao: "revisar",
        texto: e instanceof Error ? e.message : "Não foi possível aplicar a revisão.",
      });
    } finally {
      setRevisando(false);
    }
  }

  async function decidirRevisao(aceitar: boolean) {
    const candidata = peticao?.revisao_pendente;
    if (!peticao || !candidata) return;
    setRevisando(true);
    setErro(null);
    try {
      const resultado = aceitar
        ? await aceitarRevisaoPendente(casoId, candidata.id)
        : await descartarRevisaoPendente(casoId, candidata.id);
      setPeticao(resultado.peticao);
      setEdicao(Object.fromEntries((resultado.peticao.sections ?? []).map((s) => [s.code, s.content])));
      setConcluido({ acao: "revisar", texto: aceitar ? "Revisão aceita e gravada como nova versão." : "Revisão descartada; a peça original foi preservada." });
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
    } catch (e) {
      setErroAnexa(e instanceof Error ? e.message : "Não foi possível gerar esta peça.");
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
  const [edicaoAnexa, setEdicaoAnexa] = useState<Record<string, string>>({});
  const [carregandoAnexa, setCarregandoAnexa] = useState(false);
  const [salvandoAnexa, setSalvandoAnexa] = useState(false);
  /* Revisão por prompt — recurso opcional, oferecido para a peça anexa com a
   * mesma qualidade da petição inicial; sem "ensinar a IA" nem versão anterior
   * guardada, porque a anexa já não tem histórico nem para "gerar de novo"
   * (ver `app/peticao_local.revisar_anexa_com_prompt`). */
  const [promptRevisaoAnexa, setPromptRevisaoAnexa] = useState("");
  const [revisandoAnexa, setRevisandoAnexa] = useState(false);
  const [retornoAnexa, setRetornoAnexa] = useState<{ tom: "ok" | "atencao"; texto: string } | null>(null);
  const [historicoAnexa, setHistoricoAnexa] = useState<HistoricoDePeticao | null>(null);
  const [mostrarHistoricoAnexa, setMostrarHistoricoAnexa] = useState(false);

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
      setEdicaoAnexa(Object.fromEntries((dados.sections ?? []).map((s) => [s.code, s.content])));
    } catch (e) {
      setErroAnexa(e instanceof Error ? e.message : "Não foi possível abrir esta peça para edição.");
      setAnexaAberta(null);
    } finally {
      setCarregandoAnexa(false);
    }
  }

  async function salvarEdicaoAnexa() {
    if (!peticaoAnexa) return;
    setErroAnexa(null);
    setSalvandoAnexa(true);
    try {
      const secoes = (peticaoAnexa.sections ?? []).map((s) => ({
        code: s.code,
        content: edicaoAnexa[s.code] ?? s.content,
      }));
      const atualizada = await salvarRascunhoPeticao(casoId, peticaoAnexa.id, secoes);
      setPeticaoAnexa(atualizada);
      await Promise.all([recarregarAnexas(), carregarHistoricoAnexa(peticaoAnexa.id)]);
    } catch (e) {
      setErroAnexa(e instanceof Error ? e.message : "Não foi possível salvar esta peça.");
    } finally {
      setSalvandoAnexa(false);
    }
  }

  async function revisarEdicaoAnexa() {
    if (!peticaoAnexa || !promptRevisaoAnexa.trim()) return;
    setErroAnexa(null);
    setRetornoAnexa(null);
    setRevisandoAnexa(true);
    try {
      const secoesAtuais = peticaoAnexa.sections ?? [];
      if (secoesAtuais.some((s) => (edicaoAnexa[s.code] ?? s.content) !== s.content)) {
        await salvarRascunhoPeticao(
          casoId,
          peticaoAnexa.id,
          secoesAtuais.map((s) => ({ code: s.code, content: edicaoAnexa[s.code] ?? s.content })),
        );
      }
      const resultado = await revisarPeticaoComPrompt(
        casoId,
        peticaoAnexa.id,
        promptRevisaoAnexa.trim(),
        false,
      );
      setPeticaoAnexa(resultado.peticao);
      setEdicaoAnexa(
        Object.fromEntries((resultado.peticao.sections ?? []).map((s) => [s.code, s.content])),
      );
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

  return (
    <Cartao className="grid gap-4">
      <header className="grid gap-2">
        <h2 className={TITULO}>Análise e petição</h2>
        <p className={SUB}>
          Cruza a entrevista com os documentos lidos por OCR e redige a petição inicial com
          DeepSeek. Use o botão no topo do dossiê para gerar.
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
            <h3 className="text-sm font-semibold m-0">
              Petição inicial — versão {peticao.version}
            </h3>
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
            titulo={peticao.title}
            secoes={peticao.sections ?? []}
            edicao={edicao}
            onEditar={(codigo, valor) => setEdicao((atual) => ({ ...atual, [codigo]: valor }))}
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

          {/* A revisão por prompt vem DEPOIS do texto: ela age sobre o que está
            * escrito, e pedir a mudança antes de ver a peça invertia a leitura —
            * o advogado abria a tela num campo em branco e precisava rolar para
            * descobrir o que iria alterar. */}
          <div className="grid gap-2 border border-borda-forte bg-papel p-3">
            <RotuloCampo htmlFor="prompt-revisao">
              Pedir uma revisão por prompt
            </RotuloCampo>
            <p className="text-xs text-tinta-3 m-0">
              Descreva o que deve mudar (ex.: &quot;separe dano moral do material nos
              pedidos&quot;). A IA gera uma nova versão completa para comparação. A versão
              atual só muda depois que você aceitar a revisão.
            </p>
            <Campo
              area
              id="prompt-revisao"
              value={promptRevisao}
              onChange={(e) => setPromptRevisao(e.target.value)}
              rows={3}
              placeholder="O que deve mudar nesta petição?"
            />
            <div className="flex items-center gap-2">
              <Botao variante="secundario" pequeno onClick={alternarMicrofoneRevisao}>
                {ouvindoRevisao ? "Parar transcrição" : "🎙️ Falar pedido"}
              </Botao>
              {ouvindoRevisao && <span className="text-xs text-tinta-3">Ouvindo em português… fale a alteração desejada.</span>}
            </div>
            <label className="flex items-start gap-2 text-xs text-tinta-2 cursor-pointer">
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
          </div>
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
                            titulo={peticaoAnexa.title}
                            secoes={peticaoAnexa.sections ?? []}
                            edicao={edicaoAnexa}
                            onEditar={(codigo, valor) =>
                              setEdicaoAnexa((atual) => ({ ...atual, [codigo]: valor }))
                            }
                          />
                          <div>
                            <BotaoProcesso
                              variante="secundario"
                              pequeno
                              processando={salvandoAnexa}
                              textoProcessando="Salvando…"
                              onClick={salvarEdicaoAnexa}
                            >
                              Salvar edição
                            </BotaoProcesso>
                          </div>
                        </div>

                        {historicoAnexa && historicoAnexa.versoes.length > 0 && (
                          <HistoricoDeCriticas
                            historico={historicoAnexa}
                            aberto={mostrarHistoricoAnexa}
                            onAlternar={() => setMostrarHistoricoAnexa((atual) => !atual)}
                          />
                        )}

                        <div className="grid gap-2 border border-borda-forte bg-papel p-3">
                          <RotuloCampo htmlFor={`anexa-${peca.id}-prompt-revisao`}>
                            Pedir uma revisão por prompt (opcional)
                          </RotuloCampo>
                          <p className="text-xs text-tinta-3 m-0">
                            Descreva o que deve mudar nesta peça. A IA aplica só o que você
                            pedir, confere o resultado e preserva o resto do texto. A versão
                            atual fica guardada no histórico desta peça.
                          </p>
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
                        </div>
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
  );
}

/** Uma seção do documento, editável, alta o bastante para o próprio texto.
 *
 * A altura acompanha o conteúdo de propósito: caixa com rolagem própria dentro
 * de uma página que também rola é o que tornava a revisão penosa — dois scrolls
 * concorrentes, e a pessoa perdia o lugar entre eles.
 *
 * O ajuste roda a cada mudança de `valor`, e não só ao digitar, porque a revisão
 * por prompt troca o texto inteiro por fora: a peça revisada chega pronta e
 * precisa caber sem que ninguém encoste no campo. */
function CampoDoDocumento({
  valor,
  rotulo,
  formato = "corpo",
  onEditar,
}: {
  valor: string;
  rotulo: string;
  formato?: "corpo" | "fechamento" | "enderecamento";
  onEditar: (valor: string) => void;
}) {
  const campo = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    const elemento = campo.current;
    if (!elemento) return;
    // Zerar antes de medir: sem isto a altura só cresce, nunca encolhe quando o
    // texto diminui.
    elemento.style.height = "auto";
    elemento.style.height = `${elemento.scrollHeight}px`;
  }, [valor]);

  return (
    <textarea
      ref={campo}
      aria-label={rotulo}
      value={valor}
      onChange={(evento) => onEditar(evento.target.value)}
      rows={1}
      /* `font-titulo` explícito: campo de formulário não herda a fonte do
         contêiner, e sem isto a seção editada sairia com a cara errada dentro
         do próprio documento. */
      className={`w-full resize-none overflow-hidden border-0 bg-transparent p-0 font-titulo text-[15px] leading-[1.75] text-tinta focus:outline-none whitespace-pre-wrap ${
        formato === "fechamento" || formato === "enderecamento"
          ? "text-center"
          : "text-justify [text-indent:1.25cm]"
      }`}
    />
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
function PreviaPeticao({
  titulo,
  secoes,
  edicao,
  onEditar,
}: {
  titulo: string;
  secoes: SecaoPeticao[];
  edicao: Record<string, string>;
  onEditar: (codigo: string, valor: string) => void;
}) {
  return (
    <div className="grid gap-2">
      {/* Sem `max-h`/`overflow` e sem `sticky`: o documento rola com a página,
          que é o que se espera de um texto que se está escrevendo. */}
      <div className="mx-auto w-full max-w-[850px] font-titulo border border-borda-forte bg-papel shadow-sm px-10 py-12 max-[640px]:px-5 max-[640px]:py-7">
        <h1 className="text-center text-sm font-bold uppercase tracking-wide text-tinta mb-6">
          {titulo || "Petição inicial"}
        </h1>
        <div className="grid gap-6">
          {secoes.map((secao) => (
            <section key={secao.code} className="grid gap-3">
              {secao.label && !["HEADING", "VALUE", "CLOSING"].includes(secao.code) && (
                <h2 className="text-left text-sm font-bold uppercase tracking-wide text-tinta">
                  {secao.label}
                </h2>
              )}
              <CampoDoDocumento
                valor={edicao[secao.code] ?? secao.content}
                rotulo={secao.label || secao.code}
                formato={secao.code === "CLOSING" ? "fechamento" : secao.code === "HEADING" ? "enderecamento" : "corpo"}
                onEditar={(valor) => onEditar(secao.code, valor)}
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

function ComparacaoRevisao({
  anterior, candidata, revisando, onAceitar, onDescartar,
}: {
  anterior: SecaoPeticao[]; candidata: SecaoPeticao[]; revisando: boolean;
  onAceitar: () => void; onDescartar: () => void;
}) {
  const comparacaoRef = useRef<HTMLElement>(null);
  const porCodigo = new Map(candidata.map((s) => [s.code, s]));
  const todos = [...anterior, ...candidata.filter((s) => !anterior.some((a) => a.code === s.code))];
  const anteriorVisivel = todos.map((s) => anterior.find((a) => a.code === s.code) ?? { ...s, content: "" });
  const candidataVisivel = todos.map((s) => porCodigo.get(s.code) ?? { ...s, content: "" });
  // Uma seção pode trocar de código/posição numa revisão. Antes isso fazia o
  // texto idêntico ficar todo verde/vermelho; primeiro pareamos conteúdo igual,
  // depois caímos no código da seção.
  const opostasDaAnterior = parearSecoes(anteriorVisivel, candidataVisivel);
  const opostasDaCandidata = parearSecoes(candidataVisivel, anteriorVisivel);
  const mudancas = todos.filter((s) => (porCodigo.get(s.code)?.content ?? "") !== (anterior.find((a) => a.code === s.code)?.content ?? "")).length;
  useEffect(() => {
    // Ao chegar a candidata, o advogado não precisa procurar a alteração numa
    // peça longa. O primeiro trecho marcado (vermelho ou verde) vira o ponto
    // de entrada da revisão; `scrollIntoView` também ajusta a coluna rolável.
    const primeiro = comparacaoRef.current?.querySelector<HTMLElement>("[data-revisao-alteracao='true']");
    if (!primeiro) return;
    const quadro = window.requestAnimationFrame(() => {
      primeiro.scrollIntoView({ behavior: "smooth", block: "center", inline: "nearest" });
      primeiro.focus({ preventScroll: true });
    });
    return () => window.cancelAnimationFrame(quadro);
  }, [anterior, candidata]);
  return (
    <section ref={comparacaoRef} className="border-2 border-acao-borda bg-papel p-4">
      <div className="flex flex-wrap items-center justify-between gap-2 mb-3">
        <div><h3 className={TITULO}>Revisão pendente</h3><p className={SUB}>Compare a peça completa antes de aceitar. {mudancas} seção(ões) com alteração.</p></div>
        <span className="rounded-full bg-acao-clara px-3 py-1 text-xs font-semibold text-tinta-2">A peça oficial continua preservada</span>
      </div>
      <div className="grid grid-cols-2 gap-3 max-[760px]:grid-cols-1">
        <ColunaComparacao titulo="VERSÃO ANTERIOR" secoes={anteriorVisivel} oposta={opostasDaAnterior} tipo="antes" />
        <ColunaComparacao titulo="NOVA VERSÃO" secoes={candidataVisivel} oposta={opostasDaCandidata} tipo="depois" />
      </div>
      <div className="mt-4 flex justify-end gap-2">
        <Botao variante="secundario" pequeno disabled={revisando} onClick={onDescartar}>Descartar revisão</Botao>
        <Botao variante="primario" pequeno disabled={revisando} onClick={onAceitar}>{revisando ? "Salvando…" : "Aceitar revisão"}</Botao>
      </div>
    </section>
  );
}

function normalizarParaComparacao(texto: string): string {
  return texto.replace(/\s+/g, " ").trim();
}

function parearSecoes(secoes: SecaoPeticao[], opostas: SecaoPeticao[]): Map<string, SecaoPeticao> {
  const usados = new Set<number>();
  const resultado = new Map<string, SecaoPeticao>();
  secoes.forEach((secao) => {
    const texto = normalizarParaComparacao(secao.content);
    let indice = opostas.findIndex((outra, i) => !usados.has(i) && texto !== "" && normalizarParaComparacao(outra.content) === texto);
    if (indice < 0) indice = opostas.findIndex((outra, i) => !usados.has(i) && outra.code === secao.code);
    if (indice >= 0) {
      usados.add(indice);
      resultado.set(secao.code, opostas[indice]);
    }
  });
  return resultado;
}

function ColunaComparacao({ titulo, secoes, oposta, tipo }: { titulo: string; secoes: SecaoPeticao[]; oposta: Map<string, SecaoPeticao>; tipo: "antes" | "depois" }) {
  return <article className="min-w-0 max-h-[70vh] overflow-auto border border-borda bg-papel-2 p-3">
    <h4 className="sticky top-0 bg-papel-2 py-1 text-xs font-bold tracking-wide text-tinta">{titulo}</h4>
    {secoes.map((secao, i) => <div key={`${secao.code}-${i}`} className="mb-4 whitespace-pre-wrap text-sm leading-relaxed text-tinta">
      <p className="mb-1 font-semibold">{secao.label}</p>
      <TextoComDiff texto={secao.content} outro={oposta.get(secao.code)?.content ?? ""} tipo={tipo} />
    </div>)}
  </article>;
}

function TextoComDiff({ texto, outro, tipo }: { texto: string; outro: string; tipo: "antes" | "depois" }) {
  if (texto === outro) return <>{texto}</>;
  const palavras = texto.split(/(\s+)/);
  const alteradas = indicesAlterados(texto, outro, tipo);
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

/** Diff por sequência (LCS), não por conjunto: repetição e posição importam. */
function indicesAlterados(texto: string, outro: string, tipo: "antes" | "depois"): Set<number> {
  const atual = texto.split(/\s+/).filter(Boolean);
  const comparado = outro.split(/\s+/).filter(Boolean);
  // Evita custo quadrático impróprio numa peça excepcionalmente grande. O
  // prefixo/sufixo ainda não marca texto que permaneceu no mesmo lugar.
  if (atual.length > 1_500 || comparado.length > 1_500) {
    let inicio = 0; while (atual[inicio] === comparado[inicio]) inicio += 1;
    let fimAtual = atual.length - 1; let fimComparado = comparado.length - 1;
    while (fimAtual >= inicio && fimComparado >= inicio && atual[fimAtual] === comparado[fimComparado]) { fimAtual -= 1; fimComparado -= 1; }
    return new Set(Array.from({ length: Math.max(0, fimAtual - inicio + 1) }, (_, i) => inicio + i));
  }
  const linhas = Array.from({ length: atual.length + 1 }, () => new Uint16Array(comparado.length + 1));
  for (let i = atual.length - 1; i >= 0; i -= 1) for (let j = comparado.length - 1; j >= 0; j -= 1) {
    linhas[i][j] = atual[i] === comparado[j] ? linhas[i + 1][j + 1] + 1 : Math.max(linhas[i + 1][j], linhas[i][j + 1]);
  }
  const mantidos = new Set<number>(); let i = 0; let j = 0;
  while (i < atual.length && j < comparado.length) {
    if (atual[i] === comparado[j]) { mantidos.add(i); i += 1; j += 1; }
    else if (linhas[i + 1][j] >= linhas[i][j + 1]) i += 1;
    else j += 1;
  }
  if (tipo === "antes") return new Set(atual.map((_, indice) => indice).filter((indice) => !mantidos.has(indice)));
  // Reexecuta invertido para devolver os índices que são realmente novos na candidata.
  return indicesAlteradosNoComparado(atual, comparado);
}

function indicesAlteradosNoComparado(antes: string[], depois: string[]): Set<number> {
  return indicesAlterados(depois.join(" "), antes.join(" "), "antes");
}
