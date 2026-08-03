/** Espelha o JSON devolvido por POST /api/extrair (ver app/pipeline.py). */

export interface Campo {
  nome: string;
  rotulo: string;
  valor: string;
  valor_bruto: string;
  confianca: number;
  /** `null` quando o campo não tem regra de validação (nome, endereço…). */
  valido: boolean | null;
  observacao: string;
  origem: string;
}

export type Veredito = "APROVADO" | "APROVADO_COM_RESSALVAS" | "REPROVADO";

export interface Validacao {
  veredito: Veredito;
  resumo: string;
  /** `dados_utilizaveis` E foto sem nenhuma ressalva de qualidade. */
  aprovado: boolean;
  /** "posso usar esses dados?" — é este que um fluxo automatizado consulta. */
  dados_utilizaveis: boolean;
  imagem_legivel: boolean;
  score_legibilidade: number;
  completude_percentual: number;
  campos_esperados: string[];
  campos_faltando: string[];
  campos_invalidos: string[];
  campos_baixa_confianca: string[];
  erros: string[];
  avisos: string[];
  sugestoes: string[];
}

export interface Metrica {
  nome: string;
  valor: number;
  score: number;
  ok: boolean;
  mensagem: string;
}

export interface QualidadeImagem {
  score_legibilidade: number;
  legivel: boolean;
  metricas: Metrica[];
  problemas: string[];
  sugestoes: string[];
}

export interface LinhaTexto {
  texto: string;
  confianca: number;
}

export interface Documento {
  id: string;
  arquivo: string;
  processado_em: string;
  tempo_processamento_s: number;
  imagem: {
    largura: number;
    altura: number;
    rotacao_aplicada_graus: number;
    tamanho_bytes: number;
  };
  tipo: {
    /** Tipo usado na extração — igual a `detectado` quando ninguém força. */
    codigo: string;
    descricao: string;
    /** O que o classificador leu sozinho; é o que revela arquivo trocado. */
    detectado: string;
    descricao_detectado: string;
    confianca_classificacao: number;
    pontuacoes: Record<string, number>;
    forcado_pelo_usuario: boolean;
  };
  campos: Campo[];
  validacao: Validacao;
  qualidade_imagem: QualidadeImagem;
  ocr: {
    motor: string;
    idioma: string;
    confianca_media: number | null;
    blocos_detectados: number;
    caracteres_detectados: number;
  };
  texto_linhas: LinhaTexto[];
  texto_completo: string;
  arquivos_temporarios: {
    json: string;
    xml: string;
    expira_em_segundos: number;
  };
}

export interface TipoDocumento {
  codigo: string;
  descricao: string;
}

// ------------------------------------------------ categorias e checklists

export interface ItemChecklist {
  codigo: string;
  numero: number;
  nome: string;
  obrigatorio: boolean;
  /** Código do classificador de OCR, quando o sistema sabe conferir o tipo. */
  tipo_ocr: string | null;
  observacao: string;
}

export interface Categoria {
  codigo: string;
  nome: string;
  descricao: string;
  total_documentos: number;
  total_obrigatorios: number;
  itens: ItemChecklist[];
}

// ------------------------------------------------------ casos e entregas

export type StatusItem = "pendente" | "conferir" | "entregue";

export interface Caso {
  id: string;
  cliente: string;
  categoria: string;
  observacao: string;
  criado_em: string;
  atualizado_em: string;
  total_entregas?: number;
}

export interface Entrega {
  id: string;
  caso_id: string;
  item_codigo: string;
  arquivo: string;
  tipo_detectado: string | null;
  /** `null` quando não há classificador para o item ou o OCR não reconheceu. */
  tipo_confere: boolean | null;
  veredito: Veredito | null;
  dados_utilizaveis: boolean;
  score_legibilidade: number | null;
  criado_em: string;
  /** Mensagens para o advogado — não são o texto que vai ao cliente. */
  alertas: string[];
}

export interface ItemSituacao extends ItemChecklist {
  status: StatusItem;
  entregas: Entrega[];
}

export interface Progresso {
  obrigatorios_total: number;
  obrigatorios_entregues: number;
  obrigatorios_pendentes: number;
  opcionais_total: number;
  opcionais_entregues: number;
  itens_a_conferir: number;
  percentual_obrigatorios: number;
  pronto: boolean;
}

export interface SituacaoCaso {
  caso: Caso;
  categoria: { codigo: string; nome: string; descricao: string } | null;
  itens: ItemSituacao[];
  progresso: Progresso;
  erro?: string;
}

export interface Pedido {
  texto: string;
  faltando_obrigatorios: string[];
  faltando_opcionais: string[];
  reenviar: string[];
  progresso: Progresso;
}

export interface RespostaEnvio {
  entrega: Entrega;
  extracao: Documento;
}
