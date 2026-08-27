/**
 * Cliente do agente geral — o chat que não começa dentro de um caso.
 *
 * Fala com `/api/agente/conversas*` do backend do Acervo, que é quem decide para onde vai
 * cada pergunta. A decisão é dele, e não daqui, por um motivo prático: ela é
 * determinística e precisa ser a mesma para qualquer tela que venha a existir depois.
 *
 * A distinção que atravessa este arquivo inteiro é a `natureza` da resposta. São quatro,
 * e a tela mostra cada uma de um jeito porque elas valem coisas diferentes:
 *
 * - `CASO` — veio do agente jurídico, sobre um caso, com o lastro dele;
 * - `ANALISE` — veio do ANALISTA: ele consultou o acervo (panorama, casos, dossiês,
 *   documentos) e escreveu a leitura em cima do que mediu. Vem com as consultas que fez;
 * - `SISTEMA` — explicação de como o produto funciona. Texto fixo do próprio sistema;
 * - `ACERVO` — a pergunta atravessa vários casos e **ninguém responde isso ainda**;
 * - `ESCOLHA` — a pergunta citou mais de um caso, e escolher um seria adivinhar.
 *
 * Achatar `SISTEMA` e `CASO` na mesma bolha faria explicação de produto e dado apurado
 * chegarem com o mesmo peso — que é exatamente o que este sistema não pode produzir.
 */

import {
  chamarAgente,
  traduzirPropostaCrua,
  type AfirmacaoDoAgente,
  type PropostaDoAgente,
} from "./agente";

export type NaturezaDaResposta =
  | "CASO"
  /** O analista: leitura do acervo construída a partir de consultas deste sistema. */
  | "ANALISE"
  | "SISTEMA"
  | "ACERVO"
  | "ESCOLHA"
  | "INDISPONIVEL"
  | "PERGUNTA";

/** Um caso citado numa pergunta ambígua — vira um botão, não outra digitação.
 *
 * A categoria e a data não são enfeite: o mesmo cliente com dois casos é corriqueiro
 * (mesma pessoa, duas ações), e uma lista de botões todos escritos com o mesmo nome não
 * distingue nada — quem escolhe estaria clicando no escuro. */
export interface CandidatoDeCaso {
  casoId: string;
  cliente: string;
  categoria: string;
  criadoEm: string;
  /** Os primeiros caracteres do identificador. Só vem preenchido quando categoria e data
   *  de abertura coincidem com as de outro candidato — o último recurso para distinguir
   *  dois processos do mesmo cliente abertos no mesmo dia. */
  desempate: string;
}

export interface MensagemDaConversa {
  id: string;
  papel: "USER" | "ASSISTANT";
  conteudo: string;
  natureza: NaturezaDaResposta;
  criadaEm: string;
  /** O caso sobre o qual esta resposta foi dada. É o que leva o "abrir o caso" ao lugar. */
  casoId?: string;
  cliente?: string;
  citacoes: string[];
  afirmacoes: AfirmacaoDoAgente[];
  pendencias: string[];
  /** `ACERVO`: o que faltaria construir para que a pergunta passasse a ter resposta. */
  falta: string[];
  /** `ESCOLHA`: os casos que a pergunta citou. */
  candidatos: CandidatoDeCaso[];
  /** `SISTEMA`: o verbete do glossário que respondeu, e o título dele. */
  verbete?: string;
  tituloDoVerbete?: string;
  /** `ANALISE`: o caminho que a resposta percorreu, consulta por consulta.
   *
   * Não é enfeite de transparência: uma leitura crítica do acervo é indistinguível de um
   * palpite bem escrito, e é isto que permite ao advogado conferir de onde veio. */
  consultas: ConsultaDoAnalista[];
  /** `ANALISE`: os casos que a resposta cita, para virarem caminho até o dossiê. */
  casos: string[];
}

export interface ConsultaDoAnalista {
  ferramenta: string;
  argumentos: Record<string, unknown>;
  passo: number;
}

export interface ResumoDeConversa {
  id: string;
  titulo: string;
  /** A linha de contexto no histórico: o cliente, "Sobre o sistema", "Sem resposta ainda". */
  resumo: string;
  casoId: string | null;
  criadoEm: string;
  atualizadoEm: string;
}

export interface ConversaCompleta extends ResumoDeConversa {
  mensagens: MensagemDaConversa[];
}

export interface RespostaDaConversa {
  conversa: ResumoDeConversa;
  mensagem: MensagemDaConversa;
  propostas: PropostaDoAgente[];
}

/* ------------------------------------------------------------------ tradução */

interface ConversaCrua {
  id: string;
  titulo: string;
  resumo: string;
  caso_id: string | null;
  criado_em: string;
  atualizado_em: string;
  mensagens?: MensagemCrua[] | null;
}

interface MensagemCrua {
  id: string;
  papel: string;
  conteudo: string;
  natureza: string;
  criado_em: string;
  payload?: Record<string, unknown> | null;
}

function lista(payload: Record<string, unknown>, chave: string): string[] {
  const valor = payload[chave];
  return Array.isArray(valor) ? valor.map((item) => String(item)) : [];
}

function traduzirMensagem(crua: MensagemCrua): MensagemDaConversa {
  const payload = (crua.payload ?? {}) as Record<string, unknown>;
  const candidatos = Array.isArray(payload.candidatos)
    ? (payload.candidatos as Record<string, unknown>[]).map((item) => ({
        casoId: String(item.caso_id ?? ""),
        cliente: String(item.cliente ?? ""),
        categoria: String(item.categoria ?? ""),
        criadoEm: String(item.criado_em ?? ""),
        desempate: String(item.desempate ?? ""),
      }))
    : [];

  return {
    id: crua.id,
    papel: crua.papel === "USER" ? "USER" : "ASSISTANT",
    conteudo: crua.conteudo,
    natureza: crua.natureza as NaturezaDaResposta,
    criadaEm: crua.criado_em,
    casoId: payload.caso_id ? String(payload.caso_id) : undefined,
    cliente: payload.cliente ? String(payload.cliente) : undefined,
    citacoes: lista(payload, "citacoes"),
    // As afirmações vêm no formato do agente (`statement` / `nature` / `refs`), o mesmo
    // que o painel do caso já lê. Traduzir aqui para outro vocabulário faria as duas
    // telas divergirem sobre como um fato alegado aparece — e o guardrail de lastro do
    // backend deixaria de valer numa delas.
    afirmacoes: Array.isArray(payload.afirmacoes)
      ? (payload.afirmacoes as Record<string, unknown>[]).map((item) => ({
          statement: String(item.statement ?? ""),
          nature: (item.nature ?? "INFERENCE") as AfirmacaoDoAgente["nature"],
          refs: Array.isArray(item.refs) ? item.refs.map((r) => String(r)) : [],
        }))
      : [],
    pendencias: lista(payload, "pendencias"),
    falta: lista(payload, "falta"),
    candidatos,
    verbete: payload.verbete ? String(payload.verbete) : undefined,
    tituloDoVerbete: payload.titulo ? String(payload.titulo) : undefined,
    consultas: Array.isArray(payload.consultas)
      ? (payload.consultas as Record<string, unknown>[]).map((item) => ({
          ferramenta: String(item.ferramenta ?? ""),
          argumentos: (item.argumentos ?? {}) as Record<string, unknown>,
          passo: Number(item.passo ?? 0),
        }))
      : [],
    casos: lista(payload, "casos"),
  };
}

function traduzirConversa(crua: ConversaCrua): ConversaCompleta {
  return {
    id: crua.id,
    titulo: crua.titulo,
    resumo: crua.resumo,
    casoId: crua.caso_id,
    criadoEm: crua.criado_em,
    atualizadoEm: crua.atualizado_em,
    mensagens: (crua.mensagens ?? []).map(traduzirMensagem),
  };
}

/* --------------------------------------------------------------------- rotas */

export async function listarConversas(busca = ""): Promise<ResumoDeConversa[]> {
  const parametros = busca.trim() ? `?busca=${encodeURIComponent(busca.trim())}` : "";
  const corpo = await chamarAgente<{ conversas: ConversaCrua[] }>(
    `/api/agente/conversas${parametros}`,
  );
  return corpo.conversas.map(traduzirConversa);
}

/** Abre uma conversa vazia. O título real chega com a primeira pergunta. */
export async function abrirConversa(casoId?: string): Promise<ConversaCompleta> {
  return traduzirConversa(
    await chamarAgente<ConversaCrua>("/api/agente/conversas", {
      method: "POST",
      body: JSON.stringify({ caso_id: casoId ?? null }),
    }),
  );
}

export async function buscarConversa(conversaId: string): Promise<ConversaCompleta> {
  return traduzirConversa(await chamarAgente<ConversaCrua>(`/api/agente/conversas/${conversaId}`));
}

/** A pergunta. O roteamento acontece no servidor — a tela não adivinha o destino. */
export async function perguntar(
  conversaId: string,
  mensagem: string,
  casoId?: string,
): Promise<RespostaDaConversa> {
  const corpo = await chamarAgente<{
    conversa: ConversaCrua;
    mensagem: MensagemCrua;
    propostas?: Record<string, unknown>[] | null;
  }>(`/api/agente/conversas/${conversaId}/mensagens`, {
    method: "POST",
    body: JSON.stringify({ mensagem, caso_id: casoId ?? null }),
  });

  return {
    conversa: traduzirConversa(corpo.conversa),
    mensagem: traduzirMensagem(corpo.mensagem),
    // A proposta chega no formato do agente, o mesmo que o painel do caso recebe, e a
    // tradução é a de `lib/agente.ts`. Uma segunda cópia divergiria no dia em que o
    // campo `preview` mudasse de nome — e a confirmação passaria a mostrar o antes vazio.
    propostas: (corpo.propostas ?? []).map(traduzirPropostaCrua),
  };
}

/** Cola a conversa a um caso, ou a solta (`null`) para voltar a falar do sistema. */
export async function fixarCaso(
  conversaId: string,
  casoId: string | null,
): Promise<ConversaCompleta> {
  return traduzirConversa(
    await chamarAgente<ConversaCrua>(`/api/agente/conversas/${conversaId}/caso`, {
      method: "PATCH",
      body: JSON.stringify({ caso_id: casoId }),
    }),
  );
}

export async function apagarConversa(conversaId: string): Promise<void> {
  // O `204` volta sem corpo, e `chamarAgente` já trata isso: o que importa aqui é passar
  // pelo mesmo tratamento de erro das demais — apagar a conversa de outra pessoa responde
  // `404`, e essa mensagem precisa chegar legível à tela.
  await chamarAgente<void>(`/api/agente/conversas/${conversaId}`, { method: "DELETE" });
}
