"use client";

import { Eye, EyeOff, FileText, Loader2 } from "lucide-react";

import ChangePasswordModal from "./ChangePasswordModal";
import LoginVisualPanel from "./LoginVisualPanel";
import Turnstile from "./Turnstile";
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
    captchaVersao,
    aoValidarCaptcha,
    captchaConcluido,
  } = props;

  const {
    register,
    handleSubmit,
    formState: { errors },
  } = form;

  return (
    <main className="relative flex min-h-screen overflow-hidden bg-[#182933] px-3 py-3 text-[#dbe7ee] sm:px-6 sm:py-6 lg:px-8">
      <div
        className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_18%_16%,rgba(91,139,161,0.16),transparent_36%),radial-gradient(circle_at_88%_82%,rgba(8,18,25,0.24),transparent_34%)]"
        aria-hidden
      />
      <div className="relative mx-auto grid min-h-[calc(100vh-1.5rem)] w-full max-w-[1120px] items-center overflow-hidden rounded-[28px] border border-[#426274] bg-[#203340] shadow-[0_30px_75px_rgba(4,14,21,0.36)] lg:min-h-[620px] lg:grid-cols-2 lg:items-stretch xl:min-h-[680px]">
        <LoginVisualPanel />

        <section className="mx-auto flex min-h-[620px] w-full flex-col justify-center bg-[#203340] p-7 text-[#dbe7ee] sm:p-10 lg:min-h-0 lg:rounded-r-[28px] lg:p-12">
          <div className="mx-auto w-full max-w-[350px] motion-safe:animate-[loginFloat_0.7s_ease-out_1]">
            <div className="mb-10">
              <div className="flex items-center gap-3">
                <span className="inline-flex h-10 w-10 shrink-0 items-center justify-center rounded-xl border border-[#567589] bg-[#2e4b5e] text-[#e9f2f5] shadow-[0_10px_22px_rgba(7,20,29,0.24)]">
                  <FileText size={20} aria-hidden />
                </span>
                <div className="min-w-0">
                  <span className="block truncate font-titulo text-xl leading-none text-white">Forense</span>
                  <span className="mt-1 block text-[11px] font-semibold uppercase tracking-[0.15em] text-[#9cb3c1]">
                    Escritório jurídico
                  </span>
                </div>
              </div>
            </div>

            <p className="text-[11px] font-bold uppercase tracking-[0.17em] text-[#91b8c9]">Acesso seguro</p>
            <h1 className="mt-3 font-titulo text-[1.7rem] !text-white">Entrar no sistema</h1>
            <p className="mt-2 text-sm leading-6 text-[#adc0cb]">
              Acesse sua mesa de trabalho e acompanhe os próximos passos de cada caso.
            </p>

            <form onSubmit={handleSubmit(onSubmit)} className="mt-8 flex flex-col gap-4" noValidate>
              <div className="flex flex-col gap-1.5">
                <label htmlFor="email" className="text-sm font-medium text-[#d7e3e9]">
                  E-mail
                </label>
                <input
                  id="email"
                  type="email"
                  autoComplete="username"
                  autoFocus
                  {...register("email")}
                  className="min-h-[46px] rounded-xl border border-[#4c6b7e] bg-[#203744] px-3.5 py-2.5 text-base text-white outline-none transition-[border-color,box-shadow,background-color] placeholder:text-[#7f98a8] focus:border-[#83b0c5] focus:bg-[#243e4d] focus:ring-2 focus:ring-[#83b0c5]/20"
                  aria-invalid={Boolean(errors.email)}
                  aria-describedby={errors.email ? "erro-email" : undefined}
                />
                {errors.email && (
                  <span id="erro-email" className="text-xs text-[#ffb4ad]">
                    {errors.email.message}
                  </span>
                )}
              </div>

              <div className="flex flex-col gap-1.5">
                <label htmlFor="senha" className="text-sm font-medium text-[#d7e3e9]">
                  Senha
                </label>
                <div className="relative">
                  <input
                    id="senha"
                    type={mostrarSenha ? "text" : "password"}
                    autoComplete="current-password"
                    {...register("senha")}
                    className="min-h-[46px] w-full rounded-xl border border-[#4c6b7e] bg-[#203744] px-3.5 py-2.5 pr-11 text-base text-white outline-none transition-[border-color,box-shadow,background-color] placeholder:text-[#7f98a8] focus:border-[#83b0c5] focus:bg-[#243e4d] focus:ring-2 focus:ring-[#83b0c5]/20"
                    aria-invalid={Boolean(errors.senha)}
                    aria-describedby={errors.senha ? "erro-senha" : undefined}
                  />
                  <button
                    type="button"
                    onClick={() => setMostrarSenha(!mostrarSenha)}
                    className="absolute right-2 top-1/2 -translate-y-1/2 rounded-lg p-1.5 text-[#9db3bf] transition-colors hover:bg-white/10 hover:text-white"
                    aria-label={mostrarSenha ? "Ocultar a senha" : "Mostrar a senha"}
                  >
                    {mostrarSenha ? <EyeOff size={18} /> : <Eye size={18} />}
                  </button>
                </div>
                {errors.senha && (
                  <span id="erro-senha" className="text-xs text-[#ffb4ad]">
                    {errors.senha.message}
                  </span>
                )}
              </div>

              <Turnstile key={captchaVersao} onToken={aoValidarCaptcha} />

              <button
                type="submit"
                disabled={entrando || !captchaConcluido}
                className="mt-3 inline-flex min-h-[48px] w-full items-center justify-center gap-2 rounded-xl border border-[#80aabd] bg-[#80aabd] px-4 py-3 text-base font-semibold text-[#162631] shadow-[0_12px_25px_rgba(0,0,0,0.20)] transition-[transform,background-color,box-shadow] enabled:hover:-translate-y-0.5 enabled:hover:bg-[#9abfce] enabled:hover:shadow-[0_16px_28px_rgba(0,0,0,0.26)] disabled:cursor-not-allowed disabled:border-white/10 disabled:bg-[#3a4e5c] disabled:text-[#94a5af]"
              >
                {entrando && <Loader2 size={18} className="animate-spin" />}
                {entrando ? "Entrando…" : "Entrar"}
              </button>
            </form>

            <p className="mt-8 text-center text-xs leading-5 text-[#8fa7b4]">
              O acesso aos módulos continua definido pelo perfil cadastrado no escritório.
            </p>
          </div>
        </section>
      </div>

      <ChangePasswordModal
        aberto={trocaDeSenhaAberta}
        salvando={trocandoSenha}
        onSalvar={aoTrocarSenha}
      />
    </main>
  );
}

export default LoginPage;
