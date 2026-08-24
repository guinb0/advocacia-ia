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

import { Aviso, Botao } from "@/components/ui/Basicos";
import {
  ApiError,
  criarUsuario,
  listarPerfis,
  listarUsuarios,
  type Perfil,
  type UsuarioCadastrado,
} from "@/lib/api";

interface Props {
  onVoltar: () => void;
}

const VAZIO = { nome: "", email: "", perfil: "advogado", senha: "" };

export default function Usuarios({ onVoltar }: Props) {
  const [perfis, setPerfis] = useState<Perfil[]>([]);
  const [itens, setItens] = useState<UsuarioCadastrado[]>([]);
  const [form, setForm] = useState(VAZIO);
  const [carregando, setCarregando] = useState(true);
  const [salvando, setSalvando] = useState(false);
  const [erro, setErro] = useState<string | null>(null);
  /* Separado de `erro`: falhar em LISTAR os perfis não impede ver os usuários
   * já cadastrados, então os dois não podem disputar a mesma faixa. */
  const [erroPerfis, setErroPerfis] = useState<string | null>(null);
  const [feito, setFeito] = useState<string | null>(null);

  const recarregar = useCallback(async () => {
    try {
      setItens(await listarUsuarios());
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
    void recarregar();
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
      setForm(VAZIO);
      await recarregar();
    } catch (e) {
      setErro(e instanceof ApiError ? e.message : "Não foi possível cadastrar.");
    } finally {
      setSalvando(false);
    }
  }

  const descricaoPerfil = perfis.find((p) => p.codigo === form.perfil)?.descricao;

  return (
    <div className="max-w-[1080px] mx-auto px-5 pt-6 pb-16">
      <Botao variante="secundario" onClick={onVoltar}>
        ← Voltar para a carteira
      </Botao>

      <header className="my-5 mb-6">
        <h1 className="mb-[6px] mt-0 text-[1.6rem]">Usuários</h1>
        <p className="m-0 text-tinta-3 max-w-[62ch] leading-[1.5]">
          Quem pode entrar no sistema, e com qual perfil. O cadastro é o mesmo login
          usado em todas as máquinas do escritório.
        </p>
      </header>

      <div className="grid grid-cols-[minmax(320px,420px)_1fr] max-[860px]:grid-cols-1 gap-7 items-start">
        <section className="border border-borda-forte rounded-[10px] p-[18px] bg-papel">
          <h2 className="mb-4 mt-0 text-base uppercase tracking-[0.04em] text-tinta-3">Cadastrar</h2>
          <form onSubmit={enviar}>
            <label className="block mb-4">
              <span className="block mb-[5px] font-semibold text-[0.9rem]">Nome completo</span>
              <input
                className="w-full px-[11px] py-[9px] border border-borda-forte rounded-[7px] [font:inherit] bg-papel focus:[outline:2px_solid_var(--foco)] focus:outline-offset-[1px]"
                required
                minLength={3}
                value={form.nome}
                onChange={(e) => setForm({ ...form, nome: e.target.value })}
                placeholder="Mariana Alves Souza"
              />
            </label>

            <label className="block mb-4">
              <span className="block mb-[5px] font-semibold text-[0.9rem]">E-mail</span>
              <input
                className="w-full px-[11px] py-[9px] border border-borda-forte rounded-[7px] [font:inherit] bg-papel focus:[outline:2px_solid_var(--foco)] focus:outline-offset-[1px]"
                required
                type="email"
                value={form.email}
                onChange={(e) => setForm({ ...form, email: e.target.value })}
                placeholder="mariana@escritorio.adv.br"
              />
              <small className="block mt-[5px] text-tinta-3 leading-[1.4]">
                É com ele que a pessoa entra — não há usuário separado.
              </small>
            </label>

            <label className="block mb-4">
              <span className="block mb-[5px] font-semibold text-[0.9rem]">Perfil</span>
              {/* `text-tinta` no select E cor nas `option` não é redundância. O
                * `globals.css` põe `color: inherit` em todo select, então sem isto
                * ele herda a cor do rótulo; e no Windows a lista ABERTA de um
                * select sem cor/fundo próprios herda as do sistema — o resultado
                * é uma faixa preta sem texto legível. Mesmo defeito já registrado
                * em `ModelosDePeticao`. */}
              <select
                className="w-full px-[11px] py-[9px] border border-borda-forte rounded-[7px] [font:inherit] bg-papel text-tinta [&>option]:bg-papel [&>option]:text-tinta focus:[outline:2px_solid_var(--foco)] focus:outline-offset-[1px] disabled:text-tinta-3"
                value={form.perfil}
                onChange={(e) => setForm({ ...form, perfil: e.target.value })}
                disabled={perfis.length === 0}
              >
                {perfis.length === 0 && <option value="">— nenhum perfil disponível —</option>}
                {perfis.map((p) => (
                  <option key={p.codigo} value={p.codigo}>
                    {p.rotulo}
                  </option>
                ))}
              </select>
              {erroPerfis && (
                <small className="block mt-[5px] text-critico leading-[1.4]">{erroPerfis}</small>
              )}
              {descricaoPerfil && (
                <small className="block mt-[5px] text-tinta-3 leading-[1.4]">{descricaoPerfil}</small>
              )}
            </label>

            <label className="block mb-4">
              <span className="block mb-[5px] font-semibold text-[0.9rem]">Senha</span>
              <input
                className="w-full px-[11px] py-[9px] border border-borda-forte rounded-[7px] [font:inherit] bg-papel focus:[outline:2px_solid_var(--foco)] focus:outline-offset-[1px]"
                required
                type="password"
                minLength={8}
                value={form.senha}
                onChange={(e) => setForm({ ...form, senha: e.target.value })}
                placeholder="ao menos 8 caracteres"
              />
              <small className="block mt-[5px] text-tinta-3 leading-[1.4]">
                Vale já no primeiro acesso; a pessoa troca depois se quiser.
              </small>
            </label>

            {/* Só o botão base, sem variante — assim como no CSS original. */}
            <button
              type="submit"
              className="inline-flex items-center justify-center gap-2 min-h-10 px-4 py-[9px] border border-transparent rounded-campo bg-transparent font-ui text-sm font-semibold text-tinta-2 cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed"
              disabled={salvando}
            >
              {salvando ? "Cadastrando…" : "Cadastrar usuário"}
            </button>
          </form>

          {erro && (
            <Aviso tom="critico" titulo="Não deu para cadastrar">
              {erro}
            </Aviso>
          )}
          {feito && (
            <p className="mt-[14px] mb-0 px-3 py-[10px] rounded-[7px] bg-ok-claro text-ok">{feito}</p>
          )}

          {/* O perfil Cliente existe, mas o caminho do cliente é o portal do
            * caso, com a senha dele. Dizer isto aqui evita cadastrar cliente
            * achando que é assim que ele acompanha o processo. */}
          {form.perfil === "cliente" && (
            <Aviso tom="atencao" titulo="Antes de cadastrar um cliente">
              O cliente acompanha o caso pelo <strong>portal</strong>, com o link e a
              senha do próprio caso — não precisa de conta aqui. Uma conta com perfil
              Cliente entra no sistema, mas não alcança casos, documentos nem
              entrevistas.
            </Aviso>
          )}
        </section>

        <section className="border border-borda-forte rounded-[10px] p-[18px] bg-papel">
          <h2 className="mb-4 mt-0 text-base uppercase tracking-[0.04em] text-tinta-3">
            Já cadastrados{" "}
            {itens.length > 0 && <span className="normal-case tracking-normal">({itens.length})</span>}
          </h2>
          {carregando ? (
            <p className="m-0 text-tinta-3">Carregando…</p>
          ) : itens.length === 0 ? (
            <p className="m-0 text-tinta-3">Ninguém cadastrado ainda.</p>
          ) : (
            <ul className="list-none m-0 p-0">
              {itens.map((u) => (
                <li
                  key={u.id}
                  className="flex justify-between items-center gap-3 py-[11px] border-b border-borda last:border-b-0"
                >
                  <div className="flex flex-col min-w-0">
                    <strong>{u.nome}</strong>
                    <span className="text-tinta-3 text-[0.85rem] [overflow-wrap:anywhere]">{u.usuario}</span>
                  </div>
                  <div className="flex gap-[6px] flex-shrink-0">
                    {u.perfis.length === 0 ? (
                      <span className="px-[9px] py-[2px] rounded-pill text-[0.78rem] whitespace-nowrap bg-critico-claro text-critico">
                        sem perfil
                      </span>
                    ) : (
                      u.perfis.map((p) => (
                        <span
                          key={p}
                          className="px-[9px] py-[2px] rounded-pill text-[0.78rem] whitespace-nowrap bg-acao-clara text-acao"
                        >
                          {p}
                        </span>
                      ))
                    )}
                    {!u.ativo && (
                      <span className="px-[9px] py-[2px] rounded-pill text-[0.78rem] whitespace-nowrap bg-papel-3 text-tinta-3">
                        inativo
                      </span>
                    )}
                  </div>
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>
    </div>
  );
}
