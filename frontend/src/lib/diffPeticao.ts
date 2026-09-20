/**
 * O diff da revisão: o que sai do texto e o que entra.
 *
 * Vivia dentro do `FluxoPeticao.tsx`, junto do componente que pinta as duas colunas.
 * Saiu porque é a parte que PRECISA ser exercitada com peça de verdade — o vermelho
 * riscado e o verde destacado são a única coisa que o advogado tem para conferir uma
 * alteração antes de aceitá-la, e uma marcação errada é pior do que marcação nenhuma:
 * ela diz que mudou o que não mudou.
 *
 * Aqui não há React nem estado, só texto — é o que permite rodar contra o par
 * (antes, depois) que o backend produziu numa revisão real (`src/lib/diffPeticao.teste.mjs`).
 */

export interface SecaoComparavel {
  code: string;
  label?: string;
  content: string;
}

export function normalizarParaComparacao(texto: string): string {
  return texto.replace(/\s+/g, " ").trim();
}

export function parearSecoes(secoes: SecaoComparavel[], opostas: SecaoComparavel[]): Map<string, SecaoComparavel> {
  const usados = new Set<number>();
  const resultado = new Map<string, SecaoComparavel>();
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

/** Uma linha visual da comparação. O código de uma seção pode mudar quando a IA
 * reorganiza a peça; por isso a tela precisa renderizar o PAR encontrado, em vez de
 * montar as duas colunas separadamente por `code`. */
export interface LinhaComparacao {
  antes: SecaoComparavel;
  depois: SecaoComparavel;
}

export function alinharSecoes(antes: SecaoComparavel[], depois: SecaoComparavel[]): LinhaComparacao[] {
  const pares = parearSecoes(antes, depois);
  const usados = new Set<string>();
  const linhas = antes.map((secao) => {
    const oposta = pares.get(secao.code);
    if (oposta) usados.add(oposta.code);
    return {
      antes: secao,
      depois: oposta ?? { ...secao, content: "" },
    };
  });
  depois.filter((secao) => !usados.has(secao.code)).forEach((secao) => {
    linhas.push({ antes: { ...secao, content: "" }, depois: secao });
  });
  return linhas;
}

/**
 * As palavras de `texto` que NÃO existem em `outro` na mesma sequência.
 *
 * Por sequência (LCS), e não por conjunto: repetição e posição importam — "danos morais e
 * danos materiais" com um pedido a menos tem de derrubar UM dos dois "danos".
 *
 * O resultado é sempre sobre `texto`, qualquer que seja o lado da comparação: a coluna da
 * esquerda pergunta o que saiu, a da direita o que entrou, e o cálculo é o mesmo com os
 * argumentos trocados. Só a cor muda.
 *
 * Já não foi assim: a coluna da direita reexecutava o diff invertido e devolvia índices
 * calculados sobre o texto ANTIGO, que o componente aplicava às palavras do texto NOVO.
 * Numa substituição do mesmo tamanho ("R$ 40.000,00" para "R$ 60.000,00") as posições
 * coincidiam e ninguém via; numa INSERÇÃO — acrescentar um pedido de justiça gratuita —
 * o verde caía numa palavra solta no meio do parágrafo, em vez de marcar o trecho que
 * entrou. Achado com revisões reais da DeepSeek (`diffPeticao.teste.mjs`).
 */
export function indicesAlterados(texto: string, outro: string): Set<number> {
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
  return new Set(atual.map((_, indice) => indice).filter((indice) => !mantidos.has(indice)));
}
