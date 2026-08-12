"use client";

import { useCallback, useEffect, useState } from "react";

import { consultarPortal, gerarPortal } from "@/lib/api";
import type { PortalGerado } from "@/lib/types";
import { Aviso } from "./Basicos";
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
    <div className="cartao">
      <h3 className="tituloCartao">Portal do cliente</h3>
      <p className="subtituloCartao">
        Um endereço com senha para o próprio cliente enviar os documentos e acompanhar o que ainda
        falta.
      </p>

      {erro && (
        <div style={{ marginBottom: 14 }}>
          <Aviso tom="critico" titulo="Não foi possível gerar o acesso">
            {erro}
          </Aviso>
        </div>
      )}

      {!ativo ? (
        <button type="button" className="botao botao--primario" onClick={gerar} disabled={gerando}>
          {gerando ? "Gerando…" : "Gerar o link e a senha"}
        </button>
      ) : (
        <>
          <div className={estilos.linha}>
            <span className={estilos.chave}>Link</span>
            <span className={estilos.valor}>{url}</span>
            <button
              type="button"
              className="botao botao--secundario botao--pequeno"
              onClick={() => url && copiar(url, "url")}
            >
              {copiado === "url" ? "✓ Copiado" : "Copiar"}
            </button>
          </div>

          {recemGerado ? (
            <>
              <div className={estilos.linha}>
                <span className={estilos.chave}>Senha</span>
                <span className={`${estilos.valor} ${estilos.senha}`}>{recemGerado.senha}</span>
                <button
                  type="button"
                  className="botao botao--secundario botao--pequeno"
                  onClick={() => copiar(recemGerado.senha, "senha")}
                >
                  {copiado === "senha" ? "✓ Copiado" : "Copiar"}
                </button>
              </div>

              <Aviso tom="atencao" titulo="Copie a senha agora">
                {recemGerado.aviso}
              </Aviso>

              <div className={estilos.acoes}>
                <button
                  type="button"
                  className="botao botao--primario"
                  onClick={() =>
                    copiar(
                      `Olá! Envie seus documentos por aqui: ${recemGerado.url}\nSenha: ${recemGerado.senha}`,
                      "msg",
                    )
                  }
                >
                  {copiado === "msg" ? "✓ Mensagem copiada" : "Copiar a mensagem pronta"}
                </button>
              </div>
            </>
          ) : (
            <>
              <p className={estilos.texto}>
                A senha aparece uma única vez, no momento em que é criada, e não pode ser
                consultada depois. Se o cliente a perdeu, gere outra — a anterior deixa de valer
                na hora.
              </p>
              <button
                type="button"
                className="botao botao--secundario"
                onClick={gerar}
                disabled={gerando}
                title="O link e a senha anteriores param de funcionar"
              >
                {gerando ? "Gerando…" : "Gerar uma nova senha"}
              </button>
            </>
          )}
        </>
      )}
    </div>
  );
}
