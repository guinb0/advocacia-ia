"use client";

import { useState } from "react";

import type { SituacaoCaso } from "@/lib/types";
import estilos from "./Checklist.module.css";
import ItemChecklistLinha from "./ItemChecklistLinha";
import PainelPortal from "./PainelPortal";
import PedidoCliente from "./PedidoCliente";
import ui from "./ui.module.css";

type Filtro = "todos" | "obrigatorios" | "falta";

interface Props {
  situacao: SituacaoCaso;
  enviando: string | null;
  erro: string | null;
  onVoltar: () => void;
  onEnviar: (itemCodigo: string, arquivo: File, usarParaRgECpf?: boolean) => void;
  onRemover: (entregaId: string) => void;
  onVincularIdentidade: (entregaId: string, itemCodigo: string) => void;
}

/** "há 2 h", "há 3 dias" — a mesma leitura do cabeçalho no desenho. */
function desde(iso: string): string {
  const minutos = Math.floor((Date.now() - new Date(iso).getTime()) / 60_000);
  if (!Number.isFinite(minutos) || minutos < 1) return "agora";
  if (minutos < 60) return `há ${minutos} min`;
  const horas = Math.floor(minutos / 60);
  if (horas < 24) return `há ${horas} h`;
  const dias = Math.floor(horas / 24);
  return dias === 1 ? "há 1 dia" : `há ${dias} dias`;
}

export default function Checklist({
  situacao,
  enviando,
  erro,
  onVoltar,
  onEnviar,
  onRemover,
  onVincularIdentidade,
}: Props) {
  const [filtro, setFiltro] = useState<Filtro>("obrigatorios");
  const { caso, categoria, progresso, itens } = situacao;

  if (!categoria) {
    return (
      <>
        <button type="button" className={estilos.voltar} onClick={onVoltar}>
          ← Carteira
        </button>
        <div className={ui.caixaErro}>{situacao.erro ?? "Categoria indisponível."}</div>
      </>
    );
  }

  const naoResolvidos = itens.filter((i) => i.status !== "entregue").length;

  const visiveis = itens.filter((item) => {
    if (filtro === "obrigatorios") return item.obrigatorio;
    if (filtro === "falta") return item.status !== "entregue";
    return true;
  });

  const filtros: { id: Filtro; nome: string }[] = [
    { id: "obrigatorios", nome: `Obrigatórios (${progresso.obrigatorios_total})` },
    { id: "falta", nome: `Falta resolver (${naoResolvidos})` },
    { id: "todos", nome: `Todos (${itens.length})` },
  ];

  return (
    <>
      <button type="button" className={estilos.voltar} onClick={onVoltar}>
        ← Carteira
      </button>

      <div className={estilos.faixaCaso}>
        <span className={estilos.faixaRotulo}>CASO · {categoria.nome.toUpperCase()}</span>
        <span className={estilos.faixaMeta}>
          atualizado {desde(caso.atualizado_em || caso.criado_em)}
        </span>
      </div>
      <div className={estilos.filete} />

      <div className={estilos.identificacaoCaso}>
        <div>
          <h2 className={estilos.cliente}>{caso.cliente}</h2>
          <p className={estilos.descricao}>{categoria.descricao}</p>
        </div>
        <div>
          <span className={estilos.numeroGrande}>
            {progresso.obrigatorios_entregues}
            <span className={estilos.numeroTotal}>/{progresso.obrigatorios_total}</span>
          </span>
          <div className={estilos.numeroRotulo}>obrigatórios entregues</div>
        </div>
      </div>

      <div className={estilos.barra}>
        <i
          className={estilos.barraPreenchimento}
          style={{ width: `${Math.max(0, Math.min(100, progresso.percentual_obrigatorios))}%` }}
        />
      </div>

      <div className={estilos.contadores}>
        <span className={estilos.semArquivo}>
          <strong>{progresso.obrigatorios_pendentes}</strong> sem arquivo
        </span>
        <span className={estilos.aConferir}>
          <strong>{progresso.itens_a_conferir}</strong> a conferir
        </span>
        <span>
          <strong>{progresso.opcionais_entregues}</strong> opcionais de {progresso.opcionais_total}
        </span>
      </div>

      {progresso.pronto && (
        <div className={estilos.completo}>
          ✓ Todos os documentos obrigatórios foram entregues e validados.
        </div>
      )}

      {erro && <div className={ui.caixaErro}>{erro}</div>}

      <div className={estilos.abas} role="tablist">
        {filtros.map((f) => (
          <button
            key={f.id}
            type="button"
            role="tab"
            aria-selected={filtro === f.id}
            className={`${estilos.aba} ${filtro === f.id ? estilos.abaAtiva : ""}`}
            onClick={() => setFiltro(f.id)}
          >
            {f.nome}
          </button>
        ))}
      </div>

      {visiveis.length === 0 ? (
        <p className={ui.vazio}>Nada aqui — tudo resolvido neste filtro.</p>
      ) : (
        <ul className={estilos.lista}>
          {visiveis.map((item) => (
            <ItemChecklistLinha
              key={item.codigo}
              item={item}
              enviando={enviando === item.codigo}
              onEnviar={onEnviar}
              onRemover={onRemover}
              onVincularIdentidade={onVincularIdentidade}
            />
          ))}
        </ul>
      )}

      <div className={estilos.rodapePedido}>
        <span className={estilos.resumoPedido}>
          {naoResolvidos} {naoResolvidos === 1 ? "item pendente vira" : "itens pendentes viram"}{" "}
          texto pronto para o cliente
        </span>
      </div>

      <PainelPortal casoId={caso.id} />

      <div className={estilos.blocoPedido}>
        <PedidoCliente casoId={caso.id} progresso={progresso} />
      </div>
    </>
  );
}
