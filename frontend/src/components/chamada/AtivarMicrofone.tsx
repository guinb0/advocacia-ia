"use client";

import { useEffect, useState } from "react";

import { Botao } from "@/components/ui/Basicos";
import { BotaoProcesso } from "@/components/ui/BotaoProcesso";
import {
  consultarPermissaoMicrofone,
  pedirPermissaoMicrofone,
  type PermissaoMicrofone,
} from "@/lib/chamadaJitsi";

type Estado = PermissaoMicrofone | "perguntar" | "verificando";

function ehIphone(): boolean {
  return typeof navigator !== "undefined" && /iPhone|iPad|iPod/i.test(navigator.userAgent);
}

function ehNavegadorDeAplicativo(): boolean {
  return typeof navigator !== "undefined" && /FBAN|FBAV|Instagram|Line\/|WhatsApp/i.test(navigator.userAgent);
}

const CAIXA = "mt-4 rounded-campo border-[1.5px] p-4 text-base leading-[1.55] font-ui";

export default function AtivarMicrofone() {
  const [estado, setEstado] = useState<Estado>("verificando");
  const [pedindo, setPedindo] = useState(false);
  const [aplicativo, setAplicativo] = useState(false);

  useEffect(() => {
    let vivo = true;
    setAplicativo(ehNavegadorDeAplicativo());
    void consultarPermissaoMicrofone().then((atual) => {
      if (vivo) setEstado(atual);
    });
    return () => {
      vivo = false;
    };
  }, []);

  async function ativar() {
    setPedindo(true);
    try {
      setEstado(await pedirPermissaoMicrofone());
    } finally {
      setPedindo(false);
    }
  }

  if (estado === "verificando") return null;

  if (estado === "permitido") {
    return (
      <p className="mt-4 mb-0 text-base font-semibold leading-[1.5] font-ui text-ok" aria-live="polite">
        ✓ Microfone ligado. Agora é só entrar na chamada.
      </p>
    );
  }

  if (estado === "indisponivel" || aplicativo) {
    return (
      <div className={`${CAIXA} border-atencao bg-papel-2 text-tinta`} role="alert">
        <strong className="block mb-1">Abra este link no navegador do celular</strong>
        {estado === "indisponivel"
          ? "Por aqui o microfone não funciona. "
          : "Dentro de aplicativos o microfone pode não funcionar. "}
        Toque nos três pontinhos (⋯) no canto da tela e escolha{" "}
        <strong>{ehIphone() ? "“Abrir no Safari”" : "“Abrir no Chrome”"}</strong>.
        {estado !== "indisponivel" && (
          <BotaoProcesso
            variante="primario"
            bloco
            className="mt-3"
            classeBotao="text-base"
            style={{ minHeight: 56 }}
            onClick={ativar}
            processando={pedindo}
            textoProcessando="Aguardando sua resposta…"
          >
            Tentar ligar o microfone mesmo assim
          </BotaoProcesso>
        )}
      </div>
    );
  }

  if (estado === "negado") {
    return (
      <div className={`${CAIXA} border-critico bg-papel-2 text-tinta`} role="alert">
        <strong className="block mb-2">O microfone está bloqueado</strong>
        {ehIphone() ? (
          <ol className="m-0 pl-5">
            <li>Toque em <strong>“aA”</strong>, ao lado do endereço do site.</li>
            <li>Toque em <strong>“Ajustes do Site”</strong>.</li>
            <li>Em <strong>Microfone</strong>, escolha <strong>“Permitir”</strong>.</li>
            <li>Volte aqui e toque em <strong>“Tentar de novo”</strong>.</li>
          </ol>
        ) : (
          <ol className="m-0 pl-5">
            <li>Toque no <strong>cadeado</strong> ao lado do endereço do site.</li>
            <li>Toque em <strong>“Permissões”</strong>.</li>
            <li>Em <strong>Microfone</strong>, escolha <strong>“Permitir”</strong>.</li>
            <li>Volte aqui e toque em <strong>“Tentar de novo”</strong>.</li>
          </ol>
        )}
        <div className="mt-3 grid gap-2">
          <BotaoProcesso
            variante="primario"
            bloco
            classeBotao="text-base"
            style={{ minHeight: 56 }}
            onClick={ativar}
            processando={pedindo}
            textoProcessando="Aguardando sua resposta…"
          >
            Tentar de novo
          </BotaoProcesso>
          <Botao variante="secundario" onClick={() => window.location.reload()}>
            Recarregar a página
          </Botao>
        </div>
      </div>
    );
  }

  return (
    <div className={`${CAIXA} border-acao-borda bg-acao-clara text-tinta`}>
      <strong className="block mb-1">Primeiro, ligue o microfone</strong>
      Toque no botão abaixo. O celular vai perguntar se pode usar o microfone: toque em{" "}
      <strong>“Permitir”</strong>.
      <BotaoProcesso
        variante="primario"
        bloco
        className="mt-3"
        classeBotao="text-base"
        style={{ minHeight: 56 }}
        onClick={ativar}
        processando={pedindo}
        textoProcessando="Aguardando sua resposta…"
      >
        Toque aqui para ligar o microfone
      </BotaoProcesso>
    </div>
  );
}
