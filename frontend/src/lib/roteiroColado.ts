import type { Bloco, Pergunta, RoteiroCompleto } from "./types";

function perguntaColada(texto: string): Pergunta {
  return {
    id: "",
    texto,
    tipo: "relato",
    transcrever: true,
    opcoes: [],
    dica: "",
    obrigatoria: false,
    validacao: "",
    busca: "",
    preenche: "",
    depende_de: "",
    depende_valor: "",
    fala: {},
    impedimento: "",
  };
}

function ehTitulo(linha: string): boolean {
  if (linha.startsWith("(")) return false;
  const titulo = linha.replace(/:$/, "").trim();
  const letras = titulo.match(/\p{L}/gu) ?? [];
  return letras.length >= 4 && titulo.length <= 90 && !/\p{Ll}/u.test(titulo) && !titulo.endsWith("?");
}

function limpar(bruta: string): { texto: string; marcada: boolean } {
  const aparada = bruta.trim();
  const marcada = /^[*•·\-–—]\s+/.test(aparada);
  const texto = aparada
    .replace(/^[*•·\-–—>]+\s*/, "")
    .replace(/^[“"]+/, "")
    .replace(/[”"]+$/, "")
    .replace(/;$/, "")
    .trim();
  return { texto, marcada };
}

function juntar(a: string, b: string): string {
  return a ? `${a}\n${b}` : b;
}

function ehInstrucao(linha: string): boolean {
  return (
    /^\(/.test(linha) ||
    /^(orienta[çc][ãa]o|objetivo|procedimento|agrade[çc]a|cobrar|informe|informar|aguardar|sempre|explicar|registrar|verificar|encaminhar|pe[çc]a)\b/i.test(
      linha,
    )
  );
}

function acrescentarParagrafo(lista: string[], linha: string): void {
  const anterior = lista[lista.length - 1];
  if (anterior !== undefined && !/[.?!:)”"]$/.test(anterior)) {
    lista[lista.length - 1] = `${anterior} ${linha}`;
  } else {
    lista.push(linha);
  }
}

/* Um nome para o roteiro, tirado do próprio texto colado.
 *
 * POR QUE ISTO EXISTE
 *
 * `roteiros.de_dict` recusa roteiro sem nome ("O roteiro precisa de um nome").
 * Como o roteiro novo nasce com o campo vazio, colar o documento inteiro e
 * mandar salvar dava 422 — pedindo à mão um dado que o texto colado já traz.
 * Era a burocracia entre "colou" e "já era".
 *
 * A PRIMEIRA LINHA-TÍTULO COSTUMA SER O NOME DO DOCUMENTO
 *
 * Não é acaso: o título de abertura ("ENTREVISTA EMPREGADO PÚBLICO") não tem
 * perguntas embaixo, então `montarRoteiroColado` o descarta como seção e o
 * recolhe em `sobra`. Ele não vira bloco justamente por ser o nome do todo — é
 * o melhor candidato disponível, e sai preenchido no campo, à vista e editável,
 * em vez de escondido. */
export function nomeSugerido(texto: string): string {
  let primeira = "";
  for (const bruta of texto.split(/\r?\n/)) {
    const { texto: linha, marcada } = limpar(bruta);
    if (!linha) continue;
    if (!marcada && ehTitulo(linha)) return linha.replace(/:$/, "").trim().slice(0, 80);
    if (!primeira) primeira = linha;
  }
  // Sem título em MAIÚSCULAS: a primeira linha serve, e nomear pela data é
  // melhor que barrar quem acabou de colar um roteiro válido.
  return (primeira || `Roteiro colado em ${new Date().toLocaleDateString("pt-BR")}`).slice(0, 80);
}

export function montarRoteiroColado(texto: string, base: RoteiroCompleto): RoteiroCompleto {
  const saudacao: string[] = [];
  const encerramento: string[] = [];
  const blocos: Bloco[] = [];
  let modo: "saudacao" | "bloco" | "encerramento" = "saudacao";
  let atual: Bloco | null = null;
  let instrucaoPendente = "";

  for (const bruta of texto.split(/\r?\n/)) {
    const { texto: linha, marcada } = limpar(bruta);
    if (!linha) continue;
    if (/^encerramento\b/i.test(linha) && !marcada) {
      modo = "encerramento";
      atual = null;
      continue;
    }
    if (!marcada && ehTitulo(linha)) {
      modo = "bloco";
      atual = {
        id: "",
        titulo: linha.replace(/:$/, "").trim(),
        perguntas: [],
        modulo: null,
        objetivo: "",
        abertura: "",
        instrucao: instrucaoPendente,
        delegado_a: "",
      };
      instrucaoPendente = "";
      blocos.push(atual);
      continue;
    }
    if (modo === "saudacao") {
      acrescentarParagrafo(saudacao, linha);
      continue;
    }
    if (modo === "encerramento") {
      if (ehInstrucao(linha) && !/^\((aguardar|se o cliente)/i.test(linha)) {
        instrucaoPendente = juntar(instrucaoPendente, linha);
      } else {
        acrescentarParagrafo(encerramento, linha);
      }
      continue;
    }
    if (!atual) continue;
    if (marcada || linha.endsWith("?")) {
      atual.perguntas.push(perguntaColada(linha));
    } else if (ehInstrucao(linha) || linha.split(/\s+/).length <= 3) {
      atual.instrucao = juntar(atual.instrucao, linha);
    } else if (linha.length > 220) {
      atual.abertura = juntar(atual.abertura, linha);
    } else if (linha.length <= 130 && !/[:+]/.test(linha)) {
      atual.perguntas.push(perguntaColada(linha));
    } else {
      atual.instrucao = juntar(atual.instrucao, linha);
    }
  }

  const finais: Bloco[] = [];
  let sobra = instrucaoPendente;
  for (const bloco of blocos) {
    if (bloco.perguntas.length === 0) {
      sobra = juntar(sobra, [bloco.titulo, bloco.abertura, bloco.instrucao].filter(Boolean).join("\n"));
      continue;
    }
    if (sobra) {
      bloco.instrucao = juntar(sobra, bloco.instrucao);
      sobra = "";
    }
    finais.push(bloco);
  }
  if (sobra && finais.length > 0) {
    const ultimo = finais[finais.length - 1];
    ultimo.instrucao = juntar(ultimo.instrucao, sobra);
  }

  return {
    ...base,
    saudacao,
    encerramento,
    blocos: [...base.blocos.filter((b) => b.id === "abertura"), ...finais],
  };
}

export function roteiroComoTexto(roteiro: RoteiroCompleto): string {
  const partes: string[] = [...roteiro.saudacao];
  for (const bloco of roteiro.blocos) {
    if (bloco.id === "abertura") continue;
    partes.push("", (bloco.titulo || "SEÇÃO").toUpperCase(), "");
    if (bloco.abertura) partes.push(...bloco.abertura.split("\n"));
    for (const linha of (bloco.instrucao || "").split("\n").filter(Boolean)) {
      partes.push(linha.startsWith("(") ? linha : `(${linha})`);
    }
    for (const pergunta of bloco.perguntas) partes.push(`- ${pergunta.texto}`);
  }
  if (roteiro.encerramento.length > 0) partes.push("", "ENCERRAMENTO", "", ...roteiro.encerramento);
  return partes.join("\n").trim();
}
