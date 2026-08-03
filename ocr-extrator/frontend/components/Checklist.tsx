"use client";

import { useState } from "react";

import type { SituacaoCaso } from "@/lib/types";
import { Barra } from "./Basicos";
import estilos from "./Checklist.module.css";
import ItemChecklistLinha from "./ItemChecklistLinha";
import PedidoCliente from "./PedidoCliente";
import ui from "./ui.module.css";

type Filtro = "todos" | "obrigatorios" | "falta";

interface Props {
  situacao: SituacaoCaso;
  enviando: string | null;
  erro: string | null;
  onVoltar: () => void;
  onEnviar: (itemCodigo: string, arquivo: File) => void;
  onRemover: (entregaId: string) => void;
}

export default function Checklist({
  situacao,
  enviando,
  erro,
  onVoltar,
  onEnviar,
  onRemover,
}: Props) {
  const [filtro, setFiltro] = useState<Filtro>("obrigatorios");
  const { caso, categoria, progresso, itens } = situacao;

  if (!categoria) {
    return (
      <div className={ui.card}>
        <button type="button" className={estilos.voltar} onClick={onVoltar}>
          ← Voltar
        </button>
        <div className={ui.caixaErro}>{situacao.erro ?? "Categoria indisponível."}</div>
      </div>
    );
  }

  const visiveis = itens.filter((item) => {
    if (filtro === "obrigatorios") return item.obrigatorio;
    if (filtro === "falta") return item.status !== "entregue";
    return true;
  });

  const filtros: { id: Filtro; nome: string }[] = [
    { id: "obrigatorios", nome: `Obrigatórios (${progresso.obrigatorios_total})` },
    { id: "falta", nome: `Falta resolver (${itens.filter((i) => i.status !== "entregue").length})` },
    { id: "todos", nome: `Todos (${itens.length})` },
  ];

  return (
    <>
      <div className={estilos.cabecalho}>
        <button type="button" className={estilos.voltar} onClick={onVoltar}>
          ← Casos
        </button>
        <div>
          <h2 className={estilos.cliente}>{caso.cliente}</h2>
          <span className={ui.observacao}>{categoria.nome}</span>
        </div>
      </div>

      <div className={estilos.paineis}>
        <div className={ui.card}>
          <h3 className={ui.tituloCard}>Progresso</h3>

          <div className={estilos.numeroGrande}>
            {progresso.obrigatorios_entregues}
            <span className={estilos.numeroTotal}>/{progresso.obrigatorios_total}</span>
          </div>
          <div className={ui.observacao}>documentos obrigatórios entregues</div>
          <Barra score={progresso.percentual_obrigatorios} />

          <div className={estilos.resumo}>
            <div>
              <strong>{progresso.obrigatorios_pendentes}</strong> obrigatórios sem arquivo
            </div>
            <div>
              <strong>{progresso.itens_a_conferir}</strong> a conferir
            </div>
            <div>
              <strong>{progresso.opcionais_entregues}</strong> opcionais de{" "}
              {progresso.opcionais_total}
            </div>
          </div>

          {progresso.pronto && (
            <div className={estilos.completo}>
              ✓ Todos os documentos obrigatórios foram entregues e validados.
            </div>
          )}
        </div>

        <PedidoCliente casoId={caso.id} progresso={progresso} />
      </div>

      {erro && <div className={ui.caixaErro}>{erro}</div>}

      <div className={ui.abas} role="tablist">
        {filtros.map((f) => (
          <button
            key={f.id}
            type="button"
            role="tab"
            aria-selected={filtro === f.id}
            className={`${ui.aba} ${filtro === f.id ? ui.abaAtiva : ""}`}
            onClick={() => setFiltro(f.id)}
          >
            {f.nome}
          </button>
        ))}
      </div>

      {visiveis.length === 0 ? (
        <div className={ui.vazio}>Nada aqui — tudo resolvido neste filtro.</div>
      ) : (
        <ul className={estilos.lista}>
          {visiveis.map((item) => (
            <ItemChecklistLinha
              key={item.codigo}
              item={item}
              enviando={enviando === item.codigo}
              onEnviar={onEnviar}
              onRemover={onRemover}
            />
          ))}
        </ul>
      )}
    </>
  );
}
