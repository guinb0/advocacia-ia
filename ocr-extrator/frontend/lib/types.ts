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
    codigo: string;
    descricao: string;
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
