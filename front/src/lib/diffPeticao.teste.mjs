/* O verde e o vermelho da revisão, exercitados com o módulo real.
 *
 * O QUE ESTE TESTE PROTEGE
 *
 * A comparação antes × depois é a única coisa que o advogado tem para conferir uma
 * alteração antes de aceitá-la e transformá-la em versão da peça. Marcação errada é pior
 * do que marcação nenhuma: ela afirma que mudou o que não mudou — e quem confia nela
 * aprova um parágrafo que nunca leu.
 *
 * Três armadilhas, todas já vistas em revisão de verdade:
 *
 * 1. **palavra repetida**: "danos morais e danos materiais" — marcar por conjunto acusa
 *    a palavra certa no lugar errado. Por isso o diff é por SEQUÊNCIA (LCS);
 * 2. **seção que troca de posição ou de código**: o texto é idêntico e apareceria todo
 *    verde/vermelho. `parearSecoes` casa primeiro por conteúdo, depois por código;
 * 3. **peça enorme**: acima de 1.500 palavras o LCS cede lugar ao corte por
 *    prefixo/sufixo, e o teste garante que ele ainda não marca o que ficou igual.
 *
 * Rodar (a partir de front/):
 *     node --experimental-strip-types src/lib/diffPeticao.teste.mjs
 *
 * Com um arquivo de revisões reais gravado pelo backend (ver docs/CHAT-DA-PETICAO.md):
 *     node --experimental-strip-types src/lib/diffPeticao.teste.mjs revisoes.json
 */

import { readFileSync } from "node:fs";

import { alinharSecoes, indicesAlterados, parearSecoes } from "./diffPeticao.ts";

let falhas = 0;
function checar(condicao, descricao) {
  if (condicao) console.log(`  OK    ${descricao}`);
  else {
    falhas += 1;
    console.log(`  FALHA ${descricao}`);
  }
}

/** As palavras que a tela marcaria: em vermelho as que saem, em verde as que entram.
 *
 * A ordem dos argumentos é o que decide a cor — `marcadas(antes, depois)` é a coluna da
 * esquerda, `marcadas(depois, antes)` é a da direita. */
function marcadas(texto, outro) {
  const palavras = texto.split(/\s+/).filter(Boolean);
  const alterados = indicesAlterados(texto, outro);
  return [...alterados].sort((a, b) => a - b).map((i) => palavras[i]);
}

console.log("\n1. O que sai e o que entra");

const antes = "o valor da indenização é de R$ 40.000,00";
const depois = "o valor da indenização é de R$ 60.000,00";
checar(
  marcadas(antes, depois).join(" ") === "40.000,00",
  "só o valor antigo fica riscado em vermelho",
);
checar(
  marcadas(depois, antes).join(" ") === "60.000,00",
  "e só o novo fica destacado em verde",
);
checar(indicesAlterados(antes, antes).size === 0, "texto idêntico não marca nada");

/* A INSERÇÃO é o caso que pega o defeito que a substituição esconde.
 *
 * Trocar "40.000,00" por "60.000,00" mantém a palavra na mesma posição, então marcar por
 * engano os índices da outra coluna dá o mesmo resultado. Acrescentar uma alínea inteira,
 * não: foi assim que o verde apareceu sobre uma palavra solta no meio do parágrafo, numa
 * revisão real que só ACRESCENTAVA o pedido de justiça gratuita. */
const semGratuidade = "requer a condenação da reclamada nas custas processuais";
const comGratuidade =
  "requer a concessão dos benefícios da justiça gratuita e a condenação da reclamada nas custas processuais";
const entraram = marcadas(comGratuidade, semGratuidade);
checar(
  entraram.join(" ") === "concessão dos benefícios da justiça gratuita e a",
  "o trecho que ENTROU é marcado inteiro — e só ele (oito palavras)",
);
checar(
  !entraram.includes("custas") && !entraram.includes("processuais"),
  "o que já estava lá continua sem marca",
);
checar(
  marcadas(semGratuidade, comGratuidade).length === 0,
  "e do lado de lá nada fica vermelho — não saiu nada do texto",
);

console.log("\n2. Palavra repetida no mesmo parágrafo");

const comDois = "requer danos morais e danos materiais";
const semMaterial = "requer danos morais";
const saiu = marcadas(comDois, semMaterial);
checar(saiu.includes("materiais"), "a palavra que saiu é marcada");
checar(
  saiu.filter((p) => p === "danos").length === 1,
  "e só UM dos dois «danos» cai — o diff é por sequência, não por conjunto",
);
checar(!saiu.includes("morais"), "o pedido que ficou não é marcado");

console.log("\n3. Seção que muda de posição");

const par = parearSecoes(
  [
    { code: "FACTS", content: "o acidente ocorreu em 14/08/2024" },
    { code: "CLAIMS", content: "requer indenização" },
  ],
  [
    { code: "CLAIMS_2", content: "requer indenização" },
    { code: "FATOS", content: "o acidente ocorreu em 14/08/2024" },
  ],
);
checar(
  par.get("FACTS")?.content === "o acidente ocorreu em 14/08/2024",
  "a seção é reencontrada pelo conteúdo, mesmo com outro código e outra posição",
);
checar(
  indicesAlterados("o acidente ocorreu em 14/08/2024", par.get("FACTS").content).size === 0,
  "e por isso não aparece toda marcada",
);
const linhasReordenadas = alinharSecoes(
  [{ code: "FACTS", content: "o acidente ocorreu em 14/08/2024" }],
  [{ code: "FATOS", content: "o acidente ocorreu em 14/08/2024" }],
);
checar(
  linhasReordenadas.length === 1 && linhasReordenadas[0].antes.content === linhasReordenadas[0].depois.content,
  "a tela mantém o par numa única linha quando o código muda",
);

console.log("\n4. Peça longa (acima do teto do LCS)");

const miolo = Array.from({ length: 1600 }, (_, i) => `palavra${i}`).join(" ");
const longoAntes = `${miolo} valor de R$ 40.000,00`;
const longoDepois = `${miolo} valor de R$ 60.000,00`;
const marcadasNoLongo = marcadas(longoAntes, longoDepois);
checar(marcadasNoLongo.length <= 2, `o corte por prefixo/sufixo marca pouco (${marcadasNoLongo.length})`);
checar(
  marcadasNoLongo.includes("40.000,00"),
  "e ainda assim acha o que mudou no fim da peça",
);

/* ------------------------------------------------------------------ peça real
 *
 * Opcional: o arquivo é gravado pelo backend depois de rodar revisões de verdade contra
 * a DeepSeek. Sem ele, o teste acima já vale; com ele, prova que a marcação funciona no
 * texto que o modelo devolve, e não só nos casos que eu soube imaginar. */

const arquivo = process.argv[2];
if (arquivo) {
  console.log(`\n5. Revisões reais (${arquivo})`);
  const { revisoes } = JSON.parse(readFileSync(arquivo, "utf-8"));
  for (const revisao of revisoes) {
    if (!revisao.propos || !revisao.depois?.length) continue;
    const parDaEsquerda = parearSecoes(revisao.antes, revisao.depois);
    let vermelhas = 0;
    let verdes = 0;
    let secoesTocadas = 0;
    for (const secao of revisao.antes) {
      const oposta = parDaEsquerda.get(secao.code);
      if (!oposta || oposta.content === secao.content) continue;
      secoesTocadas += 1;
      vermelhas += indicesAlterados(secao.content, oposta.content).size;
      verdes += indicesAlterados(oposta.content, secao.content).size;
    }
    console.log(
      `  [${revisao.numero}] ${revisao.comando}\n` +
        `        ${secoesTocadas} seção(ões) · ${vermelhas} palavra(s) em vermelho · ${verdes} em verde`,
    );
    checar(
      secoesTocadas > 0 && vermelhas + verdes > 0,
      `      a comparação da revisão ${revisao.numero} tem o que mostrar`,
    );
  }
}

console.log(`\n${falhas ? `${falhas} FALHA(S)` : "TODOS OS TESTES PASSARAM"}`);
process.exit(falhas ? 1 : 0);
