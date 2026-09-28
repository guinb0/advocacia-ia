/** Modelo visual da petição e skill de petição. */

import { buscar, comoJson } from "./base";

export interface AtributosModeloVisual {
  tamanho_fonte_pt?: number;
  espacamento_linha?: number;
  alinhamento?: string;
  margens_cm?: { top?: number | null; right?: number | null; bottom?: number | null; left?: number | null };
  tabelas?: { quantidade: number; colunas_detectadas: number[] };
}

export interface ModeloVisualPeticao {
  arquivo: string;
  origem: "banco" | "embutido";
  fonte: string;
  enviado_por?: string;
  atualizado_em?: string;
  /** O que o sistema captou do padrão do .docx além da logo e da fonte. */
  atributos?: AtributosModeloVisual;
}

export interface ConfiguracaoVisualPeticao {
  fonte: string;
  tamanho_fonte_pt: number;
  espacamento_linha: number;
  recuo_primeira_linha_cm: number;
  margem_superior_cm: number;
  margem_direita_cm: number;
  margem_inferior_cm: number;
  margem_esquerda_cm: number;
  alinhamento_corpo: "justificado" | "esquerda" | "direita";
  alinhamento_titulos: "esquerda" | "centralizado";
  altura_logo_cm: number;
  preferir_tabelas: boolean;
}

export interface EstatisticasAcervoConteudistico {
  simples: number;
  complexas: number;
  trechos: number;
  corrompidas: number;
}

export async function estatisticasAcervoConteudistico(): Promise<EstatisticasAcervoConteudistico> {
  return comoJson(await buscar("/api/modelos/peticao/acervo-conteudistico"));
}

export async function obterModeloVisualPeticao(): Promise<ModeloVisualPeticao> {
  return comoJson(await buscar("/api/modelos/peticao/visual"));
}

export async function obterConfiguracaoVisualPeticao(): Promise<ConfiguracaoVisualPeticao> {
  return comoJson(await buscar("/api/modelos/peticao/visual/configuracao"));
}

export async function salvarConfiguracaoVisualPeticao(
  dados: ConfiguracaoVisualPeticao,
): Promise<ConfiguracaoVisualPeticao> {
  return comoJson(await buscar("/api/modelos/peticao/visual/configuracao", {
    method: "PUT", body: JSON.stringify(dados),
  }));
}

export async function enviarLogoModeloVisualPeticao(arquivo: File): Promise<{ arquivo: string }> {
  const form = new FormData();
  form.append("arquivo", arquivo);
  return comoJson(await buscar("/api/modelos/peticao/visual/logo", { method: "POST", body: form }));
}

export async function enviarModeloVisualPeticao(
  arquivo: File,
): Promise<ModeloVisualPeticao> {
  const form = new FormData();
  form.append("arquivo", arquivo);
  return comoJson(await buscar("/api/modelos/peticao/visual", { method: "POST", body: form }));
}

export async function restaurarModeloVisualPeticao(): Promise<ModeloVisualPeticao> {
  return comoJson(await buscar("/api/modelos/peticao/visual", { method: "DELETE" }));
}

/** A orientação de redação do escritório — UMA, para toda peça.
 *
 * Era uma por categoria de ação (`/skills/{categoria}`). Virou única porque o
 * que o escritório ensina sobre como redigir não muda com o tipo da ação, e
 * manter cinco cópias significava reescrever a mesma instrução cinco vezes. Não
 * depende do agente jurídico (`ia-juridica`) estar ativo. */
export interface SkillDePeticao {
  instrucoes: string;
  atualizado_por?: string;
  atualizado_em?: string;
}

export async function obterSkillDePeticao(): Promise<SkillDePeticao> {
  return comoJson(await buscar("/api/modelos/peticao/skill"));
}

export async function salvarSkillDePeticao(instrucoes: string): Promise<SkillDePeticao> {
  return comoJson(
    await buscar("/api/modelos/peticao/skill", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ instrucoes }),
    }),
  );
}
