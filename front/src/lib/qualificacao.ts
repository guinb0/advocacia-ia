import type { RoteiroCompleto } from "@/lib/types";

/* A QUALIFICAÇÃO NÃO ENTRA NAS SUGESTÕES DA ENTREVISTA — ela é etapa DEPOIS.
 *
 * Nome, CPF, estado civil, UF e município são digitados fora da conversa (é o
 * que `escuta.DADOS_DIGITADOS` fixa do lado do servidor), e o bloco de
 * qualificação inteiro sai da entrevista por `delegado_a`. Roteiro importado
 * não marca `delegado_a`, mas chama o bloco de `identificacao` — o mesmo id que
 * o `Roteiro` já esconde da tela, junto com `abertura`. Cobrar esses campos como
 * "ainda não perguntado" enche a tela de pendência que ninguém resolve com o
 * cliente na linha e empurra para baixo o que falta DO CASO.
 *
 * O filtro sai do roteiro em uso, e não de uma lista de nomes de campo: roteiro
 * de outro escritório nomeia "cpf" como quiser. */
export const DADOS_DIGITADOS = new Set(["nome", "cpf", "estado_civil", "uf", "municipio"]);

const BLOCOS_FORA_DA_CONVERSA = new Set(["identificacao", "abertura"]);

export function idsDeQualificacao(roteiro: RoteiroCompleto | null): Set<string> {
  const ids = new Set(DADOS_DIGITADOS);
  for (const bloco of roteiro?.blocos ?? []) {
    const blocoInteiro = Boolean(bloco.delegado_a) || BLOCOS_FORA_DA_CONVERSA.has(bloco.id);
    for (const pergunta of bloco.perguntas) {
      if (blocoInteiro || pergunta.validacao) ids.add(pergunta.id);
    }
  }
  return ids;
}

/* Para texto livre vindo do modelo (pergunta sugerida, lacuna), onde não há id
 * para comparar. Mesma lista do `analise_resposta._QUALIFICACAO` no servidor:
 * e-mail, WhatsApp e telefone soltos ficam de fora porque "mensagem da empresa
 * no WhatsApp" é prova do caso — só o uso cadastral deles é filtrado. */
const TEXTO_DE_QUALIFICACAO = new RegExp(
  [
    "\\bcpf\\b", "\\brg\\b", "carteira de identidade", "\\bcep\\b", "estado civil",
    "nacionalidade", "naturalidade", "data de nascimento", "\\bnasceu\\b", "nome completo",
    "nome d[ao] (m[aã]e|pai)", "nome dos pais", "filia[cç][aã]o", "\\bpis\\b", "\\bnit\\b",
    "pasep", "t[ií]tulo de eleitor", "profiss[aã]o", "escolaridade", "renda familiar",
    "(seu|sua|n[uú]mero de) (telefone|celular|e-?mail)", "(telefone|e-?mail) (de|para) contato",
    "(seu|sua) endere[cç]o", "endere[cç]o (residencial|completo|atual)",
    "onde (o senhor|a senhora|voc[eê]) mora",
  ].join("|"),
  "i",
);

export function eQualificacao(texto: string): boolean {
  return TEXTO_DE_QUALIFICACAO.test(texto);
}
