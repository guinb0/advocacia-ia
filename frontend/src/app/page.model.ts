"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { useForm } from "react-hook-form";
import { toast } from "sonner";
import { z } from "zod";

import { useUser } from "@/contexts/ContextWrapper";
import { useMutateChangePassword, useMutateLogin } from "@/global/hooks/useMutationAuth";

const loginSchema = z.object({
  email: z.string().min(1, "Informe o e-mail.").email("E-mail inválido."),
  senha: z.string().min(1, "Senha é obrigatória."),
  turnstileToken: z.string(),
});

export type LoginFormValues = z.infer<typeof loginSchema>;

export const usePageModel = () => {
  const router = useRouter();
  const { setCookieLoggedUser } = useUser();
  const [mostrarSenha, setMostrarSenha] = useState(false);
  const [trocaDeSenhaAberta, setTrocaDeSenhaAberta] = useState(false);
  const [captchaVersao, setCaptchaVersao] = useState(0);

  const { data: sessao, isPending: entrando, mutate: entrar, failureCount } = useMutateLogin();
  const { isPending: trocandoSenha, mutate: trocarSenha } = useMutateChangePassword();

  const form = useForm<LoginFormValues>({
    resolver: zodResolver(loginSchema),
    defaultValues: { email: "", senha: "", turnstileToken: "" },
  });

  const onSubmit = (dados: LoginFormValues) => entrar(dados);
  const captchaAtivo = Boolean(process.env.NEXT_PUBLIC_TURNSTILE_SITE_KEY);
  const tokenTurnstile = form.watch("turnstileToken");
  const aoValidarCaptcha = useCallback(
    (token: string) => form.setValue("turnstileToken", token),
    [form],
  );

  useEffect(() => {
    if (!failureCount) return;
    form.setValue("turnstileToken", "");
    setCaptchaVersao((atual) => atual + 1);
  }, [failureCount, form]);

  useEffect(() => {
    if (!sessao) return;

    setCookieLoggedUser(sessao);

    /* Senha ainda na padrão: a troca vem ANTES da navegação, de propósito. Se a
     * pessoa entrasse primeiro e o aviso ficasse para depois, ela fecharia o
     * aviso e seguiria trabalhando — e a conta continuaria com a senha que todo
     * mundo do escritório sabe qual é. */
    if (sessao.senhaPadrao) {
      setTrocaDeSenhaAberta(true);
      return;
    }
    router.push("/home");
  }, [sessao, setCookieLoggedUser, router]);

  const aoTrocarSenha = (novaSenha: string) => {
    trocarSenha(novaSenha, {
      onSuccess: () => {
        setTrocaDeSenhaAberta(false);
        toast.success("Senha alterada.");
        router.push("/home");
      },
    });
  };

  return {
    form,
    onSubmit,
    entrando,
    mostrarSenha,
    setMostrarSenha,
    trocaDeSenhaAberta,
    aoTrocarSenha,
    trocandoSenha,
    nomeDeQuemEntrou: sessao?.nome ?? "",
    captchaVersao,
    aoValidarCaptcha,
    captchaConcluido: !captchaAtivo || Boolean(tokenTurnstile),
  };
};
