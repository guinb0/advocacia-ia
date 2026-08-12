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
  naoResolvidos,
}: {
  casoId: string;
  /** Só serve para refazer o pedido quando algo muda no checklist. */
  progresso: Progresso;
  /** Quantos itens do checklist ainda entram no texto do pedido. */
  naoResolvidos: number;
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
    <div className="cartao">
      <h3 className="tituloCartao">Pedido para o cliente</h3>
      <p className="subtituloCartao">
        {naoResolvidos === 0
          ? "Nada pendente — o texto abaixo só confirma o que já foi recebido."
          : `${naoResolvidos} ${naoResolvidos === 1 ? "item pendente virou" : "itens pendentes viraram"} a mensagem abaixo. Cole no WhatsApp ou no e-mail do cliente.`}
      </p>

      {pedido === null ? (
        <div className={ui.vazio}>Montando o pedido…</div>
      ) : (
        <>
          <div className={estilos.acoesPedido}>
            {/* A ação principal do bloco é copiar: é para isso que o bloco existe. */}
            <button type="button" className="botao botao--primario" onClick={copiar}>
              {copiado ? "✓ Mensagem copiada" : "Copiar a mensagem"}
            </button>
            <label className="marcacao">
              <input
                type="checkbox"
                checked={incluirOpcionais}
                onChange={(e) => setIncluirOpcionais(e.target.checked)}
              />
              <span>Incluir também os documentos opcionais</span>
            </label>
          </div>

          <label className="rotuloCampo" htmlFor="texto-pedido">
            Mensagem gerada
          </label>
          <textarea
            id="texto-pedido"
            className={estilos.textoPedido}
            value={pedido.texto}
            readOnly
            rows={12}
          />

          <p className="ajudaCampo">
            O texto se refaz sozinho conforme os documentos chegam — não precisa editar aqui.
          </p>
        </>
      )}
    </div>
  );
}
