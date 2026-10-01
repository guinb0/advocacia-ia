/** Supervisão de entrevistas. */

import { buscar, comoJson } from "./base";

// ------------------------------------------------- supervisão (secretário)

export interface EntrevistaResumo {
  id: string;
  caso_id: string | null;
  /** Nome do cliente do caso. Data sozinha não diz qual atendimento é qual. */
  cliente: string;
  arquivo: string | null;
  realizada_em: string | null;
  criado_em: string | null;
  caracteres: number;
  fatos_gerados: number | null;
  /** Os dois sinais que a lista dá sem ida ao modelo (ver `app/supervisao.py`). */
  avaliacao_google: boolean;
  enviada: boolean;
  /** Vazio = anexada como arquivo; preenchida = conduzida ao vivo, e tem áudio. */
  gravacao_id: string;
}

export interface PessoaSupervisao {
  entrevistador: string;
  quantidade: number;
  entrevistas: EntrevistaResumo[];
  /* O resumo de cada um vem calculado do servidor — a tela ordena e desenha barra
   * a partir dele, e refazer a conta no navegador a espalharia por dois lugares. */
  com_avaliacao: number;
  com_dossie: number;
  ao_vivo: number;
  /** dd/mm/aaaa, já normalizada: `realizada_em` é texto livre e tem dois formatos. */
  ultima_em: string;
}

export interface EntrevistasSupervisaoPaginadas {
  entrevistador: string;
  itens: EntrevistaResumo[];
  total: number;
  pagina: number;
  tamanho: number;
  paginas: number;
}

/** O que o escritório deve, em número. Pendências, não acertos — ver `app/supervisao.py`. */
export interface PendenciasSupervisao {
  sem_avaliacao: number;
  sem_dossie: number;
  sem_quem_conduziu: number;
  ao_vivo: number;
  anexadas: number;
}

export interface PerguntaAuditada {
  id: string;
  texto: string;
  bloco: string;
  obrigatoria: boolean;
}

/** As partes que a atendente LÊ em voz alta, e não são perguntas. */
export interface ParteLida {
  situacao: "feita" | "parcial" | "ausente" | "incerta";
  faltou: string[];
}

export interface Auditoria {
  entrevista_id: string;
  abertura: ParteLida;
  encerramento: ParteLida;
  entrevistador: string;
  roteiro: string;
  total_perguntas: number;
  total_obrigatorias: number;
  resumo: string;
  cobertas: PerguntaAuditada[];
  nao_cobertas: PerguntaAuditada[];
  incertas: PerguntaAuditada[];
  faltando_obrigatorias: PerguntaAuditada[];
  observacoes: { item: string; porque: string }[];
  pontos_fortes: string[];
  transcricao_truncada: boolean;
  aviso: string;
}

export async function listarSupervisao(): Promise<{
  itens: PessoaSupervisao[];
  total_entrevistas: number;
  total_pessoas: number;
  sem_atribuicao: number;
  pendencias: PendenciasSupervisao;
  entrevistas: EntrevistasSupervisaoPaginadas;
}> {
  return comoJson(await buscar("/api/supervisao/entrevistas"));
}

export async function listarSupervisaoPaginada({
  entrevistador,
  pagina = 1,
  tamanho = 8,
}: {
  entrevistador?: string | null;
  pagina?: number;
  tamanho?: number;
} = {}): Promise<{
  itens: PessoaSupervisao[];
  total_entrevistas: number;
  total_pessoas: number;
  sem_atribuicao: number;
  pendencias: PendenciasSupervisao;
  entrevistas: EntrevistasSupervisaoPaginadas;
}> {
  const paginaSegura = Number.isFinite(pagina) ? Math.max(1, Math.floor(pagina)) : 1;
  const tamanhoSeguro = Number.isFinite(tamanho) ? Math.min(Math.max(1, Math.floor(tamanho)), 30) : 8;
  const params = new URLSearchParams({
    pagina: String(paginaSegura),
    tamanho: String(tamanhoSeguro),
  });
  if (entrevistador) params.set("entrevistador", entrevistador);

  const dados = await comoJson<{
    itens?: PessoaSupervisao[];
    total_entrevistas?: number;
    total_pessoas?: number;
    sem_atribuicao?: number;
    pendencias?: PendenciasSupervisao;
    entrevistas?: Partial<EntrevistasSupervisaoPaginadas>;
  }>(await buscar(`/api/supervisao/entrevistas?${params.toString()}`));

  const entrevistas = dados.entrevistas ?? {};
  const itens = Array.isArray(dados.itens) ? dados.itens : [];
  const lista = Array.isArray(entrevistas.itens) ? entrevistas.itens : [];
  const total = Number.isFinite(entrevistas.total) ? Math.max(0, Math.floor(entrevistas.total ?? 0)) : lista.length;
  const tamanhoReal = Number.isFinite(entrevistas.tamanho)
    ? Math.max(1, Math.floor(entrevistas.tamanho ?? tamanhoSeguro))
    : tamanhoSeguro;
  const paginas = Number.isFinite(entrevistas.paginas)
    ? Math.max(1, Math.floor(entrevistas.paginas ?? 1))
    : Math.max(1, Math.ceil(total / tamanhoReal));
  const paginaReal = Number.isFinite(entrevistas.pagina)
    ? Math.min(Math.max(1, Math.floor(entrevistas.pagina ?? paginaSegura)), paginas)
    : Math.min(paginaSegura, paginas);

  return {
    itens,
    total_entrevistas: dados.total_entrevistas ?? 0,
    total_pessoas: dados.total_pessoas ?? 0,
    sem_atribuicao: dados.sem_atribuicao ?? 0,
    pendencias: dados.pendencias ?? {
      sem_avaliacao: 0,
      sem_dossie: 0,
      sem_quem_conduziu: 0,
      ao_vivo: 0,
      anexadas: 0,
    },
    entrevistas: {
      entrevistador: entrevistas.entrevistador ?? entrevistador ?? "",
      itens: lista,
      total,
      pagina: paginaReal,
      tamanho: tamanhoReal,
      paginas,
    },
  };
}

export async function obterTranscricao(id: string): Promise<{
  id: string;
  entrevistador: string;
  realizada_em: string | null;
  texto: string;
  resumo: string;
}> {
  return comoJson(await buscar(`/api/supervisao/entrevistas/${encodeURIComponent(id)}`));
}

/** POST, e não GET: cada chamada custa uma ida ao modelo. */
export async function auditarEntrevista(id: string): Promise<Auditoria> {
  return comoJson(
    await buscar(`/api/supervisao/entrevistas/${encodeURIComponent(id)}/auditoria`, {
      method: "POST",
    }),
  );
}
