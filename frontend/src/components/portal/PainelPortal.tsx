"use client";

import { useCallback, useEffect, useState } from "react";

import { consultarPortal, gerarPortal } from "@/lib/api";
import type { PortalGerado } from "@/lib/types";
import { Aviso, Botao, Cartao } from "@/components/ui/Basicos";
import ChamadaAoVivo from "@/components/chamada/ChamadaAoVivo";

/** Link e senha que o cliente usa para enviar documentos sozinho. */
export default function PainelPortal({
  casoId,
  semChamada = false,
}: {
  casoId: string;
  /* Não desenhar a chamada aqui dentro.
   *
   * Vale quando este painel aparece DENTRO do atendimento: ali a chamada já
   * está na tela, com o rosto do cliente, e o advogado já entrou na sala do
   * caso ao criá-lo. Sem esta trava, a página dos documentos abria uma segunda
   * chamada com câmera e tudo — duas do mesmo lado da conversa. */
  semChamada?: boolean;
}) {
  const [url, setUrl] = useState<string | null>(null);
  /* O mesmo token que abre o portal nomeia a sala da chamada — o cliente já o
   * tem no link, e ninguém entra na sala por adivinhação. */
  const [token, setToken] = useState<string | null>(null);
  const [ativo, setAtivo] = useState(false);
  /* A senha só existe em memória, e só logo após a geração: o backend guarda
   * apenas o hash. Sair da tela a perde de vez — por isso o aviso. */
  const [recemGerado, setRecemGerado] = useState<PortalGerado | null>(null);
  const [gerando, setGerando] = useState(false);
  const [erro, setErro] = useState<string | null>(null);
  const [copiado, setCopiado] = useState<string | null>(null);

  useEffect(() => {
    let cancelado = false;
    consultarPortal(casoId)
      .then((p) => {
        if (cancelado) return;
        setAtivo(p.ativo);
        setUrl(p.url);
        setToken(p.token);
      })
      .catch(() => {
        /* a tela mostra o botão de gerar */
      });
    return () => {
      cancelado = true;
    };
  }, [casoId]);

  const gerar = useCallback(async () => {
    setGerando(true);
    setErro(null);
    try {
      const p = await gerarPortal(casoId);
      setRecemGerado(p);
      setUrl(p.url);
      setToken(p.token);
      setAtivo(true);
    } catch (e) {
      setErro(e instanceof Error ? e.message : "Não foi possível gerar o link.");
    } finally {
      setGerando(false);
    }
  }, [casoId]);

  async function copiar(texto: string, qual: string) {
    try {
      await navigator.clipboard.writeText(texto);
      setCopiado(qual);
      setTimeout(() => setCopiado(null), 2000);
    } catch {
      // Sem permissão de área de transferência: o texto está visível para
      // seleção manual, então não vale interromper o fluxo com um erro.
    }
  }

  return (
    <>
      <Cartao
        titulo="Portal do cliente"
        subtitulo="Um endereço com senha para o próprio cliente enviar os documentos e acompanhar o que ainda falta."
      >
        {erro && (
          <div className="mb-[14px]">
            <Aviso tom="critico" titulo="Não foi possível gerar o acesso">
              {erro}
            </Aviso>
          </div>
        )}

        {!ativo ? (
          <Botao variante="primario" onClick={gerar} disabled={gerando}>
            {gerando ? "Gerando…" : "Gerar o link e a senha"}
          </Botao>
        ) : (
          <>
            <div className="flex items-center gap-[10px] px-3 py-[10px] mb-2 border border-borda rounded-campo bg-papel-2 flex-wrap">
              <span className="flex-none w-[52px] text-tinta-3 text-xs font-semibold">Link</span>
              <span className="flex-1 min-w-[190px] text-tinta font-codigo text-xs [overflow-wrap:anywhere] select-all">
                {url}
              </span>
              <Botao variante="secundario" pequeno onClick={() => url && copiar(url, "url")}>
                {copiado === "url" ? "✓ Copiado" : "Copiar"}
              </Botao>
            </div>

            {recemGerado ? (
              <>
                <div className="flex items-center gap-[10px] px-3 py-[10px] mb-2 border border-borda rounded-campo bg-papel-2 flex-wrap">
                  <span className="flex-none w-[52px] text-tinta-3 text-xs font-semibold">Senha</span>
                  <span className="flex-1 min-w-[190px] text-tinta font-codigo [overflow-wrap:anywhere] select-all text-[1.25rem] font-semibold tracking-[0.16em] leading-[1.3]">
                    {recemGerado.senha}
                  </span>
                  <Botao variante="secundario" pequeno onClick={() => copiar(recemGerado.senha, "senha")}>
                    {copiado === "senha" ? "✓ Copiado" : "Copiar"}
                  </Botao>
                </div>

                <Aviso tom="atencao" titulo="Copie a senha agora">
                  {recemGerado.aviso}
                </Aviso>

                <div className="flex gap-[10px] items-center flex-wrap mt-3">
                  <Botao
                    variante="primario"
                    onClick={() =>
                      copiar(
                        `Olá! Envie seus documentos por aqui: ${recemGerado.url}\nSenha: ${recemGerado.senha}`,
                        "msg",
                      )
                    }
                  >
                    {copiado === "msg" ? "✓ Mensagem copiada" : "Copiar a mensagem pronta"}
                  </Botao>
                </div>
              </>
            ) : (
              <>
                <p className="mb-[14px] mt-0 max-w-[62ch] text-tinta-2 text-sm leading-[1.6]">
                  A senha aparece uma única vez, no momento em que é criada, e não pode ser
                  consultada depois. Se o cliente a perdeu, gere outra — a anterior deixa de valer
                  na hora.
                </p>
                <Botao
                  variante="secundario"
                  onClick={gerar}
                  disabled={gerando}
                  title="O link e a senha anteriores param de funcionar"
                >
                  {gerando ? "Gerando…" : "Gerar uma nova senha"}
                </Botao>
              </>
            )}
          </>
        )}
      </Cartao>

    {/* Trocar a senha troca a sala: a chave remonta a chamada em vez de
        deixá-la apontando para uma sala que o cliente não alcança mais. */}
    {ativo && token && !semChamada && <ChamadaAoVivo key={token} sala={token} />}
    </>
  );
}
