"use client";

import { useState } from "react";

import type { SituacaoCaso } from "@/lib/types";
import { Aviso, Selo } from "./Basicos";
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
        <button
          type="button"
          className={`botao botao--secundario ${estilos.voltar}`}
          onClick={onVoltar}
        >
          ← Voltar para a carteira
        </button>
        <Aviso tom="critico" titulo="Categoria indisponível">
          {situacao.erro ?? "O tipo de ação deste caso não pôde ser carregado."}
        </Aviso>
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
    { id: "todos", nome: `Todos os documentos (${itens.length})` },
  ];

  const pct = Math.max(0, Math.min(100, progresso.percentual_obrigatorios));

  return (
    <>
      <button
        type="button"
        className={`botao botao--secundario ${estilos.voltar}`}
        onClick={onVoltar}
      >
        ← Voltar para a carteira
      </button>

      <div className={estilos.cartaoCaso}>
        <div className={estilos.faixaCaso}>
          <Selo tom="info">{categoria.nome}</Selo>
          <span className={estilos.faixaMeta}>
            atualizado {desde(caso.atualizado_em || caso.criado_em)}
          </span>
        </div>

        <div className={estilos.identificacaoCaso}>
          <div>
            <h2 className={estilos.cliente}>{caso.cliente}</h2>
            <p className={estilos.descricao}>{categoria.descricao}</p>
          </div>
          <div className={estilos.numeros}>
            <span className={estilos.numeroGrande}>
              {progresso.obrigatorios_entregues}
              <span className={estilos.numeroTotal}>/{progresso.obrigatorios_total}</span>
            </span>
            <div className={estilos.numeroRotulo}>documentos obrigatórios entregues</div>
          </div>
        </div>

        <div
          className={estilos.barra}
          role="progressbar"
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={pct}
          aria-label="Documentos obrigatórios entregues"
        >
          <i className={estilos.barraPreenchimento} style={{ width: `${pct}%` }} />
        </div>

        <div className={estilos.contadores}>
          {progresso.obrigatorios_pendentes > 0 && (
            <Selo tom="critico" simbolo="✕">
              {progresso.obrigatorios_pendentes} sem arquivo
            </Selo>
          )}
          {progresso.itens_a_conferir > 0 && (
            <Selo tom="atencao" simbolo="!">
              {progresso.itens_a_conferir} a conferir
            </Selo>
          )}
          <Selo tom="neutro">
            {progresso.opcionais_entregues} de {progresso.opcionais_total} opcionais
          </Selo>
        </div>

        {progresso.pronto && (
          <div style={{ marginTop: 16 }}>
            <Aviso tom="ok" titulo="Instrução completa">
              Todos os documentos obrigatórios foram entregues e conferidos. O caso está pronto
              para a inicial.
            </Aviso>
          </div>
        )}
      </div>

      {erro && (
        <div style={{ marginBottom: 16 }}>
          <Aviso tom="critico" titulo="Não foi possível concluir a ação">
            {erro}
          </Aviso>
        </div>
      )}

      <div className={estilos.abas} role="tablist" aria-label="Filtrar os documentos">
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
        <div style={{ marginTop: 16 }}>
          <div className={ui.vazio}>Nada aqui — tudo resolvido neste filtro.</div>
        </div>
      ) : (
        <div className={estilos.painelLista}>
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
        </div>
      )}

      <div className={estilos.blocoFinal}>
        <PainelPortal casoId={caso.id} />
        <PedidoCliente casoId={caso.id} progresso={progresso} naoResolvidos={naoResolvidos} />
      </div>
    </>
  );
}
