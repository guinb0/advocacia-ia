/** Helpers de apresentação compartilhados pelos componentes. */

/** Verde acima de 75, âmbar acima de 50, vermelho abaixo disso. */
export function corDoScore(score: number): string {
  if (score >= 75) return "var(--ok)";
  // O âmbar de texto é fechado demais para preencher barra; a variante -marca
  // é a que se vê num traço de 6px e ainda passa dos 3:1 exigidos.
  if (score >= 50) return "var(--atencao-marca)";
  return "var(--critico)";
}

/** Palavra + símbolo do score, para que a barra não informe só pela cor. */
export function leituraDoScore(score: number): { texto: string; simbolo: string } {
  if (score >= 75) return { texto: "bom", simbolo: "✓" };
  if (score >= 50) return { texto: "regular", simbolo: "!" };
  return { texto: "ruim", simbolo: "✕" };
}

export function porcentagem(fracao: number | null | undefined): string {
  if (fracao === null || fracao === undefined) return "—";
  return `${Math.round(fracao * 100)}%`;
}

export function tamanhoLegivel(bytes: number): string {
  return `${(bytes / 1024 / 1024).toFixed(2)} MB`;
}

/** "data_nascimento" -> "data nascimento" */
export function semUnderscore(texto: string): string {
  return texto.replace(/_/g, " ");
}

/* Veredito da validação. `tom` é o tom do <Aviso> (ver components/ui/Basicos)
 * e `rotulo` é a leitura em português corrente: "APROVADO_COM_RESSALVAS" com o
 * underscore trocado por espaço não era uma frase que alguém de fora leria
 * sem tropeçar. */
export const ESTILO_VEREDITO = {
  APROVADO: {
    tom: "ok",
    icone: "✓",
    rotulo: "Documento aprovado",
  },
  APROVADO_COM_RESSALVAS: {
    tom: "atencao",
    icone: "!",
    rotulo: "Aprovado, mas confira",
  },
  REPROVADO: {
    tom: "critico",
    icone: "✕",
    rotulo: "Documento reprovado",
  },
} as const satisfies Record<string, { tom: TomSelo; icone: string; rotulo: string }>;

/** Tom do selo de estado, no vocabulário dos primitivos globais. */
export const SELO_TOM = {
  ok: "selo--ok",
  atencao: "selo--atencao",
  critico: "selo--critico",
  info: "selo--info",
  neutro: "selo--neutro",
} as const;

export type TomSelo = keyof typeof SELO_TOM;
