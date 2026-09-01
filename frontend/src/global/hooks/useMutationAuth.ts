"use client";

import { useMutation } from "@tanstack/react-query";
import { toast } from "sonner";

import { ChangePasswordService, LoginService } from "@/global/services/auth.service";

/** O login como mutação: a tela lê `isPending` para travar o botão e `data`
 *  para saber que entrou, sem manter estado de carregamento à mão. */
export const useMutateLogin = () =>
  useMutation({
    mutationFn: LoginService,
    onError: (erro: Error) => {
      /* A mensagem vem do servidor e é deliberadamente vaga ("E-mail ou senha
       * incorretos"): dizer qual dos dois errou conta a quem tenta quais e-mails
       * têm conta aqui. */
      toast.error("Não foi possível entrar", {
        description: erro.message,
        duration: 6000,
        closeButton: true,
      });
    },
  });

export const useMutateChangePassword = () =>
  useMutation({
    mutationFn: ChangePasswordService,
    onError: (erro: Error) => {
      toast.error("Não foi possível alterar a senha", {
        description: erro.message,
        duration: 6000,
        closeButton: true,
      });
    },
  });
