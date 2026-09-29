"use client";

/* Telemetria local, propositalmente sem áudio, vídeo, rótulo de dispositivo,
 * nome da sala ou identificador de participante. Ela existe para separar
 * permission/device/autoplay do transporte WebRTC sem criar nova superfície de
 * dados sensíveis. Em produção só liga por NEXT_PUBLIC_JITSI_DIAGNOSTIC=1 ou
 * pela chave localStorage `jitsi-diagnostic=1`. */
export type EventoDiagnosticoJitsi = {
  quando: string;
  evento: string;
  dados?: Record<string, unknown>;
};

const LIMITE = 120;
let eventos: EventoDiagnosticoJitsi[] = [];
const ouvintes = new Set<() => void>();

export function diagnosticoJitsiAtivo(): boolean {
  if (typeof window === "undefined") return false;
  return (
    process.env.NEXT_PUBLIC_JITSI_DIAGNOSTIC === "1" ||
    window.localStorage.getItem("jitsi-diagnostic") === "1" ||
    new URLSearchParams(window.location.search).get("jitsiDiagnostic") === "1"
  );
}

export function registrarDiagnosticoJitsi(evento: string, dados?: Record<string, unknown>): void {
  if (!diagnosticoJitsiAtivo()) return;
  eventos = [...eventos.slice(-(LIMITE - 1)), { quando: new Date().toISOString(), evento, dados }];
  // Console estruturado facilita exportar um caso reproduzido sem depender do DevTools do Jitsi.
  console.info("[JITSI_DIAGNOSTIC]", eventos.at(-1));
  ouvintes.forEach((ouvinte) => ouvinte());
}

export function erroDiagnosticoJitsi(erro: unknown): Record<string, string> {
  if (erro instanceof Error) {
    return { nome: erro.name || "Error", mensagem: erro.message, stack: erro.stack?.slice(0, 700) ?? "" };
  }
  if (erro && typeof erro === "object") {
    const valor = erro as { name?: unknown; message?: unknown; gum?: { error?: { name?: unknown; message?: unknown } } };
    return {
      nome: String(valor.name ?? valor.gum?.error?.name ?? "Erro desconhecido"),
      mensagem: String(valor.message ?? valor.gum?.error?.message ?? ""),
    };
  }
  return { nome: "Erro desconhecido", mensagem: String(erro ?? "") };
}

export function listarDiagnosticoJitsi(): EventoDiagnosticoJitsi[] {
  return eventos;
}

export function assinarDiagnosticoJitsi(ouvinte: () => void): () => void {
  ouvintes.add(ouvinte);
  return () => ouvintes.delete(ouvinte);
}

export async function retratoDiagnosticoJitsi(): Promise<Record<string, unknown>> {
  const navegador = typeof navigator === "undefined" ? undefined : navigator;
  const base: Record<string, unknown> = {
    browser: navegador?.userAgent ?? "indisponível",
    mobile: Boolean(navegador && /Android|iPhone|iPad|iPod|Mobile/i.test(navegador.userAgent)),
    secureContext: typeof window !== "undefined" ? window.isSecureContext : false,
    mediaDevices: Boolean(navegador?.mediaDevices),
    getUserMedia: Boolean(navegador?.mediaDevices?.getUserMedia),
    enumerateDevices: Boolean(navegador?.mediaDevices?.enumerateDevices),
    online: navegador?.onLine ?? "indisponível",
  };
  const conexao = navegador && (navegador as Navigator & {
    connection?: { effectiveType?: string; downlink?: number; rtt?: number; saveData?: boolean };
  }).connection;
  if (conexao) {
    base.rede = {
      tipo: conexao.effectiveType ?? "desconhecido",
      downlink: conexao.downlink,
      rtt: conexao.rtt,
      economiaDados: conexao.saveData,
    };
  }
  if (!navegador?.mediaDevices) return base;
  try {
    const dispositivos = await navegador.mediaDevices.enumerateDevices();
    base.dispositivos = {
      cameras: dispositivos.filter((d) => d.kind === "videoinput").length,
      microfones: dispositivos.filter((d) => d.kind === "audioinput").length,
      saidasAudio: dispositivos.filter((d) => d.kind === "audiooutput").length,
    };
  } catch (erro) {
    base.erroDispositivos = erroDiagnosticoJitsi(erro);
  }
  for (const nome of ["camera", "microphone"] as const) {
    try {
      const permissao = await navegador.permissions?.query({ name: nome as PermissionName });
      base[`permissao_${nome}`] = permissao?.state ?? "não suportada";
    } catch {
      base[`permissao_${nome}`] = "não suportada";
    }
  }
  return base;
}
