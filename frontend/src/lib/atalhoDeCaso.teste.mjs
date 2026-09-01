/* O atalho `#` do chat geral, exercitado de verdade — o módulo real, não uma cópia dele.
 *
 * O QUE ESTE TESTE PROTEGE
 *
 * O atalho existe porque escrever o nome por extenso é onde a conversa erra: o acervo
 * tem homônimos, mistura grafias ("José", "Jose") e o roteador do servidor RECUSA um
 * primeiro nome sozinho, de propósito — escolher entre três Marias seria sorteio. Se a
 * lista daqui divergir do que o servidor reconhece, o advogado escolhe um caso da lista
 * e recebe de volta "sobre qual deles eu respondo?".
 *
 * Rodar (a partir de frontend/):
 *     node --experimental-strip-types src/lib/atalhoDeCaso.teste.mjs
 */

import { filtrarCasos, inicioDaMencao, normalizarNome } from "./atalhoDeCaso.ts";

let falhas = 0;
function checar(condicao, descricao) {
  if (condicao) console.log(`  OK    ${descricao}`);
  else {
    falhas += 1;
    console.log(`  FALHA ${descricao}`);
  }
}

const caso = (id, cliente, categoria = "acidente_trabalho", criado = "2026-08-20T09:00:00Z") => ({
  id,
  cliente,
  categoria,
  criado_em: criado,
});

console.log("\n1. onde a menção começa");
checar(inicioDaMencao("#", 1) === 0, "o `#` no começo do texto abre a lista");
checar(inicioDaMencao("resuma o caso de #ma", 20) === 17, "depois de espaço também");
checar(inicioDaMencao("sem menção nenhuma", 18) === -1, "sem `#` não há menção");

// A regra que impede o seletor de aparecer por cima do que está sendo escrito.
checar(
  inicioDaMencao("processo 0801234-55#", 20) === -1,
  "`#` colado em palavra NÃO abre — número de processo não é menção",
);
checar(inicioDaMencao("art. 5#", 7) === -1, "nem grudado num artigo de lei");

// O cursor manda, não o texto: ele se move sozinho com seta e clique.
checar(
  inicioDaMencao("#maria e o resto da frase", 6) === 0,
  "com o cursor DENTRO da menção, ela continua aberta",
);
checar(
  inicioDaMencao("#maria\ne agora outra linha", 25) === -1,
  "quebra de linha encerra a menção",
);

console.log("\n2. a normalização é a mesma do servidor");
checar(normalizarNome("José") === "jose", "acento sai");
checar(normalizarNome("  MARIA   SILVA ") === "maria silva", "caixa e espaços colapsam");

console.log("\n3. o que a lista mostra");
const acervo = [
  caso("c1", "Maria Santos"),
  caso("c2", "Ana Maria Souza"),
  caso("c3", "José Pereira"),
  caso("c4", "Maria Santos", "acidente_trabalho", "2026-08-25T03:55:12Z"),
];

checar(filtrarCasos(acervo, "").length === 4, "termo vazio mostra o acervo inteiro");
checar(
  filtrarCasos(acervo, "").map((c) => c.id)[0] === "c1",
  "e na ordem em que a carteira já entrega (mais recente primeiro)",
);

const comMa = filtrarCasos(acervo, "ma");
checar(
  comMa.map((c) => c.id).join(",") === "c1,c4,c2",
  "quem COMEÇA com o termo vem antes de quem apenas contém",
);

checar(
  filtrarCasos(acervo, "jose").map((c) => c.id).join(",") === "c3",
  "procurar sem acento acha o nome acentuado",
);
checar(
  filtrarCasos(acervo, "JOSÉ").map((c) => c.id).join(",") === "c3",
  "e procurar com acento também",
);
checar(
  filtrarCasos(acervo, "maria s").map((c) => c.id).join(",") === "c1,c4,c2",
  "o termo com espaço continua filtrando — nome composto é o caso comum",
);
// "Ana Maria Souza" entra por conter "maria s" no MEIO do nome, e fica atrás das duas que
// começam com ele. É o desejado: quem digitou "maria s" pode estar procurando qualquer um
// dos três, e a ordem já responde qual é o mais provável.
checar(
  filtrarCasos(acervo, "maria sa").map((c) => c.id).join(",") === "c1,c4",
  "mais uma letra descarta quem só continha o termo",
);
checar(filtrarCasos(acervo, "zzz").length === 0, "nome que não existe não inventa candidato");

console.log("\n4. o corte em oito");
const muitos = Array.from({ length: 20 }, (_, n) => caso(`id${n}`, `Maria ${n}`));
checar(filtrarCasos(muitos, "maria").length === 8, "no máximo oito, como na desambiguação");

console.log(`\n${falhas ? `${falhas} FALHA(S)` : "TODOS OS TESTES PASSARAM"}`);
process.exit(falhas ? 1 : 0);
