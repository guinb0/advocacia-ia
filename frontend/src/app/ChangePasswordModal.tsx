"use client";

import { useRef, useState } from "react";
import { KeyRound, ShieldAlert } from "lucide-react";

import { Botao } from "@/components/ui/Basicos";
import { useFocoContido } from "@/lib/foco";

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
  const painelRef = useRef<HTMLDivElement>(null);
  /* `aria-modal` avisa o leitor de tela, mas não segura o Tab: sem isto a
   * tabulação saía do diálogo e caía no formulário de login atrás dele, que a
   * pessoa nem está vendo. O `autoFocus` do primeiro campo continua valendo —
   * o gancho só move o foco quando ainda não há nada focado dentro. */
  useFocoContido(painelRef, aberto);

  if (!aberto) return null;

  const curta = senha.length > 0 && senha.length < 8;
  const divergem = confirmacao.length > 0 && senha !== confirmacao;
  const podeSalvar = senha.length >= 8 && senha === confirmacao && !salvando;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-acao/70 p-4 backdrop-blur-[2px] sm:p-6"
      role="dialog"
      aria-modal="true"
      aria-labelledby="titulo-troca-senha"
    >
      <div ref={painelRef} className="max-h-[90dvh] w-full max-w-[460px] overflow-y-auto rounded-cartao bg-papel shadow-modal ring-1 ring-borda">
        <div className="border-b border-borda bg-papel-2 px-6 py-5 sm:px-8">
          <div className="flex items-start gap-3">
            <span className="mt-0.5 inline-flex h-10 w-10 shrink-0 items-center justify-center rounded-campo bg-atencao-claro text-atencao ring-1 ring-atencao-borda">
              <ShieldAlert size={20} aria-hidden />
            </span>
            <div>
              <h2 id="titulo-troca-senha" className="font-titulo text-lg text-tinta">
                Escolha uma senha
              </h2>
              <p className="mt-1 text-sm leading-6 text-tinta-2">
                Sua conta ainda está com a senha padrão. Defina uma senha própria para continuar.
              </p>
            </div>
          </div>
        </div>

        <form
          className="flex flex-col gap-4 px-6 py-6 sm:px-8"
          onSubmit={(evento) => {
            evento.preventDefault();
            if (podeSalvar) onSalvar(senha);
          }}
        >
          <div className="flex flex-col gap-1.5">
            <label htmlFor="nova-senha" className="text-sm font-semibold text-tinta">
              Nova senha
            </label>
            <div className="relative">
              <KeyRound
                size={17}
                className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-tinta-3"
                aria-hidden
              />
              <input
                id="nova-senha"
                type="password"
                autoComplete="new-password"
                autoFocus
                value={senha}
                onChange={(e) => setSenha(e.target.value)}
                className="min-h-[44px] w-full rounded-campo border border-borda-campo bg-papel px-10 py-2.5 text-base text-tinta outline-none transition-[border-color,box-shadow] focus:border-foco focus:ring-2 focus:ring-foco/30"
                aria-describedby="ajuda-nova-senha"
              />
            </div>
            <span id="ajuda-nova-senha" className={curta ? "text-xs text-critico" : "text-xs text-tinta-3"}>
              Pelo menos 8 caracteres.
            </span>
          </div>

          <div className="flex flex-col gap-1.5">
            <label htmlFor="confirma-senha" className="text-sm font-semibold text-tinta">
              Repita a senha
            </label>
            <div className="relative">
              <KeyRound
                size={17}
                className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-tinta-3"
                aria-hidden
              />
              <input
                id="confirma-senha"
                type="password"
                autoComplete="new-password"
                value={confirmacao}
                onChange={(e) => setConfirmacao(e.target.value)}
                className="min-h-[44px] w-full rounded-campo border border-borda-campo bg-papel px-10 py-2.5 text-base text-tinta outline-none transition-[border-color,box-shadow] focus:border-foco focus:ring-2 focus:ring-foco/30"
                aria-invalid={divergem}
                aria-describedby={divergem ? "erro-confirma-senha" : undefined}
              />
            </div>
            {divergem && <span id="erro-confirma-senha" className="text-xs text-critico">As duas senhas não são iguais.</span>}
          </div>

          <Botao
            type="submit"
            variante="primario"
            bloco
            disabled={!podeSalvar && !salvando}
            carregando={salvando}
            textoCarregando="Salvando…"
            className="mt-3"
          >
            Salvar e entrar
          </Botao>
        </form>
      </div>
    </div>
  );
}
