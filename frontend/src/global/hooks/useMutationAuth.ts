"use client";

import { useMutation, useQuery } from "@tanstack/react-query";
import { toast } from "sonner";

import {
  ChangePasswordService,
  ConfigDeAcessoService,
  ConfirmarCodigoService,
  LoginService,
  ReenviarCodigoService,
} from "@/global/services/auth.service";

/** A configuração pública da porta de entrada: se há captcha e com que chave.
 *
 * Precisa chegar ANTES de o formulário poder ser enviado — o widget do Turnstile
 * não tem como ser desenhado sem a `site_key`. Sem `retry`: se a API não
 * respondeu, insistir três vezes só atrasa a tela, e o serviço já devolve `null`
 * em vez de erro para o login continuar desenhável. */
export const useConfigDeAcesso = () =>
  useQuery({
    queryKey: ["config-acesso"],
    queryFn: ConfigDeAcessoService,
    staleTime: Infinity,
    retry: false,
  });

/** O primeiro passo do login: senha e captcha.
 *
 * A tela lê `isPending` para travar o botão. O `data` NÃO quer mais dizer
 * "entrou" — pode ser `etapa: "dois_fatores"`, que é senha aceita e sessão
 * ainda não aberta. Quem interpreta isso é o `page.model.ts`. */
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

/** O segundo passo: o código de seis dígitos. É aqui que a sessão nasce. */
export const useMutateConfirmarCodigo = () =>
  useMutation({
    mutationFn: ConfirmarCodigoService,
    onError: (erro: Error) => {
      /* Ao contrário do login, esta mensagem é específica de propósito — o
       * servidor devolve quantas tentativas restam. Quem chegou até aqui já
       * provou a senha, então contar isso não entrega informação a estranho, e
       * esconder faria a pessoa ser bloqueada sem aviso. */
      toast.error("Código não confere", {
        description: erro.message,
        duration: 6000,
        closeButton: true,
      });
    },
  });

export const useMutateReenviarCodigo = () =>
  useMutation({
    mutationFn: ReenviarCodigoService,
    onSuccess: () => toast.success("Novo código enviado para o seu e-mail."),
    onError: (erro: Error) => {
      toast.error("Não foi possível reenviar o código", {
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
