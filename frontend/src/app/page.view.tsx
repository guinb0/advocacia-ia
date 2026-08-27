"use client";

import { Eye, EyeOff, FileText, Loader2 } from "lucide-react";

import ChangePasswordModal from "./ChangePasswordModal";
import LoginVisualPanel from "./LoginVisualPanel";
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
    <main className="flex min-h-screen bg-[#f4f8fc] px-4 py-6 text-[#33465c] dark:bg-[#07111d] sm:px-6 lg:px-8">
      <div className="mx-auto grid min-h-[calc(100vh-3rem)] w-full max-w-[1180px] items-center gap-6 lg:min-h-[600px] lg:grid-cols-2 lg:items-stretch xl:min-h-[680px]">
        <LoginVisualPanel />

        <section className="mx-auto flex w-full max-w-[520px] flex-col justify-center rounded-[24px] border border-[#d7e2ef] bg-white p-6 shadow-[0_22px_70px_rgba(16,32,51,0.11)] dark:border-[#2e4259] dark:bg-[#111c2a] dark:shadow-[0_28px_80px_rgba(0,0,0,0.42)] sm:p-8 lg:h-full lg:max-w-none lg:p-10">
          <div className="mx-auto w-full max-w-[390px]">
            <div className="mb-8">
              <div className="flex items-center gap-3">
                <span className="inline-flex h-11 w-11 shrink-0 items-center justify-center rounded-[12px] bg-[#002a47] text-white shadow-[0_10px_24px_rgba(0,42,71,0.22)] dark:bg-[#1f6feb]">
                  <FileText size={22} aria-hidden />
                </span>
                <div className="min-w-0">
                  <span className="block truncate font-titulo text-xl leading-none text-[#102033] dark:text-white">
                    Acervo
                  </span>
                  <span className="mt-1 block text-xs font-semibold uppercase tracking-[0.12em] text-[#65758a] dark:text-[#9fb3ca]">
                    Escritório jurídico
                  </span>
                </div>
              </div>
            </div>

            <h1 className="font-titulo text-xl !text-[#102033] dark:!text-white">Entrar no sistema</h1>
            <p className="mt-2 text-sm leading-6 text-[#33465c] dark:text-[#c8d6e5]">
              A carteira de casos e os documentos dos clientes exigem identificação.
            </p>

            <form onSubmit={handleSubmit(onSubmit)} className="mt-7 flex flex-col gap-4" noValidate>
              <div className="flex flex-col gap-1.5">
                <label htmlFor="email" className="text-sm font-semibold text-[#20334a] dark:text-[#dce8f5]">
                  E-mail
                </label>
                <input
                  id="email"
                  type="email"
                  autoComplete="username"
                  autoFocus
                  {...register("email")}
                  className="min-h-[46px] rounded-[10px] border border-[#8fa1b5] bg-white px-3 py-2.5 text-base text-[#102033] outline-none transition-[border-color,box-shadow] focus:border-[#1f6feb] focus:ring-2 focus:ring-[#1f6feb]/25 dark:border-[#5f7893] dark:bg-[#0d1724] dark:text-white dark:focus:border-[#79b8ff] dark:focus:ring-[#79b8ff]/25"
                  /* `aria-invalid` e o `id` do erro: quem usa leitor de tela ouve
                   * "campo inválido" e o motivo junto, em vez de só encontrar um
                   * texto vermelho solto depois do campo. */
                  aria-invalid={Boolean(errors.email)}
                  aria-describedby={errors.email ? "erro-email" : undefined}
                />
                {errors.email && (
                  <span id="erro-email" className="text-xs text-critico dark:text-[#ffb4ad]">
                    {errors.email.message}
                  </span>
                )}
              </div>

              <div className="flex flex-col gap-1.5">
                <label htmlFor="senha" className="text-sm font-semibold text-[#20334a] dark:text-[#dce8f5]">
                  Senha
                </label>
                <div className="relative">
                  <input
                    id="senha"
                    type={mostrarSenha ? "text" : "password"}
                    autoComplete="current-password"
                    {...register("senha")}
                    className="min-h-[46px] w-full rounded-[10px] border border-[#8fa1b5] bg-white px-3 py-2.5 pr-11 text-base text-[#102033] outline-none transition-[border-color,box-shadow] focus:border-[#1f6feb] focus:ring-2 focus:ring-[#1f6feb]/25 dark:border-[#5f7893] dark:bg-[#0d1724] dark:text-white dark:focus:border-[#79b8ff] dark:focus:ring-[#79b8ff]/25"
                    aria-invalid={Boolean(errors.senha)}
                    aria-describedby={errors.senha ? "erro-senha" : undefined}
                  />
                  <button
                    type="button"
                    onClick={() => setMostrarSenha(!mostrarSenha)}
                    className="absolute right-2 top-1/2 -translate-y-1/2 rounded-[8px] p-1.5 text-[#65758a] transition-colors hover:bg-[#e6ecf2] hover:text-[#102033] dark:text-[#a8bcd2] dark:hover:bg-[#1d2b3b] dark:hover:text-white"
                    aria-label={mostrarSenha ? "Ocultar a senha" : "Mostrar a senha"}
                  >
                    {mostrarSenha ? <EyeOff size={18} /> : <Eye size={18} />}
                  </button>
                </div>
                {errors.senha && (
                  <span id="erro-senha" className="text-xs text-critico dark:text-[#ffb4ad]">
                    {errors.senha.message}
                  </span>
                )}
              </div>

              <button
                type="submit"
                disabled={entrando}
                className="mt-3 inline-flex min-h-[48px] w-full items-center justify-center gap-2 rounded-[10px] border border-[#0b57d0] bg-[#0b57d0] px-4 py-3 text-base font-semibold text-white shadow-[0_14px_28px_rgba(11,87,208,0.22)] transition-colors enabled:hover:border-[#0846ad] enabled:hover:bg-[#0846ad] disabled:cursor-not-allowed disabled:opacity-50 dark:border-[#1f6feb] dark:bg-[#1f6feb] dark:enabled:hover:border-[#2f81f7] dark:enabled:hover:bg-[#2f81f7]"
              >
                {entrando && <Loader2 size={18} className="animate-spin" />}
                {entrando ? "Entrando…" : "Entrar"}
              </button>
            </form>

            <p className="mt-7 text-center text-xs leading-5 text-[#65758a] dark:text-[#98acc3]">
              O acesso aos módulos continua definido pelo perfil cadastrado no escritório.
            </p>
          </div>
        </section>
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
