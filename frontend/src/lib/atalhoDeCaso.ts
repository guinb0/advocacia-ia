/**
 * O atalho `#` do chat geral: onde a menção começa e quais casos ela alcança.
 *
 * Mora fora do componente porque é DECISÃO, não desenho — e decisão que precisa casar
 * com a do servidor. A normalização daqui é a mesma de `conversa_geral.normalizar` no
 * backend: se as duas divergirem, a lista oferece um caso que o roteador depois não
 * reconhece, e o advogado escolhe da lista para receber "não encontrei esse caso".
 *
 * Puro de propósito — sem React, sem rede —, o que permite exercitá-lo direto:
 *
 *     node --experimental-strip-types src/lib/atalhoDeCaso.teste.mjs
 */

import type { Caso } from "./types";

/** Onde começa a menção sob o cursor, ou `-1` quando não há nenhuma.
 *
 * O `#` só abre a lista no começo do texto ou depois de espaço. Sem essa regra,
 * "processo 0801234-55#" e qualquer `#` no meio de uma palavra abririam o seletor por
 * cima do que estava sendo escrito.
 */
export function inicioDaMencao(texto: string, cursor: number): number {
  const antes = texto.slice(0, cursor);
  const marca = antes.lastIndexOf("#");
  if (marca < 0) return -1;
  if (marca > 0 && !/\s/.test(antes[marca - 1])) return -1;
  // Quebra de linha encerra a menção: ela é uma citação dentro de uma frase, não um
  // parágrafo inteiro.
  if (antes.slice(marca).includes("\n")) return -1;
  return marca;
}

/** Minúsculas, sem acento, espaços colapsados.
 *
 * O acervo mistura grafias — "José", "Jose", "JOSÉ" — e o nome é digitado com pressa.
 * É a MESMA normalização que o servidor faz em `conversa_geral.normalizar`: se as duas
 * divergirem, a lista mostra um caso que o roteador depois não reconhece.
 */
export function normalizarNome(valor: string): string {
  return valor
    .normalize("NFKD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase()
    .split(/\s+/)
    .filter(Boolean)
    .join(" ");
}

/** Quantos casos cabem na lista antes de ela deixar de ajudar.
 *
 * Oito ainda se lê de relance — é o mesmo limite da desambiguação do servidor. Passar
 * disso vira uma segunda carteira dentro do campo de texto, e aí a busca por nome faz
 * esse trabalho melhor. */
const MAXIMO_NO_ATALHO = 8;

/** Os casos que casam com o que já foi digitado depois do `#`.
 *
 * Quem começa com o termo vem primeiro: digitar "ma" tem de trazer "Maria" antes de
 * "Ana Maria" — o prefixo é o que a pessoa está escrevendo, e é ele que ela espera ver
 * no topo. Termo vazio mostra o acervo do jeito que a carteira já ordena (mais recentes
 * primeiro), que é onde está o caso do dia.
 */
export function filtrarCasos(casos: Caso[], termo: string): Caso[] {
  const procurado = normalizarNome(termo);
  if (!procurado) return casos.slice(0, MAXIMO_NO_ATALHO);

  const comeca: Caso[] = [];
  const contem: Caso[] = [];
  for (const caso of casos) {
    const nome = normalizarNome(String(caso.cliente ?? ""));
    if (nome.startsWith(procurado)) comeca.push(caso);
    else if (nome.includes(procurado)) contem.push(caso);
  }
  return [...comeca, ...contem].slice(0, MAXIMO_NO_ATALHO);
}
