"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import { useForm } from "react-hook-form";
import { toast } from "sonner";
import { z } from "zod";

import { useUser } from "@/contexts/ContextWrapper";
import {
  useConfigDeAcesso,
  useMutateChangePassword,
  useMutateConfirmarCodigo,
  useMutateLogin,
  useMutateReenviarCodigo,
} from "@/global/hooks/useMutationAuth";
import type { DesafioDeAcesso, SessaoUsuario } from "./page.interface";

const loginSchema = z.object({
  email: z.string().min(1, "Informe o e-mail.").email("E-mail inválido."),
  senha: z.string().min(1, "Senha é obrigatória."),
});

export type LoginFormValues = z.infer<typeof loginSchema>;

/** Em que passo do login a tela está.
 *
 * `credencial` é o formulário de sempre. `codigo` é o segundo fator: a senha já
 * conferiu, mas NENHUMA sessão existe ainda — o cookie só é gravado quando o
 * código de seis dígitos confere. */
export type EtapaDoLogin = "credencial" | "codigo";

export const usePageModel = () => {
  const router = useRouter();
  const { setCookieLoggedUser } = useUser();
  const [mostrarSenha, setMostrarSenha] = useState(false);
  const [trocaDeSenhaAberta, setTrocaDeSenhaAberta] = useState(false);
  const [nomeDeQuemEntrou, setNomeDeQuemEntrou] = useState("");

  const [etapa, setEtapa] = useState<EtapaDoLogin>("credencial");
  const [desafio, setDesafio] = useState<DesafioDeAcesso | null>(null);
  const [codigo, setCodigo] = useState("");
  const [segundosParaReenviar, setSegundosParaReenviar] = useState(0);

  const { data: config } = useConfigDeAcesso();
  const captchaAtivo = Boolean(config?.captcha?.ativo && config.captcha.site_key);
  const [tokenCaptcha, setTokenCaptcha] = useState("");

  /* O `reset` do widget chega por callback e fica em `ref` para não entrar nas
   * dependências de nada. Ele precisa ser disparado depois de CADA tentativa
   * falha: o token do Turnstile vale uma vez só, e reenviar o mesmo faria a
   * segunda tentativa ser recusada pelo captcha em vez de pela senha. */
  const reiniciarCaptcha = useRef<(() => void) | null>(null);
  const guardarResetDoCaptcha = useCallback((reset: () => void) => {
    reiniciarCaptcha.current = reset;
  }, []);

  const limparCaptcha = useCallback(() => {
    setTokenCaptcha("");
    reiniciarCaptcha.current?.();
  }, []);

  const { isPending: entrando, mutate: entrar } = useMutateLogin();
  const { isPending: confirmando, mutate: confirmar } = useMutateConfirmarCodigo();
  const { isPending: reenviando, mutate: reenviar } = useMutateReenviarCodigo();
  const { isPending: trocandoSenha, mutate: trocarSenha } = useMutateChangePassword();

  const form = useForm<LoginFormValues>({
    resolver: zodResolver(loginSchema),
    defaultValues: { email: "", senha: "" },
  });

  /** O que fazer quando a sessão finalmente existe — venha ela do login direto
   *  (perfil isento do segundo fator) ou da confirmação do código. */
  const aoAbrirSessao = useCallback(
    (sessao: SessaoUsuario) => {
      setCookieLoggedUser(sessao);
      setNomeDeQuemEntrou(sessao.nome);

      /* Senha ainda na padrão: a troca vem ANTES da navegação, de propósito. Se a
       * pessoa entrasse primeiro e o aviso ficasse para depois, ela fecharia o
       * aviso e seguiria trabalhando — e a conta continuaria com a senha que todo
       * mundo do escritório sabe qual é. */
      if (sessao.senhaPadrao) {
        setTrocaDeSenhaAberta(true);
        return;
      }
      router.push("/home");
    },
    [setCookieLoggedUser, router],
  );

  const iniciarContagemDeReenvio = useCallback((segundos: number) => {
    setSegundosParaReenviar(segundos);
  }, []);

  useEffect(() => {
    if (segundosParaReenviar <= 0) return;
    const relogio = setInterval(() => {
      setSegundosParaReenviar((restantes) => (restantes <= 1 ? 0 : restantes - 1));
    }, 1000);
    return () => clearInterval(relogio);
  }, [segundosParaReenviar]);

  const onSubmit = (dados: LoginFormValues) => {
    /* A checagem acontece aqui e não no schema do zod porque o captcha é
     * condicional: com `TURNSTILE_SECRET_KEY` vazio no servidor, o widget nem é
     * desenhado, e um campo obrigatório no schema deixaria o botão inerte para
     * sempre em desenvolvimento. */
    if (captchaAtivo && !tokenCaptcha) {
      toast.error("Aguarde a verificação de segurança", {
        description: "Ela termina sozinha em alguns segundos.",
      });
      return;
    }

    entrar(
      { ...dados, captcha: tokenCaptcha },
      {
        onSuccess: (resposta) => {
          /* O token do captcha foi consumido pelo servidor de qualquer jeito —
           * mesmo dando certo — então ele é descartado aqui também. Voltar para
           * esta tela (por erro no código, por exemplo) precisa de um token novo. */
          limparCaptcha();

          if (resposta.etapa === "sessao") {
            aoAbrirSessao(resposta);
            return;
          }
          setDesafio(resposta);
          setCodigo("");
          setEtapa("codigo");
          iniciarContagemDeReenvio(resposta.reenviar_em_segundos);
        },
        onError: limparCaptcha,
      },
    );
  };

  const aoConfirmarCodigo = () => {
    if (!desafio) return;
    confirmar({ desafio: desafio.desafio, codigo }, { onSuccess: aoAbrirSessao });
  };

  const aoReenviarCodigo = () => {
    if (!desafio || segundosParaReenviar > 0) return;
    reenviar(desafio.desafio, {
      onSuccess: (novo) => {
        setDesafio(novo);
        setCodigo("");
        iniciarContagemDeReenvio(novo.reenviar_em_segundos);
      },
    });
  };

  /** Volta ao formulário de senha. O desafio no servidor continua de pé até
   *  vencer; o que se perde aqui é só o estado da tela. A senha é limpa porque
   *  recomeçar com o campo preenchido esconderia de quem digitou errado que a
   *  tentativa vai ser exatamente a mesma. */
  const voltarParaCredencial = () => {
    setEtapa("credencial");
    setDesafio(null);
    setCodigo("");
    form.setValue("senha", "");
    limparCaptcha();
  };

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
    nomeDeQuemEntrou,

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
    siteKeyDoCaptcha: config?.captcha?.site_key ?? "",
    guardarResetDoCaptcha,
    definirTokenCaptcha: setTokenCaptcha,
    limparTokenCaptcha: () => setTokenCaptcha(""),
    captchaResolvido: Boolean(tokenCaptcha),
  };
};
