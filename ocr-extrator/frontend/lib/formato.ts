/** Helpers de apresentação compartilhados pelos componentes. */

/** Verde acima de 75, âmbar acima de 50, vermelho abaixo disso. */
export function corDoScore(score: number): string {
  if (score >= 75) return "var(--ok)";
  if (score >= 50) return "var(--warn)";
  return "var(--err)";
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

export const ESTILO_VEREDITO = {
  APROVADO: { classe: "ok", icone: "✓" },
  APROVADO_COM_RESSALVAS: { classe: "warn", icone: "!" },
  REPROVADO: { classe: "err", icone: "✕" },
} as const;
