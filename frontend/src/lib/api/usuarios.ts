/** Usuários, perfis e matriz de acesso. */

import { buscar, comoJson } from "./base";

// ------------------------------------------------------- usuários e perfis
//
// As contas vivem na tabela `acervo_usuarios` do SQL Server (ver `app/usuarios.py`).
// Daqui isso não aparece: a tela fala com a API, e a API fala com o banco.

export interface Perfil {
  id: number;
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
  id?: number;
  codigo: string;
  rotulo: string;
  descricao: string;
  rota?: string;
  grupo?: string;
  ordem?: number;
}

/** Quantas contas dependem de um perfil. É o tamanho do impacto de mexer nele. */
export interface ContagemDeContas {
  total: number;
  ativos: number;
}

/** Um perfil com os módulos que ele alcança — a linha da matriz de acesso. */
export interface PerfilComAcesso {
  id: number;
  codigo: string;
  rotulo: string;
  descricao: string;
  /** Perfil que o sistema garante existir e não deixa apagar. */
  sistema: boolean;
  criado_em: string;
  /** Códigos dos módulos marcados, na ordem do catálogo. */
  modulos: string[];
  /** Contas ligadas a este perfil. Opcional porque só a matriz (protegida) a
   *  traz — o vocabulário de `listarPerfis` sai sem token e não expõe isso. */
  usuarios?: ContagemDeContas;
}

/** Uma alteração já feita em algum perfil — a linha do histórico. */
export interface AlteracaoDePerfil {
  id: number;
  perfil: string;
  /** `criado`, `atualizado` ou `removido`. */
  acao: string;
  /** Quem alterou: o e-mail da conta, que é o login do escritório. */
  autor: string;
  /** O que mudou, em uma linha. Vem pronto do servidor para a tela não
   *  reconstruir a comparação e correr o risco de descrevê-la diferente. */
  resumo: string;
  criado_em: string;
}

export interface UsuarioCadastrado {
  id: string;
  usuario: string;
  nome: string;
  email: string | null;
  /** Só dígitos, como o servidor guarda. A máscara é da tela (`formatarTelefone`). */
  telefone?: string;
  ativo: boolean;
  perfis: string[];
  perfilId?: number | null;
}

export interface UsuariosPaginados {
  itens: UsuarioCadastrado[];
  total: number;
  pagina: number;
  tamanho: number;
  paginas: number;
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
): Promise<{ alteracao: { resumo: string } | null }> {
  /* A resposta é lida, e não descartada: ela diz o que o servidor ENTENDEU da
   * alteração — inclusive quando ele não gravou nada por não haver mudança. É
   * isso que a tela mostra de volta, em vez de um "salvo" que não distingue as
   * duas situações. */
  return comoJson(
    await buscar(`/api/usuarios/perfis/${encodeURIComponent(codigo)}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ codigo, rotulo, descricao, modulos }),
    }),
  );
}

/** Apaga um perfil. Os de sistema recusam.
 *
 * Não desfaz a atribuição de quem já tem o papel no login: isso é conta de
 * pessoa, e apagar perfil não pode apagar acesso de gente sem alguém decidir
 * para onde essas pessoas vão. */
export async function removerPerfil(codigo: string): Promise<void> {
  await buscar(`/api/usuarios/perfis/${encodeURIComponent(codigo)}`, { method: "DELETE" });
}

/** As últimas alterações feitas nos perfis — quem mexeu, quando e no quê.
 *
 * A matriz mostra como o acesso ESTÁ; isto mostra como ele chegou aí. Sem o
 * segundo, "quem abriu este módulo?" só se responde pela memória de alguém. */
export async function listarHistoricoPerfis(limite = 30): Promise<AlteracaoDePerfil[]> {
  const r = await comoJson<{ alteracoes: AlteracaoDePerfil[] }>(
    await buscar(`/api/usuarios/perfis/historico?limite=${limite}`),
  );
  return r.alteracoes;
}

function normalizarPaginacaoUsuarios(
  resposta: Partial<UsuariosPaginados>,
  paginaPedida: number,
  tamanhoPedido: number,
): UsuariosPaginados {
  const itens = Array.isArray(resposta.itens) ? resposta.itens : [];
  const tamanho = Number.isFinite(resposta.tamanho)
    ? Math.max(1, Math.floor(resposta.tamanho ?? tamanhoPedido))
    : Math.max(1, Math.floor(tamanhoPedido));
  const total = Number.isFinite(resposta.total)
    ? Math.max(0, Math.floor(resposta.total ?? itens.length))
    : itens.length;
  const paginas = Number.isFinite(resposta.paginas)
    ? Math.max(1, Math.floor(resposta.paginas ?? 1))
    : Math.max(1, Math.ceil(total / tamanho));
  const pagina = Number.isFinite(resposta.pagina)
    ? Math.min(Math.max(1, Math.floor(resposta.pagina ?? paginaPedida)), paginas)
    : Math.min(Math.max(1, Math.floor(paginaPedida)), paginas);

  return { itens, total, pagina, tamanho, paginas };
}

export async function listarUsuariosPaginado(
  pagina = 1,
  tamanho = 12,
): Promise<UsuariosPaginados> {
  const paginaSegura = Number.isFinite(pagina) ? Math.max(1, Math.floor(pagina)) : 1;
  const tamanhoSeguro = Number.isFinite(tamanho)
    ? Math.min(Math.max(1, Math.floor(tamanho)), 50)
    : 12;
  const params = new URLSearchParams({
    pagina: String(paginaSegura),
    tamanho: String(tamanhoSeguro),
  });
  const r = await comoJson<Partial<UsuariosPaginados>>(
    await buscar(`/api/usuarios?${params.toString()}`),
  );
  return normalizarPaginacaoUsuarios(r, paginaSegura, tamanhoSeguro);
}

export async function listarUsuarios(): Promise<UsuarioCadastrado[]> {
  return (await listarUsuariosPaginado()).itens;
}

export async function criarUsuario(dados: {
  nome: string;
  email: string;
  telefone?: string;
  perfilId: number;
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

/** A conta inteira como deve ficar depois da edição. */
export interface EdicaoDeUsuario {
  nome: string;
  email: string;
  /** Como foi digitado; o servidor guarda só os dígitos. Vazio apaga o telefone. */
  telefone: string;
  perfilId: number;
  ativo: boolean;
  /** Vazio mantém a senha atual — ela nunca volta do servidor, então não há o
   *  que reenviar. */
  senha: string;
  /** Volta para a senha padrão, que obriga a pessoa a trocar ao entrar. */
  redefinirSenha: boolean;
}

/** Edita uma conta existente. Só o secretário: para os demais o servidor responde 403.
 *
 * `alterados` diz o que de fato mudou (nomes de campo, nunca valores), e é isso
 * que a tela repete — salvar sem mexer em nada volta com a lista vazia. */
export async function editarUsuario(
  id: string,
  dados: EdicaoDeUsuario,
): Promise<UsuarioCadastrado & { alterados: string[] }> {
  return comoJson(
    await buscar(`/api/usuarios/${encodeURIComponent(id)}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(dados),
    }),
  );
}
