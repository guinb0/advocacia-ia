"use client";

/**
 * Edição de uma conta existente — só para o secretário.
 *
 * POR QUE O FORMULÁRIO INTEIRO, E NÃO CAMPO A CAMPO
 *
 * A tela manda a conta completa e o servidor substitui o que está gravado. Editar
 * um campo por vez parece mais leve, mas cria o caso de a tela mostrar um estado
 * que o banco não tem. A senha é a exceção: ela nunca sai do servidor, então o
 * campo começa vazio e vazio quer dizer "manter".
 *
 * O QUE ESTA TELA AVISA ANTES DE SALVAR
 *
 * As consequências que não se veem no formulário. Trocar o e-mail derruba a
 * sessão aberta da pessoa (o e-mail é o login). Trocar a senha NÃO derruba — o
 * token dura até 24 h —, e quem precisa cortar acesso agora deve desativar a
 * conta. Dizer isso aqui é o que evita o secretário achar que trancou uma conta
 * comprometida só porque trocou a senha dela.
 */

import { useState } from "react";
import { KeyRound, Pencil } from "lucide-react";

import {
  AjudaCampo,
  Aviso,
  Botao,
  Campo,
  CampoSeletor,
  Cartao,
  Marcacao,
  RotuloCampo,
} from "@/components/ui/Basicos";
import { BotaoProcesso } from "@/components/ui/BotaoProcesso";
import {
  ApiError,
  editarUsuario,
  type Perfil,
  type UsuarioCadastrado,
} from "@/lib/api";

/** (61) 99999-0000 a partir dos dígitos. Número fora do padrão volta como veio. */
export function formatarTelefone(valor: string): string {
  const digitos = valor.replace(/\D/g, "");
  const nacional = digitos.length > 11 && digitos.startsWith("55") ? digitos.slice(2) : digitos;
  if (nacional.length === 11) {
    return `(${nacional.slice(0, 2)}) ${nacional.slice(2, 7)}-${nacional.slice(7)}`;
  }
  if (nacional.length === 10) {
    return `(${nacional.slice(0, 2)}) ${nacional.slice(2, 6)}-${nacional.slice(6)}`;
  }
  return valor;
}

/** Como cada campo que o servidor devolve em `alterados` aparece para quem lê. */
const ROTULO_ALTERADO: Record<string, string> = {
  nome: "nome",
  email: "e-mail",
  telefone: "telefone",
  perfil: "perfil",
  "situação": "situação",
  senha: "senha",
  "senha padrão": "senha (voltou para a padrão)",
};

interface Props {
  usuario: UsuarioCadastrado;
  perfis: Perfil[];
  /** A conta aberta é a de quem está editando: perfil e situação ficam travados. */
  contaPropria: boolean;
  onCancelar: () => void;
  onSalvo: (resumo: string) => void | Promise<void>;
}

export default function EditarUsuario({
  usuario,
  perfis,
  contaPropria,
  onCancelar,
  onSalvo,
}: Props) {
  const emailOriginal = (usuario.email ?? usuario.usuario ?? "").toLowerCase();
  const perfilOriginal =
    usuario.perfilId ?? perfis.find((p) => p.codigo === usuario.perfis[0])?.id ?? 0;

  const [form, setForm] = useState({
    nome: usuario.nome,
    email: usuario.email ?? usuario.usuario ?? "",
    telefone: usuario.telefone ? formatarTelefone(usuario.telefone) : "",
    perfilId: perfilOriginal,
    ativo: usuario.ativo,
    senha: "",
    redefinirSenha: false,
  });
  const [salvando, setSalvando] = useState(false);
  const [erro, setErro] = useState<string | null>(null);

  const emailMudou = form.email.trim().toLowerCase() !== emailOriginal;
  const perfilSelecionado = perfis.find((p) => p.id === form.perfilId);
  const desativando = usuario.ativo && !form.ativo;

  const pendencia = !perfilSelecionado
    ? "Escolha o perfil da conta."
    : form.senha && form.senha.length < 8
      ? "A senha nova precisa de pelo menos 8 caracteres."
      : null;

  async function salvar(evento: React.FormEvent) {
    evento.preventDefault();
    setSalvando(true);
    setErro(null);
    try {
      const r = await editarUsuario(usuario.id, {
        ...form,
        nome: form.nome.trim(),
        email: form.email.trim(),
      });
      const resumo =
        r.alterados.length === 0
          ? `${r.nome}: nada mudou.`
          : `${r.nome}: ${r.alterados.map((c) => ROTULO_ALTERADO[c] ?? c).join(", ")} — alterado.`;
      await onSalvo(resumo);
    } catch (e) {
      setErro(e instanceof ApiError ? e.message : "Não foi possível salvar as alterações.");
    } finally {
      setSalvando(false);
    }
  }

  return (
    <Cartao
      titulo={
        <span className="inline-flex min-w-0 items-center gap-2">
          <Pencil size={18} className="text-acao" aria-hidden />
          <span className="truncate">Editar {usuario.nome}</span>
        </span>
      }
      subtitulo={`ID ${usuario.id}. As alterações valem assim que forem salvas.`}
      className="min-w-0 overflow-hidden"
    >
      {erro && (
        <div className="mb-4">
          <Aviso tom="critico" titulo="Não deu para salvar">
            {erro}
          </Aviso>
        </div>
      )}

      <form onSubmit={salvar} className="grid gap-4">
        <div className="grid gap-4 grid-cols-2 max-[720px]:grid-cols-1">
          <div>
            <RotuloCampo>Nome completo</RotuloCampo>
            <Campo
              required
              minLength={3}
              maxLength={120}
              value={form.nome}
              onChange={(e) => setForm({ ...form, nome: e.target.value })}
            />
          </div>

          <div>
            <RotuloCampo>E-mail (login)</RotuloCampo>
            <Campo
              required
              type="email"
              maxLength={160}
              value={form.email}
              onChange={(e) => setForm({ ...form, email: e.target.value })}
            />
            {emailMudou && (
              <AjudaCampo className="text-atencao">
                {contaPropria
                  ? "Você passa a entrar com o e-mail novo."
                  : "A pessoa passa a entrar com o e-mail novo, e a sessão aberta dela cai."}
              </AjudaCampo>
            )}
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
            <AjudaCampo>Opcional. Deixe vazio para apagar.</AjudaCampo>
          </div>

          <div>
            <RotuloCampo>Perfil (cargo)</RotuloCampo>
            <CampoSeletor
              value={form.perfilId || ""}
              onChange={(e) => setForm({ ...form, perfilId: Number(e.target.value) })}
              disabled={contaPropria || perfis.length === 0}
            >
              {!perfilSelecionado && <option value="">— escolha um perfil —</option>}
              {perfis.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.rotulo}
                </option>
              ))}
            </CampoSeletor>
            <AjudaCampo>
              {contaPropria
                ? "O próprio perfil não se muda por aqui: peça a outro secretário."
                : "Vale na hora, sem a pessoa precisar sair e entrar."}
            </AjudaCampo>
          </div>
        </div>

        <div>
          <Marcacao>
            <input
              type="checkbox"
              checked={form.ativo}
              disabled={contaPropria}
              onChange={(e) => setForm({ ...form, ativo: e.target.checked })}
            />
            <span>
              <strong>Conta ativa</strong>
              <br />
              {contaPropria
                ? "Você não pode desativar a própria conta."
                : "Desmarcada, a pessoa perde o acesso imediatamente — inclusive a sessão aberta."}
            </span>
          </Marcacao>
        </div>

        <div className="rounded-campo border border-borda bg-papel-2 p-4">
          <div className="mb-3 flex items-center gap-2 text-sm font-semibold text-tinta">
            <KeyRound size={16} className="text-acao" aria-hidden />
            Senha
          </div>
          <div className="grid gap-3">
            <div>
              <RotuloCampo>Senha nova</RotuloCampo>
              <Campo
                type="password"
                autoComplete="new-password"
                minLength={8}
                maxLength={128}
                value={form.senha}
                disabled={form.redefinirSenha}
                onChange={(e) => setForm({ ...form, senha: e.target.value })}
                placeholder="vazio mantém a senha atual"
              />
            </div>
            <Marcacao>
              <input
                type="checkbox"
                checked={form.redefinirSenha}
                onChange={(e) =>
                  setForm({ ...form, redefinirSenha: e.target.checked, senha: "" })
                }
              />
              <span>
                Voltar para a <strong>senha padrão</strong> — a pessoa é obrigada a criar
                uma senha nova no próximo acesso.
              </span>
            </Marcacao>
            {(form.senha || form.redefinirSenha) && !desativando && (
              <Aviso tom="info" titulo="Trocar a senha não derruba sessão aberta">
                Quem já está com o sistema aberto continua até a sessão vencer (até 24 h).
                Para cortar o acesso agora, desmarque <strong>Conta ativa</strong>.
              </Aviso>
            )}
          </div>
        </div>

        <div className="flex flex-wrap justify-end gap-2">
          <Botao type="button" variante="secundario" onClick={onCancelar} disabled={salvando}>
            Cancelar
          </Botao>
          <BotaoProcesso
            type="submit"
            variante="primario"
            processando={salvando}
            textoProcessando="Salvando…"
            pendencia={pendencia}
          >
            Salvar alterações
          </BotaoProcesso>
        </div>
      </form>
    </Cartao>
  );
}
