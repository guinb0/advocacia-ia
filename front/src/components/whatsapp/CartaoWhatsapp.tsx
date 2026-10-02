"use client";

import { useEffect, useState } from "react";

import { Aviso, Botao, Cartao, Selo } from "@/components/ui/Basicos";
import {
  ApiError,
  conectarWhatsapp,
  desconectarWhatsapp,
  statusWhatsapp,
  type StatusWhatsapp,
} from "@/lib/api";

/** Conexão do WhatsApp do escritório (Evolution): verde/vermelho e, se caiu, o
 *  QR para religar. Faz o próprio polling — vale mesmo com o agente desligado, e
 *  dá autonomia ao escritório para reconectar ou trocar de número sozinho. */
export default function CartaoWhatsapp() {
  const [status, setStatus] = useState<StatusWhatsapp | null>(null);
  const [qr, setQr] = useState<{ qrcode: string; codigo: string } | null>(null);
  const [pedindoQr, setPedindoQr] = useState(false);
  const [desconectando, setDesconectando] = useState(false);
  const [erro, setErro] = useState<string | null>(null);

  useEffect(() => {
    let vivo = true;
    const ler = () => {
      void statusWhatsapp()
        .then((s) => {
          if (!vivo) return;
          setStatus(s);
          // Reconectou: o QR já não serve, some da tela.
          if (s.conectado) setQr(null);
        })
        .catch(() => {});
    };
    ler();
    // Enquanto o QR está na tela, checa mais rápido para sumir assim que parear.
    const id = window.setInterval(ler, qr ? 3000 : 15000);
    return () => {
      vivo = false;
      window.clearInterval(id);
    };
  }, [qr]);

  async function pedirQr() {
    setPedindoQr(true);
    setErro(null);
    try {
      const r = await conectarWhatsapp();
      setQr({ qrcode: r.qrcode, codigo: r.codigo });
    } catch (e) {
      setErro(e instanceof ApiError ? e.message : "Não foi possível gerar o QR.");
    } finally {
      setPedindoQr(false);
    }
  }

  async function desconectar() {
    if (!window.confirm("Desconectar o WhatsApp do escritório? Para voltar, será preciso escanear um novo QR.")) return;
    setDesconectando(true);
    setErro(null);
    try {
      await desconectarWhatsapp();
      const s = await statusWhatsapp();
      setStatus(s);
      setQr(null);
    } catch (e) {
      setErro(e instanceof ApiError ? e.message : "Não foi possível desconectar.");
    } finally {
      setDesconectando(false);
    }
  }

  const conectado = status?.conectado;
  const conectando = status?.estado === "connecting";
  const selo = !status
    ? { tom: "info" as const, texto: "Verificando…" }
    : !status.configurado
      ? { tom: "atencao" as const, texto: "Não configurado" }
      : conectado
        ? { tom: "ok" as const, texto: "Conectado" }
        : conectando
          ? { tom: "atencao" as const, texto: "Conectando…" }
          : { tom: "critico" as const, texto: "Desconectado" };

  return (
    <Cartao
      titulo="WhatsApp do escritório"
      subtitulo="Conexão da Evolution — de onde saem os avisos e os links de assinatura ao cliente."
      className="min-w-0 overflow-hidden"
    >
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <span
            className={`inline-block h-2.5 w-2.5 rounded-full ${
              conectado ? "bg-ok" : conectando ? "bg-atencao-marca" : "bg-critico"
            }`}
            aria-hidden
          />
          <Selo tom={selo.tom} simbolo={conectado ? "✓" : "!"}>{selo.texto}</Selo>
          {conectado && status?.numero ? (
            <span className="text-sm font-semibold tabular-nums text-tinta">
              {status.numero}
              {status.perfil && <span className="ml-1 font-normal text-tinta-3">· {status.perfil}</span>}
            </span>
          ) : (
            status?.instancia && (
              <span className="text-xs text-tinta-3">instância “{status.instancia}”</span>
            )
          )}
        </div>
        {status && status.configurado && conectado && (
          <Botao
            variante="secundario"
            pequeno
            carregando={desconectando}
            textoCarregando="Desconectando…"
            onClick={() => void desconectar()}
          >
            Desconectar número
          </Botao>
        )}
        {status && status.configurado && !conectado && (
          <Botao
            variante="primario"
            pequeno
            carregando={pedindoQr}
            textoCarregando="Gerando QR…"
            onClick={() => void pedirQr()}
          >
            {qr ? "Gerar outro QR" : "Conectar / trocar número"}
          </Botao>
        )}
      </div>

      {!conectado && status?.configurado && (
        <p className="mt-2 mb-0 text-sm text-atencao">
          O WhatsApp do escritório está fora do ar — os avisos e links não estão saindo.
          {qr ? " Escaneie o QR abaixo com o aparelho para religar." : " Gere um QR novo para religar."}
        </p>
      )}

      {status?.erro && !erro && (
        <Aviso tom="critico" titulo="Diagnóstico da Evolution">
          {status.erro}
          {status.diagnostico && (
            <span className="mt-1 block text-xs">Diagnóstico do serviço: {status.diagnostico}</span>
          )}
        </Aviso>
      )}

      {erro && (
        <Aviso tom="critico" titulo="Erro">
          {erro}
        </Aviso>
      )}

      {qr && !conectado && (
        <div className="mt-4 flex flex-col items-center gap-3 rounded-campo border border-borda bg-papel-2 p-4">
          {qr.qrcode ? (
            /* eslint-disable-next-line @next/next/no-img-element -- QR base64 dinâmico da Evolution. */
            <img
              src={qr.qrcode.startsWith("data:") ? qr.qrcode : `data:image/png;base64,${qr.qrcode}`}
              alt="QR code para conectar o WhatsApp"
              className="h-56 w-56 rounded bg-white p-2"
            />
          ) : (
            <p className="m-0 text-sm text-tinta-3">A Evolution não devolveu a imagem do QR.</p>
          )}
          <p className="m-0 text-center text-xs text-tinta-3">
            No celular: WhatsApp → Aparelhos conectados → Conectar um aparelho, e aponte para o código.
            {qr.codigo ? " Código de pareamento: " : ""}
            {qr.codigo && <strong className="font-codigo text-tinta">{qr.codigo}</strong>}
          </p>
        </div>
      )}
    </Cartao>
  );
}
