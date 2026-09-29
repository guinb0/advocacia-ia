/** Skills jurídicas e módulos de skill. */

import { ApiError, buscar, comoJson, nomeDoAnexo } from "./base";

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

/** O que a skill de petição cobre, lido pelos mesmos leitores da geração. */
export type VerificacaoSkillPeticao = {
  ok: boolean;
  problemas: string[];
  avisos: string[];
  layout: {
    fonte: string;
    tamanho_pt: number;
    espacamento_linha: number;
    /** superior, direita, inferior, esquerda */
    margens_cm: [number, number, number, number];
    elementos: string[];
  };
  blocos: string[];
  assuntos: number;
  validacoes: number;
  arquivos: number;
};

export type EstadoSkillPeticao = {
  ativa: {
    id: string;
    nome: string;
    do_sistema: boolean;
    /** Caminho da imagem da skill usada no cabeçalho; vazio quando a skill não traz logo. */
    logo: string;
    ativada_por: string;
    ativada_em: string;
    verificacao: VerificacaoSkillPeticao;
  };
  disponiveis: { id: string; nome: string; atualizado_em: string }[];
};

export async function obterSkillPeticao(): Promise<EstadoSkillPeticao> {
  return comoJson(await buscar("/api/skill-peticao"));
}

/** Envia uma skill de petição; se ela cobrir a peça inteira, passa a valer na próxima geração. */
export async function enviarSkillPeticao(arquivo: File): Promise<EstadoSkillPeticao> {
  const form = new FormData();
  form.append("arquivo", arquivo);
  return comoJson(await buscar("/api/skill-peticao", { method: "POST", body: form }));
}

/** Troca a skill que gera a petição. `""` volta para a skill do sistema. */
export async function ativarSkillPeticao(skillId: string): Promise<EstadoSkillPeticao> {
  return comoJson(await buscar("/api/skill-peticao/ativa", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ skill_id: skillId }),
  }));
}

export type ArquivosSkillPeticao = {
  skill_id: string;
  nome: string;
  do_sistema: boolean;
  /** `SKILL.md` e os caminhos dentro de `references/`; sempre inclui `observacoes.md`. */
  arquivos: { caminho: string; texto: string }[];
};

/** Os arquivos de texto da skill. Sem `skillId`, os da skill do escritório. */
export async function obterArquivosSkillPeticao(skillId = ""): Promise<ArquivosSkillPeticao> {
  return comoJson(await buscar(`/api/skill-peticao/arquivos?skill_id=${encodeURIComponent(skillId)}`));
}

/**
 * Grava um arquivo da skill. O sistema confere a skill inteira antes e recusa se
 * a alteração quebrar o layout ou a estrutura. `textoLido` é o arquivo como estava
 * quando foi aberto: se outra pessoa o alterou desde então, nada é gravado (erro 409).
 * Editar a skill do sistema grava uma cópia editável, que passa a ser a do escritório.
 */
export async function salvarArquivoSkillPeticao(
  skillId: string,
  caminho: string,
  texto: string,
  textoLido: string,
): Promise<EstadoSkillPeticao> {
  return comoJson(await buscar("/api/skill-peticao/arquivo", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ skill_id: skillId, caminho, texto, texto_lido: textoLido }),
  }));
}

export type VersaoSkillPeticao = { id: number; motivo: string; gravado_por: string; gravado_em: string };

export type HistoricoSkillPeticao = {
  skill_id: string;
  /** A skill padrão do sistema nunca é alterada, então não tem histórico. */
  do_sistema: boolean;
  /** Da gravação mais nova (a que está valendo) para a mais antiga. */
  versoes: VersaoSkillPeticao[];
};

export async function obterHistoricoSkillPeticao(skillId = ""): Promise<HistoricoSkillPeticao> {
  return comoJson(await buscar(`/api/skill-peticao/versoes?skill_id=${encodeURIComponent(skillId)}`));
}

/** Volta a skill para uma versão anterior; a restauração também entra no histórico. */
export async function restaurarVersaoSkillPeticao(skillId: string, versaoId: number): Promise<EstadoSkillPeticao> {
  return comoJson(await buscar(`/api/skill-peticao/versoes/${versaoId}/restaurar`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ skill_id: skillId }),
  }));
}

export async function baixarSkillPeticao(skillId = ""): Promise<{ arquivo: Blob; nome: string }> {
  const r = await buscar(`/api/skill-peticao/pacote?skill_id=${encodeURIComponent(skillId)}`);
  if (!r.ok) throw new ApiError(r.status === 401 ? "Sessão expirada." : `Não foi possível baixar a skill (erro ${r.status}).`);
  return { arquivo: await r.blob(), nome: nomeDoAnexo(r, "skill-peticao.skill.zip") };
}
