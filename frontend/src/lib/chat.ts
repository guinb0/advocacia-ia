/**
 * Cliente do chat do escritório — `/api/chat/*`.
 *
 * A tela não decide nada sobre o destino da pergunta: ela manda o texto (e, quando a
 * pessoa clicou num botão, o `modo`) e recebe a resposta já classificada. A decisão mora
 * no servidor (`app/chat/destinos.py`) porque é determinística e precisa ser a mesma para
 * qualquer tela que venha depois desta.
 *
 * A `natureza` da resposta é o que atravessa este arquivo inteiro, e cada uma vale uma
 * coisa diferente:
 *
 * - `WEB` — veio da internet, com as fontes e o aviso de quando nenhuma é oficial;
 * - `MISTA` — a pergunta tinha duas metades (uma do escritório, uma do mundo) e as duas
 *   foram respondidas, cada uma sob o seu título. Ver `chat/sessoes._compor`;
 * - `DOCUMENTOS` — leitura do que o caso já tem. Não passou por modelo nenhum;
 * - `CASO` — veio do agente jurídico, com o lastro dele;
 * - `ANALISE` — o analista mediu o acervo e escreveu em cima do que mediu;
 * - `SISTEMA` — explicação do produto, texto fixo;
 * - `ACERVO` — a pergunta não pôde ser sustentada, e a resposta diz o que faltou;
 * - `ESCOLHA` — a pergunta citou mais de um caso (ou nenhum, quando precisava de um).
 *
 * Achatar todas na mesma bolha faria uma página da internet chegar com o mesmo peso de
 * um documento conferido do caso — que é exatamente o que este sistema não pode produzir.
 */

import { chamarAgente } from "./agente";

export type NaturezaDoChat =
  | "PERGUNTA"
  | "WEB"
  /** As duas metades: o que o acervo respondeu e o que a internet respondeu. */
  | "MISTA"
  | "DOCUMENTOS"
  | "CASO"
  | "ANALISE"
  | "SISTEMA"
  | "ACERVO"
  | "ESCOLHA"
  | "INDISPONIVEL";

/** O que a tela pode pedir em voz alta, além de deixar o servidor decidir. */
export type ModoDoChat = "AUTO" | "WEB" | "DOCUMENTOS";

/** Um caminho que a resposta abriu: ou navega, ou traz o material para dentro. */
export interface AtalhoDaResposta {
  tipo: "DOSSIE" | "DOCUMENTOS" | "TELA" | "FONTE";
  rotulo: string;
  casoId: string | null;
  /** A tela do sistema para onde ir. `null` em atalho de fonte externa. */
  tela: string | null;
  /** Endereço externo — só em `FONTE`. */
  url?: string;
  confianca?: string;
  /** Quando verdadeiro, o material cabe DENTRO da conversa (botão "Ver aqui"). */
  embutido: boolean;
}

export interface FonteDaWeb {
  url: string;
  titulo: string;
  trecho: string;
  confianca: string;
}

export interface AfirmacaoDoChat {
  statement: string;
  nature: string;
  refs: string[];
}

export interface CandidatoDoChat {
  casoId: string;
  cliente: string;
  categoria: string;
  criadoEm: string;
  desempate: string;
}

export interface EntregaDoChat {
  id: string;
  arquivo: string;
  item: string;
  tipoDetectado: string;
  /** `null` = ninguém conferiu ainda. Não é o mesmo que "não confere". */
  tipoConfere: boolean | null;
  status: string;
  recebidoEm: string;
  arquivoUrl: string;
}

export interface PainelDeDocumentos {
  caso: { id: string; cliente: string; categoria: string; criadoEm: string };
  progresso: Record<string, number>;
  entregas: EntregaDoChat[];
  entregasOcultas: number;
  pendentes: { nome: string; motivo: string; status: string }[];
  entrevistas: { id: string; realizadaEm: string; entrevistador: string; resumo: string }[];
  pecas: { id: string; titulo: string; criadoEm: string }[];
}

export interface MensagemDoChat {
  id: string;
  papel: "USER" | "ASSISTANT";
  conteudo: string;
  natureza: NaturezaDoChat;
  criadaEm: string;
  casoId?: string;
  cliente?: string;
  atalhos: AtalhoDaResposta[];
  fontes: FonteDaWeb[];
  temFonteOficial: boolean | null;
  afirmacoes: AfirmacaoDoChat[];
  pendencias: string[];
  falta: string[];
  candidatos: CandidatoDoChat[];
  consultas: { ferramenta: string; argumentos: Record<string, unknown> }[];
  /** `DOCUMENTOS`: o material do caso, já embutido na resposta. */
  documentos: PainelDeDocumentos | null;
}

export interface ResumoDeSessao {
  id: string;
  titulo: string;
  resumo: string;
  casoId: string | null;
  /** Sobre o que a conversa está falando. Toda pergunta é lida dentro disto — ver
   *  `app/chat/contexto.py`. A tela o mostra para que ninguém precise adivinhar por que
   *  "videos sobre" trouxe vídeos de bolo. */
  assunto: string;
  perguntas: number;
  criadoEm: string;
  atualizadoEm: string;
}

export interface SessaoCompleta extends ResumoDeSessao {
  mensagens: MensagemDoChat[];
}

export interface EstadoDoChat {
  web: boolean;
  analista: boolean;
  agente: boolean;
  teto: number;
}

/* ------------------------------------------------------------------ tradução
 *
 * O backend fala `snake_case` e a tela fala `camelCase`. A tradução mora aqui, numa
 * função só: espalhada pelos componentes, cada um inventaria o seu nome para o mesmo
 * campo e a primeira mudança no servidor quebraria três telas em lugares diferentes.
 */

type Cru = Record<string, unknown>;

const texto = (valor: unknown): string => (typeof valor === "string" ? valor : "");
const lista = (valor: unknown): Cru[] => (Array.isArray(valor) ? (valor as Cru[]) : []);

function traduzirAtalho(cru: Cru): AtalhoDaResposta {
  return {
    tipo: (texto(cru.tipo) || "TELA") as AtalhoDaResposta["tipo"],
    rotulo: texto(cru.rotulo),
    casoId: typeof cru.caso_id === "string" ? cru.caso_id : null,
    tela: typeof cru.tela === "string" ? cru.tela : null,
    url: texto(cru.url) || undefined,
    confianca: texto(cru.confianca) || undefined,
    embutido: Boolean(cru.embutido),
  };
}

function traduzirPainel(cru: Cru | null | undefined): PainelDeDocumentos | null {
  if (!cru || typeof cru !== "object") return null;
  const caso = (cru.caso ?? {}) as Cru;
  return {
    caso: {
      id: texto(caso.id),
      cliente: texto(caso.cliente),
      categoria: texto(caso.categoria),
      criadoEm: texto(caso.criado_em),
    },
    progresso: (cru.progresso ?? {}) as Record<string, number>,
    entregas: lista(cru.entregas).map((e) => ({
      id: texto(e.id),
      arquivo: texto(e.arquivo),
      item: texto(e.item),
      tipoDetectado: texto(e.tipo_detectado),
      tipoConfere: typeof e.tipo_confere === "boolean" ? e.tipo_confere : null,
      status: texto(e.status),
      recebidoEm: texto(e.recebido_em),
      arquivoUrl: texto(e.arquivo_url),
    })),
    entregasOcultas: Number(cru.entregas_ocultas ?? 0),
    pendentes: lista(cru.pendentes).map((p) => ({
      nome: texto(p.nome),
      motivo: texto(p.motivo),
      status: texto(p.status),
    })),
    entrevistas: lista(cru.entrevistas).map((e) => ({
      id: texto(e.id),
      realizadaEm: texto(e.realizada_em),
      entrevistador: texto(e.entrevistador),
      resumo: texto(e.resumo),
    })),
    pecas: lista(cru.pecas).map((p) => ({
      id: texto(p.id),
      titulo: texto(p.titulo),
      criadoEm: texto(p.criado_em),
    })),
  };
}

function traduzirMensagem(cru: Cru): MensagemDoChat {
  const payload = (cru.payload ?? {}) as Cru;
  return {
    id: texto(cru.id),
    papel: cru.papel === "USER" ? "USER" : "ASSISTANT",
    conteudo: texto(cru.conteudo),
    natureza: (texto(cru.natureza) || "ANALISE") as NaturezaDoChat,
    criadaEm: texto(cru.criado_em),
    casoId: texto(payload.caso_id) || undefined,
    cliente: texto(payload.cliente) || undefined,
    atalhos: lista(payload.atalhos).map(traduzirAtalho),
    fontes: lista(payload.fontes).map((f) => ({
      url: texto(f.url),
      titulo: texto(f.titulo),
      trecho: texto(f.trecho),
      confianca: texto(f.confianca),
    })),
    temFonteOficial:
      typeof payload.tem_fonte_oficial === "boolean" ? payload.tem_fonte_oficial : null,
    afirmacoes: lista(payload.afirmacoes).map((a) => ({
      statement: texto(a.statement),
      nature: texto(a.nature),
      refs: Array.isArray(a.refs) ? a.refs.map(String) : [],
    })),
    pendencias: Array.isArray(payload.pendencias) ? payload.pendencias.map(String) : [],
    falta: Array.isArray(payload.falta) ? payload.falta.map(String) : [],
    candidatos: lista(payload.candidatos).map((c) => ({
      casoId: texto(c.caso_id),
      cliente: texto(c.cliente),
      categoria: texto(c.categoria),
      criadoEm: texto(c.criado_em),
      desempate: texto(c.desempate),
    })),
    consultas: lista(payload.consultas).map((c) => ({
      ferramenta: texto(c.ferramenta),
      argumentos: (c.argumentos ?? {}) as Record<string, unknown>,
    })),
    documentos: traduzirPainel(payload.documentos as Cru | undefined),
  };
}

function traduzirSessao(cru: Cru): ResumoDeSessao {
  return {
    id: texto(cru.id),
    titulo: texto(cru.titulo) || "Nova conversa",
    resumo: texto(cru.resumo),
    casoId: typeof cru.caso_id === "string" ? cru.caso_id : null,
    assunto: texto(cru.assunto),
    perguntas: Number(cru.perguntas ?? 0),
    criadoEm: texto(cru.criado_em),
    atualizadoEm: texto(cru.atualizado_em),
  };
}

/* --------------------------------------------------------------------- rede */

export async function estadoDoChat(): Promise<EstadoDoChat> {
  const cru = await chamarAgente<Cru>("/api/chat/estado");
  return {
    web: Boolean(cru.web),
    analista: Boolean(cru.analista),
    agente: Boolean(cru.agente),
    teto: Number(cru.teto ?? 8),
  };
}

export async function listarSessoes(): Promise<{ sessoes: ResumoDeSessao[]; teto: number }> {
  const cru = await chamarAgente<Cru>("/api/chat/sessoes");
  return { sessoes: lista(cru.sessoes).map(traduzirSessao), teto: Number(cru.teto ?? 8) };
}

/** Abre uma sessão. `apagadas` são as que a poda tirou para caber no teto de oito. */
export async function abrirSessao(): Promise<{ sessao: SessaoCompleta; apagadas: string[] }> {
  const cru = await chamarAgente<Cru>("/api/chat/sessoes", { method: "POST" });
  const sessao = (cru.sessao ?? {}) as Cru;
  return {
    sessao: { ...traduzirSessao(sessao), mensagens: [] },
    apagadas: Array.isArray(cru.apagadas) ? cru.apagadas.map(String) : [],
  };
}

export async function buscarSessao(id: string): Promise<SessaoCompleta> {
  const cru = await chamarAgente<Cru>(`/api/chat/sessoes/${id}`);
  return { ...traduzirSessao(cru), mensagens: lista(cru.mensagens).map(traduzirMensagem) };
}

export async function apagarSessao(id: string): Promise<void> {
  await chamarAgente<void>(`/api/chat/sessoes/${id}`, { method: "DELETE" });
}

export async function perguntar(
  sessaoId: string,
  mensagem: string,
  opcoes: { modo?: ModoDoChat; casoId?: string | null } = {},
): Promise<{ sessao: ResumoDeSessao; mensagem: MensagemDoChat }> {
  const cru = await chamarAgente<Cru>(`/api/chat/sessoes/${sessaoId}/mensagens`, {
    method: "POST",
    body: JSON.stringify({
      mensagem,
      modo: opcoes.modo ?? "AUTO",
      caso_id: opcoes.casoId ?? null,
    }),
  });
  return {
    sessao: traduzirSessao((cru.sessao ?? {}) as Cru),
    mensagem: traduzirMensagem((cru.mensagem ?? {}) as Cru),
  };
}

/** Cola a sessão a um caso, ou a solta (`null`). */
export async function fixarCaso(sessaoId: string, casoId: string | null): Promise<SessaoCompleta> {
  const cru = await chamarAgente<Cru>(`/api/chat/sessoes/${sessaoId}/caso`, {
    method: "PATCH",
    body: JSON.stringify({ caso_id: casoId }),
  });
  return { ...traduzirSessao(cru), mensagens: lista(cru.mensagens).map(traduzirMensagem) };
}

/** O material do caso para o botão "Ver aqui" — inclusive numa sessão reaberta amanhã,
 *  quando a mensagem gravada já não reflete o que entrou no caso desde então. */
export async function documentosDoCaso(casoId: string): Promise<PainelDeDocumentos> {
  const cru = await chamarAgente<Cru>(`/api/chat/casos/${casoId}/documentos`);
  return traduzirPainel(cru) as PainelDeDocumentos;
}
