"use client";

import { useState } from "react";

import type { PortalGerado } from "@/lib/types";
import { enviarPortalWhatsApp } from "@/lib/api";
import { formatarTelefone } from "@/lib/formato";
import { Botao, Campo } from "@/components/ui/Basicos";
import { BotaoProcesso } from "@/components/ui/BotaoProcesso";

/** Link e senha do caso recém-criado.
 *
 * Aparece uma vez só, e de propósito: o backend guarda apenas o hash da senha,
 * então este é o único momento em que ela existe em texto claro. Fechar sem
 * copiar obriga a gerar outra. */
export default function CredenciaisPortal({
  cliente,
  portal,
  casoId,
  telefone = "",
  onAbrirCaso,
  onFechar,
}: {
  cliente: string;
  portal: PortalGerado;
  casoId?: string;
  telefone?: string;
  onAbrirCaso: () => void;
  onFechar: () => void;
}) {
  const [copiado, setCopiado] = useState<string | null>(null);
  const [numero, setNumero] = useState(formatarTelefone(telefone));
  const [enviando, setEnviando] = useState(false);
  const [envio, setEnvio] = useState<{ ok: boolean; texto: string } | null>(null);

  const mensagem =
    `Olá, ${cliente}! Envie os documentos do seu processo por aqui:\n` +
    `${portal.url}\n\nSenha: ${portal.senha}`;
  const digitos = numero.replace(/\D/g, "");
  const linkWhatsApp = `https://wa.me/${digitos.length <= 11 ? `55${digitos}` : digitos}?text=${encodeURIComponent(mensagem)}`;

  async function copiar(texto: string, qual: string) {
    try {
      await navigator.clipboard.writeText(texto);
      setCopiado(qual);
      setTimeout(() => setCopiado(null), 2000);
    } catch {
      // Sem permissão de área de transferência: o texto continua visível para
      // seleção manual, então não vale interromper o fluxo com um erro.
    }
  }

  async function enviar() {
    if (!casoId) return;
    setEnviando(true);
    setEnvio(null);
    try {
      await enviarPortalWhatsApp(casoId, portal.senha, numero);
      setEnvio({ ok: true, texto: "Link e senha enviados ao WhatsApp do cliente." });
    } catch (e) {
      setEnvio({ ok: false, texto: e instanceof Error ? e.message : "Não foi possível enviar pelo WhatsApp." });
    } finally {
      setEnviando(false);
    }
  }

  return (
    <div
      className="mt-[18px] p-4 border border-atencao-borda border-l-4 rounded-campo bg-atencao-claro"
      style={{ borderLeftColor: "var(--atencao-marca)" }}
      role="status"
    >
      <span className="flex items-center gap-2 mb-1 text-tinta text-base font-bold">
        <span className="text-atencao" aria-hidden>
          !
        </span>
        Caso criado — copie a senha agora
      </span>
      <p className="mb-[14px] max-w-[56ch] text-tinta-2 text-xs leading-[1.55]">{portal.aviso}</p>

      {/* De quem são estas credenciais.
        *
        * Elas abrem o portal do CLIENTE, e só ele precisa delas — quem está
        * aqui já entrou no sistema pelo login e já está na sala do caso. Sem
        * esta linha, o atendente tentava usar o link e a senha para "entrar no
        * caso", que é o caminho errado e pede senha à toa. */}
      <p className="mb-[14px] max-w-[56ch] text-tinta-2 text-xs leading-[1.55]">
        <strong>Link e senha são do cliente.</strong> Você não precisa deles: o caso já
        está aberto aí embaixo e você já está na sala da chamada.
      </p>

      <div className="flex items-center gap-[10px] px-3 py-[10px] mb-2 border border-borda-forte rounded-campo bg-papel flex-wrap">
        <span className="flex-none w-[52px] text-tinta-3 text-xs font-semibold">Link</span>
        <span className="flex-1 min-w-[170px] text-tinta font-codigo text-xs [overflow-wrap:anywhere] select-all">
          {portal.url}
        </span>
        <Botao variante="secundario" pequeno onClick={() => copiar(portal.url, "url")}>
          {copiado === "url" ? "✓ Copiado" : "Copiar"}
        </Botao>
      </div>

      <div className="flex items-center gap-[10px] px-3 py-[10px] mb-2 border border-borda-forte rounded-campo bg-papel flex-wrap">
        <span className="flex-none w-[52px] text-tinta-3 text-xs font-semibold">Senha</span>
        <span className="flex-1 min-w-[170px] text-tinta font-codigo [overflow-wrap:anywhere] select-all text-[1.35rem] font-semibold tracking-[0.16em] leading-[1.3]">
          {portal.senha}
        </span>
        <Botao variante="secundario" pequeno onClick={() => copiar(portal.senha, "senha")}>
          {copiado === "senha" ? "✓ Copiado" : "Copiar"}
        </Botao>
      </div>

      <div className="flex items-center gap-[10px] px-3 py-[10px] mb-2 border border-borda-forte rounded-campo bg-papel flex-wrap">
        <span className="flex-none w-[52px] text-tinta-3 text-xs font-semibold">WhatsApp</span>
        <Campo
          className="flex-1 min-w-[170px]"
          type="tel"
          inputMode="tel"
          value={numero}
          onChange={(e) => setNumero(formatarTelefone(e.target.value))}
          placeholder="(61) 98180-8863"
        />
        {casoId && (
          <BotaoProcesso
            variante="primario"
            pequeno
            onClick={enviar}
            processando={enviando}
            textoProcessando="Enviando…"
            pendencia={digitos.length >= 10 ? null : "Informe o WhatsApp do cliente com DDD."}
          >
            Enviar link e senha
          </BotaoProcesso>
        )}
        {digitos.length >= 10 && (
          <a
            className="text-xs font-semibold text-acao underline"
            href={linkWhatsApp}
            target="_blank"
            rel="noreferrer"
          >
            Abrir no meu WhatsApp
          </a>
        )}
      </div>
      {envio && (
        <p className={`mb-2 mt-0 text-xs leading-[1.5] ${envio.ok ? "text-ok" : "text-critico"}`} aria-live="polite">
          {envio.texto}
        </p>
      )}

      <div className="flex gap-[10px] flex-wrap items-center mt-[14px]">
        <Botao variante="secundario" onClick={() => copiar(mensagem, "msg")}>
          {copiado === "msg" ? "✓ Mensagem copiada" : "Copiar a mensagem para o cliente"}
        </Botao>
        <Botao variante="secundario" onClick={onAbrirCaso}>
          Abrir o caso
        </Botao>
        <Botao variante="discreto" onClick={onFechar}>
          Fechar
        </Botao>
      </div>
    </div>
  );
}
