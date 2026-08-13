import type { Bloco, Pergunta } from "./types";

/* Entrevista de mentira, para testar o contrato sem digitar treze campos.
 *
 * SÓ EXISTE EM DESENVOLVIMENTO. Quem faz o corte é o `process.env.NODE_ENV` em
 * `Roteiro.tsx`: o Next troca essa comparação por `false` na hora do build e o
 * empacotador remove o bloco inteiro, botão e dados juntos. Não é decisão de
 * tela nem de configuração — é código que não existe no pacote de produção.
 *
 * O nome traz "(TESTE)" de propósito, e não é enfeite: se um contrato gerado
 * por este botão escapar para uma pasta de cliente, ele se denuncia na primeira
 * linha da qualificação. Um nome plausível ficaria indistinguível do verdadeiro.
 *
 * O CPF é o 111.444.777-35, que fecha no módulo 11 — assim o campo mostra o
 * "CPF confere" em verde e dá para conferir a validação junto. */

export const AMOSTRA: Record<string, string> = {
  nome: "Maria Aparecida da Silva (TESTE)",
  nacionalidade: "brasileira",
  nascimento: "1985-03-15",
  estado_civil: "Casado(a)",
  profissao: "carteira",
  cpf: "111.444.777-35",
  rg: "1234567",
  rg_orgao: "SSP",
  rg_uf: "PA",
  mae: "Ana Aparecida da Silva",
  pai: "José Ribamar da Silva",
  cep: "66055-240",
  endereco:
    "Avenida Governador José Malcher, nº 100, Nazaré, Belém/PA, CEP 66055-240",
  telefone: "(91) 98888-7777",
  email: "teste@exemplo.com",
  pis: "120.12345.67-2",
  tempo_casa: "8 anos",
};

const RELATO_EXEMPLO =
  "Resposta de teste. Durante a entrega, por volta das 15h, fui abordado por " +
  "dois homens em uma motocicleta. Levaram a moto dos Correios e as encomendas. " +
  "Desde então tenho dificuldade para dormir e medo de sair para trabalhar.";

function respostaDeTeste(pergunta: Pergunta): string | string[] {
  const conhecida = AMOSTRA[pergunta.id];
  if (conhecida !== undefined) return conhecida;

  switch (pergunta.tipo) {
    case "sim_nao":
      // "não" mantém os módulos condicionais fechados: o teste do contrato não
      // precisa das 40 perguntas de assalto, doença e sequela.
      return "não";
    case "escolha":
    case "lista":
      return pergunta.opcoes[0] ?? "";
    case "documentos":
      return pergunta.opcoes.slice(0, 2);
    case "data":
      return "2026-03-12";
    case "relato":
      return RELATO_EXEMPLO;
    default:
      return "preenchido para teste";
  }
}

/** Respostas de teste para o roteiro inteiro, módulos fechados incluídos. */
export function entrevistaDeTeste(blocos: Bloco[]): Record<string, string | string[]> {
  const respostas: Record<string, string | string[]> = {};
  for (const bloco of blocos) {
    for (const pergunta of bloco.perguntas) {
      respostas[pergunta.id] = respostaDeTeste(pergunta);
    }
  }
  return respostas;
}
