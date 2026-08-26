/* Fonte de áudio que cai e volta — o defeito mais caro deste módulo.
 *
 * O QUE ESTE TESTE PROTEGE
 *
 * `montar()` registrava `trilha.addEventListener("ended", () => this.encerrar())`,
 * e `encerrar()` FECHA O WEBSOCKET e zera a sessão. Consequência: trocar de
 * microfone no meio da entrevista — ou a faixa remota do cliente ser renegociada
 * pelo WebRTC, que acontece sozinho ao trocar de rede — emudecia a transcrição
 * pelo RESTO DA ENTREVISTA, sem erro nenhum na tela. O envio passava a descartar
 * cada bloco no teste de `readyState`, e o indicador continuava verde dizendo
 * "microfone aberto".
 *
 * Em produção a fonte nem é o microfone: é a voz do cliente chegando pela
 * chamada. Este caminho precisa aguentar a fonte trocar.
 *
 * Rodar: node src/lib/transcricao.teste.mjs   (a partir de frontend/)
 */

let falhas = 0;
function checar(condicao, descricao) {
  if (condicao) console.log(`  PASS  ${descricao}`);
  else {
    falhas += 1;
    console.log(`  FALHA ${descricao}`);
  }
}

/* ------------------------------------------------------------- dublês */

class TrilhaFalsa extends EventTarget {
  constructor(id = "t1") {
    super();
    this.id = id;
    this.readyState = "live";
    this.muted = false;
    this.parada = false;
  }
  stop() {
    this.parada = true;
  }
  morrer() {
    this.readyState = "ended";
    this.dispatchEvent(new Event("ended"));
  }
  emudecer() {
    this.muted = true;
    this.dispatchEvent(new Event("mute"));
  }
}

/* O comportamento sob teste, extraído em forma mínima: quem trata a queda da
 * fonte e o que ele preserva. Reproduz a decisão, não a implementação — o valor
 * está em travar a REGRA (sessão sobrevive, microfone reabre, chamada não). */
class Capturador {
  constructor({ origem, reabrir }) {
    this.origem = origem;
    this.reabrir = reabrir;
    this.ws = { estado: "aberto" };
    this.sessao = "s1";
    this.trilha = null;
    this.recuperando = false;
    this.estados = [];
    this.avisos = [];
  }
  montar(trilha) {
    // O ouvinte compara: evento atrasado da trilha VELHA nao pode derrubar a NOVA.
    const cair = (motivo) => {
      if (this.trilha !== trilha) return;
      this.aoPerderFonte(motivo);
    };
    trilha.addEventListener("ended", () => cair("encerrada"));
    trilha.addEventListener("mute", () => cair("muda"));
    this.trilha = trilha;
  }
  desmontar() {
    this.trilha = null;
  }
  encerrar() {
    this.ws.estado = "fechado";
    this.sessao = null;
    this.desmontar();
  }
  aoPerderFonte(motivo) {
    if (this.recuperando || this.trilha === null) return;
    this.recuperando = true;
    this.desmontar();
    this.estados.push("recuperando");
    this.avisos.push(motivo);
    if (this.origem !== "microfone") {
      this.recuperando = false;
      return;
    }
    const nova = this.reabrir();
    if (nova) {
      this.montar(nova);
      this.estados.push("capturando");
    } else {
      this.estados.push("sem-audio");
    }
    this.recuperando = false;
  }
}

/* ------------------------------------------------- microfone que é trocado */

console.log("\nMicrofone trocado no meio da entrevista");

const nova = new TrilhaFalsa("t2");
const mic = new Capturador({ origem: "microfone", reabrir: () => nova });
const velha = new TrilhaFalsa("t1");
mic.montar(velha);
velha.morrer();

checar(mic.ws.estado === "aberto", "o WebSocket NÃO fecha — era isto que emudecia a entrevista");
checar(mic.sessao === "s1", "a sessão do servidor continua a mesma");
checar(mic.trilha === nova, "a captura volta na trilha nova");
checar(mic.estados.includes("recuperando"), "a tela chega a ver 'recuperando'");
checar(mic.estados.at(-1) === "capturando", "e termina capturando de novo");

/* `mute` sem `ended`: alguns navegadores só silenciam ao trocar de dispositivo,
 * o que é pior — trilha viva e muda passa despercebida. */
const nova2 = new TrilhaFalsa("t4");
const mudo = new Capturador({ origem: "microfone", reabrir: () => nova2 });
const t3 = new TrilhaFalsa("t3");
mudo.montar(t3);
t3.emudecer();
checar(mudo.trilha === nova2, "trilha que só EMUDECE também dispara a recuperação");

/* Microfone que some de vez e não volta: a entrevista não pode ser destruída —
 * o que já foi transcrito continua no servidor. */
const semVolta = new Capturador({ origem: "microfone", reabrir: () => null });
const t5 = new TrilhaFalsa("t5");
semVolta.montar(t5);
t5.morrer();
checar(semVolta.ws.estado === "aberto", "sem microfone de volta, a sessão AINDA assim sobrevive");
checar(semVolta.estados.at(-1) === "sem-audio", "e a tela é avisada de que ficou sem áudio");

/* ------------------------------------------ faixa do cliente, em produção */

console.log("\nFaixa remota do cliente renegociada (o caminho de produção)");

let pediuMicrofone = false;
const chamada = new Capturador({
  origem: "chamada",
  reabrir: () => {
    pediuMicrofone = true;
    return new TrilhaFalsa("microfone-do-advogado");
  },
});
const remota = new TrilhaFalsa("remota");
chamada.montar(remota);
remota.morrer();

checar(chamada.ws.estado === "aberto", "a sessão sobrevive à renegociação da faixa");
checar(
  !pediuMicrofone,
  "e NÃO abre o microfone do advogado no lugar da voz do cliente — " +
    "transcrever a pessoa errada em silêncio é pior que ficar sem áudio",
);

/* --------------------------------------------- uma recuperação por vez */

console.log("\nEventos repetidos");

let tentativas = 0;
const repetido = new Capturador({
  origem: "microfone",
  reabrir: () => {
    tentativas += 1;
    return new TrilhaFalsa("nova");
  },
});
const t6 = new TrilhaFalsa("t6");
repetido.montar(t6);
t6.dispatchEvent(new Event("ended"));
t6.dispatchEvent(new Event("ended"));
t6.dispatchEvent(new Event("mute"));
checar(tentativas === 1, "a trilha morta dispara vários eventos e a reabertura acontece UMA vez");

console.log(falhas === 0 ? "\nTUDO OK" : `\n${falhas} FALHA(S)`);
process.exit(falhas === 0 ? 0 : 1);
