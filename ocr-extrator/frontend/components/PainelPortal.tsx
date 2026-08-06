"use client";

import { useCallback, useEffect, useState } from "react";

import { consultarPortal, gerarPortal } from "@/lib/api";
import type { PortalGerado } from "@/lib/types";
import estilos from "./PainelPortal.module.css";

/** Link e senha que o cliente usa para enviar documentos sozinho. */
export default function PainelPortal({ casoId }: { casoId: string }) {
  const [url, setUrl] = useState<string | null>(null);
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
    <div className={estilos.bloco}>
      <span className={estilos.rotulo}>PORTAL DO CLIENTE</span>

      {erro && <div className={estilos.erro}>{erro}</div>}

      {!ativo ? (
        <>
          <p className={estilos.texto}>
            Gere um link com senha para o cliente enviar os documentos sozinho e acompanhar
            o que ainda falta.
          </p>
          <button type="button" className={estilos.botao} onClick={gerar} disabled={gerando}>
            {gerando ? "Gerando…" : "Gerar link e senha"}
          </button>
        </>
      ) : (
        <>
          <div className={estilos.linha}>
            <span className={estilos.valor}>{url}</span>
            <button
              type="button"
              className={estilos.acao}
              onClick={() => url && copiar(url, "url")}
            >
              {copiado === "url" ? "✓" : "Copiar"}
            </button>
          </div>

          {recemGerado ? (
            <>
              <div className={estilos.linha}>
                <span className={`${estilos.valor} ${estilos.senha}`}>{recemGerado.senha}</span>
                <button
                  type="button"
                  className={estilos.acao}
                  onClick={() => copiar(recemGerado.senha, "senha")}
                >
                  {copiado === "senha" ? "✓" : "Copiar"}
                </button>
              </div>
              <p className={estilos.aviso}>{recemGerado.aviso}</p>
              <button
                type="button"
                className={estilos.acao}
                onClick={() =>
                  copiar(
                    `Olá! Envie seus documentos por aqui: ${recemGerado.url}\nSenha: ${recemGerado.senha}`,
                    "msg",
                  )
                }
              >
                {copiado === "msg" ? "✓ Mensagem copiada" : "Copiar mensagem pronta"}
              </button>
            </>
          ) : (
            <p className={estilos.texto}>
              A senha foi mostrada só na geração e não pode ser consultada. Se o cliente
              perdeu, gere outra — a anterior deixa de valer.
            </p>
          )}

          <button
            type="button"
            className={estilos.trocar}
            onClick={gerar}
            disabled={gerando}
            title="A senha e o link anteriores param de funcionar"
          >
            {gerando ? "Gerando…" : "Gerar nova senha"}
          </button>
        </>
      )}
    </div>
  );
}
