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
