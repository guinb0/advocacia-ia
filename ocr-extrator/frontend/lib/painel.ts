/**
 * Cliente e derivações do painel analítico do caso.
 *
 * O backend (`app/painel.py`) entrega tudo que exige conhecimento do banco: durações
 * medidas, comparação com os casos anteriores da categoria, saúde, insights. Aqui só
 * fica o que depende do **filtro de período** escolhido na tela — movimentações por dia,
 * mapa de atividade e distribuição por tipo —, derivado da mesma lista de eventos que a
 * linha do tempo exibe. Duas fontes para o mesmo número dariam dois números.
 *
 * Nada aqui completa lacuna: função que não tem dado devolve lista vazia, e quem desenha
 * é que decide qual estado vazio mostrar.
 */

import { cabecalhos, urlApi } from "./api";

export type Tom = "ok" | "atencao" | "critico" | "info" | "neutro";

export interface EtapaDoDossie {
  codigo: string;
  titulo: string;
  estado: "pendente" | "andamento" | "pronto" | "atencao" | "indisponivel";
  detalhe: string;
}

export interface Indicador {
  codigo: string;
  rotulo: string;
  valor: number | null;
  unidade: string;
  detalhe: string;
  tom: Tom;
  comparacao: { rotulo: string; valor: number; desvio_percentual: number | null } | null;
}

export interface EventoDoCaso {
  quando: string;
  tipo: "caso" | "documento" | "entrevista" | "contrato" | "agente" | "ocorrencia";
  titulo: string;
  detalhe: string;
  tom: Tom;
}

export interface EtapaMedida {
  codigo: string;
  titulo: string;
  descricao: string;
  inicio: string | null;
  fim: string | null;
  horas: number | null;
  em_curso: boolean;
  iniciada: boolean;
  comparavel: boolean;
}

export interface LinhaComparacao {
  codigo: string;
  titulo: string;
  realizado_horas: number | null;
  /** Mediana da categoria. `null` quando a amostra não sustenta comparação. */
  previsto_horas: number | null;
  amostra: number;
  em_curso: boolean;
  desvio_horas: number | null;
  desvio_percentual: number | null;
  motivo: string | null;
}

export interface ReferenciaHistorica {
  categoria: string;
  amostra: number;
  suficiente: boolean;
  motivo: string | null;
  etapas: Record<
    string,
    {
      mediana_horas: number | null;
      amostra: number;
      minimo_horas: number | null;
      maximo_horas: number | null;
    }
  >;
}

export interface Ocorrencia {
  quando: string | null;
  tipo: string;
  titulo: string;
  detalhe: string;
  gravidade: Tom;
  estado: "aberta" | "resolvida";
  referencia: string;
}

export interface PendenciaDoPlaybook {
  codigo: string;
  rotulo: string;
  tipo: string;
  severidade: "BLOCKING" | "RECOMMENDED";
  estado: string;
  pergunta: string | null;
  exigido_por: { playbook_id?: string; requirement?: string }[];
  satisfeita_em: string | null;
}

export interface FatoDoCaso {
  id: string;
  tipo: string;
  /** Valor tipado, como o agente o guarda: {"date": "..."}, {"amount": 2850}. */
  valor: Record<string, unknown>;
  status: string;
  confianca: number | null;
  relevancia: string | null;
  /** Proveniência já escrita: "ocr_document, página 1, campo cpf". */
  origens: string[];
  tipos_de_origem: string[];
  criado_em: string | null;
  /** `false` para fato rejeitado ou substituído — fica na lista, fora das contagens. */
  vigente: boolean;
}

export interface ComponenteDaSaude {
  codigo: string;
  rotulo: string;
  peso: number;
  valor: number | null;
  /** A fórmula, em português. É o que o tooltip mostra — nota sem fórmula é chute. */
  base: string;
}

export interface Painel {
  caso: {
    id: string;
    cliente: string;
    categoria_codigo: string;
    categoria: string;
    observacao: string;
    aberto_em: string;
    atualizado_em: string;
    portal_ativo: boolean;
    caso_ref_agente: string | null;
  };
  resumo: {
    etapa_atual: EtapaDoDossie | null;
    etapas: EtapaDoDossie[];
    progresso: {
      obrigatorios_total?: number;
      obrigatorios_entregues?: number;
      obrigatorios_pendentes?: number;
      opcionais_total?: number;
      opcionais_entregues?: number;
      itens_a_conferir?: number;
      percentual_obrigatorios?: number;
      pronto?: boolean;
    };
    tempo_em_aberto_horas: number | null;
    ultima_movimentacao: string | null;
    dias_sem_movimentacao: number | null;
    limiar_parado_dias: number;
    responsaveis: {
      nome: string;
      informado: boolean;
      desde: string | null;
      arquivo: string;
      fatos_gerados: number;
      lida: boolean;
    }[];
  };
  indicadores: Indicador[];
  eventos: EventoDoCaso[];
  etapas_medidas: EtapaMedida[];
  distribuicao_do_tempo: {
    codigo: string;
    titulo: string;
    horas: number;
    percentual: number | null;
    em_curso: boolean;
  }[];
  comparacao_historica: { referencia: ReferenciaHistorica; linhas: LinhaComparacao[] };
  ocorrencias: {
    itens: Ocorrencia[];
    abertas: number;
    resolvidas: number;
    por_tipo: { tipo: string; quantidade: number }[];
  };
  pendencias: {
    disponivel: boolean;
    motivo: string | null;
    itens: PendenciaDoPlaybook[];
    abertas: number;
    bloqueantes: number;
  };
  saude: {
    pontuacao: number | null;
    faixa: string;
    tom: Tom;
    componentes: ComponenteDaSaude[];
    peso_medido: number;
    base: string;
  };
  fatos: {
    disponivel: boolean;
    motivo: string | null;
    itens: FatoDoCaso[];
    total: number;
    vigentes: number;
    por_tipo: { tipo: string; quantidade: number }[];
    por_status: { status: string; quantidade: number }[];
    por_origem: { origem: string; quantidade: number }[];
    sem_origem: number;
    apenas_relatados: number;
  };
  radar: { eixo: string; valor: number | null; base: string }[];
  insights: { texto: string; tom: Tom; base: string }[];
  ausencias: { campo: string; motivo: string }[];
  agente: { ligado: boolean; disponivel: boolean; vinculado: boolean; motivo: string | null };
  gerado_em: string;
}

export async function buscarPainel(casoId: string): Promise<Painel> {
  const resposta = await fetch(urlApi(`/api/casos/${casoId}/painel`), {
    headers: cabecalhos(),
  });
  const corpo = await resposta.json().catch(() => null);
  if (!resposta.ok) {
    const detalhe =
      corpo && typeof corpo === "object" && "detail" in corpo
        ? String((corpo as { detail: unknown }).detail)
        : `Erro ${resposta.status}`;
    throw new Error(detalhe);
  }
  return corpo as Painel;
}

// ------------------------------------------------------------------ período

export type Periodo = 7 | 30 | 90 | 0;

export const PERIODOS: { valor: Periodo; rotulo: string }[] = [
  { valor: 7, rotulo: "7 dias" },
  { valor: 30, rotulo: "30 dias" },
  { valor: 90, rotulo: "90 dias" },
  { valor: 0, rotulo: "Todo o caso" },
];

/** Eventos dentro da janela escolhida. Período 0 devolve o caso inteiro. */
export function filtrarPorPeriodo(eventos: EventoDoCaso[], dias: Periodo): EventoDoCaso[] {
  if (!dias) return eventos;
  const corte = Date.now() - dias * 24 * 3600 * 1000;
  return eventos.filter((evento) => new Date(evento.quando).getTime() >= corte);
}

function diaISO(data: Date): string {
  return data.toISOString().slice(0, 10);
}

export interface PontoDoDia {
  dia: string;
  movimentacoes: number;
  documentos: number;
  /** Documentos recebidos até este dia, inclusive — a curva de progresso real. */
  documentosAcumulados: number;
}

/**
 * Uma linha por dia do período, inclusive os dias sem nada.
 *
 * Dia vazio precisa existir na série: sem ele, três documentos em três semanas viram
 * três pontos colados e o gráfico sugere um ritmo que não houve.
 */
export function serieDiaria(
  eventos: EventoDoCaso[],
  dias: Periodo,
  aberturaISO: string,
): PontoDoDia[] {
  if (eventos.length === 0) return [];

  const fim = new Date();
  const primeiro = new Date(
    Math.min(...eventos.map((e) => new Date(e.quando).getTime()), new Date(aberturaISO).getTime()),
  );
  const inicio = dias ? new Date(Date.now() - dias * 24 * 3600 * 1000) : primeiro;
  const comeco = inicio > primeiro ? inicio : primeiro;

  const porDia = new Map<string, { movimentacoes: number; documentos: number }>();
  for (const evento of eventos) {
    const chave = diaISO(new Date(evento.quando));
    const linha = porDia.get(chave) ?? { movimentacoes: 0, documentos: 0 };
    linha.movimentacoes += 1;
    if (evento.tipo === "documento") linha.documentos += 1;
    porDia.set(chave, linha);
  }

  const pontos: PontoDoDia[] = [];
  let acumulado = 0;
  const cursor = new Date(Date.UTC(comeco.getUTCFullYear(), comeco.getUTCMonth(), comeco.getUTCDate()));
  // Teto de segurança: uma data corrompida no banco não pode virar laço infinito.
  for (let passo = 0; passo < 400 && cursor <= fim; passo += 1) {
    const chave = diaISO(cursor);
    const linha = porDia.get(chave) ?? { movimentacoes: 0, documentos: 0 };
    acumulado += linha.documentos;
    pontos.push({ dia: chave, ...linha, documentosAcumulados: acumulado });
    cursor.setUTCDate(cursor.getUTCDate() + 1);
  }
  return pontos;
}

export interface CelulaDoMapa {
  diaDaSemana: number;
  hora: number;
  quantidade: number;
}

/** Mapa de calor de atividade: dia da semana x faixa de 3 horas. */
export function mapaDeAtividade(eventos: EventoDoCaso[]): CelulaDoMapa[] {
  const contagem = new Map<string, number>();
  for (const evento of eventos) {
    const data = new Date(evento.quando);
    const faixa = Math.floor(data.getHours() / 3) * 3;
    const chave = `${data.getDay()}-${faixa}`;
    contagem.set(chave, (contagem.get(chave) ?? 0) + 1);
  }
  const celulas: CelulaDoMapa[] = [];
  for (let dia = 0; dia < 7; dia += 1) {
    for (let hora = 0; hora < 24; hora += 3) {
      celulas.push({
        diaDaSemana: dia,
        hora,
        quantidade: contagem.get(`${dia}-${hora}`) ?? 0,
      });
    }
  }
  return celulas;
}

export function porTipo(eventos: EventoDoCaso[]): { tipo: string; quantidade: number }[] {
  const contagem = new Map<string, number>();
  for (const evento of eventos) {
    contagem.set(evento.tipo, (contagem.get(evento.tipo) ?? 0) + 1);
  }
  return [...contagem.entries()]
    .map(([tipo, quantidade]) => ({ tipo, quantidade }))
    .sort((a, b) => b.quantidade - a.quantidade);
}

// ------------------------------------------------------------------ formato

/** "3 d 4 h" — duração legível a partir de horas decimais. */
export function duracao(horas: number | null | undefined): string {
  if (horas === null || horas === undefined) return "—";
  if (horas < 1) return `${Math.round(horas * 60)} min`;
  if (horas < 48) return `${horas.toFixed(1).replace(/\.0$/, "")} h`;
  const dias = Math.floor(horas / 24);
  const resto = Math.round(horas - dias * 24);
  return resto ? `${dias} d ${resto} h` : `${dias} d`;
}

export function dias(horas: number | null | undefined): string {
  if (horas === null || horas === undefined) return "—";
  return `${(horas / 24).toFixed(1).replace(/\.0$/, "")}`;
}

export function dataHora(iso: string | null | undefined): string {
  if (!iso) return "—";
  const data = new Date(iso);
  if (Number.isNaN(data.getTime())) return "—";
  return data.toLocaleString("pt-BR", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function dataCurta(iso: string): string {
  const data = new Date(iso);
  if (Number.isNaN(data.getTime())) return iso;
  return data.toLocaleDateString("pt-BR", { day: "2-digit", month: "2-digit" });
}

export function numero(valor: number | null | undefined, casas = 1): string {
  if (valor === null || valor === undefined) return "—";
  return valor.toLocaleString("pt-BR", { maximumFractionDigits: casas });
}

/** Símbolo + palavra de cada tom — a cor nunca informa sozinha (GUIA-VISUAL). */
export const LEITURA_DO_TOM: Record<Tom, { simbolo: string; palavra: string }> = {
  ok: { simbolo: "✓", palavra: "em ordem" },
  atencao: { simbolo: "!", palavra: "atenção" },
  critico: { simbolo: "✕", palavra: "problema" },
  info: { simbolo: "→", palavra: "informação" },
  neutro: { simbolo: "•", palavra: "sem medida" },
};

export const ROTULO_DO_TIPO: Record<string, string> = {
  caso: "Caso",
  documento: "Documentos",
  entrevista: "Entrevista",
  contrato: "Contrato",
  agente: "Agente jurídico",
  ocorrencia: "Ocorrências",
  checklist: "Checklist",
  contradicao: "Contradições",
};

/** Tipo da pendência no vocabulário de quem lê, não no do banco. */
export const ROTULO_DA_PENDENCIA: Record<string, string> = {
  FACT: "fato",
  DOCUMENT: "documento",
  EVIDENCE: "prova",
};

/** Código de fato do agente ("EMPLOYMENT.WORK_SCHEDULE") em português corrente.
 *
 * O agente devolve `label` igual ao `code` quando o playbook não traz rótulo próprio, e
 * uma tabela cheia de CONSTANTE_EM_CAIXA_ALTA é ilegível para quem só quer saber o que
 * falta. Código desconhecido passa intacto — inventar tradução seria pior. */
const ROTULO_DO_CODIGO: Record<string, string> = {
  "PERSON.NAME": "Nome",
  "PERSON.CPF": "CPF",
  "PERSON.RG": "RG",
  "PERSON.PIS": "PIS/PASEP",
  "PERSON.BIRTH_DATE": "Data de nascimento",
  "PERSON.ADDRESS": "Endereço",
  "EMPLOYMENT.RELATIONSHIP": "Vínculo de emprego",
  "EMPLOYMENT.ADMISSION_DATE": "Data de admissão",
  "EMPLOYMENT.TERMINATION_DATE": "Data de saída",
  "EMPLOYMENT.MONTHLY_SALARY": "Salário mensal",
  "EMPLOYMENT.WORK_SCHEDULE": "Jornada de trabalho",
  "EMPLOYMENT.LEAVE": "Afastamento",
  "SOCIAL_SECURITY.INSS_BENEFIT": "Benefício do INSS",
};

export function rotuloLegivel(codigo: string): string {
  return ROTULO_DO_CODIGO[codigo] ?? codigo;
}

// -------------------------------------------------------------------- fatos

/** Estado do fato no vocabulário de quem lê a tela, com o tom que ele merece.
 *
 * A distinção que importa numa peça é a primeira: `ALLEGED` é o que o cliente contou e
 * `EXTRACTED` é o que saiu de um documento. Chamar os dois de "fato" na tela apagaria
 * exatamente a diferença que decide se a alegação precisa de prova. */
export const ESTADO_DO_FATO: Record<string, { palavra: string; simbolo: string; tom: Tom; explicacao: string }> = {
  ALLEGED: {
    palavra: "relatado",
    simbolo: "•",
    tom: "info",
    explicacao: "Veio do relato da entrevista. Ainda não há documento que o comprove.",
  },
  EXTRACTED: {
    palavra: "extraído",
    simbolo: "✓",
    tom: "ok",
    explicacao: "Lido de um documento do caso pelo OCR.",
  },
  CONFIRMED: {
    palavra: "confirmado",
    simbolo: "✓",
    tom: "ok",
    explicacao: "Conferido e confirmado no agente.",
  },
  CONTESTED: {
    palavra: "contestado",
    simbolo: "!",
    tom: "atencao",
    explicacao: "Alguém contestou este fato; ele não deve entrar na peça sem decisão.",
  },
  CONTRADICTED: {
    palavra: "em contradição",
    simbolo: "!",
    tom: "atencao",
    explicacao: "Conflita com outro fato do caso.",
  },
  SUPERSEDED: {
    palavra: "substituído",
    simbolo: "→",
    tom: "neutro",
    explicacao: "Uma versão mais nova deste fato tomou o lugar dele.",
  },
  REJECTED: {
    palavra: "rejeitado",
    simbolo: "✕",
    tom: "critico",
    explicacao: "Descartado: não vale como fato do caso.",
  },
};

export const ORIGEM_DO_FATO: Record<string, string> = {
  OCR_DOCUMENT: "documento lido",
  DOCUMENT: "documento",
  INTERVIEW: "entrevista",
  USER: "informado à mão",
  AGENT: "agente",
  SEM_ORIGEM: "sem origem",
};

/** "ocr_document, página 1, campo cpf" -> "documento lido, página 1, campo cpf".
 *
 * O agente escreve a proveniência com o nome técnico da fonte; o resto da frase (página,
 * campo, quem falou) já vem em português e passa intacto — é a citação da origem, e
 * reescrevê-la seria afastar o texto do que está gravado. */
export function origemLegivel(origem: string): string {
  const [fonte, ...resto] = origem.split(",");
  const traduzida = ORIGEM_DO_FATO[fonte.trim().toUpperCase()] ?? fonte.trim();
  return [traduzida, ...resto.map((parte) => parte.trim())].join(", ");
}

/** Enums do agente que aparecem dentro do valor de um fato.
 *
 * Só os que têm tradução óbvia e sem perda; qualquer outro valor passa como veio. */
const VALOR_TRADUZIDO: Record<string, string> = {
  GRANTED: "concedido",
  DENIED: "negado",
  PENDING: "em análise",
  APPEALED: "em recurso",
  CANCELLED: "cancelado",
  ACTIVE: "ativo",
  TERMINATED: "encerrado",
};

const ROTULO_DA_CHAVE: Record<string, string> = {
  date: "data",
  start_date: "início",
  end_date: "fim",
  reason: "motivo",
  amount: "valor",
  currency: "moeda",
  employer_name: "empregador",
  recognized: "reconhecido",
  benefit_type: "benefício",
  benefit_number: "número",
  status: "situação",
  full_name: "nome",
  digits: "número",
  number: "número",
  street: "logradouro",
  city: "cidade",
  state: "UF",
  zip_code: "CEP",
  schedule: "jornada",
  hours_per_week: "horas semanais",
};

function valorDaChave(chave: string, valor: unknown): string {
  if (valor === null || valor === undefined || valor === "") return "";
  if (typeof valor === "boolean") return valor ? "sim" : "não";
  if (typeof valor === "number") {
    // Dinheiro vem em `amount` com `currency` ao lado; o resto é número puro.
    return chave === "amount"
      ? valor.toLocaleString("pt-BR", { style: "currency", currency: "BRL" })
      : String(valor);
  }
  const texto = String(valor);
  if (VALOR_TRADUZIDO[texto]) return VALOR_TRADUZIDO[texto];
  // Data ISO do agente vira data brasileira; qualquer outro texto passa intacto —
  // reescrever o que veio do documento seria alterar o conteúdo do fato.
  if (/^\d{4}-\d{2}-\d{2}$/.test(texto)) {
    const [ano, mes, dia] = texto.split("-");
    return `${dia}/${mes}/${ano}`;
  }
  return texto;
}

/** O valor do fato em uma linha legível, sem perder de vista qual campo é qual. */
export function valorDoFato(valor: Record<string, unknown>): string {
  const partes: string[] = [];
  for (const [chave, bruto] of Object.entries(valor ?? {})) {
    if (chave === "currency") continue; // já embutida no valor monetário
    const texto = valorDaChave(chave, bruto);
    if (!texto) continue;
    const rotulo = ROTULO_DA_CHAVE[chave];
    // Campo único e óbvio (nome, número) dispensa o rótulo; os demais o levam para
    // que "05/02/2024" não apareça sem dizer se é início ou fim.
    partes.push(
      rotulo && Object.keys(valor).length > 1 ? `${rotulo}: ${texto}` : texto,
    );
  }
  return partes.join(" · ") || "—";
}
