"use client";

import type { DuplicidadeDocumento, ItemSituacao } from "@/lib/types";
import { Aviso, Botao } from "@/components/ui/Basicos";
import { BotaoProcesso } from "@/components/ui/BotaoProcesso";

interface Props {
  /** A frase do servidor — já diz qual arquivo e desde quando. */
  mensagem: string;
  duplicidades: DuplicidadeDocumento[];
  /** Para dizer o nome do item em que o documento parecido está. */
  itens?: ItemSituacao[];
  confirmando?: boolean;
  rotuloConfirmar: string;
  onConfirmar: () => Promise<void> | void;
  onCancelar: () => void;
}

/** A suspeita de documento repetido, com a decisão na mão de quem está olhando.
 *
 * Não decide sozinho: dois atestados parecidos podem ser de dias diferentes. O que
 * ele garante é que ninguém conclua sem ter visto a suspeita — e confirmar deixa
 * registro no histórico do documento. */
export default function AvisoDuplicidade({
  mensagem,
  duplicidades,
  itens = [],
  confirmando = false,
  rotuloConfirmar,
  onConfirmar,
  onCancelar,
}: Props) {
  const nomeDoItem = (codigo: string) => itens.find((i) => i.codigo === codigo)?.nome ?? codigo;

  return (
    <Aviso tom="atencao" titulo="Possível documento repetido">
      <p className="m-0">{mensagem}</p>
      <ul className="mt-2 mb-0 pl-4">
        {duplicidades.map((d) => (
          <li key={d.entrega_id}>
            <span className="font-codigo [overflow-wrap:anywhere]">{d.arquivo}</span> — {d.explicacao}
            {d.itens.length ? ` · em ${d.itens.map(nomeDoItem).join(", ")}` : " · na triagem"}
          </li>
        ))}
      </ul>
      <p className="mt-2 mb-0">
        Se for o mesmo documento, cancele e remova a cópia que sobrar. Se não for, confirme: a
        decisão fica registrada no histórico do documento.
      </p>
      <div className="flex gap-2 flex-wrap items-start mt-2">
        <BotaoProcesso
          variante="primario"
          pequeno
          processando={confirmando}
          textoProcessando="Salvando…"
          onClick={() => onConfirmar()}
        >
          {rotuloConfirmar}
        </BotaoProcesso>
        <Botao variante="texto" pequeno onClick={onCancelar}>
          Cancelar
        </Botao>
      </div>
    </Aviso>
  );
}
