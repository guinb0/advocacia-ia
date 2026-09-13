"use client";

import { ArrowLeft, Eye, EyeOff, FileText, Loader2, MailCheck } from "lucide-react";

import ChangePasswordModal from "./ChangePasswordModal";
import LoginVisualPanel from "./LoginVisualPanel";
import TurnstileWidget from "./TurnstileWidget";
import type { usePageModel } from "./page.model";

type LoginPageProps = ReturnType<typeof usePageModel>;

/* Os tres nasceram supondo um cartao branco (`bg-white`, texto #102033), e a
 * coluna do formulario acabou ficando escura nos dois temas: titulo, rotulos e
 * explicacao ficavam azul-escuro sobre azul-escuro, perto de 1,3:1 — ilegiveis
 * no tema claro. Agora a coluna e `--papel` e o texto sai dos tokens, entao os
 * dois temas se resolvem sozinhos. O CTA e o Gold do sistema, o mesmo de
 * "Novo caso". */
const CAMPO =
  "min-h-[46px] w-full rounded-campo border border-borda-campo bg-papel px-3 py-2.5 text-base " +
  "text-tinta outline-none transition-[border-color,box-shadow] " +
  "hover:border-acao focus:border-foco focus:ring-2 focus:ring-foco/20 " +
  "aria-invalid:border-critico aria-invalid:focus:ring-critico/20";

const BOTAO_PRIMARIO =
  "inline-flex min-h-[48px] w-full items-center justify-center gap-2 rounded-campo " +
  "border border-marca-ouro bg-marca-ouro px-4 py-3 text-base font-semibold text-primario-texto " +
  "shadow-cartao transition-colors " +
  "enabled:hover:border-marca-ouro-hover enabled:hover:bg-marca-ouro-hover " +
  "enabled:focus-visible:outline-none enabled:focus-visible:ring-2 enabled:focus-visible:ring-foco " +
  "disabled:cursor-not-allowed disabled:border-borda-forte disabled:bg-papel-3 disabled:text-tinta-desabilitada";

const ROTULO = "text-sm font-semibold text-tinta";

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
    <main className="relative flex min-h-screen overflow-hidden bg-nav-fundo px-3 py-3 text-nav-texto-2 sm:px-6 sm:py-6 lg:px-8">
      <div
        className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_18%_16%,rgba(91,139,161,0.16),transparent_36%),radial-gradient(circle_at_88%_82%,rgba(8,18,25,0.24),transparent_34%)]"
        aria-hidden
      />
      <div className="relative mx-auto grid min-h-[calc(100vh-1.5rem)] w-full max-w-[1120px] items-center overflow-hidden rounded-[28px] border border-nav-borda bg-nav-fundo-ativo shadow-[0_30px_75px_rgba(4,14,21,0.36)] lg:min-h-[620px] lg:grid-cols-2 lg:items-stretch xl:min-h-[680px]">
        <LoginVisualPanel />

        <section className="mx-auto flex min-h-[620px] w-full flex-col justify-center bg-papel p-7 text-tinta-2 sm:p-10 lg:min-h-0 lg:rounded-r-[28px] lg:p-12">
          <div className="mx-auto w-full max-w-[350px] motion-safe:animate-[loginFloat_0.7s_ease-out_1]">
            <div className="mb-10">
              <div className="flex items-center gap-3">
                <span className="inline-flex h-10 w-10 shrink-0 items-center justify-center rounded-xl border border-nav-borda bg-nav-fundo text-marca-ouro shadow-[0_10px_22px_rgba(7,20,29,0.24)]">
                  <FileText size={20} aria-hidden />
                </span>
                <div className="min-w-0">
                  <span className="block truncate font-titulo text-xl leading-none text-tinta">Forense</span>
                  <span className="mt-1 block text-[11px] font-semibold uppercase tracking-[0.15em] text-tinta-3">
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
                <h1 className="font-titulo text-xl text-tinta">
                  Entrar no sistema
                </h1>
                <p className="mt-2 text-sm leading-6 text-tinta-2">
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
                      <span id="erro-email" className="text-xs text-critico">
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
                        className={`${CAMPO} pr-11`}
                        aria-invalid={Boolean(errors.senha)}
                        aria-describedby={errors.senha ? "erro-senha" : undefined}
                      />
                      <button
                        type="button"
                        onClick={() => setMostrarSenha(!mostrarSenha)}
                        className="absolute right-2 top-1/2 -translate-y-1/2 rounded-campo p-1.5 text-tinta-3 transition-colors hover:bg-papel-3 hover:text-tinta focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-foco"
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

                <p className="mt-7 text-center text-xs leading-5 text-tinta-3">
                  O acesso aos módulos continua definido pelo perfil cadastrado no escritório.
                </p>
              </>
            ) : (
              <>
                <div className="flex items-start gap-3">
                  <span className="mt-0.5 inline-flex h-10 w-10 shrink-0 items-center justify-center rounded-campo border border-acao-borda bg-acao-clara text-acao-texto">
                    <MailCheck size={20} aria-hidden />
                  </span>
                  <div className="min-w-0">
                    <h1 className="font-titulo text-xl text-tinta">
                      Confirme o acesso
                    </h1>
                    <p className="mt-2 text-sm leading-6 text-tinta-2">
                      Enviamos um código de 6 dígitos para{" "}
                      <strong className="text-tinta">{desafio?.email}</strong>.
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
                    className="rounded-campo text-sm font-semibold text-acao-texto transition-colors enabled:hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-foco disabled:cursor-not-allowed disabled:text-tinta-desabilitada"
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
                    className="inline-flex items-center gap-1.5 rounded-campo text-sm text-tinta-3 transition-colors hover:text-tinta focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-foco"
                  >
                    <ArrowLeft size={15} aria-hidden />
                    Entrar com outra conta
                  </button>
                </div>

                <p className="mt-7 text-center text-xs leading-5 text-tinta-3">
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
