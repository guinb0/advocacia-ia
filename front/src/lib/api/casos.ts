/** Casos: cadastro, carteira, qualificação, consultas de CPF/CEP e portal. */

import type {
  Caso,
  CasoCriado,
  Categoria,
  DocumentosPendentesCaso,
  EnderecoCep,
  Entrega,
  Pedido,
  PortalEstado,
  PortalGerado,
  SituacaoCaso,
} from "../types";
import { ApiError, buscar, comoJson } from "./base";

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

export interface PaginaCarteira {
  situacoes: SituacaoCaso[];
  total: number;
  pagina: number;
  tamanho: number;
  paginas: number;
  triagem: {
    travados: number;
    aConferir: number;
    pedidosProntos: number;
    completos: number;
    ativos: number;
  };
  chegando_agora: { entrega: Entrega; cliente: string }[];
  pedidos: { casoId: string; cliente: string; faltantes: number; reenvios: number }[];
  /** Categorias presentes na carteira, para a tela oferecer só o que existe. */
  categorias: { codigo: string; nome: string }[];
}

/** Filtros da carteira. Vazio/omesso significa "sem filtro". `situacao` usa o
 *  mesmo vocabulário dos chips: critico, atencao, pedido, pronto. */
export interface FiltrosCarteira {
  busca?: string;
  categoria?: string;
  situacao?: string;
  ordenar?: "risco" | "recente" | "parado" | "nome";
}

/** A fila da carteira já montada e paginada pelo servidor (ver `app/carteira.py`).
 *  Os filtros vão ao servidor para valerem na carteira inteira, não só na página. */
export async function obterCarteira(
  pagina: number,
  tamanho: number,
  filtros: FiltrosCarteira = {},
): Promise<PaginaCarteira> {
  const params = new URLSearchParams({ pagina: String(pagina), tamanho: String(tamanho) });
  if (filtros.busca?.trim()) params.set("busca", filtros.busca.trim());
  if (filtros.categoria) params.set("categoria", filtros.categoria);
  if (filtros.situacao) params.set("situacao", filtros.situacao);
  if (filtros.ordenar && filtros.ordenar !== "recente") params.set("ordenar", filtros.ordenar);
  return comoJson<PaginaCarteira>(await buscar(`/api/carteira?${params.toString()}`));
}

/** Abre o caso. O `telefone` é o WhatsApp que a entrevista colheu.
 *
 * Vai junto na criação porque é a única passagem em que ele existe: as
 * respostas do roteiro não são guardadas, e sem isto a cobrança automática de
 * documentos só encontra o número depois que o contrato vai para a assinatura
 * (ver `automacoes_whatsapp.telefone_do_caso`). */
export async function criarCaso(
  cliente: string,
  categoria: string,
  observacao = "",
  telefone = "",
  tipoAcao = "",
  /** Skill que gera a petição do caso. Vazio: a skill em uso no escritório. */
  skillJuridicaId = "",
): Promise<CasoCriado> {
  const form = new FormData();
  form.append("cliente", cliente);
  form.append("categoria", categoria);
  form.append("observacao", observacao);
  form.append("telefone", telefone);
  form.append("tipo_acao", tipoAcao);
  if (skillJuridicaId) form.append("skill_juridica_id", skillJuridicaId);
  return comoJson<CasoCriado>(await buscar("/api/casos", { method: "POST", body: form }));
}

/** Troca a skill que gera a petição do caso. `""` volta para a skill em uso no escritório. */
export async function definirSkillDoCaso(casoId: string, skillJuridicaId: string): Promise<Caso> {
  const form = new FormData();
  form.append("skill_juridica_id", skillJuridicaId);
  return comoJson<Caso>(await buscar(`/api/casos/${encodeURIComponent(casoId)}`, { method: "PATCH", body: form }));
}

/** Cria o caso pelo nome e importa todos os documentos de uma pasta ZIP. */
export async function criarCasoPorZip(
  cliente: string,
  categoria: string,
  arquivo: File,
  skillJuridicaId = "",
  telefone = "",
): Promise<CasoCriado> {
  const form = new FormData();
  form.append("cliente", cliente);
  form.append("categoria", categoria);
  form.append("arquivo", arquivo);
  if (skillJuridicaId) form.append("skill_juridica_id", skillJuridicaId);
  if (telefone) form.append("telefone", telefone);
  const controlador = new AbortController();
  const prazo = window.setTimeout(() => controlador.abort(), 120_000);
  try {
    return comoJson<CasoCriado>(await buscar("/api/casos/importar-zip", {
      method: "POST", body: form, signal: controlador.signal,
    }));
  } catch (erro) {
    if (controlador.signal.aborted) {
      throw new ApiError("O envio do ZIP demorou mais de 2 minutos. O caso não foi confirmado; tente novamente com o ZIP menor.");
    }
    throw erro;
  } finally {
    window.clearTimeout(prazo);
  }
}

/** Grava a qualificação do cliente (o que o CPF puxou + o que foi digitado) no caso.
 *
 * Vai só o cadastro — nome e telefone já vivem no próprio caso. Campo vazio segue
 * vazio e o backend o grava como NULL: o cadastro é opcional. Fica numa tabela à
 * parte (`qualificacao`), 1:1 com o caso. */
export async function salvarQualificacaoDoCaso(
  casoId: string,
  respostas: Record<string, string | string[]>,
): Promise<void> {
  const texto = (id: string) =>
    typeof respostas[id] === "string" ? (respostas[id] as string).trim() : "";
  await comoJson(
    await buscar(`/api/casos/${encodeURIComponent(casoId)}/qualificacao`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        cpf: texto("cpf"),
        nascimento: texto("nascimento"),
        sexo: texto("sexo"),
        nome_mae: texto("mae"),
        cep: texto("cep"),
        endereco: texto("endereco"),
        email: texto("email"),
        renda_estimada: texto("renda_estimada"),
        /* Estes a tela sempre mostrou e o salvamento sempre ignorou: o atendente
         * preenchia RG, PIS, profissão e o resto, o contrato os usava na hora
         * (`contrato.valores_da_entrevista`) e nada disso chegava à tabela. Ao
         * reabrir o caso, o cadastro voltava pela metade. */
        idade: texto("idade"),
        nacionalidade: texto("nacionalidade"),
        profissao: texto("profissao"),
        estado_civil: texto("estado_civil"),
        rg: texto("rg"),
        rg_orgao: texto("rg_orgao"),
        rg_uf: texto("rg_uf"),
        nome_pai: texto("pai"),
        pis: texto("pis"),
        uf: texto("uf"),
        municipio: texto("municipio"),
        telefones_extras: texto("telefones_extras"),
        emails_extras: texto("emails_extras"),
        enderecos_extras: texto("enderecos_extras"),
      }),
    }),
  );
}

/** Qualificação do cidadão pelo CPF, na base da Receita (Conecta gov.br).
 *
 * Devolve os campos já nos ids das perguntas do roteiro. Vai por POST porque o
 * CPF no caminho da URL entraria em log de acesso e histórico de proxy — e isto
 * é dado pessoal, diferente do CEP.
 *
 * Lança quando não há credencial configurada, e é o caso comum enquanto o
 * convênio com o Conecta não sai: quem chama trata como silêncio. */
export async function consultarCpf(cpf: string): Promise<ConsultaCpf> {
  return comoJson<ConsultaCpf>(
    await buscar("/api/cpf", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ cpf }),
    }),
  );
}

export interface ConsultaCpf {
  /** Já nos ids das perguntas: `nome`, `mae`, `nascimento`, `uf`, `municipio`,
   *  `endereco`, `telefone`, `nacionalidade`. Só o que veio preenchido. */
  campos: Record<string, string>;
  /** "regular", "suspensa", "titular falecido"… */
  situacao: string;
  /** Vazio quando regular; senão, o que dizer na tela antes de assinar. */
  aviso: string;
  /** O nome de registro, que o contrato usa mesmo havendo nome social. */
  nome_registro: string;
  fonte: string;
}

export async function obterCaso(casoId: string): Promise<SituacaoCaso> {
  return comoJson<SituacaoCaso>(await buscar(`/api/casos/${casoId}`));
}

export async function atualizarCategoriaCaso(casoId: string, categoria: string): Promise<void> {
  const form = new FormData();
  form.append("categoria", categoria);
  await comoJson(await buscar(`/api/casos/${casoId}`, { method: "PATCH", body: form }));
}

export async function excluirCaso(casoId: string): Promise<void> {
  await comoJson(await buscar(`/api/casos/${casoId}`, { method: "DELETE" }));
}

export async function obterPedido(casoId: string, incluirOpcionais: boolean): Promise<Pedido> {
  const query = incluirOpcionais ? "?incluir_opcionais=true" : "";
  return comoJson<Pedido>(await buscar(`/api/casos/${casoId}/pedido${query}`));
}

export async function obterDocumentosPendentes(
  casoId: string,
  incluirOpcionais = false,
): Promise<DocumentosPendentesCaso> {
  const query = incluirOpcionais ? "?incluir_opcionais=true" : "";
  return comoJson<DocumentosPendentesCaso>(
    await buscar(`/api/casos/${encodeURIComponent(casoId)}/documentos/pendentes${query}`),
  );
}

/** Documento cujo conteúdo lido (campos e texto do OCR) casou com a busca. */
export interface AchadoNoConteudo {
  entrega_id: string;
  arquivo: string;
  /** Itens do checklist que o documento atende. */
  itens: string[];
  /** Onde o termo apareceu: "CEP: 70000-000" ou um trecho do texto. */
  onde: string[];
}

export async function buscarNoConteudoDoCaso(
  casoId: string,
  consulta: string,
  sinal?: AbortSignal,
): Promise<AchadoNoConteudo[]> {
  const query = new URLSearchParams({ q: consulta }).toString();
  return comoJson<AchadoNoConteudo[]>(
    await buscar(`/api/casos/${encodeURIComponent(casoId)}/documentos/busca?${query}`, { signal: sinal }),
  );
}

// ------------------------------------------------------- consultas públicas

/** Endereço a partir do CEP. Só o CEP sai daqui — nenhum dado do cliente. */
export async function consultarCep(cep: string): Promise<EnderecoCep> {
  return comoJson<EnderecoCep>(await buscar(`/api/cep/${cep.replace(/\D/g, "")}`));
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
