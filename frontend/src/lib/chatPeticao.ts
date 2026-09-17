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
export type NaturezaDaMensagem = "PERGUNTA" | "RESPOSTA" | "EVENTO" | "ERRO";

export interface FonteDaWeb {
  url: string;
  titulo: string;
  trecho: string;
}

/** Uma alteração que a IA PROPÔS. Nada aqui aconteceu ainda. */
export interface AcaoProposta {
  tipo: "REVISAR" | "GERAR" | "ANALISAR_DOCUMENTOS" | "PECA_ANEXA";
  pedido?: string;
  titulo?: string;
  motivo?: string;
  pedidos?: string[];
  /** Mexe em valor, retira cláusula ou toca na fundamentação: a tela avisa em destaque. */
  sensivel?: boolean;
  oQueAcontece?: string;
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
}

export interface ChatDaPeticao {
  id: string;
  casoId: string;
  mensagens: MensagemDoChat[];
  /** Sem chave do modelo o campo de pergunta não deve nem aceitar texto. */
  modeloDisponivel: boolean;
  webDisponivel: boolean;
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
        }))
      : [],
    acoes: Array.isArray(payload.acoes)
      ? (payload.acoes as Record<string, unknown>[]).map(traduzirAcao)
      : [],
    podeRepetir: Boolean(payload.pode_repetir),
    perguntaOriginal: payload.pergunta ? String(payload.pergunta) : "",
  };
}

export async function abrirChatDaPeticao(casoId: string): Promise<ChatDaPeticao> {
  const corpo = await chamarAgente<{
    id: string;
    caso_id: string;
    mensagens: MensagemCrua[];
    modelo_disponivel: boolean;
    web_disponivel: boolean;
  }>(`/api/agente/casos/${casoId}/chat-peticao`);
  return {
    id: corpo.id,
    casoId: corpo.caso_id,
    mensagens: (corpo.mensagens ?? []).map(traduzirMensagem),
    modeloDisponivel: Boolean(corpo.modelo_disponivel),
    webDisponivel: Boolean(corpo.web_disponivel),
  };
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
): Promise<void> {
  const resposta = await fetch(urlApi(`/api/agente/casos/${casoId}/chat-peticao/mensagens`), {
    method: "POST",
    credentials: CREDENCIAIS,
    headers: cabecalhos({ "Content-Type": "application/json" }),
    body: JSON.stringify({ mensagem }),
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

  for (;;) {
    const { done, value } = await leitor.read();
    if (done) break;
    sobra += decodificador.decode(value, { stream: true });
    const partes = sobra.split("\n\n");
    sobra = partes.pop() ?? "";
    for (const parte of partes) {
      const linha = parte.split("\n").find((l) => l.startsWith("data:"));
      if (!linha) continue;
      let bruto: Record<string, unknown>;
      try {
        bruto = JSON.parse(linha.slice(5).trim());
      } catch {
        continue;
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
        aoEvento({ tipo: "fim", mensagem: traduzirMensagem(bruto.mensagem as MensagemCrua) });
      } else if (tipo === "erro") {
        aoEvento({
          tipo: "erro",
          texto: String(bruto.texto ?? "Não foi possível responder."),
          mensagem: bruto.mensagem
            ? traduzirMensagem(bruto.mensagem as MensagemCrua)
            : undefined,
        });
      }
    }
  }
}

/** Executa uma proposta que o advogado confirmou. Nada é aplicado sem passar por aqui. */
export async function executarAcaoDoChat(
  casoId: string,
  acao: AcaoProposta,
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
): Promise<MensagemDoChat | null> {
  const corpo = await chamarAgente<{ mensagem: MensagemCrua | null }>(
    `/api/agente/casos/${casoId}/chat-peticao/eventos`,
    { method: "POST", body: JSON.stringify({ tipo, dados }) },
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
 * O mesmo padrão que o app já usa para a sessão expirada (`lib/api.ts`).
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
