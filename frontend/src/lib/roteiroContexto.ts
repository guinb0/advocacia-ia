import type { ContextoRevisaoRoteiro, RoteiroCompleto } from "./types";

export type RespostasRoteiro = Record<string, string | string[]>;

/** Assinatura estável para impedir reuso de análise após edição manual. */
export function chaveDasRespostas(respostas: RespostasRoteiro): string {
  return JSON.stringify(
    Object.fromEntries(Object.entries(respostas).sort(([a], [b]) => a.localeCompare(b))),
  );
}

export const CAMPOS_TECNICOS_DIGITADOS = new Set([
  "nome", "cpf", "estado_civil", "uf", "municipio",
]);

export const CAMPOS_AUTO_CPF = new Set([
  "nascimento", "sexo", "mae", "cep", "endereco", "telefone", "email",
  "renda_estimada",
]);

interface BaseContexto {
  roteiro: RoteiroCompleto;
  chave: string;
}

const basesPorRoteiro = new WeakMap<
  RoteiroCompleto,
  { automatico?: BaseContexto; manual?: BaseContexto }
>();

function baseContexto(roteiro: RoteiroCompleto, preenchimentoAuto: boolean): BaseContexto {
  let variantes = basesPorRoteiro.get(roteiro);
  if (!variantes) {
    variantes = {};
    basesPorRoteiro.set(roteiro, variantes);
  }
  const variante = preenchimentoAuto ? "automatico" : "manual";
  const existente = variantes[variante];
  if (existente) return existente;

  // Desligar a consulta por CPF não retira campos do roteiro: exceto pelos
  // cinco dados manuais acima, a transcrição continua responsável por todos.
  const roteiroVisivel = roteiro;
  const base = {
    roteiro: roteiroVisivel,
    chave: JSON.stringify(roteiroVisivel),
  };
  variantes[variante] = base;
  return base;
}

/** Mantém respostas do próprio roteiro; entre roteiros, só dados cadastrais. */
export function respostasCompativeis(
  atuais: RespostasRoteiro,
  anterior: RoteiroCompleto | null,
  novo: RoteiroCompleto,
): RespostasRoteiro {
  const perguntasAnteriores = new Map(
    anterior?.blocos.flatMap((bloco) => bloco.perguntas).map((pergunta) => [pergunta.id, pergunta]) ?? [],
  );
  const perguntasDoNovo = new Map(
    novo.blocos.flatMap((bloco) => bloco.perguntas).map((pergunta) => [pergunta.id, pergunta]),
  );
  const mesmoRoteiro = anterior?.codigo === novo.codigo;
  return Object.fromEntries(
    Object.entries(atuais).filter(([id]) => {
      if (!perguntasDoNovo.has(id)) return false;
      if (CAMPOS_TECNICOS_DIGITADOS.has(id) || CAMPOS_AUTO_CPF.has(id)) return true;
      return mesmoRoteiro && perguntasAnteriores.has(id);
    }),
  );
}

function dependenciaAberta(
  pergunta: RoteiroCompleto["blocos"][number]["perguntas"][number],
  respostas: RespostasRoteiro,
): boolean {
  if (!pergunta.depende_de) return true;
  const valor = String(respostas[pergunta.depende_de] ?? "").trim().toLowerCase();
  const esperado = pergunta.depende_valor.trim().toLowerCase();
  if (esperado === "nao" || esperado === "não") return valor === "nao" || valor === "não";
  return valor === esperado;
}

/** Monta a única versão usada pela tela, pela escuta e pela revisão final. */
export function criarContextoRevisao(
  roteiro: RoteiroCompleto | null,
  preenchimentoAuto: boolean,
  respostas: RespostasRoteiro = {},
): ContextoRevisaoRoteiro | null {
  if (!roteiro) return null;
  const base = baseContexto(roteiro, preenchimentoAuto);
  const ids_renderizaveis = base.roteiro.blocos.filter((bloco) => bloco.id !== "abertura").flatMap((bloco) =>
    bloco.perguntas
      .filter((pergunta) => dependenciaAberta(pergunta, respostas))
      .map((pergunta) => pergunta.id),
  );
  return {
    roteiro: base.roteiro,
    chave: base.chave,
    ids_renderizaveis,
  };
}
