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

import { Aviso } from "@/components/Basicos";
import {
  ApiError,
  criarUsuario,
  listarPerfis,
  listarUsuarios,
  type Perfil,
  type UsuarioCadastrado,
} from "@/lib/api";
import estilos from "./Usuarios.module.css";

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
    void listarPerfis().then(setPerfis).catch(() => setPerfis([]));
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
    <div className={estilos.container}>
      <button type="button" className="botao botao--secundario" onClick={onVoltar}>
        ← Voltar para a carteira
      </button>

      <header className={estilos.cabecalho}>
        <h1>Usuários</h1>
        <p>
          Quem pode entrar no sistema, e com qual perfil. O cadastro é o mesmo login
          usado em todas as máquinas do escritório.
        </p>
      </header>

      <div className={estilos.colunas}>
        <section className={estilos.formulario}>
          <h2>Cadastrar</h2>
          <form onSubmit={enviar}>
            <label className={estilos.campo}>
              <span>Nome completo</span>
              <input
                required
                minLength={3}
                value={form.nome}
                onChange={(e) => setForm({ ...form, nome: e.target.value })}
                placeholder="Mariana Alves Souza"
              />
            </label>

            <label className={estilos.campo}>
              <span>E-mail</span>
              <input
                required
                type="email"
                value={form.email}
                onChange={(e) => setForm({ ...form, email: e.target.value })}
                placeholder="mariana@escritorio.adv.br"
              />
              <small>É com ele que a pessoa entra — não há usuário separado.</small>
            </label>

            <label className={estilos.campo}>
              <span>Perfil</span>
              <select
                value={form.perfil}
                onChange={(e) => setForm({ ...form, perfil: e.target.value })}
              >
                {perfis.map((p) => (
                  <option key={p.codigo} value={p.codigo}>
                    {p.rotulo}
                  </option>
                ))}
              </select>
              {descricaoPerfil && <small>{descricaoPerfil}</small>}
            </label>

            <label className={estilos.campo}>
              <span>Senha</span>
              <input
                required
                type="password"
                minLength={8}
                value={form.senha}
                onChange={(e) => setForm({ ...form, senha: e.target.value })}
                placeholder="ao menos 8 caracteres"
              />
              <small>Vale já no primeiro acesso; a pessoa troca depois se quiser.</small>
            </label>

            <button type="submit" className="botao" disabled={salvando}>
              {salvando ? "Cadastrando…" : "Cadastrar usuário"}
            </button>
          </form>

          {erro && (
            <Aviso tom="critico" titulo="Não deu para cadastrar">
              {erro}
            </Aviso>
          )}
          {feito && <p className={estilos.feito}>{feito}</p>}

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

        <section className={estilos.lista}>
          <h2>Já cadastrados {itens.length > 0 && <span>({itens.length})</span>}</h2>
          {carregando ? (
            <p className={estilos.vazio}>Carregando…</p>
          ) : itens.length === 0 ? (
            <p className={estilos.vazio}>Ninguém cadastrado ainda.</p>
          ) : (
            <ul>
              {itens.map((u) => (
                <li key={u.id}>
                  <div className={estilos.pessoa}>
                    <strong>{u.nome}</strong>
                    <span className={estilos.login}>{u.usuario}</span>
                  </div>
                  <div className={estilos.marcadores}>
                    {u.perfis.length === 0 ? (
                      <span className={estilos.semPerfil}>sem perfil</span>
                    ) : (
                      u.perfis.map((p) => (
                        <span key={p} className={estilos.perfil}>
                          {p}
                        </span>
                      ))
                    )}
                    {!u.ativo && <span className={estilos.inativo}>inativo</span>}
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
