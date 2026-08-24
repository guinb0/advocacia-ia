"use client";

import { Eye, EyeOff, Loader2 } from "lucide-react";

import { Botao } from "@/components/ui/Basicos";

import ChangePasswordModal from "./ChangePasswordModal";
import type { usePageModel } from "./page.model";

type LoginPageProps = ReturnType<typeof usePageModel>;

export function LoginPage(props: LoginPageProps) {
  const {
    form,
    onSubmit,
    entrando,
    mostrarSenha,
    setMostrarSenha,
    trocaDeSenhaAberta,
    aoTrocarSenha,
    trocandoSenha,
  } = props;

  const {
    register,
    handleSubmit,
    formState: { errors },
  } = form;

  return (
    <main className="flex min-h-screen items-center justify-center bg-fundo p-6">
      <div className="w-full max-w-[420px] rounded-cartao bg-papel p-8 shadow-cartao-forte ring-1 ring-borda-forte">
        <span className="font-titulo text-xl text-tinta">Acervo</span>
        <p className="mt-1 text-sm text-tinta-3">Documentos e casos do escritório</p>

        <hr className="my-6 border-borda" />

        <h1 className="font-titulo text-lg text-tinta">Entrar no sistema</h1>
        <p className="mt-2 text-sm text-tinta-2">
          A carteira de casos e os documentos dos clientes exigem identificação.
        </p>

        <form onSubmit={handleSubmit(onSubmit)} className="mt-6 flex flex-col gap-4" noValidate>
          <div className="flex flex-col gap-1.5">
            <label htmlFor="email" className="text-sm font-medium text-tinta-2">
              E-mail
            </label>
            <input
              id="email"
              type="email"
              autoComplete="username"
              autoFocus
              {...register("email")}
              className="rounded-campo border border-borda-campo bg-papel-2 px-3 py-2.5 text-base text-tinta outline-none focus:border-foco focus:ring-2 focus:ring-foco/30"
              /* `aria-invalid` e o `id` do erro: quem usa leitor de tela ouve
               * "campo inválido" e o motivo junto, em vez de só encontrar um
               * texto vermelho solto depois do campo. */
              aria-invalid={Boolean(errors.email)}
              aria-describedby={errors.email ? "erro-email" : undefined}
            />
            {errors.email && (
              <span id="erro-email" className="text-xs text-critico">
                {errors.email.message}
              </span>
            )}
          </div>

          <div className="flex flex-col gap-1.5">
            <label htmlFor="senha" className="text-sm font-medium text-tinta-2">
              Senha
            </label>
            <div className="relative">
              <input
                id="senha"
                type={mostrarSenha ? "text" : "password"}
                autoComplete="current-password"
                {...register("senha")}
                className="w-full rounded-campo border border-borda-campo bg-papel-2 px-3 py-2.5 pr-11 text-base text-tinta outline-none focus:border-foco focus:ring-2 focus:ring-foco/30"
                aria-invalid={Boolean(errors.senha)}
                aria-describedby={errors.senha ? "erro-senha" : undefined}
              />
              <button
                type="button"
                onClick={() => setMostrarSenha(!mostrarSenha)}
                className="absolute right-2 top-1/2 -translate-y-1/2 rounded-campo p-1.5 text-tinta-3 hover:bg-papel-3"
                aria-label={mostrarSenha ? "Ocultar a senha" : "Mostrar a senha"}
              >
                {mostrarSenha ? <EyeOff size={18} /> : <Eye size={18} />}
              </button>
            </div>
            {errors.senha && (
              <span id="erro-senha" className="text-xs text-critico">
                {errors.senha.message}
              </span>
            )}
          </div>

          <Botao type="submit" variante="primario" bloco disabled={entrando} className="mt-2">
            {entrando && <Loader2 size={18} className="animate-spin" />}
            {entrando ? "Entrando…" : "Entrar"}
          </Botao>
        </form>
      </div>

      {/* O aviso de erro não fica aqui: o `useMutateLogin` já o mostra em toast.
        * Repeti-lo na tela daria duas mensagens para a mesma falha. */}
      <ChangePasswordModal
        aberto={trocaDeSenhaAberta}
        salvando={trocandoSenha}
        onSalvar={aoTrocarSenha}
      />
    </main>
  );
}

export default LoginPage;
