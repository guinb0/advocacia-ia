"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { Botao, CampoSeletor } from "@/components/ui/Basicos";
import { BotaoProcesso } from "@/components/ui/BotaoProcesso";
import { LIMIAR_VOZ, medirNivel } from "@/lib/medidorNivel";
import { consultarPermissaoMicrofone, type PermissaoMicrofone } from "@/lib/chamadaJitsi";

/* O teste de microfone ANTES de entrar na chamada.
 *
 * O QUE ESTAVA ERRADO AQUI
 *
 * Esta tela dizia "✓ Microfone ligado" assim que o navegador concedia a
 * PERMISSÃO. Permissão concedida e microfone funcionando são coisas diferentes,
 * e a distância entre as duas é exatamente onde o cliente idoso se perde: fone
 * Bluetooth pareado mas com a entrada errada selecionada, microfone do monitor
 * escolhido como padrão, outro aplicativo segurando o dispositivo. Em todos
 * esses casos a permissão é concedida, o ✓ ficava verde, o cliente entrava na
 * chamada e ninguém o ouvia — sem nada na tela sugerindo o que havia de errado.
 * Foi assim na chamada de 15/09/2026.
 *
 * Agora o ✓ só aparece depois de ENTRAR SOM DE VERDADE. A pessoa fala, a barra
 * se mexe, e aí está provado. Nada além de falar é exigido dela.
 *
 * POR QUE O TESTE SOLTA O MICROFONE AO TERMINAR
 *
 * O iOS mantém UMA sessão de captura por página: se este teste continuasse
 * segurando o microfone, a captura que a `ChamadaJitsi` abre logo depois
 * derrubaria a nossa — ou a nossa derrubaria a dela, que é o mesmo defeito do
 * "celular mudo" documentado em `chamadaJitsi.entrar`. Provado que entra som, o
 * dispositivo é liberado na hora e o resultado fica na tela como texto. */

type Estado =
  | "verificando"
  | "perguntar"
  | "negado"
  | "indisponivel"
  /** Microfone aberto, esperando a pessoa falar. */
  | "testando"
  /** Entrou som: está provado. */
  | "ok";

interface Microfone {
  id: string;
  nome: string;
}

/** Sem som por este tempo durante o teste, oferece-se a saída (trocar de
 *  dispositivo). Curto porque aqui a pessoa está ATIVAMENTE tentando falar. */
const ESPERA_SEM_SOM_MS = 7_000;

const CAIXA = "mt-4 rounded-campo border-[1.5px] p-4 text-base leading-[1.55] font-ui";

function ehIphone(): boolean {
  return typeof navigator !== "undefined" && /iPhone|iPad|iPod/i.test(navigator.userAgent);
}

function ehNavegadorDeAplicativo(): boolean {
  return typeof navigator !== "undefined" && /FBAN|FBAV|Instagram|Line\/|WhatsApp/i.test(navigator.userAgent);
}

function versaoDoChrome(): number | null {
  if (typeof navigator === "undefined") return null;
  const chrome = navigator.userAgent.match(/Chrome\/(\d+)/);
  return chrome ? Number(chrome[1]) : null;
}

export default function AtivarMicrofone({
  onMicrofone,
}: {
  /** O dispositivo que passou no teste, para a chamada abrir COM ELE e não com
   *  o padrão do sistema — que pode ser justamente o que não funciona. */
  onMicrofone?: (id: string | undefined) => void;
}) {
  const [chromeAntigo, setChromeAntigo] = useState<number | null>(null);

  useEffect(() => {
    const versao = versaoDoChrome();
    if (versao !== null && versao < 100) setChromeAntigo(versao);
  }, []);

  return (
    <>
      {chromeAntigo !== null && (
        <div className={`${CAIXA} border-atencao bg-papel-2 text-tinta`} role="alert">
          <strong className="block mb-1">Seu Google Chrome está desatualizado (versão {chromeAntigo})</strong>
          A chamada pode ficar só “conectando” e não entrar. Abra a <strong>Play Store</strong>, procure por{" "}
          <strong>Google Chrome</strong>, toque em <strong>Atualizar</strong> e abra este link de novo.
        </div>
      )}
      <TesteDoMicrofone onMicrofone={onMicrofone} />
    </>
  );
}

function TesteDoMicrofone({ onMicrofone }: { onMicrofone?: (id: string | undefined) => void }) {
  const [estado, setEstado] = useState<Estado>("verificando");
  const [pedindo, setPedindo] = useState(false);
  const [aplicativo, setAplicativo] = useState(false);
  const [nivel, setNivel] = useState(0);
  const [semSom, setSemSom] = useState(false);
  const [microfones, setMicrofones] = useState<Microfone[]>([]);
  const [escolhido, setEscolhido] = useState<string | undefined>(undefined);

  // O que o teste está segurando agora. Num ref porque precisa ser solto na
  // limpeza do efeito e ao trocar de dispositivo, fora do ciclo de render.
  const streamRef = useRef<MediaStream | null>(null);
  const medidorRef = useRef<{ parar(): void } | null>(null);
  /** Já entrou som neste teste: impede soltar o microfone mais de uma vez. */
  const provado = useRef(false);

  const soltar = useCallback(() => {
    medidorRef.current?.parar();
    medidorRef.current = null;
    streamRef.current?.getTracks().forEach((t) => t.stop());
    streamRef.current = null;
  }, []);

  // Sair da tela sem soltar deixaria a luz do microfone acesa e, no celular,
  // roubaria o dispositivo da chamada que está prestes a abrir.
  useEffect(() => soltar, [soltar]);

  useEffect(() => {
    let vivo = true;
    setAplicativo(ehNavegadorDeAplicativo());
    void consultarPermissaoMicrofone().then((atual: PermissaoMicrofone | "perguntar") => {
      if (!vivo) return;
      // Permissão já concedida não basta para dizer "funciona" — mas basta para
      // abrir o teste sozinho, sem exigir um toque a mais de quem já respondeu.
      if (atual === "permitido") void abrir(undefined);
      else setEstado(atual);
    });
    return () => {
      vivo = false;
    };
    // `abrir` é estável o bastante para o efeito de montagem; incluí-la aqui
    // reabriria o microfone a cada troca de dispositivo.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  /** Abre o microfone pedido e começa a medir. É aqui que a permissão é pedida. */
  const abrir = useCallback(
    async (dispositivo: string | undefined) => {
      soltar();
      setNivel(0);
      setSemSom(false);
      try {
        const stream = await navigator.mediaDevices.getUserMedia({
          audio: dispositivo ? { deviceId: { exact: dispositivo } } : true,
        });
        streamRef.current = stream;
        const trilha = stream.getAudioTracks()[0];
        if (!trilha) {
          setEstado("indisponivel");
          return;
        }
        setEstado("testando");

        /* Os nomes dos dispositivos só existem DEPOIS da primeira permissão —
         * antes dela o navegador devolve a lista com rótulos vazios, que não
         * ajudariam ninguém a escolher. Por isso a enumeração vem aqui, e não
         * na montagem. */
        try {
          const todos = await navigator.mediaDevices.enumerateDevices();
          setMicrofones(
            todos
              .filter((d) => d.kind === "audioinput")
              .map((d, i) => ({ id: d.deviceId, nome: d.label || `Microfone ${i + 1}` })),
          );
        } catch {
          /* Sem lista, o teste continua valendo com o dispositivo padrão. */
        }

        const atual = dispositivo ?? trilha.getSettings().deviceId;
        setEscolhido(atual);
        onMicrofone?.(atual);

        let ultimaVoz = Date.now();
        provado.current = false;
        medidorRef.current = medirNivel(trilha, (valor) => {
          setNivel(valor);
          if (valor >= LIMIAR_VOZ) {
            ultimaVoz = Date.now();
            setSemSom(false);
            /* "Já provou" mora num ref, e não no estado, porque soltar o
             * microfone é efeito colateral: dentro de um updater do `setEstado`
             * ele rodaria duas vezes em StrictMode — updater tem de ser puro. O
             * ref também garante que só o PRIMEIRO pico solte o dispositivo,
             * mesmo com leituras chegando a cada 100 ms. */
            if (!provado.current) {
              provado.current = true;
              soltar();
              setEstado("ok");
            }
          } else if (Date.now() - ultimaVoz > ESPERA_SEM_SOM_MS) {
            setSemSom(true);
          }
        });
      } catch (e) {
        const nome = e instanceof DOMException ? e.name : "";
        setEstado(/NotAllowed|Security/i.test(nome) ? "negado" : "indisponivel");
      }
    },
    [onMicrofone, soltar],
  );

  async function ativar() {
    setPedindo(true);
    try {
      await abrir(escolhido);
    } finally {
      setPedindo(false);
    }
  }

  if (estado === "verificando") return null;

  if (estado === "ok") {
    return (
      <div className={`${CAIXA} border-ok-borda bg-ok-claro text-tinta`}>
        <strong className="block mb-1 text-ok">✓ Microfone funcionando</strong>
        Ouvimos a sua voz. Pode entrar na chamada.
        {microfones.length > 1 && (
          <Botao variante="texto" className="mt-2" onClick={() => void abrir(escolhido)}>
            Testar de novo
          </Botao>
        )}
      </div>
    );
  }

  if (estado === "testando") {
    return (
      <div className={`${CAIXA} border-acao-borda bg-acao-clara text-tinta`}>
        <strong className="block mb-1">Agora fale: diga “alô”</strong>
        A barra abaixo tem que se mexer quando você falar. É assim que sabemos que o
        escritório vai conseguir ouvir você.

        <div
          className="mt-3 h-4 rounded-pill bg-papel-3 overflow-hidden"
          role="progressbar"
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={Math.round(Math.sqrt(nivel) * 100)}
          aria-label="Volume do seu microfone"
        >
          <i
            className="block h-full rounded-pill transition-[width] duration-100 ease-out"
            style={{ width: `${Math.round(Math.sqrt(nivel) * 100)}%`, background: "var(--ok)" }}
          />
        </div>

        {microfones.length > 1 && (
          <div className="mt-3">
            <label className="block mb-[6px] text-[13px] font-semibold font-ui text-tinta-3" htmlFor="escolha-microfone">
              Se tiver mais de um microfone, escolha aqui
            </label>
            <CampoSeletor
              id="escolha-microfone"
              value={escolhido ?? ""}
              onChange={(e) => void abrir(e.target.value || undefined)}
            >
              {microfones.map((m) => (
                <option key={m.id} value={m.id}>
                  {m.nome}
                </option>
              ))}
            </CampoSeletor>
          </div>
        )}

        {semSom && (
          <div className="mt-3 rounded-campo border border-atencao-borda bg-papel px-3 py-[10px] text-[13.5px] leading-[1.5]" role="alert">
            <strong className="block text-tinta">Ainda não ouvimos nada</strong>
            {microfones.length > 1
              ? "Tente escolher outro microfone na lista acima."
              : "Se usa fone de ouvido, tire e ponha de novo."}{" "}
            Confira também se o microfone não está mudo no aparelho.
          </div>
        )}
      </div>
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
      <strong className="block mb-1">Primeiro, vamos testar o microfone</strong>
      Toque no botão abaixo. O celular vai perguntar se pode usar o microfone: toque em{" "}
      <strong>“Permitir”</strong>. Depois é só falar “alô”.
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
        Toque aqui para testar o microfone
      </BotaoProcesso>
    </div>
  );
}
