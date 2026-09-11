"use client";

/* Cadastro de quem usa o sistema.
 *
 * Poucos campos, e é de propósito: conta se cria no meio do atendimento, com
 * alguém esperando. Nome, e-mail, perfil e senha bastam para entrar; o telefone
 * é opcional. CPF e endereço o cadastro do CASO já coleta, e pedir duas vezes é
 * a forma mais rápida de ninguém preencher nenhuma das duas.
 *
 * Editar uma conta que já existe é outra coisa — é poder entrar como aquela
 * pessoa — e fica só com o secretário (ver `EditarUsuario.tsx`).
 *
 * A lista fica ao lado do formulário, e não atrás de um botão, porque a pergunta
 * que antecede "cadastrar" quase sempre é "ele já não está aí?".
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { ArrowLeft, LayoutList, Mail, Pencil, Phone, ShieldCheck, UserPlus, UsersRound } from "lucide-react";

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
import { BotaoProcesso } from "@/components/ui/BotaoProcesso";
import {
  ApiError,
  criarUsuario,
  listarPerfis,
  listarUsuariosPaginado,
  type Perfil,
  type UsuarioCadastrado,
} from "@/lib/api";
/* A matriz de perfis mora nesta tela, e não numa própria, porque as duas
 * respondem à mesma pergunta em ordens diferentes: aqui se escolhe o perfil de
 * alguém, e é aqui que se descobre que o perfil disponível não alcança o que a
 * pessoa precisa. Separá-las obrigaria a sair da tela para conferir isso. */
import PerfisDeAcesso from "@/components/PerfisDeAcesso";
import ModelosContrato from "@/components/admin/ModelosContrato";
import EditarUsuario, { formatarTelefone } from "@/components/admin/EditarUsuario";
import { useSessao } from "@/lib/auth";

interface Props {
  onVoltar: () => void;
}

const VAZIO = { nome: "", email: "", telefone: "", perfilId: 0, senha: "" };
const TAMANHO_PAGINA = 12;

export default function Usuarios({ onVoltar }: Props) {
  const [aba, setAba] = useState<"membros" | "perfis" | "contratos">("membros");
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

  /* Só o secretário edita conta existente. Esconder o botão aqui é para não
   * oferecer o que vai dar 403 — quem de fato barra é o servidor
   * (`PodeEditarContas`), e é lá que a regra vale. */
  const sessao = useSessao();
  const podeEditar = sessao.papeis.includes("secretario");
  const [editando, setEditando] = useState<UsuarioCadastrado | null>(null);
  const [editado, setEditado] = useState<string | null>(null);

  /* O cartão de edição nasce no topo da tela, e o botão fica lá embaixo, na linha
   * da tabela. `window.scrollTo` não servia: a partir de `lg` quem rola é a área de
   * conteúdo do `AppShell`, não a janela — o cartão abria fora da vista e o clique
   * parecia não fazer nada. `scrollIntoView` acha o contêiner certo sozinho. */
  const cartaoEdicao = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const cartao = cartaoEdicao.current;
    if (!editando || !cartao) return;
    cartao.scrollIntoView({ behavior: "smooth", block: "start" });
    cartao.querySelector<HTMLInputElement>("input")?.focus({ preventScroll: true });
  }, [editando]);

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
            Administração de acessos
          </h1>
          <p className="m-0 max-w-[66ch] text-tinta-3 leading-[1.5]">
            Membros, perfis e permissões do escritório. O e-mail continua sendo o
            login oficial do sistema.
          </p>
        </div>
        <div className="grid min-w-[220px] grid-cols-2 gap-2 max-[520px]:w-full">
          <div className="rounded-campo border border-borda bg-papel-2 px-3 py-2">
            <div className="text-xs font-semibold text-tinta-3">Membros cadastrados</div>
            <div className="mt-1 font-titulo text-lg font-semibold text-tinta tabular-nums">
              {total}
            </div>
          </div>
          <div className="rounded-campo border border-borda bg-papel-2 px-3 py-2">
            <div className="text-xs font-semibold text-tinta-3">Membros ativos</div>
            <div className="mt-1 font-titulo text-lg font-semibold text-ok tabular-nums">
              {ativos}
            </div>
          </div>
        </div>
      </header>

      <nav
        className="flex w-full gap-1 overflow-x-auto rounded-cartao border border-borda bg-papel p-1"
        aria-label={"Administra\u00e7\u00e3o de acessos"}
      >
        <button
          type="button"
          onClick={() => setAba("membros")}
          aria-current={aba === "membros" ? "page" : undefined}
          className={
            "inline-flex min-h-10 shrink-0 items-center gap-2 rounded-campo px-4 text-sm font-semibold transition-colors " +
            (aba === "membros"
              ? "bg-acao text-papel shadow-cartao"
              : "text-tinta-2 hover:bg-papel-3 hover:text-tinta")
          }
        >
          <UsersRound size={16} aria-hidden />
          Membros e acessos
        </button>
        <button
          type="button"
          onClick={() => setAba("perfis")}
          aria-current={aba === "perfis" ? "page" : undefined}
          className={
            "inline-flex min-h-10 shrink-0 items-center gap-2 rounded-campo px-4 text-sm font-semibold transition-colors " +
            (aba === "perfis"
              ? "bg-acao text-papel shadow-cartao"
              : "text-tinta-2 hover:bg-papel-3 hover:text-tinta")
          }
        >
          <LayoutList size={16} aria-hidden />
          {"Perfis e permiss\u00f5es"}
        </button>
        {sessao.modulos.includes("contratos") && (
          <button
            type="button"
            onClick={() => setAba("contratos")}
            aria-current={aba === "contratos" ? "page" : undefined}
            className={
              "inline-flex min-h-10 shrink-0 items-center gap-2 rounded-campo px-4 text-sm font-semibold transition-colors " +
              (aba === "contratos" ? "bg-acao text-papel shadow-cartao" : "text-tinta-2 hover:bg-papel-3 hover:text-tinta")
            }
          >
            <ShieldCheck size={16} aria-hidden />
            Modelos de contrato
          </button>
        )}
      </nav>

      {aba === "membros" && <>
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

      {editado && !editando && (
        <Aviso tom="ok" titulo="Alterações salvas">
          {editado}
        </Aviso>
      )}

      {editando && (
        <div ref={cartaoEdicao} className="scroll-mt-4">
          <EditarUsuario
            key={editando.id}
            usuario={editando}
            perfis={perfis}
            contaPropria={
              (editando.email ?? editando.usuario ?? "").toLowerCase() ===
              sessao.usuario.toLowerCase()
            }
            onCancelar={() => setEditando(null)}
            onSalvo={async (resumo) => {
              setEditando(null);
              setEditado(resumo);
              await recarregar(pagina);
            }}
          />
        </div>
      )}

      <div className="space-y-5">
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
          <form onSubmit={enviar} className="grid grid-cols-2 gap-x-5 gap-y-4 max-[720px]:grid-cols-1">
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
              <RotuloCampo>Telefone</RotuloCampo>
              <Campo
                type="tel"
                inputMode="tel"
                maxLength={30}
                value={form.telefone}
                onChange={(e) => setForm({ ...form, telefone: e.target.value })}
                placeholder="(61) 99999-0000"
              />
              <AjudaCampo>Opcional.</AjudaCampo>
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

            <div className="col-span-2 flex flex-wrap items-center justify-between gap-3 border-t border-borda pt-4 max-[720px]:col-span-1">
              <span className="text-xs leading-[1.45] text-tinta-3">
                O acesso fica ativo assim que o cadastro for confirmado.
              </span>
            <BotaoProcesso
              type="submit"
              variante="primario"
              processando={salvando}
              textoProcessando="Cadastrando…"
              pendencia={perfilSelecionado ? null : "Escolha o perfil do novo usuário."}
            >
              <UserPlus size={16} aria-hidden />
              Cadastrar usuário
            </BotaoProcesso>
            </div>
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
                      {podeEditar && <Th className="text-right">Ação</Th>}
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
                          {u.telefone && (
                            <span className="mt-1 flex items-center gap-2 text-xs text-tinta-3 tabular-nums">
                              <Phone size={12} className="shrink-0" aria-hidden />
                              {formatarTelefone(u.telefone)}
                            </span>
                          )}
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
                        {podeEditar && (
                          <Td className="text-right">
                            <Botao
                              pequeno
                              variante="secundario"
                              onClick={() => {
                                setEditado(null);
                                setEditando(u);
                              }}
                              aria-label={`Editar ${u.nome}`}
                            >
                              <Pencil size={14} aria-hidden />
                              Editar
                            </Botao>
                          </Td>
                        )}
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
      </>}

      {aba === "perfis" && <PerfisDeAcesso />}
      {aba === "contratos" && <ModelosContrato />}
    </div>
  );
}
