"use client";

import { ArrowLeft, Eye, EyeOff, FileText, Loader2, MailCheck } from "lucide-react";

import ChangePasswordModal from "./ChangePasswordModal";
import LoginVisualPanel from "./LoginVisualPanel";
import TurnstileWidget from "./TurnstileWidget";
import type { usePageModel } from "./page.model";

type LoginPageProps = ReturnType<typeof usePageModel>;

const CAMPO =
  "min-h-[46px] rounded-[10px] border border-[#8fa1b5] bg-white px-3 py-2.5 text-base " +
  "text-[#102033] outline-none transition-[border-color,box-shadow] focus:border-[#1f6feb] " +
  "focus:ring-2 focus:ring-[#1f6feb]/25 dark:border-[#5f7893] dark:bg-[#0d1724] " +
  "dark:text-white dark:focus:border-[#79b8ff] dark:focus:ring-[#79b8ff]/25";

const BOTAO_PRIMARIO =
  "inline-flex min-h-[48px] w-full items-center justify-center gap-2 rounded-[10px] " +
  "border border-[#0b57d0] bg-[#0b57d0] px-4 py-3 text-base font-semibold text-white " +
  "shadow-[0_14px_28px_rgba(11,87,208,0.22)] transition-colors " +
  "enabled:hover:border-[#0846ad] enabled:hover:bg-[#0846ad] " +
  "disabled:cursor-not-allowed disabled:opacity-50 dark:border-[#1f6feb] dark:bg-[#1f6feb] " +
  "dark:enabled:hover:border-[#2f81f7] dark:enabled:hover:bg-[#2f81f7]";

const ROTULO = "text-sm font-semibold text-[#20334a] dark:text-[#dce8f5]";

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
    etapa,
    desafio,
    codigo,
    setCodigo,
    aoConfirmarCodigo,
    confirmando,
    aoReenviarCodigo,
    reenviando,
    segundosParaReenviar,
    voltarParaCredencial,
    captchaAtivo,
    siteKeyDoCaptcha,
    guardarResetDoCaptcha,
    definirTokenCaptcha,
    limparTokenCaptcha,
  } = props;

  const {
    register,
    handleSubmit,
    formState: { errors },
  } = form;

  const noSegundoFator = etapa === "codigo";

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

            {/* O formulário de senha e o do código NÃO ficam na mesma tela ao
              * mesmo tempo. Deixar a senha visível atrás do segundo passo faria
              * a pessoa reenviá-la achando que o código não chegou — e daria a
              * impressão de que o segundo fator é opcional. */}
            {!noSegundoFator ? (
              <>
                <h1 className="font-titulo text-xl !text-[#102033] dark:!text-white">
                  Entrar no sistema
                </h1>
                <p className="mt-2 text-sm leading-6 text-[#33465c] dark:text-[#c8d6e5]">
                  A carteira de casos e os documentos dos clientes exigem identificação.
                </p>

                <form
                  onSubmit={handleSubmit(onSubmit)}
                  className="mt-7 flex flex-col gap-4"
                  noValidate
                >
                  <div className="flex flex-col gap-1.5">
                    <label htmlFor="email" className={ROTULO}>
                      E-mail
                    </label>
                    <input
                      id="email"
                      type="email"
                      autoComplete="username"
                      autoFocus
                      {...register("email")}
                      className={CAMPO}
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
                    <label htmlFor="senha" className={ROTULO}>
                      Senha
                    </label>
                    <div className="relative">
                      <input
                        id="senha"
                        type={mostrarSenha ? "text" : "password"}
                        autoComplete="current-password"
                        {...register("senha")}
                        className={`${CAMPO} w-full pr-11`}
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

                  {/* Só aparece quando o servidor diz que há captcha configurado.
                    * Em desenvolvimento, sem `TURNSTILE_SECRET_KEY`, o espaço
                    * simplesmente não existe — e não uma caixa vazia sem explicação. */}
                  {captchaAtivo && siteKeyDoCaptcha && (
                    <TurnstileWidget
                      siteKey={siteKeyDoCaptcha}
                      aoResolver={definirTokenCaptcha}
                      aoExpirar={limparTokenCaptcha}
                      aoPronto={guardarResetDoCaptcha}
                    />
                  )}

                  <button type="submit" disabled={entrando} className={`mt-3 ${BOTAO_PRIMARIO}`}>
                    {entrando && <Loader2 size={18} className="animate-spin" />}
                    {entrando ? "Entrando…" : "Entrar"}
                  </button>
                </form>

                <p className="mt-7 text-center text-xs leading-5 text-[#65758a] dark:text-[#98acc3]">
                  O acesso aos módulos continua definido pelo perfil cadastrado no escritório.
                </p>
              </>
            ) : (
              <>
                <div className="flex items-start gap-3">
                  <span className="mt-0.5 inline-flex h-10 w-10 shrink-0 items-center justify-center rounded-[10px] bg-[#e7f0fd] text-[#0b57d0] dark:bg-[#12263f] dark:text-[#79b8ff]">
                    <MailCheck size={20} aria-hidden />
                  </span>
                  <div className="min-w-0">
                    <h1 className="font-titulo text-xl !text-[#102033] dark:!text-white">
                      Confirme o acesso
                    </h1>
                    <p className="mt-2 text-sm leading-6 text-[#33465c] dark:text-[#c8d6e5]">
                      Enviamos um código de 6 dígitos para{" "}
                      <strong className="text-[#102033] dark:text-white">{desafio?.email}</strong>.
                      Ele vale uma única vez.
                    </p>
                  </div>
                </div>

                <form
                  onSubmit={(evento) => {
                    evento.preventDefault();
                    aoConfirmarCodigo();
                  }}
                  className="mt-7 flex flex-col gap-4"
                  noValidate
                >
                  <div className="flex flex-col gap-1.5">
                    <label htmlFor="codigo" className={ROTULO}>
                      Código de acesso
                    </label>
                    <input
                      id="codigo"
                      /* `inputMode` numérico e não `type="number"`: o segundo
                       * traz setas de incremento, aceita sinal e notação
                       * científica, e come o zero à esquerda de um código como
                       * "042318". */
                      inputMode="numeric"
                      autoComplete="one-time-code"
                      autoFocus
                      maxLength={6}
                      value={codigo}
                      onChange={(evento) =>
                        setCodigo(evento.target.value.replace(/\D/g, "").slice(0, 6))
                      }
                      placeholder="000000"
                      className={`${CAMPO} text-center font-mono text-2xl tracking-[0.5em]`}
                    />
                  </div>

                  <button
                    type="submit"
                    disabled={confirmando || codigo.length < 6}
                    className={BOTAO_PRIMARIO}
                  >
                    {confirmando && <Loader2 size={18} className="animate-spin" />}
                    {confirmando ? "Confirmando…" : "Confirmar e entrar"}
                  </button>
                </form>

                <div className="mt-5 flex flex-col items-center gap-3">
                  <button
                    type="button"
                    onClick={aoReenviarCodigo}
                    disabled={reenviando || segundosParaReenviar > 0}
                    className="text-sm font-semibold text-[#0b57d0] transition-colors enabled:hover:underline disabled:cursor-not-allowed disabled:text-[#8fa1b5] dark:text-[#79b8ff] dark:disabled:text-[#5f7893]"
                  >
                    {segundosParaReenviar > 0
                      ? `Reenviar código em ${segundosParaReenviar}s`
                      : reenviando
                        ? "Reenviando…"
                        : "Não recebeu? Reenviar código"}
                  </button>

                  <button
                    type="button"
                    onClick={voltarParaCredencial}
                    className="inline-flex items-center gap-1.5 text-sm text-[#65758a] transition-colors hover:text-[#102033] dark:text-[#98acc3] dark:hover:text-white"
                  >
                    <ArrowLeft size={15} aria-hidden />
                    Entrar com outra conta
                  </button>
                </div>

                <p className="mt-7 text-center text-xs leading-5 text-[#65758a] dark:text-[#98acc3]">
                  Se você não pediu este acesso, alguém pode ter a sua senha. Troque-a e avise quem
                  administra o sistema.
                </p>
              </>
            )}
          </div>
        </section>
      </div>

      {/* O aviso de erro não fica aqui: os hooks de mutação já o mostram em toast.
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
