"use client";

/* Cadastro de quem usa o sistema.
 *
 * Quatro campos, e é de propósito: conta se cria no meio do atendimento, com
 * alguém esperando. Nome, e-mail, perfil e senha bastam para entrar — CPF,
 * telefone e endereço o cadastro do CASO já coleta, e pedir duas vezes é a
 * forma mais rápida de ninguém preencher nenhuma das duas.
 *
 * A lista fica ao lado do formulário, e não atrás de um botão, porque a pergunta
 * que antecede "cadastrar" quase sempre é "ele já não está aí?".
 */

import { useCallback, useEffect, useState } from "react";
import { ArrowLeft, Mail, ShieldCheck, UserPlus, UsersRound } from "lucide-react";

import {
  AjudaCampo,
  Aviso,
  Botao,
  Campo,
  CampoSeletor,
  Cartao,
  Paginacao,
  RotuloCampo,
  Selo,
  Tabela,
  Td,
  Th,
  TrZebra,
  Vazio,
} from "@/components/ui/Basicos";
import {
  ApiError,
  criarUsuario,
  listarPerfis,
  listarUsuariosPaginado,
  type Perfil,
  type UsuarioCadastrado,
} from "@/lib/api";

interface Props {
  onVoltar: () => void;
}

const VAZIO = { nome: "", email: "", perfilId: 0, senha: "" };
const TAMANHO_PAGINA = 12;

export default function Usuarios({ onVoltar }: Props) {
  const [perfis, setPerfis] = useState<Perfil[]>([]);
  const [itens, setItens] = useState<UsuarioCadastrado[]>([]);
  const [total, setTotal] = useState(0);
  const [pagina, setPagina] = useState(1);
  const [totalPaginas, setTotalPaginas] = useState(1);
  const [form, setForm] = useState(VAZIO);
  const [carregando, setCarregando] = useState(true);
  const [salvando, setSalvando] = useState(false);
  const [erro, setErro] = useState<string | null>(null);
  /* Separado de `erro`: falhar em LISTAR os perfis não impede ver os usuários
   * já cadastrados, então os dois não podem disputar a mesma faixa. */
  const [erroPerfis, setErroPerfis] = useState<string | null>(null);
  const [feito, setFeito] = useState<string | null>(null);

  const recarregar = useCallback(async (paginaSolicitada = 1) => {
    const paginaSegura = Number.isFinite(paginaSolicitada) ? Math.max(1, paginaSolicitada) : 1;
    try {
      const resposta = await listarUsuariosPaginado(paginaSegura, TAMANHO_PAGINA);
      setItens(resposta.itens);
      setTotal(resposta.total);
      setPagina(resposta.pagina);
      setTotalPaginas(resposta.paginas);
      setErro(null);
    } catch (e) {
      setErro(e instanceof ApiError ? e.message : "Não foi possível carregar os usuários.");
    } finally {
      setCarregando(false);
    }
  }, []);

  useEffect(() => {
    /* O `.catch` daqui zerava a lista em silêncio, e o sintoma era uma caixa de
     * seleção vazia sem nada na tela explicando por quê — indistinguível de
     * "o escritório não tem perfis". Agora a falha aparece, e com ela o motivo. */
    void listarPerfis()
      .then((lista) => {
        setPerfis(lista);
        const perfilInicial = lista.find((perfil) => perfil.codigo === "advogado") ?? lista[0];
        setForm((atual) => ({
          ...atual,
          perfilId: lista.some((perfil) => perfil.id === atual.perfilId)
            ? atual.perfilId
            : (perfilInicial?.id ?? 0),
        }));
        setErroPerfis(
          lista.length === 0 ? "Nenhum perfil cadastrado. Crie um em Perfis de acesso." : null,
        );
      })
      .catch((e: unknown) => {
        setPerfis([]);
        setErroPerfis(
          e instanceof ApiError
            ? `Não foi possível carregar os perfis: ${e.message}`
            : "Não foi possível carregar os perfis. O servidor respondeu?",
        );
      });
    void recarregar(1);
  }, [recarregar]);

  async function enviar(evento: React.FormEvent) {
    evento.preventDefault();
    setSalvando(true);
    setErro(null);
    setFeito(null);
    try {
      const novo = await criarUsuario(form);
      // O e-mail é o login; dizê-lo de volta evita a dúvida de quem digitou
      // rápido e não sabe com o que a pessoa vai entrar.
      setFeito(`${novo.nome} cadastrado. Entra com ${novo.usuario}.`);
      const perfilInicial = perfis.find((perfil) => perfil.codigo === "advogado") ?? perfis[0];
      setForm({ ...VAZIO, perfilId: perfilInicial?.id ?? 0 });
      await recarregar(1);
    } catch (e) {
      setErro(e instanceof ApiError ? e.message : "Não foi possível cadastrar.");
    } finally {
      setSalvando(false);
    }
  }

  const perfilSelecionado = perfis.find((p) => p.id === form.perfilId);
  const descricaoPerfil = perfilSelecionado?.descricao;
  const inicio = total === 0 ? 0 : (pagina - 1) * TAMANHO_PAGINA;
  const fim = Math.min(inicio + itens.length, total);
  const ativos = itens.filter((usuario) => usuario.ativo).length;
  const semPerfil = itens.filter((usuario) => usuario.perfis.length === 0).length;

  return (
    <div className="min-w-0 space-y-5">
      <Botao variante="texto" onClick={onVoltar} className="inline-flex items-center gap-2">
        <ArrowLeft size={16} aria-hidden />
        Voltar para a carteira
      </Botao>

      <header className="flex min-w-0 flex-wrap items-end justify-between gap-4">
        <div className="min-w-0">
          <p className="mb-2 mt-0 font-ui text-xs font-bold uppercase tracking-[0.12em] text-tinta-3">
            Administração
          </p>
          <h1 className="mb-[6px] mt-0 text-tinta font-titulo text-xl font-semibold">
            Usuários
          </h1>
          <p className="m-0 max-w-[66ch] text-tinta-3 leading-[1.5]">
            Quem pode entrar no sistema, com qual perfil e em que situação. O e-mail
            continua sendo o login oficial do escritório.
          </p>
        </div>
        <div className="grid min-w-[220px] grid-cols-2 gap-2 max-[520px]:w-full">
          <div className="rounded-campo border border-borda bg-papel-2 px-3 py-2">
            <div className="text-xs font-semibold text-tinta-3">Nesta página</div>
            <div className="mt-1 font-titulo text-lg font-semibold text-tinta tabular-nums">
              {itens.length}
            </div>
          </div>
          <div className="rounded-campo border border-borda bg-papel-2 px-3 py-2">
            <div className="text-xs font-semibold text-tinta-3">Ativos</div>
            <div className="mt-1 font-titulo text-lg font-semibold text-ok tabular-nums">
              {ativos}
            </div>
          </div>
        </div>
      </header>

      {(erro || feito) && (
        <div className="space-y-3">
          {erro && (
            <Aviso tom="critico" titulo="Não deu para cadastrar ou carregar">
              {erro}
            </Aviso>
          )}
          {feito && (
            <Aviso tom="ok" titulo="Usuário cadastrado">
              {feito}
            </Aviso>
          )}
        </div>
      )}

      <div className="grid min-w-0 grid-cols-[minmax(min(100%,320px),400px)_minmax(0,1fr)] items-start gap-5 max-[920px]:grid-cols-1">
        <Cartao
          titulo={
            <span className="inline-flex min-w-0 items-center gap-2">
              <UserPlus size={18} className="text-acao" aria-hidden />
              <span className="truncate">Cadastrar acesso</span>
            </span>
          }
          subtitulo="Dados mínimos para liberar entrada no sistema."
          className="min-w-0 overflow-hidden"
        >
          <form onSubmit={enviar} className="grid gap-4">
            <div>
              <RotuloCampo>Nome completo</RotuloCampo>
              <Campo
                required
                minLength={3}
                value={form.nome}
                onChange={(e) => setForm({ ...form, nome: e.target.value })}
                placeholder="Mariana Alves Souza"
              />
            </div>

            <div>
              <RotuloCampo>E-mail</RotuloCampo>
              <Campo
                required
                type="email"
                value={form.email}
                onChange={(e) => setForm({ ...form, email: e.target.value })}
                placeholder="mariana@escritorio.adv.br"
              />
              <AjudaCampo>
                É com ele que a pessoa entra — não há usuário separado.
              </AjudaCampo>
            </div>

            <div>
              <RotuloCampo>Perfil</RotuloCampo>
              <CampoSeletor
                value={form.perfilId || ""}
                onChange={(e) => setForm({ ...form, perfilId: Number(e.target.value) })}
                disabled={perfis.length === 0}
              >
                {perfis.length === 0 && <option value="">— nenhum perfil disponível —</option>}
                {perfis.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.rotulo}
                  </option>
                ))}
              </CampoSeletor>
              {erroPerfis && (
                <small className="block mt-[5px] text-critico leading-[1.4]">{erroPerfis}</small>
              )}
              {descricaoPerfil && (
                <AjudaCampo className="line-clamp-3">{descricaoPerfil}</AjudaCampo>
              )}
            </div>

            <div>
              <RotuloCampo>Senha</RotuloCampo>
              <Campo
                required
                type="password"
                minLength={8}
                value={form.senha}
                onChange={(e) => setForm({ ...form, senha: e.target.value })}
                placeholder="ao menos 8 caracteres"
              />
              <AjudaCampo>
                Vale já no primeiro acesso; a pessoa troca depois se quiser.
              </AjudaCampo>
            </div>

            <Botao
              type="submit"
              variante="primario"
              bloco
              disabled={salvando || !perfilSelecionado}
            >
              <UserPlus size={16} aria-hidden />
              {salvando ? "Cadastrando…" : "Cadastrar usuário"}
            </Botao>
          </form>

          {/* O perfil Cliente existe, mas o caminho do cliente é o portal do
            * caso, com a senha dele. Dizer isto aqui evita cadastrar cliente
            * achando que é assim que ele acompanha o processo. */}
          {perfilSelecionado?.codigo === "cliente" && (
            <div className="mt-4">
            <Aviso tom="atencao" titulo="Antes de cadastrar um cliente">
              O cliente acompanha o caso pelo <strong>portal</strong>, com o link e a
              senha do próprio caso — não precisa de conta aqui. Uma conta com perfil
              Cliente entra no sistema, mas não alcança casos, documentos nem
              entrevistas.
            </Aviso>
            </div>
          )}
        </Cartao>

        <Cartao
          titulo={
            <span className="inline-flex min-w-0 items-center gap-2">
              <UsersRound size={18} className="text-acao" aria-hidden />
              <span className="truncate">Acessos cadastrados</span>
            </span>
          }
          subtitulo={
            total > 0
              ? `${total.toLocaleString("pt-BR")} conta(s) no cadastro.`
              : "A lista aparece assim que houver contas cadastradas."
          }
          className="min-w-0 overflow-hidden"
        >
          {carregando ? (
            <p className="m-0 text-tinta-3">Carregando…</p>
          ) : itens.length === 0 ? (
            <Vazio>Ninguém cadastrado ainda.</Vazio>
          ) : (
            <>
              {semPerfil > 0 && (
                <Aviso tom="atencao" titulo="Conta sem perfil nesta página">
                  {semPerfil} conta(s) precisam de ajuste de perfil antes de operar.
                </Aviso>
              )}
              <div className="mt-4 max-w-full overflow-x-auto rounded-campo border border-borda">
                <Tabela className="min-w-[720px]">
                  <thead>
                    <tr>
                      <Th>Usuário</Th>
                      <Th>Login</Th>
                      <Th>Perfil</Th>
                      <Th>Situação</Th>
                    </tr>
                  </thead>
                  <tbody>
                    {itens.map((u) => (
                      <TrZebra key={u.id}>
                        <Td>
                          <span className="flex min-w-0 items-center gap-2">
                            <span className="grid size-8 shrink-0 place-items-center rounded-campo border border-acao-borda bg-acao-clara text-acao">
                              <ShieldCheck size={15} aria-hidden />
                            </span>
                            <span className="min-w-0">
                              <strong className="block truncate">{u.nome}</strong>
                              <span className="block text-xs text-tinta-3 tabular-nums">ID {u.id}</span>
                            </span>
                          </span>
                        </Td>
                        <Td>
                          <span className="flex min-w-0 items-center gap-2">
                            <Mail size={14} className="shrink-0 text-tinta-3" aria-hidden />
                            <span className="min-w-0 truncate" title={u.usuario}>
                              {u.usuario}
                            </span>
                          </span>
                        </Td>
                        <Td>
                          <span className="flex max-w-[260px] flex-wrap gap-1">
                            {u.perfis.length === 0 ? (
                              <Selo tom="critico" simbolo="!">
                                sem perfil
                              </Selo>
                            ) : (
                              u.perfis.map((p) => (
                                <Selo key={p} tom="info">
                                  {p}
                                </Selo>
                              ))
                            )}
                          </span>
                        </Td>
                        <Td>
                          <Selo tom={u.ativo ? "ok" : "neutro"} simbolo={u.ativo ? "✓" : "•"}>
                            {u.ativo ? "ativo" : "inativo"}
                          </Selo>
                        </Td>
                      </TrZebra>
                    ))}
                  </tbody>
                </Tabela>
              </div>
              <Paginacao
                pagina={pagina}
                totalPaginas={totalPaginas}
                total={total}
                inicio={inicio}
                fim={fim}
                rotulo="usuários"
                onPagina={(proxima) => {
                  setCarregando(true);
                  void recarregar(proxima);
                }}
              />
            </>
          )}
        </Cartao>
      </div>
    </div>
  );
}
