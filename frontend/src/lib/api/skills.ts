/** Skills jurídicas e módulos de skill. */

import { buscar, comoJson } from "./base";

export type SkillJuridica = {
  id: string;
  nome: string;
  descricao: string;
  referencias: number;
};

export async function listarSkillsJuridicas(): Promise<SkillJuridica[]> {
  return comoJson(await buscar("/api/skills-juridicas"));
}

/** Importa uma skill de redação para que ela possa ser escolhida no próximo caso. */
export async function importarSkillJuridica(arquivo: File): Promise<{ id: string }> {
  const form = new FormData();
  form.append("arquivo", arquivo);
  return comoJson(await buscar("/api/skills-juridicas/importar", { method: "POST", body: form }));
}

export type SkillModulo = {
  id: string;
  nome: string;
  descricao: string;
  origem: "arquivo" | "importada";
};

export type SkillModuloDetalhe = SkillModulo & { texto: string; cortado: boolean };

export async function listarModulosDeSkill(): Promise<SkillModulo[]> {
  return comoJson(await buscar("/api/skills-modulos"));
}

export async function obterModuloDeSkill(skillId: string): Promise<SkillModuloDetalhe> {
  return comoJson(await buscar(`/api/skills-modulos/${encodeURIComponent(skillId)}`));
}

export async function criarSkill(pedido: { nome: string; descricao: string; texto: string }): Promise<{ id: string }> {
  return comoJson(await buscar("/api/skills-juridicas", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(pedido),
  }));
}
