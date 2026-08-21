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

export type StatusItem = "pendente" | "processando" | "conferir" | "entregue";

export interface Caso {
  id: string;
  cliente: string;
  categoria: string;
  observacao: string;
  criado_em: string;
  atualizado_em: string;
  total_entregas?: number;
  /** Verdadeiro quando o caso já tem link de portal. */
  portal_ativo?: boolean;
}

/** `POST /api/casos` devolve o caso já com o portal recém-criado. */
export interface CasoCriado extends Caso {
  portal: PortalGerado;
}

export interface Entrega {
  id: string;
  /** Estado real da fila/leitura; 'erro' indica que o arquivo foi preservado. */
  status_proc?: "na_fila" | "processando" | "pronto" | "erro";
  erro_proc?: string | null;
  caso_id: string;
  item_codigo: string;
  arquivo: string;
  tipo_detectado: string | null;
  /** `null` quando não há classificador para o item ou o OCR não reconheceu. */
  tipo_confere: boolean | null;
  veredito: Veredito | null;
  dados_utilizaveis: boolean;
  /** Confirmação explícita de que uma CIN deve atender RG e CPF. */
  confirmado_manual: boolean;
  score_legibilidade: number | null;
  /** Itens do checklist atendidos pelo mesmo arquivo; CIN pode atender RG e CPF. */
  itens_atendidos: string[];
  criado_em: string;
  /** Mensagens para o advogado — não são o texto que vai ao cliente. */
  alertas: string[];
}

/** `GET /api/entregas/{id}` devolve a entrega com a extração completa anexada
 * (a coluna `extracao_json`), que é de onde saem os campos exibidos no visor. */
export interface EntregaDetalhe extends Entrega {
  extracao?: Documento;
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

// ------------------------------------------------------ roteiro de entrevista

/** `escolha` é fileira de botões; `lista` é seletor, para muitas opções. */
export type TipoResposta =
  | "dado" | "data" | "sim_nao" | "escolha" | "lista" | "documentos" | "relato";

export interface Pergunta {
  id: string;
  texto: string;
  tipo: TipoResposta;
  /** Só as narrativas abrem o gravador; dado é digitado. */
  transcrever: boolean;
  opcoes: string[];
  dica: string;
  obrigatoria: boolean;
  /** Documento a conferir enquanto se digita. Vazio = campo livre. */
  validacao: "" | "cpf";
  /** Base pública que preenche o campo sozinha. Vazio = digitado à mão. */
  busca: "" | "cep";
  /** Id da pergunta que recebe o resultado da busca. */
  preenche: string;
  /** Texto que a atendente LÊ em voz alta conforme a resposta. Chave "sim"/"não"
   *  nas de rastreio, "*" para qualquer uma. Vem do roteiro do escritório. */
  fala: Record<string, string>;
  /** Resposta que IMPEDE o prosseguimento. Hoje só a ação anterior não recebida. */
  impedimento: string;
}

export interface EnderecoCep {
  cep: string;
  logradouro: string;
  bairro: string;
  cidade: string;
  uf: string;
  /** Pronto para o campo de endereço, com o número marcado como pendente. */
  endereco_formatado: string;
  /** Qual base respondeu — aparece na tela, para saber de onde veio o dado. */
  fonte: string;
}

export interface Bloco {
  id: string;
  titulo: string;
  perguntas: Pergunta[];
  /** `null` = sempre visível; senão, só com o rastreio positivo. */
  modulo: string | null;
  objetivo: string;
  /** Lido em voz alta ao entrar no bloco. */
  abertura: string;
  /** Orientação à atendente. NÃO é lida ao cliente. */
  instrucao: string;
  /** O bloco saiu da entrevista e é de outra equipe. Hoje, a qualificação. */
  delegado_a: string;
}

export interface RoteiroCompleto {
  codigo: string;
  nome: string;
  descricao: string;
  blocos: Bloco[];
  /** Os parágrafos de abertura, para ler antes da primeira pergunta. */
  saudacao: string[];
  /** Os de encerramento, depois da última. */
  encerramento: string[];
  /** O que ler quando o cliente sai do assunto, da mais gentil à mais firme.
   *  Todas terminam em dois-pontos: emendam com o enunciado da pergunta. */
  retomadas: string[];
  /** Complemento da retomada por tipo de resposta ("basta sim ou não"). */
  fechos_por_tipo: Record<string, string>;
  /** id da pergunta de rastreio -> módulo que ela libera. */
  mapa_rastreio: Record<string, string>;
}

// ----------------------------------------------------- triagem da entrevista

export interface SugestaoCategoria {
  codigo: string;
  nome: string;
  pontos: number;
  /** Fração do total de pontos — serve para ordenar, não é probabilidade. */
  confianca: number;
  /** Trechos do relato que sustentaram a pontuação. */
  evidencias: string[];
}

export interface Triagem {
  sugestoes: SugestaoCategoria[];
  /** `false` quando o sinal é fraco ou duas categorias ficaram próximas. */
  confiante: boolean;
  motivo: string;
  dados: { cliente?: string; cpf?: string };
  caracteres: number;
  /** 'llm' = o modelo leu e interpretou; 'pistas' = casamento local de termos. */
  metodo?: "llm" | "pistas";
  /** As duas leituras (modelo e termos) apontaram categorias diferentes. */
  divergiu?: boolean;
  /** O relato traz doença crônica E acidente súbito — podem ser duas ações. */
  concorrentes?: boolean;
}

export interface ItemEstatistico {
  nome: string;
  quantidade: number;
  percentual: number;
}

export interface PrecedenteEstrategia {
  indice: string;
  processo?: string;
  resultado?: string;
  vara?: string;
  relator?: string;
  magistrados?: string[];
  fonte?: string;
  tipo_documento?: string;
  similaridade: number;
  url?: string;
}

export interface Estrategia {
  resumo: string;
  acoes: Array<{ acao: string; porque: string; aplicabilidade?: string; contrapontos?: string; forca?: string; precedentes: string[] }>;
  riscos: Array<{ risco: string; aplicabilidade?: string; contrapontos?: string; forca?: string; precedentes: string[] }>;
  divergencias?: Array<{ ponto: string; precedentes_favoraveis: string[]; precedentes_contrarios: string[] }>;
  lacunas: string[];
  perguntas_criticas?: string[];
  aviso: string;
  metodologia: string;
  precedentes: PrecedenteEstrategia[];
  estatisticas: {
    processos_analisados: number;
    resultados: ItemEstatistico[];
    varas: ItemEstatistico[];
    magistrados: ItemEstatistico[];
    desfechos_favoraveis_amplos: {
      quantidade: number;
      percentual: number;
      criterio: string;
    };
    desfechos_merito: { processos: number; favoraveis: number; percentual: number; criterio: string };
    similaridade_amostra: { maxima: number; mediana: number; minima: number };
    aviso: string;
  };
}

/** Resposta de `POST /api/casos/{id}/portal`. A senha vem só aqui. */
export interface PortalGerado {
  url: string;
  token: string;
  senha: string;
  aviso: string;
}

export interface PortalEstado {
  ativo: boolean;
  url: string | null;
  /** Nomeia a sala da chamada de voz. Nunca some da URL — só do que é exibido. */
  token: string | null;
  criado_em: string | null;
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

// ------------------------------------------- assinatura eletrônica (ZapSign)

/** Como cada signatário está no documento mandado assinar. */
export type EstadoSignatario =
  | "pendente"
  | "abriu"
  | "assinou"
  | "recusou"
  | "expirou"
  | "cancelado";

export type EstadoAssinatura = "pendente" | "assinado" | "recusado";

export interface Signatario {
  token: string;
  nome: string;
  email: string;
  telefone: string;
  /** "cliente" ou "escritório" — rótulo nosso, a ZapSign não o guarda. */
  papel: string;
  estado: EstadoSignatario;
  /** O estado por extenso, como o backend o escreve ("abriu, não assinou"). */
  rotulo: string;
  assinou_em: string | null;
  visualizado_em: string | null;
  vezes_visto: number;
  /** Link individual, para reenviar à mão quando o e-mail cai em spam. */
  url_assinatura: string;
}

/** Um contrato mandado para assinatura. Sem o token da ZapSign: ele é do servidor. */
export interface Assinatura {
  id: string;
  nome: string;
  cliente: string;
  caso_id: string | null;
  estado: EstadoAssinatura;
  signatarios: Signatario[];
  assinaram: number;
  total: number;
  /** Nomes de quem ainda não assinou. */
  faltam: string[];
  /** Se o PDF assinado já está guardado em disco no escritório. */
  arquivo_local: boolean;
  criado_em: string;
  atualizado_em: string;
}

/** Resposta de `POST /api/contrato/assinatura`. */
export interface AssinaturaCriada {
  /** Uma por documento da papelada: contrato, procuração e declaração.
   *  Cada uma é um processo próprio na ZapSign, com link e trilha próprios. */
  assinaturas: Assinatura[];
  /** Campos do modelo que a entrevista não respondeu — saem entre colchetes. */
  faltando: string[];
  /** Preenchido quando um documento falhou DEPOIS de outros já terem subido:
   *  reenviar tudo duplicaria os convites que o cliente já recebeu. */
  parcial?: string;
}

/** Os documentos que o cliente assina. Os códigos vêm de `contrato.MODELOS`. */
export type DocumentoDoCliente = "contrato" | "procuracao" | "hipossuficiencia";

/** Resposta de `GET /api/assinaturas/{id}`, já consultada na ZapSign. */
export interface AssinaturaConsultada {
  assinatura: Assinatura;
  /** `false` quando a ZapSign não respondeu e o estado é o último conhecido. */
  atualizado: boolean;
  aviso?: string;
  tem_assinado?: boolean;
}

/** O que `GET /api/assinatura/config` diz antes de a tela oferecer o botão. */
export interface ConfigAssinatura {
  ativa: boolean;
  auth_mode: string;
  whatsapp: boolean;
  signatario_escritorio: { nome: string; email: string; papel: string } | null;
}

// ------------------------------- conferência da resposta durante a entrevista

/** Uma lacuna apontada na resposta, com os precedentes que a sustentam. */
export interface LacunaResposta {
  item: string;
  /** Índices "P1", "P2"… que casam com `AnaliseResposta.precedentes`. */
  precedentes: string[];
}

export interface PrecedenteAnalise {
  indice: string;
  processo: string | null;
  resultado: string | null;
  vara: string | null;
  url: string | null;
  similaridade: number;
}

/** Resposta de `POST /api/entrevista/analise`. Curta de propósito: é lida
 *  entre uma pergunta e a seguinte, com o cliente na frente. */
export interface AnaliseResposta {
  /** Nada a acrescentar neste ponto. */
  suficiente: boolean;
  /** No máximo 3. */
  faltam: LacunaResposta[];
  /** No máximo 3, prontas para ler em voz alta ao cliente. */
  perguntar: string[];
  observacao: string;
  /** `false` quando o banco de precedentes não respondeu — a análise passa a
   *  ser a leitura do modelo sobre o texto, e a tela precisa dizer isso. */
  com_precedentes: boolean;
  precedentes: PrecedenteAnalise[];
  aviso: string;
  do_cache: boolean;
}

export interface RecomendacaoEntrevista {
  recomendado: "sim" | "com_ressalva" | "atencao" | "indefinido";
  motivo: string;
  lacunas_obrigatorias: string[];
  estatistica: {
    processos_analisados?: number;
    desfechos_merito?: { processos: number; favoraveis: number; percentual: number; criterio: string };
    similaridade_amostra?: { maxima: number; mediana: number; minima: number };
  };
  precedentes: Array<{
    processo: string | null; resultado: string | null; vara: string | null;
    relator?: string | null; url: string | null; similaridade: number;
  }>;
  com_precedentes: boolean;
  analise_comparativa: null | {
    sintese: string;
    pontos_comuns: Array<{ ponto: string; impacto: string; forca: string; precedentes: string[] }>;
    diferencas_decisivas: Array<{ ponto: string; por_que_importa: string; precedentes_favoraveis: string[]; precedentes_contrarios: string[] }>;
    provas_prioritarias: Array<{ prova: string; motivo: string; precedentes: string[] }>;
    perguntas_criticas: string[];
    referencias: Record<string, { processo: string | null; resultado: string | null; url: string | null }>;
  };
  aviso: string;
}

// ------------------------------------- escuta contínua durante a entrevista

/** Um campo que a fala preencheu, com o pedaço da conversa que o sustenta. */
export interface CampoOuvido {
  pergunta_id: string;
  pergunta: string;
  valor: string;
  /** Citação literal do que foi dito. É por ela que se confere de relance. */
  trecho: string;
  /** O campo já tinha resposta e esta fala ACRESCENTOU a ela.
   *
   * O cliente volta ao assunto e traz o que faltou — "8 vezes" vira "8 vezes,
   * em 2022, 2023 e 2024". `valor` é só o acréscimo, nunca a resposta inteira,
   * porque a tela soma ao que já está no campo (ver `app/escuta.py`). */
  complemento?: boolean;
}

/** Algo que ficou pela metade, já escrito para ser lido em voz alta. */
export interface Lembrete {
  pergunta_id: string;
  pergunte: string;
}

export interface PerguntaPendente {
  pergunta_id: string;
  pergunta: string;
  obrigatoria: boolean;
}

/** Resposta de `POST /api/entrevista/escuta`. */
export interface Escuta {
  /** Entrou direto no campo — relatos, sim/não, escolhas. */
  preenchidas: CampoOuvido[];
  /** Nome e CPF: precisam de um clique para aceitar. Ver `app/escuta.py`. */
  sugestoes: CampoOuvido[];
  lembretes: Lembrete[];
  /** O que o roteiro ainda pede e ninguém falou. */
  faltando: PerguntaPendente[];
  /** `false` quando o trecho era curto demais para valer uma chamada. */
  analisado: boolean;
  /** Id da pergunta que o trecho estava apenas LENDO em voz alta.
   *
   * Presente quando a escuta reconheceu o entrevistador fazendo a pergunta, e
   * não o cliente respondendo — o trecho fecha na pausa dele, antes de a
   * resposta existir. Nada foi preenchido: a resposta vem no trecho seguinte. */
  enunciado?: string;
}
