"use client";

import { useCallback, useEffect, useState } from "react";

import { obterPedido } from "@/lib/api";
import type { Pedido, Progresso } from "@/lib/types";
import estilos from "./Checklist.module.css";
import ui from "./ui.module.css";

/** Painel que gera o texto pronto para o advogado mandar ao cliente. */
export default function PedidoCliente({
  casoId,
  progresso,
}: {
  casoId: string;
  /** Só serve para refazer o pedido quando algo muda no checklist. */
  progresso: Progresso;
}) {
  const [pedido, setPedido] = useState<Pedido | null>(null);
  const [incluirOpcionais, setIncluirOpcionais] = useState(false);
  const [copiado, setCopiado] = useState(false);

  const chave = `${progresso.obrigatorios_entregues}-${progresso.itens_a_conferir}-${progresso.opcionais_entregues}`;

  useEffect(() => {
    let cancelado = false;
    obterPedido(casoId, incluirOpcionais)
      .then((p) => {
        if (!cancelado) setPedido(p);
      })
      .catch(() => {
        if (!cancelado) setPedido(null);
      });
    return () => {
      cancelado = true;
    };
  }, [casoId, incluirOpcionais, chave]);

  const copiar = useCallback(async () => {
    if (!pedido) return;
    try {
      await navigator.clipboard.writeText(pedido.texto);
      setCopiado(true);
      setTimeout(() => setCopiado(false), 2000);
    } catch {
      // Sem permissão de área de transferência: o texto continua visível para
      // seleção manual, então não vale interromper o fluxo com um erro.
      setCopiado(false);
    }
  }, [pedido]);

  return (
    <div className={ui.card}>
      <h3 className={ui.tituloCard}>Pedido para o cliente</h3>

      {pedido === null ? (
        <div className={ui.vazio}>Montando o pedido…</div>
      ) : (
        <>
          <div className={estilos.acoesPedido}>
            <button type="button" className={estilos.botaoCopiar} onClick={copiar}>
              {copiado ? "✓ Copiado" : "Copiar mensagem"}
            </button>
            <label className={estilos.checkbox}>
              <input
                type="checkbox"
                checked={incluirOpcionais}
                onChange={(e) => setIncluirOpcionais(e.target.checked)}
              />
              incluir opcionais
            </label>
          </div>

          <textarea className={estilos.textoPedido} value={pedido.texto} readOnly rows={12} />

          <p className={ui.observacao}>
            Cole no WhatsApp ou no e-mail do cliente. O texto se refaz sozinho conforme os
            documentos chegam.
          </p>
        </>
      )}
    </div>
  );
}
