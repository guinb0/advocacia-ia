"use client";

import { useState } from "react";

import { Botao } from "@/components/ui/Basicos";

/**
 * A troca obrigatória da senha padrão.
 *
 * Não tem botão de fechar, e isso é o ponto: ele aparece quando a conta ainda
 * está com `123456`, que é a senha que todo mundo do escritório sabe qual é.
 * Um "depois eu troco" seria clicado todas as vezes, e a conta ficaria assim
 * para sempre. O caminho de fuga existe e é honesto — recarregar a página deixa
 * a pessoa fora do sistema, porque `/home` continua exigindo a troca.
 */
export default function ChangePasswordModal({
  aberto,
  salvando,
  onSalvar,
}: {
  aberto: boolean;
  salvando: boolean;
  onSalvar: (novaSenha: string) => void;
}) {
  const [senha, setSenha] = useState("");
  const [confirmacao, setConfirmacao] = useState("");

  if (!aberto) return null;

  const curta = senha.length > 0 && senha.length < 8;
  const divergem = confirmacao.length > 0 && senha !== confirmacao;
  const podeSalvar = senha.length >= 8 && senha === confirmacao && !salvando;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-tinta/50 p-6"
      role="dialog"
      aria-modal="true"
      aria-labelledby="titulo-troca-senha"
    >
      <div className="w-full max-w-[420px] rounded-cartao bg-papel p-8 shadow-modal">
        <h2 id="titulo-troca-senha" className="font-titulo text-lg text-tinta">
          Escolha uma senha
        </h2>
        <p className="mt-2 text-sm text-tinta-2">
          Sua conta ainda está com a senha padrão. Defina uma senha própria para continuar.
        </p>

        <form
          className="mt-6 flex flex-col gap-4"
          onSubmit={(evento) => {
            evento.preventDefault();
            if (podeSalvar) onSalvar(senha);
          }}
        >
          <div className="flex flex-col gap-1.5">
            <label htmlFor="nova-senha" className="text-sm font-medium text-tinta-2">
              Nova senha
            </label>
            <input
              id="nova-senha"
              type="password"
              autoComplete="new-password"
              autoFocus
              value={senha}
              onChange={(e) => setSenha(e.target.value)}
              className="rounded-campo border border-borda-campo bg-papel-2 px-3 py-2.5 text-base text-tinta outline-none focus:border-foco focus:ring-2 focus:ring-foco/30"
              aria-describedby="ajuda-nova-senha"
            />
            <span id="ajuda-nova-senha" className={curta ? "text-xs text-critico" : "text-xs text-tinta-3"}>
              Pelo menos 8 caracteres.
            </span>
          </div>

          <div className="flex flex-col gap-1.5">
            <label htmlFor="confirma-senha" className="text-sm font-medium text-tinta-2">
              Repita a senha
            </label>
            <input
              id="confirma-senha"
              type="password"
              autoComplete="new-password"
              value={confirmacao}
              onChange={(e) => setConfirmacao(e.target.value)}
              className="rounded-campo border border-borda-campo bg-papel-2 px-3 py-2.5 text-base text-tinta outline-none focus:border-foco focus:ring-2 focus:ring-foco/30"
              aria-invalid={divergem}
            />
            {divergem && <span className="text-xs text-critico">As duas senhas não são iguais.</span>}
          </div>

          <Botao type="submit" variante="primario" bloco disabled={!podeSalvar} className="mt-2">
            {salvando ? "Salvando…" : "Salvar e entrar"}
          </Botao>
        </form>
      </div>
    </div>
  );
}
