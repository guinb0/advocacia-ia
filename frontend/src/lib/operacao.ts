import { CREDENCIAIS, cabecalhos, urlApi } from "./api";

export type OrdemEquipe =
  | "colaborador"
  | "atividade"
  | "entrevistas"
  | "google"
  | "roteiro"
  | "ligacoes"
  | "revisoes"
  | "revisoes_abertas"
  | "peticoes"
  | "falhas_peticao";

export type DirecaoOrdem = "asc" | "desc";

export interface AtividadeOperacional {
  tipo: string;
  cliente: string;
  iniciado_em: string | null;
  ultima_batida_em: string | null;
}

export interface ColaboradorOperacional {
  id: string;
  nome: string;
  ligacoes: number;
  entrevistas: number;
  google_confirmado: number;
  google_sem_registro: number;
  auditorias: number;
  roteiro_cobertas: number;
  roteiro_total: number;
  roteiro_incertas: number;
  obrigatorias_ausentes: number;
  roteiro_percentual: number | null;
  entrevistas_nao_auditadas: number;
  revisoes: number;
  revisoes_abertas: number;
  peticoes_solicitadas: number;
  peticoes_concluidas: number;
  peticoes_falhas: number;
  atividades: AtividadeOperacional[];
  em_atividade: boolean;
}

export interface PainelOperacao {
  periodo: { de: string; ate: string; dias: number };
  atividade: { janela_minutos: number };
  colaboradores: ColaboradorOperacional[];
  paginacao: {
    busca: string;
    pagina: number;
    tamanho: number;
    paginas: number;
    total: number;
    ordem: OrdemEquipe;
    direcao: DirecaoOrdem;
  };
  alertas: {
    sem_movimentacao_hoje: AlertaMovimentacao;
    sem_movimentacao_7_dias: AlertaMovimentacao;
  };
  ranking_ligacoes: Array<{
    id: string;
    nome: string;
    ligacoes: number;
    posicao: number;
  }>;
  resumo: {
    colaboradores: number;
    em_atividade: number;
    ligacoes: number;
    entrevistas: number;
    google_confirmado: number;
    auditorias: number;
    revisoes: number;
    peticoes_solicitadas: number;
    maior_volume: string[];
    menor_volume: string[];
  };
  aviso: string;
  gerado_em: string;
}

export interface AlertaMovimentacao {
  total: number;
  pagina: number;
  tamanho: number;
  paginas: number;
  colaboradores: Array<{
    id: string;
    nome: string;
    ultima_movimentacao: string | null;
  }>;
}

export async function buscarAlertasMovimentacao(
  periodo: "hoje" | "7-dias",
  pagina = 1,
  tamanho = 20,
): Promise<AlertaMovimentacao> {
  const parametros = new URLSearchParams({
    pagina: String(pagina),
    tamanho: String(tamanho),
  });
  const resposta = await fetch(
    urlApi(`/api/operacao/alertas/${periodo}?${parametros}`),
    {
      headers: cabecalhos(),
      credentials: CREDENCIAIS,
    },
  );
  const corpo = await resposta.json().catch(() => null);
  if (!resposta.ok) {
    const detalhe =
      corpo && typeof corpo === "object" && "detail" in corpo
        ? String((corpo as { detail: unknown }).detail)
        : `Erro ${resposta.status}`;
    throw new Error(detalhe);
  }
  return corpo as AlertaMovimentacao;
}

export async function buscarOperacao({
  busca = "",
  pagina = 1,
  tamanho = 8,
  ordem = "entrevistas",
  direcao = "desc",
}: {
  busca?: string;
  pagina?: number;
  tamanho?: number;
  ordem?: OrdemEquipe;
  direcao?: DirecaoOrdem;
} = {}): Promise<PainelOperacao> {
  const parametros = new URLSearchParams({
    busca,
    pagina: String(pagina),
    tamanho: String(tamanho),
    ordem,
    direcao,
  });
  const resposta = await fetch(urlApi(`/api/operacao?${parametros}`), {
    headers: cabecalhos(),
    credentials: CREDENCIAIS,
  });
  const corpo = await resposta.json().catch(() => null);
  if (!resposta.ok) {
    const detalhe =
      corpo && typeof corpo === "object" && "detail" in corpo
        ? String((corpo as { detail: unknown }).detail)
        : `Erro ${resposta.status}`;
    throw new Error(detalhe);
  }
  return corpo as PainelOperacao;
}
