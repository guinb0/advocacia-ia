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
  RespostaEnvio,
  RoteiroCompleto,
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
const BASE = process.env.NEXT_PUBLIC_OCR_API ?? "http://127.0.0.1:8100";

/** Monta a URL absoluta da API a partir de um caminho tipo "/api/temp/x.json". */
export function urlApi(caminho: string): string {
  return `${BASE}${caminho}`;
}

export class ApiError extends Error {}

/* O token vive aqui, não em localStorage: um XSS que lesse o storage levaria a
 * sessão inteira. Quem mantém isto atualizado é o ProvedorAuth (lib/auth.tsx),
 * inclusive nas renovações. */
let tokenAtual: string | null = null;

export function definirTokenAtual(token: string | null): void {
  tokenAtual = token;
}

/* Exportado porque o módulo do agente (`lib/agente.ts`) tem o próprio cliente e o
 * token é um só. Se ele guardasse uma cópia, a sessão valeria numa metade da
 * aplicação e não na outra — falha que aparece como 401 numa aba só. */
export function cabecalhos(extra?: HeadersInit): HeadersInit | undefined {
  if (!tokenAtual) return extra;
  return { ...(extra ?? {}), Authorization: `Bearer ${tokenAtual}` };
}

/** fetch com o Bearer anexado — todo acesso à API passa por aqui. */
async function buscar(caminho: string, init: RequestInit = {}): Promise<Response> {
  return fetch(urlApi(caminho), { ...init, headers: cabecalhos(init.headers) });
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
  const dados = await comoJson<{ modelo_carregado: boolean }>(
    await buscar("/api/saude"),
  );
  return dados.modelo_carregado;
}

export async function aquecerModelo(): Promise<void> {
  await comoJson(await buscar("/api/aquecer", { method: "POST" }));
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
  const limite = Date.now() + 15 * 60_000;
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

// ----------------------------------------------------------------- chamada

/** Sorteia uma sala e devolve o link para mandar ao entrevistado. */
export async function criarSalaChamada(): Promise<{ sala: string; url: string }> {
  return comoJson<{ sala: string; url: string }>(
    await buscar("/api/chamada/sala", { method: "POST" }),
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
  throw new ApiError("A geração do relatório excedeu o tempo de espera.");
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
): Promise<Escuta> {
  return comoJson<Escuta>(
    await buscar("/api/entrevista/escuta", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ trecho, respostas, roteiro }),
    }),
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
