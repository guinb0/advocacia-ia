/**
 * Cliente do chat que vive dentro do Dossiê, ao lado da minuta.
 *
 * Fala com `/api/agente/casos/{caso}/chat-peticao*`. É outra conversa que a do agente
 * geral (`lib/conversas.ts`): esta é UMA por caso, persistida no servidor, e reabre
 * inteira depois do refresh — o sistema não guarda estado na URL, então um chat que
 * vivesse em memória do navegador perderia a conversa a cada F5.
 *
 * O que atravessa este arquivo: a resposta chega em FLUXO. O modelo consulta a minuta,
 * os documentos e às vezes a web antes de escrever, e isso leva dezenas de segundos —
 * sem os eventos de andamento, a tela ficaria parada sem sinal de vida.
 */

import { ApiError, CREDENCIAIS, cabecalhos, urlApi } from "./api";
import { chamarAgente } from "./agente";

export type PapelDaMensagem = "USER" | "ASSISTANT";

/** `RESPOSTA` é o que a IA respondeu; `EVENTO` é o que ela conta sem ter sido
 *  perguntada (uma ação terminou); `ERRO` é a falha que ficou registrada na
 *  transcrição em vez de sumir num toast. */
export type NaturezaDaMensagem = "PERGUNTA" | "RESPOSTA" | "EVENTO" | "ERRO" | "CONTEXTO";

/** Em que camada da hierarquia a fonte está — medida no servidor, pelo domínio.
 *
 * `OFICIAL` é o texto da norma (Planalto, Diário Oficial, LexML); `TRIBUNAL` é a
 * jurisprudência no site de quem julgou; `PUBLICA` é outro órgão público; `SECUNDARIA` é
 * todo o resto. A distinção não é preciosismo: número de súmula tirado de portal e
 * número de súmula lido no TST têm o mesmo aspecto numa resposta bem escrita, e só um
 * dos dois sustenta a petição. */
export type ConfiancaDaFonte = "OFICIAL" | "TRIBUNAL" | "PUBLICA" | "SECUNDARIA";

export interface FonteDaWeb {
  url: string;
  titulo: string;
  trecho: string;
  confianca: ConfiancaDaFonte;
}

/** Uma alteração que a IA PROPÔS. Nada aqui aconteceu ainda. */
export interface AcaoProposta {
  tipo: "REVISAR" | "GERAR" | "ANALISAR_DOCUMENTOS" | "PECA_ANEXA" | "INCLUIR_FOTO" | "INCLUIR_TRECHO";
  pedido?: string;
  titulo?: string;
  motivo?: string;
  pedidos?: string[];
  /** Mexe em valor, retira cláusula ou toca na fundamentação: a tela avisa em destaque. */
  sensivel?: boolean;
  oQueAcontece?: string;
  generaliza?: boolean;
  /** INCLUIR_FOTO: a entrega que vira imagem na peça, onde e com que legenda. */
  anexoId?: string;
  arquivo?: string;
  secao?: string;
  depoisDe?: string;
  legenda?: string;
  /** INCLUIR_TRECHO: a passagem literal do documento (`anexoId`) que entra como citação. */
  trecho?: string;
}

export interface MensagemDoChat {
  id: string;
  papel: PapelDaMensagem;
  conteudo: string;
  natureza: NaturezaDaMensagem;
  criadoEm: string;
  /** Só existe em resposta que usou a web. É o que diferencia o que veio da internet. */
  fontes: FonteDaWeb[];
  acoes: AcaoProposta[];
  /** `true` em falha: a tela oferece "tentar de novo" com a mesma pergunta. */
  podeRepetir: boolean;
  /** A pergunta que produziu a falha — é ela que o "tentar de novo" reenvia. */
  perguntaOriginal: string;
  /** Em mensagem de EVENTO nascida de uma proposta confirmada: qual proposta foi
   *  executada. É o que faz o cartão continuar «Executada» depois do refresh. */
  acaoExecutada?: { tipo: string; pedido: string; titulo: string; anexoId: string };
}

/** Uma conversa do histórico do chat desta petição. */
export interface ResumoDaConversa {
  id: string;
  titulo: string;
  criadoEm: string;
  atualizadoEm: string;
  /** Quantas perguntas o advogado fez — zero é uma conversa em branco. */
  perguntas: number;
}

/** O que a base de contexto do caso já tem (documentos lidos, pesquisas e buscas feitas). */
export interface ResumoDoContexto {
  documentosLidos: number;
  documentosSemLeitura: number;
  pesquisas: number;
  buscas: number;
  atualizadoEm: string;
  indisponivel: boolean;
}

function traduzirConversa(bruta: Record<string, unknown>): ResumoDaConversa {
  return {
    id: String(bruta.id ?? ""),
    titulo: String(bruta.titulo ?? "Conversa"),
    criadoEm: String(bruta.criado_em ?? ""),
    atualizadoEm: String(bruta.atualizado_em ?? ""),
    perguntas: Number(bruta.perguntas ?? 0),
  };
}

function traduzirContexto(bruto: unknown): ResumoDoContexto | null {
  if (!bruto || typeof bruto !== "object") return null;
  const c = bruto as Record<string, unknown>;
  return {
    documentosLidos: Number(c.documentos_lidos ?? 0),
    documentosSemLeitura: Number(c.documentos_sem_leitura ?? 0),
    pesquisas: Number(c.pesquisas ?? 0),
    buscas: Number(c.buscas ?? 0),
    atualizadoEm: String(c.atualizado_em ?? ""),
    indisponivel: Boolean(c.indisponivel),
  };
}

export interface ChatDaPeticao {
  id: string;
  casoId: string;
  mensagens: MensagemDoChat[];
  /** O histórico: as conversas desta pessoa sobre esta petição, da mais recente. */
  conversas: ResumoDaConversa[];
  contexto: ResumoDoContexto | null;
  /** Sem chave do modelo o campo de pergunta não deve nem aceitar texto. */
  modeloDisponivel: boolean;
  webDisponivel: boolean;
  /** Os anexos que a resposta pode citar — cada um vira link para o visor. */
  documentos: DocumentoCitavel[];
}

/** Um anexo do caso, do jeito que a resposta o cita: pelo nome do arquivo ou pelo tipo. */
export interface DocumentoCitavel {
  /** Id da entrega — é o que o `VisorEntrega` abre. */
  id: string;
  arquivo: string;
  tipo: string;
  situacao: string;
  /** Legado de respostas antigas; a tela não usa rótulo ordinal para abrir arquivo. */
  rotulos?: string[];
}

function traduzirDocumentos(brutos: unknown): DocumentoCitavel[] {
  if (!Array.isArray(brutos)) return [];
  return (brutos as Record<string, unknown>[])
    .map((d) => ({
      id: String(d.id ?? ""),
      arquivo: String(d.arquivo ?? ""),
      tipo: String(d.tipo ?? ""),
      situacao: String(d.situacao ?? ""),
      rotulos: Array.isArray(d.rotulos) ? (d.rotulos as unknown[]).map(String) : [],
    }))
    .filter((d) => d.id && d.arquivo);
}

interface MensagemCrua {
  id: string;
  papel: string;
  conteudo: string;
  natureza: string;
  criado_em: string;
  payload?: Record<string, unknown> | null;
}

function traduzirAcao(bruta: Record<string, unknown>): AcaoProposta {
  return {
    tipo: String(bruta.tipo ?? "REVISAR") as AcaoProposta["tipo"],
    pedido: bruta.pedido ? String(bruta.pedido) : undefined,
    titulo: bruta.titulo ? String(bruta.titulo) : undefined,
    motivo: bruta.motivo ? String(bruta.motivo) : undefined,
    pedidos: Array.isArray(bruta.pedidos) ? bruta.pedidos.map((p) => String(p)) : undefined,
    sensivel: Boolean(bruta.sensivel),
    oQueAcontece: bruta.o_que_acontece ? String(bruta.o_que_acontece) : undefined,
    anexoId: bruta.anexo_id ? String(bruta.anexo_id) : undefined,
    arquivo: bruta.arquivo ? String(bruta.arquivo) : undefined,
    secao: bruta.secao ? String(bruta.secao) : undefined,
    depoisDe: bruta.depois_de ? String(bruta.depois_de) : undefined,
    legenda: bruta.legenda ? String(bruta.legenda) : undefined,
    trecho: bruta.trecho ? String(bruta.trecho) : undefined,
  };
}

export function traduzirMensagem(crua: MensagemCrua): MensagemDoChat {
  const payload = (crua.payload ?? {}) as Record<string, unknown>;
  return {
    id: crua.id,
    papel: crua.papel === "USER" ? "USER" : "ASSISTANT",
    conteudo: crua.conteudo,
    natureza: (crua.natureza || "RESPOSTA") as NaturezaDaMensagem,
    criadoEm: crua.criado_em,
    fontes: Array.isArray(payload.fontes)
      ? (payload.fontes as Record<string, unknown>[]).map((f) => ({
          url: String(f.url ?? ""),
          titulo: String(f.titulo ?? ""),
          trecho: String(f.trecho ?? ""),
          // Mensagem gravada antes da classificação existir não tem o campo: tratar como
          // secundária é o lado seguro — ela vira "confira a fonte", não "é oficial".
          confianca: (f.confianca as ConfiancaDaFonte) || "SECUNDARIA",
        }))
      : [],
    acoes: Array.isArray(payload.acoes)
      ? (payload.acoes as Record<string, unknown>[]).map(traduzirAcao)
      : [],
    podeRepetir: Boolean(payload.pode_repetir),
    perguntaOriginal: payload.pergunta ? String(payload.pergunta) : "",
    acaoExecutada: acaoExecutadaDe(crua, payload),
  };
}

/** Só vale a mensagem de sucesso (EVENTO) gerada pelo chat: a falha da mesma ação também
 *  guarda a proposta, e ela NÃO pode marcar o cartão como executado. */
function acaoExecutadaDe(
  crua: MensagemCrua,
  payload: Record<string, unknown>,
): MensagemDoChat["acaoExecutada"] {
  const acao = payload.acao as Record<string, unknown> | undefined;
  if (crua.natureza !== "EVENTO" || payload.origem !== "chat" || !acao) return undefined;
  return {
    tipo: String(acao.tipo ?? ""),
    pedido: String(acao.pedido ?? ""),
    titulo: String(acao.titulo ?? ""),
    anexoId: String(acao.anexo_id ?? ""),
  };
}

interface ChatCru {
  id: string;
  caso_id: string;
  mensagens: MensagemCrua[];
  modelo_disponivel: boolean;
  web_disponivel: boolean;
  documentos?: unknown;
  contexto?: unknown;
  conversas?: Record<string, unknown>[];
}

function traduzirChat(corpo: ChatCru): ChatDaPeticao {
  return {
    id: corpo.id,
    casoId: corpo.caso_id,
    mensagens: (corpo.mensagens ?? []).map(traduzirMensagem),
    conversas: (corpo.conversas ?? []).map(traduzirConversa),
    contexto: traduzirContexto(corpo.contexto),
    modeloDisponivel: Boolean(corpo.modelo_disponivel),
    webDisponivel: Boolean(corpo.web_disponivel),
    documentos: traduzirDocumentos(corpo.documentos),
  };
}

/** Abre uma conversa. Sem `conversaId`, a mais recente desta pessoa neste caso. */
export async function abrirChatDaPeticao(casoId: string, conversaId?: string): Promise<ChatDaPeticao> {
  const consulta = conversaId ? `?conversa_id=${encodeURIComponent(conversaId)}` : "";
  return traduzirChat(await chamarAgente<ChatCru>(`/api/agente/casos/${casoId}/chat-peticao${consulta}`));
}

/** Um chat em branco (ou o que já está em branco), já aberto. */
export async function criarConversaDoChat(casoId: string): Promise<ChatDaPeticao> {
  return traduzirChat(
    await chamarAgente<ChatCru>(`/api/agente/casos/${casoId}/chat-peticao/conversas`, { method: "POST" }),
  );
}

/** O histórico do chat desta petição, da conversa mais recente para a mais antiga. */
export async function listarConversasDoChat(casoId: string): Promise<ResumoDaConversa[]> {
  const lista = await chamarAgente<Record<string, unknown>[]>(
    `/api/agente/casos/${casoId}/chat-peticao/conversas`,
  );
  return (lista ?? []).map(traduzirConversa);
}

export async function excluirConversaDoChat(casoId: string, conversaId: string): Promise<void> {
  await chamarAgente<null>(
    `/api/agente/casos/${casoId}/chat-peticao/conversas/${encodeURIComponent(conversaId)}`,
    { method: "DELETE" },
  );
}

export async function obterContextoDoChat(casoId: string): Promise<ResumoDoContexto | null> {
  return traduzirContexto(await chamarAgente<unknown>(`/api/agente/casos/${casoId}/chat-peticao/contexto`));
}

/** Refaz o levantamento dos documentos do caso. As pesquisas na web continuam guardadas. */
export async function atualizarContextoDoChat(casoId: string): Promise<ResumoDoContexto | null> {
  return traduzirContexto(
    await chamarAgente<unknown>(`/api/agente/casos/${casoId}/chat-peticao/contexto/atualizar`, {
      method: "POST",
    }),
  );
}

/** Relê os anexos citáveis: um documento enviado pelo checklist com a conversa aberta
 *  também precisa virar link na próxima resposta. */
export async function listarDocumentosDoChat(casoId: string): Promise<DocumentoCitavel[]> {
  return traduzirDocumentos(
    await chamarAgente<unknown>(`/api/agente/casos/${casoId}/chat-peticao/documentos`),
  );
}

export async function adicionarContextoAoChat(
  casoId: string,
  arquivo: File,
  relevancia: string,
  conversaId = "",
): Promise<{ mensagem: MensagemDoChat; caracteresLidos: number }> {
  const corpo = new FormData();
  corpo.append("arquivo", arquivo);
  corpo.append("relevancia", relevancia);
  corpo.append("conversa_id", conversaId);
  const resposta = await fetch(urlApi(`/api/agente/casos/${casoId}/chat-peticao/contextos`), {
    method: "POST", credentials: CREDENCIAIS, headers: cabecalhos(), body: corpo,
  });
  const dados = await resposta.json().catch(() => null);
  if (!resposta.ok || !dados) {
    throw new ApiError(String(dados?.detail ?? `Erro ${resposta.status}`), { status: resposta.status });
  }
  return { mensagem: traduzirMensagem(dados.mensagem as MensagemCrua), caracteresLidos: Number(dados.caracteres_lidos ?? 0) };
}

/** Os eventos do fluxo, já no vocabulário da tela. */
export type EventoDoChat =
  | { tipo: "pergunta"; mensagem: MensagemDoChat }
  | { tipo: "etapa"; texto: string }
  | { tipo: "delta"; texto: string }
  /** O modelo desistiu do que começou a escrever para consultar antes: zere o parcial. */
  | { tipo: "recomeco" }
  | { tipo: "fim"; mensagem: MensagemDoChat }
  | { tipo: "erro"; texto: string; mensagem?: MensagemDoChat };

/**
 * A pergunta, com a resposta chegando em pedaços.
 *
 * `EventSource` não serve aqui: ele só faz GET e não leva corpo. Então é `fetch` com
 * leitura do corpo em fluxo — e o cookie de sessão viaja igual ao das demais chamadas.
 */
export async function perguntarNoChat(
  casoId: string,
  mensagem: string,
  aoEvento: (evento: EventoDoChat) => void,
  sinal?: AbortSignal,
  conversaId = "",
): Promise<boolean> {
  const resposta = await fetch(urlApi(`/api/agente/casos/${casoId}/chat-peticao/mensagens`), {
    method: "POST",
    credentials: CREDENCIAIS,
    headers: cabecalhos({ "Content-Type": "application/json" }),
    body: JSON.stringify({ mensagem, conversa_id: conversaId }),
    signal: sinal,
  });

  if (!resposta.ok || !resposta.body) {
    const corpo = await resposta.json().catch(() => null);
    const detalhe =
      corpo && typeof corpo === "object" && "detail" in corpo
        ? String((corpo as { detail: unknown }).detail)
        : `Erro ${resposta.status}`;
    throw new ApiError(detalhe, { status: resposta.status });
  }

  const leitor = resposta.body.getReader();
  const decodificador = new TextDecoder();
  /* Um evento SSE pode chegar partido entre dois pedaços da rede. Sem guardar a
   * sobra, uma resposta longa perde justamente o fim — que é onde vem a mensagem
   * gravada, com as fontes e as propostas. */
  let sobra = "";
  /* `true` só quando o servidor entregou o desfecho (`fim` ou `erro`). Uma conexão que
   * cai no meio devolve `false`: quem chamou sabe que a resposta pode estar pronta no
   * servidor sem ter chegado aqui, e vai buscá-la em vez de mostrar uma tela muda. */
  let concluiu = false;

  function tratar(parte: string) {
    const linha = parte.split("\n").find((l) => l.startsWith("data:"));
    if (!linha) return;
    let bruto: Record<string, unknown>;
    try {
      bruto = JSON.parse(linha.slice(5).trim());
    } catch {
      return;
    }
    const tipo = String(bruto.tipo ?? "");
    if (tipo === "conversa" && bruto.pergunta) {
      aoEvento({ tipo: "pergunta", mensagem: traduzirMensagem(bruto.pergunta as MensagemCrua) });
    } else if (tipo === "etapa") {
      aoEvento({ tipo: "etapa", texto: String(bruto.texto ?? "") });
    } else if (tipo === "delta") {
      aoEvento({ tipo: "delta", texto: String(bruto.texto ?? "") });
    } else if (tipo === "recomeco") {
      aoEvento({ tipo: "recomeco" });
    } else if (tipo === "fim") {
      concluiu = true;
      aoEvento({ tipo: "fim", mensagem: traduzirMensagem(bruto.mensagem as MensagemCrua) });
    } else if (tipo === "erro") {
      concluiu = true;
      aoEvento({
        tipo: "erro",
        texto: String(bruto.texto ?? "Não foi possível responder."),
        mensagem: bruto.mensagem
          ? traduzirMensagem(bruto.mensagem as MensagemCrua)
          : undefined,
      });
    }
  }

  for (;;) {
    let leitura: ReadableStreamReadResult<Uint8Array>;
    try {
      leitura = await leitor.read();
    } catch (falha) {
      // Cancelado por nós (troca de caso): não é queda de conexão.
      if (sinal?.aborted) throw falha;
      return concluiu;
    }
    if (leitura.done) break;
    sobra += decodificador.decode(leitura.value, { stream: true });
    const partes = sobra.split("\n\n");
    sobra = partes.pop() ?? "";
    partes.forEach(tratar);
  }
  // O último evento pode chegar sem a linha em branco que o fecha — e é justamente o `fim`.
  sobra += decodificador.decode();
  if (sobra.trim()) tratar(sobra);
  return concluiu;
}

/** Executa uma proposta que o advogado confirmou. Nada é aplicado sem passar por aqui. */
export async function executarAcaoDoChat(
  casoId: string,
  acao: AcaoProposta,
  conversaId = "",
): Promise<{ ok: boolean; mensagem: MensagemDoChat }> {
  const corpo = await chamarAgente<{ ok: boolean; mensagem: MensagemCrua }>(
    `/api/agente/casos/${casoId}/chat-peticao/acoes`,
    {
      method: "POST",
      body: JSON.stringify({
        tipo: acao.tipo,
        pedido: acao.pedido ?? "",
        titulo: acao.titulo ?? "",
        motivo: acao.motivo ?? "",
        pedidos: acao.pedidos ?? [],
        generaliza: acao.generaliza === true,
        anexo_id: acao.anexoId ?? "",
        secao: acao.secao ?? "",
        depois_de: acao.depoisDe ?? "",
        legenda: acao.legenda ?? "",
        trecho: acao.trecho ?? "",
        conversa_id: conversaId,
      }),
    },
  );
  return { ok: corpo.ok, mensagem: traduzirMensagem(corpo.mensagem) };
}

/** O que os BOTÕES fizeram, contado pela IA dentro da conversa. */
export async function registrarEventoNoChat(
  casoId: string,
  tipo: string,
  dados: Record<string, unknown> = {},
  conversaId = "",
): Promise<MensagemDoChat | null> {
  const corpo = await chamarAgente<{ mensagem: MensagemCrua | null }>(
    `/api/agente/casos/${casoId}/chat-peticao/eventos`,
    { method: "POST", body: JSON.stringify({ tipo, dados, conversa_id: conversaId }) },
  );
  return corpo.mensagem ? traduzirMensagem(corpo.mensagem) : null;
}

/** O nome do evento de janela que leva um acontecimento da tela até o chat. */
export const EVENTO_DO_CHAT = "acervo:chat-peticao";

export interface AvisoParaOChat {
  casoId: string;
  tipo: string;
  dados?: Record<string, unknown>;
}

/**
 * Avisa o chat de que algo aconteceu fora dele.
 *
 * Por evento de janela, e não por `props`: quem dispara a análise dos documentos é um
 * painel que fica em OUTRO galho da árvore (o dossiê), e levar um callback até lá
 * obrigaria a subir estado por três componentes que não têm nada a ver com a conversa.
 * O mesmo padrão que o app já usa para a sessão expirada (`lib/api/base.ts`).
 */
export function avisarChatDaPeticao(
  casoId: string,
  tipo: string,
  dados: Record<string, unknown> = {},
): void {
  if (typeof window === "undefined") return;
  window.dispatchEvent(
    new CustomEvent<AvisoParaOChat>(EVENTO_DO_CHAT, { detail: { casoId, tipo, dados } }),
  );
}
