/** Análise documental do caso, insights e jurimetria. */

import { buscar, comoJson } from "./base";

// ----------------------------------------------------------------- chamada

/** Estado humano sobre um achado/evento — ver `case_brief_estado` no backend. */
export type EstadoInsight = "DETECTED" | "CONFIRMED" | "CORRECTED" | "REJECTED" | "NEEDS_CONFIRMATION";

export interface AchadoDocumento {
  informacao: string;
  documento: string;
  entrega_id: string;
  /** Trecho LITERAL do documento. Conferido no servidor contra o texto lido —
   *  achado cuja citação não existe no documento apontado não chega até aqui. */
  citacao: string;
  relevancia: string;
  /** De quem é a informação: o cliente (titular), a empregadora (empresa), um
   *  terceiro (médico, perito, testemunha…) ou indefinido quando não dá para
   *  saber. Fechado no servidor; valor estranho vira "indefinido". */
  parte?: "titular" | "terceiro" | "empresa" | "indefinido";
  /** O envolvimento dessa pessoa no caso, em texto livre curto. */
  papel?: string;
  /** O documento contradiz o que a entrevista registrou. */
  contradiz: boolean;
  /** Id estável (`fato-N`) usado para confirmar/corrigir/rejeitar este achado
   *  — o mesmo id que o case brief usa na geração da peça. */
  fato_id?: string;
  /** Presente só quando o advogado já reagiu a este achado. Sem o campo, o
   *  estado é implicitamente DETECTED (a IA achou, ninguém revisou ainda). */
  estado?: EstadoInsight;
}

/** Um gasto comprovado num documento (nota, recibo, comprovante). A lista vem
 *  do servidor JÁ em ordem cronológica e com a citação conferida. */
export interface GastoDocumento {
  valor: string;
  /** Data do gasto (DD/MM/AAAA); pode vir vazia quando o documento não a traz. */
  data: string;
  descricao: string;
  documento: string;
  entrega_id: string;
  citacao: string;
}

export interface AnaliseDocumentos {
  achados: AchadoDocumento[];
  cronologia?: Array<{
    data: string; evento: string; documento: string; entrega_id: string; citacao: string;
    fato_id?: string; estado?: EstadoInsight;
  }>;
  /** Gastos dos documentos, em ordem cronológica, ligados ao arquivo de origem. */
  gastos?: GastoDocumento[];
  documentos_lidos: number;
  /** Veio do que já estava guardado: os mesmos textos não são lidos de novo. */
  reaproveitada?: boolean;
  /** Contradição entre dois documentos, com as duas citações conferidas. */
  contradicoes?: Array<{
    titulo: string;
    o_que_diverge: string;
    fontes: Array<{ documento: string; citacao: string; valor: string }>;
  }>;
  /** Leitura do caso a partir do que a conferência deixou passar. */
  diagnostico?: { sentido: "POSITIVO" | "NEGATIVO"; motivo: string };
  /** Quantos achados o servidor recusou por citação não conferida. Aparece na
   *  tela de propósito: silenciar esconderia um modelo alucinando com
   *  frequência, que é o que precisa aparecer. */
  recusados?: number;
  aviso?: string;
}

/** O que os anexos dizem e a entrevista não registrou. Sob demanda. */
export async function analisarDocumentosDoCaso(casoId: string): Promise<AnaliseDocumentos> {
  return comoJson(
    await buscar(`/api/casos/${encodeURIComponent(casoId)}/analise-documentos`, { method: "POST" }),
  );
}

/** Confirma, corrige ou rejeita um achado/evento — vale a partir daqui para
 *  toda geração seguinte deste caso (ver `case_brief_estado` no backend). */
export async function definirEstadoInsight(
  casoId: string,
  fatoId: string,
  estado: EstadoInsight,
  opcoes?: { valorCorrigido?: string; observacao?: string },
): Promise<{ estado: EstadoInsight }> {
  return comoJson(
    await buscar(`/api/casos/${encodeURIComponent(casoId)}/insights/${encodeURIComponent(fatoId)}/estado`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        estado,
        valor_corrigido: opcoes?.valorCorrigido ?? "",
        observacao: opcoes?.observacao ?? "",
      }),
    }),
  );
}

export interface JurimetriaCaso {
  disponivel: boolean;
  aviso: string;
  /** De onde vieram os números: "TRT8", "TRT2 + TRT15", "acervo nacional"… */
  jurisdicao?: string;
  sinais: { categoria: string; tem_entrevista: boolean; achados: string[]; uf?: string; uf_automatica?: boolean };
  precedentes: {
    processo: string | null;
    /** O número com a pontuação do CNJ, para o advogado conferir e buscar. */
    processo_formatado?: string | null;
    /** "TRT8" — o link do processo diz para onde vai antes do clique. */
    tribunal?: string | null;
    resultado: string;
    vara: string;
    tipo_documento?: string | null;
    similaridade: number | null;
    url?: string | null;
    trecho: string;
  }[];
  estatisticas: {
    processos_analisados: number;
    resultados: { nome: string; quantidade: number; percentual: number }[];
    varas: { nome: string; quantidade: number; percentual: number }[];
    desfechos_favoraveis_amplos: { quantidade: number; percentual: number; criterio: string };
    desfechos_merito: { processos: number; favoraveis: number; percentual: number; criterio: string };
    similaridade_amostra: { maxima: number; mediana: number; minima: number };
    aviso: string;
  } | null;
}

/** Cruza os fatos do caso (entrevista + achados do OCR) com o acervo de decisões:
 *  precedentes semelhantes e a distribuição de desfechos por vara. Descritivo.
 *  `uf` foca no TRT do estado (com fallback para a região e o país). */
export async function jurimetriaDoCaso(casoId: string, uf = ""): Promise<JurimetriaCaso> {
  const q = uf ? `?uf=${encodeURIComponent(uf)}` : "";
  return comoJson(await buscar(`/api/casos/${encodeURIComponent(casoId)}/jurimetria${q}`));
}

/* ------------------------------------------------------------ análise documental (skill documental) */

export interface ProvenienciaDocumental {
  documento_id: string; arquivo: string; pagina: number | null; tipo_documento: string; citacao: string;
}

export type EstadoDocumental = "DETECTED" | "CONFIRMED" | "CORRECTED" | "REJECTED" | "NEEDS_CONFIRMATION";

export interface FonteDeInconsistencia {
  documento_id: string; arquivo?: string; origem?: string; citacao: string; valor: string; pagina?: number | null;
}

export interface AnaliseDocumental {
  id?: string;
  status: "none" | "queued" | "processing" | "analyzing" | "ready" | "error";
  erro?: string;
  skill_name?: string;
  skill_sha256?: string;
  modelo?: string;
  versao?: number;
  iniciada_em?: string;
  resultado?: {
    compacta?: boolean;
    diagnostico?: { sentido: "POSITIVO" | "NEGATIVO"; motivo: string };
    resumo_do_caso: { questao_central: string; objetivo_do_cliente: string; fatos_cronologicos: Array<{ data: string; fato: string; documento_id: string }> };
    documentos: Array<{
      documento_id: string; arquivo: string; tipo: string; nome_sugerido: string; data: string; paginas: number | null;
      pontos_fortes: string[]; vulnerabilidades: string[]; atualizacao: string; pode_melhorar: boolean | null;
      motivo_atualizacao: string; legivel: boolean; problema: string; duplicado_de: string;
      relacao_com_teses: Array<{ hipotese?: string; papel?: string }>;
    }>;
    fatos_extraidos: Array<{ id: string; fato: string; confianca: string; estado?: EstadoDocumental; proveniencia: ProvenienciaDocumental }>;
    inconsistencias: Array<{ id: string; titulo: string; tipo: string; impacto: string; acao_sugerida: string; estado?: EstadoDocumental; fontes: FonteDeInconsistencia[] }>;
    provas: Array<{ id: string; fato: string; status: string; documento_ids: string[]; observacao: string }>;
    documentos_faltantes: Array<{ id: string; documento: string; hipotese: string; classificacao: "COMPROMETE" | "ERA_MELHOR_TER" | "NAO_INTERFERE"; como_obter: string; responsavel: string; prazo_ou_dificuldade: string; estado?: EstadoDocumental }>;
    hipoteses_juridicas: Array<{ id: string; hipotese: string; objeto?: string; fundamento_legal?: string; fundamento_verificado: boolean; probabilidade_pratica?: string }>;
    perguntas: Array<{ id: string; pergunta: string; motivo: string; resposta?: string }>;
    proximos_passos: string[];
    descartados: Record<string, number>;
  };
}

export interface PlanoDeOrganizacao {
  status: "none" | "aguardando_confirmacao" | "confirmada" | "concluida" | "erro";
  plano?: { resumo: {
    documentos: Array<{ documento_id: string; arquivo_original: string; nome_final: string; duplicado: boolean }>;
    duplicados: Array<{ nome_final: string }>; problemas: Array<{ arquivo: string; problema: string }>;
    nao_identificados: string[]; arquivos_extras: string[]; exclusoes: string;
  } };
  resultado?: { pasta?: string; originais_preservados?: boolean } | null;
}

const caminhoCaso = (casoId: string) => `/api/casos/${encodeURIComponent(casoId)}`;

export async function iniciarAnaliseDocumental(casoId: string): Promise<AnaliseDocumental> {
  return comoJson(await buscar(`${caminhoCaso(casoId)}/analise-documental`, { method: "POST" }));
}

export async function obterAnaliseDocumental(casoId: string): Promise<AnaliseDocumental> {
  return comoJson(await buscar(`${caminhoCaso(casoId)}/analise-documental`));
}

export async function responderPerguntaDocumental(casoId: string, perguntaId: string, resposta: string): Promise<void> {
  await comoJson(await buscar(`${caminhoCaso(casoId)}/analise-documental/perguntas/${encodeURIComponent(perguntaId)}/resposta`, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ resposta }),
  }));
}

export async function continuarParaAPeca(casoId: string): Promise<{ proximo: string; perguntas_sem_resposta: number; contexto_da_peca: boolean }> {
  return comoJson(await buscar(`${caminhoCaso(casoId)}/analise-documental/continuar`, { method: "POST" }));
}

export async function planoDeOrganizacao(casoId: string): Promise<PlanoDeOrganizacao> {
  return comoJson(await buscar(`${caminhoCaso(casoId)}/organizacao/plano`, { method: "POST" }));
}

export async function confirmarOrganizacao(casoId: string): Promise<PlanoDeOrganizacao> {
  return comoJson(await buscar(`${caminhoCaso(casoId)}/organizacao/confirmar`, { method: "POST" }));
}
