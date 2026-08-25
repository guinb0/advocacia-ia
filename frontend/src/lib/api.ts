import type {
  AnaliseResposta,
  Assinatura,
  AssinaturaConsultada,
  AssinaturaCriada,
  Caso,
  CasoCriado,
  Categoria,
  ConfigAssinatura,
  Documento,
  DocumentoDoCliente,
  EnderecoCep,
  EntregaDetalhe,
  Escuta,
  Estrategia,
  Pedido,
  PortalEstado,
  PortalGerado,
  ProcessamentoEntrevista,
  RespostaEnvio,
  RoteiroCompleto,
  RecomendacaoEntrevista,
  SituacaoCaso,
  TipoDocumento,
  Triagem as TriagemResposta,
} from "./types";

/**
 * O navegador fala direto com o FastAPI, sem passar pelo rewrite do Next.
 *
 * O proxy do Next derruba a conexão em 30s (timeout fixo, sem opção de config) e
 * ainda bufferiza o upload inteiro na memória do Node. Como uma foto de celular tem
 * vários MB e o OCR leva de 3 a 30s, o upload morria com "socket hang up". Falar
 * direto com o Python elimina o intermediário — o backend já habilita CORS.
 */
/* Mesma regra do `global/services/api.ts`, e pelo mesmo motivo: a API precisa
 * ficar no host da página, senão o cookie de sessão não alcança o `proxy.ts` e o
 * login entra em laço. O default acompanha de onde o app foi aberto. */
const BASE =
  process.env.NEXT_PUBLIC_OCR_API ||
  (typeof window !== "undefined"
    ? `${window.location.protocol}//${window.location.hostname}:8100`
    : "http://localhost:8100");

/** Monta a URL absoluta da API a partir de um caminho tipo "/api/temp/x.json". */
export function urlApi(caminho: string): string {
  return `${BASE}${caminho}`;
}

export class ApiError extends Error {}

export async function enviarAvaliacaoGoogle(telefone: string): Promise<{ enviado: boolean }> {
  return comoJson(await buscar("/api/whatsapp/avaliacao-google", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ telefone }),
  }));
}

/** O link de assinatura de UM documento para UM signatário, pelo WhatsApp.
 *
 * Manda identificadores, nunca a URL nem o telefone: o servidor busca os dois no
 * registro do documento. Ver o cabeçalho de `app/whatsapp.py`. */
export async function enviarLinkAssinatura(
  assinaturaId: string,
  signatarioToken: string,
): Promise<{ enviado: boolean }> {
  return comoJson(await buscar("/api/whatsapp/link-assinatura", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ assinatura_id: assinaturaId, signatario_token: signatarioToken }),
  }));
}

export interface EvidenciaInvestigativa {
  identificador: string;
  categoria: string;
  titulo: string;
  url: string;
  fonte: string;
  confianca: string;
  metadados: Record<string, unknown>;
}

export interface ResultadoInvestigativo {
  texto: string;
  similaridade: number;
  metadados: Record<string, unknown>;
  titulo: string;
  url: string;
}

/* O TOKEN NÃO PASSA MAIS POR AQUI.
 *
 * Ele era guardado nesta variável — fora do localStorage, para que um XSS não
 * levasse a sessão inteira. Agora ele vive num cookie `HttpOnly`, que o
 * JavaScript não consegue ler de jeito nenhum: a mesma proteção, garantida pelo
 * navegador em vez de por disciplina nossa.
 *
 * O preço é que toda chamada precisa de `credentials: "include"`, senão o
 * navegador não manda cookie para outra origem e a rota responde 401. É o par
 * do `allow_credentials=True` do FastAPI (ver `app/main.py`).
 */
export const CREDENCIAIS: RequestCredentials = "include";

/* Continua exportada porque `lib/agente.ts` tem o próprio cliente e chama por
 * aqui. Não acrescenta mais nada aos cabeçalhos — o que autenticava era o
 * `Authorization`, e ele saiu. Fica como ponto único caso volte a existir um
 * cabeçalho comum a todas as chamadas. */
export function cabecalhos(extra?: HeadersInit): HeadersInit | undefined {
  return extra;
}

/** fetch com o cookie de sessão anexado — todo acesso à API passa por aqui. */
async function buscar(caminho: string, init: RequestInit = {}): Promise<Response> {
  const resposta = await fetch(urlApi(caminho), { ...init, credentials: CREDENCIAIS });
  if (resposta.status === 401 && typeof window !== "undefined") {
    // A sessão venceu. A carteira não deve fingir que é falha de dados: limpa o
    // estado local (quem escuta é o `ContextWrapper`) e devolve ao login.
    window.dispatchEvent(new Event("acervo:sessao-expirada"));
    /* Apaga o cookie no servidor antes de sair, senão o `proxy.ts` devolve para
     * `/home` e o 401 se repete — o laço. */
    void fetch(urlApi("/api/user/logout"), { method: "POST", credentials: CREDENCIAIS })
      .catch(() => undefined)
      .finally(() => {
        if (window.location.pathname !== "/") window.location.href = "/";
      });
  }
  return resposta;
}

async function comoJson<T>(resposta: Response): Promise<T> {
  const corpo = await resposta.json().catch(() => null);
  if (!resposta.ok) {
    const detalhe =
      corpo && typeof corpo === "object" && "detail" in corpo
        ? String((corpo as { detail: unknown }).detail)
        : `Erro ${resposta.status}`;
    throw new ApiError(detalhe);
  }
  return corpo as T;
}

export async function listarTipos(): Promise<TipoDocumento[]> {
  const dados = await comoJson<{ tipos: TipoDocumento[] }>(await buscar("/api/tipos"));
  return dados.tipos;
}

export async function verificarSaude(): Promise<boolean> {
  const dados = await comoJson<{ modelo_aquecido: boolean; ocr_via_worker: boolean }>(
    await buscar("/api/saude"),
  );
  return dados.ocr_via_worker || dados.modelo_aquecido;
}

export async function extrair(
  arquivo: File,
  idioma: string,
  tipo: string,
): Promise<Documento> {
  const form = new FormData();
  form.append("arquivo", arquivo);
  form.append("idioma", idioma);
  form.append("tipo", tipo);
  const criado = await comoJson<{ job_id: string }>(
    await buscar("/api/extrair/jobs", { method: "POST", body: form }),
  );
  // O backend trata precedentes como enriquecimento de melhor esforço. Se o
  // worker desaparecer, não deixamos o botão preso por quinze minutos.
  const limite = Date.now() + 90_000;
  while (Date.now() < limite) {
    const job = await comoJson<{
      status: "QUEUED" | "STARTED" | "PROCESSING" | "COMPLETED" | "FAILED";
      erro?: string | null;
      resultado?: Documento | null;
    }>(await buscar(`/api/jobs/${criado.job_id}`));
    if (job.status === "COMPLETED" && job.resultado) return job.resultado;
    if (job.status === "FAILED") throw new ApiError(job.erro || "O processamento do documento falhou.");
    await new Promise((resolver) => window.setTimeout(resolver, 1000));
  }
  throw new ApiError("O OCR continua na fila. Consulte o job novamente em instantes.");
}

export async function coletarInvestigacao(alvo: {
  cnpj?: string;
  numero_processo?: string;
  tribunal: string;
}): Promise<{ fontes: number; chunks: number; evidencias: EvidenciaInvestigativa[]; avisos: string[] }> {
  return comoJson(await buscar("/api/investigacao/coletar", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(alvo),
  }));
}

export async function buscarInvestigacao(filtro: {
  consulta: string;
  cnpj?: string;
  numero_processo?: string;
}): Promise<{ resultados: ResultadoInvestigativo[]; aviso: string }> {
  const params = new URLSearchParams({ consulta: filtro.consulta });
  if (filtro.cnpj) params.set("cnpj", filtro.cnpj);
  if (filtro.numero_processo) params.set("numero_processo", filtro.numero_processo);
  return comoJson(await buscar(`/api/investigacao/buscar?${params.toString()}`));
}

export interface AnaliseInvestigativa {
  resumo: string;
  insights: Array<{ achado: string; tipo: string; impacto: string; confianca: string; evidencias: string[]; como_verificar: string }>;
  contradicoes: Array<{ ponto: string; evidencias: string[]; pergunta: string }>;
  provas_a_buscar: string[];
  perguntas_entrevista: string[];
  alertas: string[];
  fontes: Array<{ indice: string; titulo: string; url: string; similaridade: number }>;
  aviso: string;
}

export async function analisarInvestigacao(alvo: {
  relato: string; cnpj?: string; numero_processo?: string; tribunal: string;
}): Promise<AnaliseInvestigativa> {
  return comoJson(await buscar("/api/investigacao/analisar", {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(alvo),
  }));
}

export async function baixarTexto(caminho: string): Promise<string> {
  const r = await buscar(caminho);
  if (!r.ok) throw new ApiError(`Erro ${r.status}`);
  return r.text();
}

// ------------------------------------------------------------- categorias

export async function listarCategorias(): Promise<Categoria[]> {
  const dados = await comoJson<{ categorias: Categoria[] }>(
    await buscar("/api/categorias"),
  );
  return dados.categorias;
}

// ------------------------------------------------------------------ casos

export async function listarCasos(): Promise<Caso[]> {
  const dados = await comoJson<{ casos: Caso[] }>(await buscar("/api/casos"));
  return dados.casos;
}

export async function criarCaso(
  cliente: string,
  categoria: string,
  observacao = "",
): Promise<CasoCriado> {
  const form = new FormData();
  form.append("cliente", cliente);
  form.append("categoria", categoria);
  form.append("observacao", observacao);
  return comoJson<CasoCriado>(await buscar("/api/casos", { method: "POST", body: form }));
}

export async function obterCaso(casoId: string): Promise<SituacaoCaso> {
  return comoJson<SituacaoCaso>(await buscar(`/api/casos/${casoId}`));
}

export async function excluirCaso(casoId: string): Promise<void> {
  await comoJson(await buscar(`/api/casos/${casoId}`, { method: "DELETE" }));
}

export async function obterPedido(casoId: string, incluirOpcionais: boolean): Promise<Pedido> {
  const query = incluirOpcionais ? "?incluir_opcionais=true" : "";
  return comoJson<Pedido>(await buscar(`/api/casos/${casoId}/pedido${query}`));
}

// ------------------------------------------------------ roteiro de entrevista

export async function obterRoteiro(codigo: string): Promise<RoteiroCompleto> {
  return comoJson<RoteiroCompleto>(await buscar(`/api/roteiros/${codigo}`));
}

export interface AtendimentoDocumentacao {
  entrevista_id: string;
  caso_id: string | null;
  cliente: string;
  sala: string | null;
  status: "entrevista" | "solicitado" | "assumido" | "encerrado";
  entrevistador_nome: string;
  documentador_nome: string | null;
  iniciado_em: string;
  solicitado_em: string | null;
}

export async function registrarAtendimentoDocumentacao(entrevistaId: string, cliente: string): Promise<void> {
  await comoJson(await buscar("/api/documentacao/atendimentos", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ entrevista_id: entrevistaId, cliente }),
  }));
}

export async function baterAtendimentoDocumentacao(entrevistaId: string): Promise<void> {
  await comoJson(await buscar(`/api/documentacao/atendimentos/${encodeURIComponent(entrevistaId)}/batida`, { method: "POST" }));
}

export async function solicitarDocumentacao(entrevistaId: string, casoId: string, sala: string, cliente: string): Promise<void> {
  await comoJson(await buscar(`/api/documentacao/atendimentos/${encodeURIComponent(entrevistaId)}/solicitar`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ caso_id: casoId, sala, cliente }),
  }));
}

export async function obterAtendimentoDocumentacao(entrevistaId: string): Promise<AtendimentoDocumentacao> {
  return comoJson(await buscar(`/api/documentacao/atendimentos/${encodeURIComponent(entrevistaId)}`));
}

export async function listarAtendimentosDocumentacao(): Promise<{ entrevistas_ativas: number; solicitacoes: number; documentadores_online: number; atendimentos: AtendimentoDocumentacao[] }> {
  return comoJson(await buscar("/api/documentacao/atendimentos"));
}

export async function registrarPresencaDocumentacao(): Promise<void> {
  await comoJson(await buscar("/api/documentacao/presenca", { method: "POST" }));
}

export async function assumirAtendimentoDocumentacao(entrevistaId: string): Promise<AtendimentoDocumentacao> {
  return comoJson(await buscar(`/api/documentacao/atendimentos/${encodeURIComponent(entrevistaId)}/assumir`, { method: "POST" }));
}

export interface MunicipioLocalidade { id: number; nome: string; uf: string }

export async function listarMunicipios(uf: string): Promise<MunicipioLocalidade[]> {
  const dados = await comoJson<{ municipios: MunicipioLocalidade[] }>(
    await buscar(`/api/localidades/municipios?uf=${encodeURIComponent(uf)}`),
  );
  return dados.municipios;
}

// ----------------------------------------------------------------- chamada

/** Sorteia uma sala e devolve o link para mandar ao entrevistado. */
export async function criarSalaChamada(sala?: string): Promise<{ sala: string; url: string; token: string }> {
  return comoJson<{ sala: string; url: string; token: string }>(
    await buscar("/api/chamada/sala", {
      method: "POST",
      headers: sala ? { "Content-Type": "application/json" } : undefined,
      body: sala ? JSON.stringify({ sala }) : undefined,
    }),
  );
}

// ---------------------------------------------------------------- contrato

function cpfValido(cpf: string): boolean {
  const normalizado = cpf.normalize("NFKC");
  if (!/^[0-9.\-\s]+$/.test(normalizado)) return false;
  const digitos = normalizado.replace(/[^0-9]/g, "");
  if (digitos.length !== 11 || /^(\d)\1{10}$/.test(digitos)) return false;

  for (const posicao of [9, 10]) {
    let soma = 0;
    for (let indice = 0; indice < posicao; indice += 1) {
      soma += Number(digitos[indice]) * (posicao + 1 - indice);
    }
    let verificador = (soma * 10) % 11;
    if (verificador === 10) verificador = 0;
    if (verificador !== Number(digitos[posicao])) return false;
  }
  return true;
}

/** Antecipação visual da barreira definitiva que também existe no servidor. */
export function requisitosDoContrato(
  respostas: Record<string, string | string[]>,
): string[] {
  const nome = typeof respostas.nome === "string" ? respostas.nome.trim() : "";
  const cpf = typeof respostas.cpf === "string" ? respostas.cpf : "";
  const partesDoNome = nome.split(/\s+/);
  const particulas = new Set(["da", "das", "de", "do", "dos", "e"]);
  const partesSubstantivas = partesDoNome.filter(
    (parte) => !particulas.has(parte.toLocaleLowerCase("pt-BR").replace(/\.+$/, "")),
  );
  const nomeCompleto =
    partesSubstantivas.length >= 2 &&
    partesDoNome.every(
      (parte) => /\p{L}/u.test(parte) && /^[\p{L}.'’-]+$/u.test(parte),
    ) &&
    partesSubstantivas.every(
      (parte) => parte.replace(/[^\p{L}]/gu, "").length >= 2,
    );
  const requisitos: string[] = [];
  if (!nomeCompleto) requisitos.push("nome completo do cliente");
  if (!cpfValido(cpf)) requisitos.push("CPF válido");
  return requisitos;
}

export interface ContratoGerado {
  arquivo: Blob;
  nome: string;
  /** Campos do modelo que a entrevista não respondeu — saem entre colchetes. */
  faltando: string[];
}

/** Preenche o modelo oficial do escritório com as respostas da entrevista.
 *
 * Volta um .docx para conferir e assinar. As cláusulas vêm do arquivo em
 * `docs/`, palavra por palavra — nada aqui é redigido por modelo de linguagem. */
export async function gerarContrato(
  respostas: Record<string, string | string[]>,
  municipio = "",
  documento: DocumentoDoCliente = "contrato",
): Promise<ContratoGerado> {
  const r = await buscar("/api/contrato", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ respostas, municipio, documento }),
  });

  return interpretarContrato(r);
}

/** Os três documentos que o cliente assina, na ordem em que o escritório os
 *  junta. Os rótulos são os mesmos de `contrato.MODELOS`, no backend. */
export const DOCUMENTOS_DO_CLIENTE: { codigo: DocumentoDoCliente; rotulo: string }[] = [
  { codigo: "contrato", rotulo: "Contrato de honorários" },
  { codigo: "procuracao", rotulo: "Procuração ad judicia" },
  { codigo: "hipossuficiencia", rotulo: "Declaração de hipossuficiência" },
];

/** Gera a partir dos fatos atuais do caso; nenhum dado pessoal vem do navegador. */
export async function gerarContratoDoCaso(casoId: string): Promise<ContratoGerado> {
  const r = await buscar(`/api/agente/casos/${encodeURIComponent(casoId)}/contrato`, {
    method: "POST",
  });
  return interpretarContrato(r);
}

async function interpretarContrato(r: Response): Promise<ContratoGerado> {
  if (!r.ok) {
    const corpo = await r.json().catch(() => null);
    throw new ApiError(
      corpo && typeof corpo === "object" && "detail" in corpo
        ? String((corpo as { detail: unknown }).detail)
        : `Erro ${r.status}`,
    );
  }

  const faltando = (r.headers.get("X-Campos-Faltando") ?? "")
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean);

  return { arquivo: await r.blob(), nome: nomeDoAnexo(r), faltando };
}

export interface RelatorioGerado {
  arquivo: Blob;
  nome: string;
  /** Pendências obrigatórias que a entrevista deixou em aberto. */
  pendencias: number;
  /** Impedimentos que o escritório mandou observar. */
  impedimentos: number;
  /** Se a análise por precedentes entrou no documento. */
  analise: "sim" | "indisponivel" | "nao";
}

/** O relatório analisado da entrevista, em PDF, com o símbolo do escritório.
 *
 * Organiza as respostas na ordem do roteiro e, quando a base de precedentes
 * responde, traz a análise assistida (síntese, ações, riscos, lacunas). O
 * `relato` é o texto corrido da entrevista — é dele que sai a análise. */
export async function gerarRelatorio(
  respostas: Record<string, string | string[]>,
  relato = "",
  roteiro = "empregado_publico",
): Promise<RelatorioGerado> {
  const criado = await comoJson<{ job_id: string }>(await buscar("/api/entrevista/relatorio/jobs", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ respostas, relato, roteiro }),
  }));

  const limite = Date.now() + 15 * 60_000;
  while (Date.now() < limite) {
    const job = await comoJson<{
      status: string;
      erro?: string | null;
      resultado?: { arquivo: string; pendencias: number; impedimentos: number; analise: RelatorioGerado["analise"] } | null;
    }>(await buscar(`/api/jobs/${criado.job_id}`));
    if (job.status === "FAILED") throw new ApiError(job.erro || "Falha ao gerar relatório.");
    if (job.status === "COMPLETED" && job.resultado) {
      const pdf = await buscar(job.resultado.arquivo);
      if (!pdf.ok) throw new ApiError("O PDF foi gerado, mas não pôde ser baixado.");
      return {
        arquivo: await pdf.blob(), nome: "relatorio-entrevista.pdf",
        pendencias: job.resultado.pendencias, impedimentos: job.resultado.impedimentos,
        analise: job.resultado.analise,
      };
    }
    await new Promise((resolver) => window.setTimeout(resolver, 1000));
  }
  throw new ApiError("O relatório não respondeu em 90 segundos. Tente novamente; respostas e entrevista permanecem salvas.");
}

// --------------------------------------------- assinatura eletrônica do contrato

/** Se o envio para assinatura está ligado — sem a chave no `.env` ele não existe. */
export async function configAssinatura(): Promise<ConfigAssinatura> {
  return comoJson<ConfigAssinatura>(await buscar("/api/assinatura/config"));
}

/** Gera o contrato e o manda assinar. O .docx é o mesmo de `gerarContrato`. */
export async function enviarParaAssinatura(
  respostas: Record<string, string | string[]>,
  signatarios: { nome: string; email?: string; telefone?: string; papel?: string }[] = [],
  municipio = "",
  casoId?: string,
): Promise<AssinaturaCriada> {
  return comoJson<AssinaturaCriada>(
    await buscar("/api/contrato/assinatura", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        respostas,
        municipio,
        signatarios,
        caso_id: casoId ?? null,
      }),
    }),
  );
}

/** Os contratos já mandados assinar, com o último estado conhecido. */
export async function listarAssinaturas(filtro: {
  casoId?: string;
  cliente?: string;
  cpf?: string;
} = {}): Promise<Assinatura[]> {
  const query = new URLSearchParams();
  if (filtro.casoId) query.set("caso_id", filtro.casoId);
  if (filtro.cliente) query.set("cliente", filtro.cliente);
  if (filtro.cpf) query.set("cpf", filtro.cpf);
  const sufixo = query.size > 0 ? `?${query}` : "";
  const dados = await comoJson<{ assinaturas: Assinatura[] }>(
    await buscar(`/api/assinaturas${sufixo}`),
  );
  return dados.assinaturas;
}

/** Quem já assinou e quem falta, consultado na ZapSign agora. */
export async function obterAssinatura(id: string): Promise<AssinaturaConsultada> {
  return comoJson<AssinaturaConsultada>(await buscar(`/api/assinaturas/${id}`));
}

export async function vincularAssinaturaAoCaso(id: string, casoId: string): Promise<void> {
  const form = new FormData();
  form.append("caso_id", casoId);
  await comoJson(await buscar(`/api/assinaturas/${id}/caso`, { method: "POST", body: form }));
}

/** Tira o contrato da lista local. Na ZapSign ele continua, com a auditoria. */
export async function excluirAssinatura(id: string): Promise<void> {
  await comoJson(await buscar(`/api/assinaturas/${id}`, { method: "DELETE" }));
}

/** O PDF assinado, com a trilha de auditoria. Vem pelo backend, que o guarda. */
export async function baixarContratoAssinado(
  id: string,
): Promise<{ arquivo: Blob; nome: string }> {
  const r = await buscar(`/api/assinaturas/${id}/arquivo`);
  if (!r.ok) {
    const corpo = await r.json().catch(() => null);
    throw new ApiError(
      corpo && typeof corpo === "object" && "detail" in corpo
        ? String((corpo as { detail: unknown }).detail)
        : `Erro ${r.status}`,
    );
  }
  return { arquivo: await r.blob(), nome: nomeDoAnexo(r, "contrato-assinado.pdf") };
}

/** Nome do arquivo vindo do Content-Disposition, preferindo a forma UTF-8. */
function nomeDoAnexo(r: Response, padrao = "contrato.docx"): string {
  const cabecalho = r.headers.get("Content-Disposition") ?? "";
  const utf8 = /filename\*=UTF-8''([^;]+)/i.exec(cabecalho);
  if (utf8) {
    try {
      return decodeURIComponent(utf8[1]);
    } catch {
      /* nome malformado: cai no genérico abaixo */
    }
  }
  return /filename="([^"]+)"/i.exec(cabecalho)?.[1] ?? padrao;
}

// ------------------------------------------------------- consultas públicas

/** Endereço a partir do CEP. Só o CEP sai daqui — nenhum dado do cliente. */
export async function consultarCep(cep: string): Promise<EnderecoCep> {
  return comoJson<EnderecoCep>(await buscar(`/api/cep/${cep.replace(/\D/g, "")}`));
}

// ----------------------------------------------------- triagem da entrevista

/** Classifica o relato e sugere a categoria. NÃO cria caso — só sugere. */
export async function triarEntrevista(texto: string, arquivo?: File): Promise<TriagemResposta> {
  const form = new FormData();
  form.append("texto", texto);
  if (arquivo) form.append("arquivo", arquivo);
  return comoJson<TriagemResposta>(
    await buscar("/api/triagem", { method: "POST", body: form }),
  );
}

/** Manda um trecho da conversa e recebe o que ele respondeu do roteiro.
 *
 * É o que sustenta a entrevista de microfone aberto: em vez de a atendente
 * apertar gravar a cada uma das 86 perguntas, a conversa corre e o roteiro se
 * preenche atrás dela. */
export async function escutarTrecho(
  trecho: string,
  respostas: Record<string, string | string[]>,
  roteiro = "empregado_publico",
  perguntaAtual = "",
): Promise<Escuta> {
  return comoJson<Escuta>(
    await buscar("/api/entrevista/escuta", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ trecho, respostas, roteiro, pergunta_atual: perguntaAtual }),
    }),
  );
}

function explicarRotaDeProcessamento(resposta: Response): Response {
  if (resposta.status === 404) {
    throw new ApiError(
      "O serviço de preenchimento está desatualizado. Reinicie a aplicação e processe a entrevista novamente.",
    );
  }
  return resposta;
}

/** Organiza a conversa completa somente depois que a captura foi encerrada. */
export async function processarEntrevista(
  transcricao: string,
  respostas: Record<string, string | string[]>,
  roteiro = "empregado_publico",
): Promise<ProcessamentoEntrevista> {
  const resposta = await buscar("/api/entrevista/processar", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ transcricao, respostas, roteiro }),
  });
  return comoJson<ProcessamentoEntrevista>(
    explicarRotaDeProcessamento(resposta),
  );
}

/** Confere UMA resposta narrativa e diz o que ela não trouxe.
 *
 * É a irmã curta de `analisarEstrategia`: aquela produz um parecer por caso,
 * esta roda uma vez por pergunta, durante a entrevista, e cabe em três itens. */
export async function analisarResposta(
  perguntaId: string,
  pergunta: string,
  resposta: string,
  contexto = "",
): Promise<AnaliseResposta> {
  return comoJson<AnaliseResposta>(
    await buscar("/api/entrevista/analise", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        pergunta_id: perguntaId,
        pergunta,
        resposta,
        contexto,
      }),
    }),
  );
}

/** Recomenda se vale ABRIR o caso para análise; nunca estima chance de vitória. */
export async function recomendarEntrevista(
  relato: string,
  lacunasObrigatorias: string[],
): Promise<RecomendacaoEntrevista> {
  return comoJson<RecomendacaoEntrevista>(
    await buscar("/api/entrevista/recomendacao", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        relato,
        lacunas_obrigatorias: lacunasObrigatorias,
        limite_precedentes: 12,
      }),
    }),
  );
}

/** Recupera processos semelhantes e gera apoio estratégico fundamentado. */
export async function analisarEstrategia(relato: string): Promise<Estrategia> {
  const criado = await comoJson<{ job_id: string }>(
    await buscar("/api/estrategia/jobs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ relato, limite_precedentes: 8 }),
    }),
  );
  const limite = Date.now() + 10 * 60_000;
  while (Date.now() < limite) {
    const job = await comoJson<{ status: string; erro?: string | null; resultado?: Estrategia | null }>(
      await buscar(`/api/jobs/${criado.job_id}`),
    );
    if (job.status === "COMPLETED" && job.resultado) return job.resultado;
    if (job.status === "FAILED") throw new ApiError(job.erro || "Falha na análise estratégica.");
    await new Promise((resolver) => window.setTimeout(resolver, 1000));
  }
  throw new ApiError("A análise estratégica excedeu o tempo de espera.");
}

// -------------------------------------------------------- portal do cliente

/** Gera (ou troca) o link e a senha. A senha volta só nesta resposta. */
export async function gerarPortal(casoId: string): Promise<PortalGerado> {
  return comoJson<PortalGerado>(
    await buscar(`/api/casos/${casoId}/portal`, { method: "POST" }),
  );
}

export async function consultarPortal(casoId: string): Promise<PortalEstado> {
  return comoJson<PortalEstado>(await buscar(`/api/casos/${casoId}/portal`));
}

// --------------------------------------------------------------- entregas

export async function enviarDocumento(
  casoId: string,
  itemCodigo: string,
  arquivo: File,
  idioma = "pt",
  usarParaRgECpf = false,
): Promise<RespostaEnvio> {
  const form = new FormData();
  form.append("item", itemCodigo);
  form.append("arquivo", arquivo);
  form.append("idioma", idioma);
  form.append("usar_para_rg_e_cpf", String(usarParaRgECpf));
  return comoJson<RespostaEnvio>(
    await buscar(`/api/casos/${casoId}/documentos`, { method: "POST", body: form }),
  );
}

export async function vincularIdentidadeUnificada(
  casoId: string,
  entregaId: string,
): Promise<RespostaEnvio> {
  const form = new FormData();
  form.append("entrega_id", entregaId);
  return comoJson<RespostaEnvio>(
    await buscar(`/api/casos/${casoId}/identidade-unificada`, {
      method: "POST",
      body: form,
    }),
  );
}

export async function excluirEntrega(entregaId: string): Promise<void> {
  await comoJson(await buscar(`/api/entregas/${entregaId}`, { method: "DELETE" }));
}

/** A entrega com a extração completa — os campos que o visor mostra. */
export async function obterEntrega(entregaId: string): Promise<EntregaDetalhe> {
  return comoJson<EntregaDetalhe>(await buscar(`/api/entregas/${entregaId}`));
}

export interface PacoteDocumentos {
  arquivo: Blob;
  nome: string;
  /** Quantos documentos entraram no pacote. */
  arquivos: number;
  /** Quantos constavam no caso mas não estavam mais no disco. */
  faltando: number;
}

/** Tudo que o cliente enviou, num ZIP só, na ordem do checklist.
 *
 * Vai por `fetch` e não por `<a href download>` porque o link cru não manda o
 * Bearer — desceria um 401 salvo em disco com nome de .zip, e o atendente só
 * descobriria ao tentar abrir. Mesmo motivo de `baixarArquivoEntrega`. */
export async function baixarDocumentosDoCaso(casoId: string): Promise<PacoteDocumentos> {
  const r = await buscar(`/api/casos/${encodeURIComponent(casoId)}/documentos.zip`);
  if (!r.ok) {
    const corpo = await r.json().catch(() => null);
    throw new ApiError(
      corpo && typeof corpo === "object" && "detail" in corpo
        ? String((corpo as { detail: unknown }).detail)
        : `Erro ${r.status}`,
    );
  }
  return {
    arquivo: await r.blob(),
    nome: nomeDoAnexo(r, "documentos.zip"),
    arquivos: Number(r.headers.get("X-Arquivos") ?? 0),
    faltando: Number(r.headers.get("X-Faltando") ?? 0),
  };
}

/** URL absoluta do arquivo. Serve para abrir em nova aba quando não há
 * autenticação; com token ligado use `baixarArquivoEntrega`, porque `<img>` e
 * `<iframe>` não enviam o header Authorization e levariam 401. */
export function urlArquivoEntrega(entregaId: string, download = false): string {
  return urlApi(`/api/entregas/${entregaId}/arquivo${download ? "?download=1" : ""}`);
}

/** Busca o arquivo COM o Bearer e devolve o blob — a origem do object URL que
 * a pré-visualização usa em `src`. */
export async function baixarArquivoEntrega(entregaId: string): Promise<Blob> {
  const r = await buscar(`/api/entregas/${entregaId}/arquivo`);
  if (!r.ok) throw new ApiError(r.status === 401 ? "Sessão expirada." : `Erro ${r.status}`);
  return r.blob();
}

export async function baixarArquivoEntregaPdf(
  entregaId: string,
): Promise<{ arquivo: Blob; nome: string }> {
  const r = await buscar(`/api/entregas/${encodeURIComponent(entregaId)}/arquivo.pdf`);
  if (!r.ok) {
    const corpo = await r.json().catch(() => null);
    throw new ApiError(
      corpo && typeof corpo === "object" && "detail" in corpo
        ? String((corpo as { detail: unknown }).detail)
        : `Erro ${r.status}`,
    );
  }
  return { arquivo: await r.blob(), nome: nomeDoAnexo(r, "documento.pdf") };
}

// ------------------------------------------------------- usuários e perfis
//
// As contas vivem na tabela `acervo_usuarios` do SQL Server (ver `app/usuarios.py`).
// Daqui isso não aparece: a tela fala com a API, e a API fala com o banco.

export interface Perfil {
  /** Texto livre, e não uma união fechada.
   *
   * Era `"advogado" | "cliente"` — errado já na origem (faltava `secretario`) e
   * incompatível com perfil criado na tela: um "analista" cadastrado pelo
   * escritório não passaria no compilador. Os códigos deixaram de ser
   * conhecidos em tempo de build quando os perfis passaram a ser dados. */
  codigo: string;
  rotulo: string;
  descricao: string;
}

/** Um módulo do sistema que um perfil pode ou não alcançar.
 *
 * O catálogo vem do SERVIDOR, nunca de uma lista digitada aqui: são os mesmos
 * códigos que as rotas usam em `auth.exigir_modulo`. Uma lista mantida na tela
 * divergiria em silêncio, e a caixa marcada não corresponderia a acesso nenhum. */
export interface ModuloDeAcesso {
  codigo: string;
  rotulo: string;
  descricao: string;
}

/** Um perfil com os módulos que ele alcança — a linha da matriz de acesso. */
export interface PerfilComAcesso {
  codigo: string;
  rotulo: string;
  descricao: string;
  /** Perfil que o sistema garante existir e não deixa apagar. */
  sistema: boolean;
  criado_em: string;
  /** Códigos dos módulos marcados, na ordem do catálogo. */
  modulos: string[];
}

export interface UsuarioCadastrado {
  id: string;
  usuario: string;
  nome: string;
  email: string | null;
  ativo: boolean;
  perfis: string[];
}

/** Os perfis que o cadastro oferece. Vêm do servidor para a tela não manter uma
 *  segunda lista que envelhece sozinha quando um perfil for criado ou renomeado. */
export async function listarPerfis(): Promise<Perfil[]> {
  const r = await comoJson<{ perfis: Perfil[] }>(await buscar("/api/usuarios/perfis"));
  return r.perfis;
}

/** Os perfis COM os módulos de cada um — a matriz de acesso.
 *
 * Separada de `listarPerfis` porque respondem a perguntas diferentes: aquela é
 * vocabulário para o seletor do cadastro e sai sem token; esta é o desenho de
 * acesso do escritório e só quem administra vê. */
export async function listarMatrizPerfis(): Promise<{
  perfis: PerfilComAcesso[];
  modulos: ModuloDeAcesso[];
}> {
  return comoJson(await buscar("/api/usuarios/perfis/matriz"));
}

/** Cria ou atualiza um perfil e a lista de módulos que ele alcança.
 *
 * Manda o estado COMPLETO das caixas: o servidor substitui a matriz inteira, em
 * vez de comparar item a item — comparar só criaria caminho para a tela e o
 * banco discordarem sobre o que está marcado. */
export async function salvarPerfil(
  codigo: string,
  rotulo: string,
  descricao: string,
  modulos: string[],
): Promise<void> {
  await buscar(`/api/usuarios/perfis/${encodeURIComponent(codigo)}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ codigo, rotulo, descricao, modulos }),
  });
}

/** Apaga um perfil. Os de sistema recusam.
 *
 * Não desfaz a atribuição de quem já tem o papel no login: isso é conta de
 * pessoa, e apagar perfil não pode apagar acesso de gente sem alguém decidir
 * para onde essas pessoas vão. */
export async function removerPerfil(codigo: string): Promise<void> {
  await buscar(`/api/usuarios/perfis/${encodeURIComponent(codigo)}`, { method: "DELETE" });
}

export async function listarUsuarios(): Promise<UsuarioCadastrado[]> {
  const r = await comoJson<{ itens: UsuarioCadastrado[] }>(await buscar("/api/usuarios"));
  return r.itens;
}

export async function criarUsuario(dados: {
  nome: string;
  email: string;
  perfil: string;
  senha: string;
}): Promise<UsuarioCadastrado> {
  return comoJson<UsuarioCadastrado>(
    await buscar("/api/usuarios", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(dados),
    }),
  );
}

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
}

export interface PessoaSupervisao {
  entrevistador: string;
  quantidade: number;
  entrevistas: EntrevistaResumo[];
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
}> {
  return comoJson(await buscar("/api/supervisao/entrevistas"));
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

/* ------------------------------------- a entrevista conduzida ao vivo
 *
 * Até aqui, a entrevista só virava registro quando alguém anexava um arquivo ao
 * caso, à mão, depois. O atendimento guiado — roteiro, escuta, gravação — não
 * gravava nada: a conversa transcrita morria com a aba, e a supervisão (que lê
 * essa tabela) enxergava só a amostra que tinha sido anexada.
 *
 * O que sobe é a transcrição BRUTA, não o relato montado das respostas: o relato
 * diz o que a escuta extraiu, e auditá-lo mediria o reconhecimento de voz em vez
 * da condução da entrevista (ver o cabeçalho de `app/auditoria.py`).
 *
 * PUT, e chamado mais de uma vez por atendimento: o caso nasce no meio da
 * rolagem e a conversa continua depois dele — avaliação, documentos, fechamento.
 * `gravacao_id` é a chave, e a segunda chamada reescreve a primeira. */

export interface EntrevistaAoVivo {
  /** Id da gravação no serviço de transcrição. Identifica a entrevista. */
  gravacao_id: string;
  texto: string;
  realizada_em: string;
  avaliacao_google: boolean;
  /** O atendimento foi encerrado — só então o agente lê a conversa. */
  concluida: boolean;
}

export async function gravarEntrevistaAoVivo(
  casoId: string,
  dados: EntrevistaAoVivo,
): Promise<EntrevistaResumo> {
  return comoJson(
    await buscar(`/api/casos/${encodeURIComponent(casoId)}/entrevista-ao-vivo`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(dados),
    }),
  );
}

/* ------------------------------------------- checklist do roteiro (secretário)
 *
 * O checklist tem DUAS origens, e elas não se misturam de propósito.
 *
 * `ChecklistRegistro` sai do banco — assinatura enviada, avaliação marcada,
 * documento recebido. É fato, é barato de consultar e carrega junto com a tela.
 *
 * `Auditoria` (acima) sai da leitura da transcrição pelo modelo, custa uma ida ao
 * DeepSeek e por isso só roda quando o secretário pede. A tela junta as duas em uma
 * lista só, mas mantém visível de onde cada linha veio: uma diz o que ACONTECEU,
 * a outra o que APARECE na conversa — e a segunda erra. */

export type SituacaoItem = "feito" | "pendente" | "incerto" | "nao_aplica";

export interface ItemChecklist {
  id: string;
  titulo: string;
  detalhe: string;
  /** Pílula à direita da linha: "Assinatura", "Dossiê", "Crítico"… */
  etiqueta: string;
  situacao: SituacaoItem;
  /** O que não tem segunda chance depois que o cliente desliga. */
  critico: boolean;
}

export interface FaseChecklist {
  codigo: string;
  titulo: string;
  descricao: string;
  itens: ItemChecklist[];
}

export interface ChecklistRegistro {
  entrevista_id: string;
  entrevistador: string;
  caso: { id: string; cliente: string; categoria: string };
  realizada_em: string | null;
  criado_em: string | null;
  avaliacao_google: boolean;
  /** "ao_vivo" foi conduzida pelo roteiro e tem áudio; "anexada" veio de arquivo. */
  origem: "ao_vivo" | "anexada";
  gravacao_id: string;
  fases: FaseChecklist[];
  progresso: { feitos: number; total: number; percentual: number };
}

/** GET, e não POST: nada aqui vai ao modelo, então repetir a chamada não custa. */
export async function obterChecklist(id: string): Promise<ChecklistRegistro> {
  return comoJson(
    await buscar(`/api/supervisao/entrevistas/${encodeURIComponent(id)}/checklist`),
  );
}

/** Conserta a marcação da avaliação do Google. Devolve o checklist já refeito. */
export async function corrigirAvaliacaoGoogle(
  id: string,
  concluida: boolean,
): Promise<ChecklistRegistro> {
  return comoJson(
    await buscar(`/api/supervisao/entrevistas/${encodeURIComponent(id)}/avaliacao-google`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ concluida }),
    }),
  );
}

/** A marcação do atendente, no atendimento — com o cliente ainda na chamada. */
export async function marcarAvaliacaoGoogle(
  casoId: string,
  entrevistaId: string,
  concluida: boolean,
): Promise<{ avaliacao_google: boolean }> {
  return comoJson(
    await buscar(
      `/api/casos/${encodeURIComponent(casoId)}/entrevista/${encodeURIComponent(entrevistaId)}/avaliacao-google`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ concluida }),
      },
    ),
  );
}

// ------------------------------------------------- acervo de precedentes

export interface ContagemAcervo { nome: string; trechos: number; documentos: number }

export interface PanoramaAcervo {
  fontes: number; trechos: number; vetorizados: number; sem_vetor: number;
  periodo: { de: string | null; ate: string | null };
  por_tipo_de_fonte: { nome: string; documentos: number }[];
  por_origem: ContagemAcervo[];
  por_tribunal: ContagemAcervo[];
  por_resultado: ContagemAcervo[];
  por_tipo_documento: ContagemAcervo[];
  por_classe: ContagemAcervo[];
}

export interface DocumentoAcervo {
  id: string; tipo: string; titulo: string; identificador: string | null;
  url: string | null; publicado_em: string | null; trechos: number;
  tribunal: string | null; resultado: string | null; origem: string | null;
  processo: string | null;
}

export interface DocumentoDetalhe {
  fonte: { id: string; tipo: string; titulo: string; identificador: string | null; url: string | null; publicado_em: string | null };
  trechos: { ordem: number; texto: string; caracteres: number; vetorizado: boolean; metadados: unknown }[];
  total_trechos: number;
}

export async function panoramaAcervo(): Promise<PanoramaAcervo> {
  return comoJson(await buscar("/api/dados"));
}

export async function listarDocumentosAcervo(f: {
  origem?: string; tribunal?: string; busca?: string;
}): Promise<{ itens: DocumentoAcervo[]; total: number }> {
  const p = new URLSearchParams();
  if (f.origem) p.set("origem", f.origem);
  if (f.tribunal) p.set("tribunal", f.tribunal);
  if (f.busca) p.set("busca", f.busca);
  return comoJson(await buscar(`/api/dados/documentos?${p.toString()}`));
}

export async function obterDocumentoAcervo(id: string): Promise<DocumentoDetalhe> {
  return comoJson(await buscar(`/api/dados/documentos/${encodeURIComponent(id)}`));
}

export interface PrazosAcervo {
  processos: number;
  segunda_instancia: number;
  percentual_recurso: number;
  duracao: { processos_medidos: number; mediana_dias: number | null; p90_dias: number | null };
  aviso: string;
}

export async function prazosAcervo(): Promise<PrazosAcervo> {
  return comoJson(await buscar("/api/dados/prazos"));
}
