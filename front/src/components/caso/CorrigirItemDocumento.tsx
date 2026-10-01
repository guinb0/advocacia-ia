"use client";

import { useState } from "react";

import type {
  DuplicidadeDocumento,
  EventoHistorico,
  ItemSituacao,
  OpcoesReclassificacao,
} from "@/lib/types";
import { duplicidadesDoErro, historicoEntrega } from "@/lib/api";
import { useTiposDocumento } from "@/lib/tiposDocumento";
import { Botao } from "@/components/ui/Basicos";
import { BotaoProcesso } from "@/components/ui/BotaoProcesso";
import AvisoDuplicidade from "@/components/caso/AvisoDuplicidade";

interface Props {
  entregaId: string;
  itemAtual: string;
  itens: ItemSituacao[];
  onReatribuir: (
    entregaId: string,
    itens: string[],
    opcoes?: OpcoesReclassificacao,
  ) => Promise<void> | void;
  /** Destaque quando a leitura automática encaminhou o arquivo. */
  destacar?: boolean;
  /** Abre o painel de movimentação de cara — útil na coleta documental. */
  expandidoPorPadrao?: boolean;
  rotulo?: string;
}

const CAMPO =
  "block w-full min-h-10 mt-1 px-3 border border-borda-campo rounded-campo bg-papel text-tinta text-sm";

const ROTULO_ACAO: Record<string, string> = {
  reclassificada: "Reclassificado",
  devolvida_triagem: "Devolvido à triagem",
  duplicidade_confirmada: "Arquivo repetido aceito no envio",
  removida: "Removido",
};

function quando(iso: string): string {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "" : d.toLocaleString("pt-BR");
}

/** Reclassifica um documento já lido — item do checklist e tipo do glossário — ou o
 *  devolve à triagem. Antes de gravar, o servidor procura duplicidade no caso; havendo
 *  suspeita, a conclusão pede confirmação. */
export default function CorrigirItemDocumento({
  entregaId,
  itemAtual,
  itens,
  onReatribuir,
  destacar = false,
  expandidoPorPadrao = false,
  rotulo = "Corrigir classificação",
}: Props) {
  const [aberto, setAberto] = useState(destacar || expandidoPorPadrao);
  const [destino, setDestino] = useState("");
  const [tipo, setTipo] = useState("");
  /* O tipo acompanha o item escolhido até a pessoa mexer nele: depois disso, trocar
   * de item não pode desfazer a escolha feita à mão. */
  const [tipoEscolhidoAMao, setTipoEscolhidoAMao] = useState(false);
  const [motivo, setMotivo] = useState("");
  const [salvando, setSalvando] = useState(false);
  const [erro, setErro] = useState<string | null>(null);
  const [suspeitas, setSuspeitas] = useState<{
    lista: DuplicidadeDocumento[];
    mensagem: string;
  } | null>(null);
  const [historico, setHistorico] = useState<EventoHistorico[] | null>(null);
  const [abrindoHistorico, setAbrindoHistorico] = useState(false);
  const { tipos } = useTiposDocumento();

  if (!aberto) {
    return (
      <Botao
        variante={destacar ? "secundario" : "discreto"}
        pequeno
        onClick={() => setAberto(true)}
        title="Corrigir o tipo identificado automaticamente"
      >
        {rotulo}
      </Botao>
    );
  }

  const nomeDoTipo = (codigo: unknown) =>
    tipos.find((t) => t.codigo === codigo)?.nome ?? (codigo ? String(codigo) : "sem tipo");
  const nomeDosItens = (codigos: unknown) => {
    const lista = Array.isArray(codigos) ? codigos.map(String) : [];
    if (lista.length === 0) return "triagem";
    return lista.map((c) => itens.find((i) => i.codigo === c)?.nome ?? c).join(" e ");
  };

  function descrever(evento: EventoHistorico): string {
    const { antes, depois } = evento;
    if (evento.acao === "removida") return `Arquivo ${String(antes?.arquivo ?? "")}.`;
    if (evento.acao === "duplicidade_confirmada") {
      const repetidos = (depois?.duplicidades as DuplicidadeDocumento[] | undefined) ?? [];
      return `Idêntico a ${repetidos.map((d) => d.arquivo).join(", ")}.`;
    }
    if (!antes || !depois) return "";
    let texto =
      `De ${nomeDoTipo(antes.tipo_documento)} (${nomeDosItens(antes.itens_atendidos)}) ` +
      `para ${nomeDoTipo(depois.tipo_documento)} (${nomeDosItens(depois.itens_atendidos)}).`;
    const confirmadas = depois.duplicidades_confirmadas as DuplicidadeDocumento[] | undefined;
    if (confirmadas?.length) {
      texto += ` Confirmado apesar de parecer repetir ${confirmadas.map((d) => d.arquivo).join(", ")}.`;
    }
    return texto;
  }

  function escolherDestino(codigo: string) {
    setDestino(codigo);
    setSuspeitas(null);
    if (!tipoEscolhidoAMao) {
      setTipo(itens.find((i) => i.codigo === codigo)?.tipo_documento ?? "");
    }
  }

  function fechar() {
    setAberto(false);
    setDestino("");
    setTipo("");
    setTipoEscolhidoAMao(false);
    setMotivo("");
    setSuspeitas(null);
    setErro(null);
  }

  async function aplicar(novoDestino: string | null, confirmar = false) {
    setSalvando(true);
    setErro(null);
    const motivoLimpo = motivo.trim() || undefined;
    try {
      await onReatribuir(
        entregaId,
        novoDestino ? [novoDestino] : [],
        novoDestino
          ? { tipo: tipo || undefined, motivo: motivoLimpo, confirmarDuplicidade: confirmar }
          : { motivo: motivoLimpo },
      );
      fechar();
    } catch (e) {
      const lista = duplicidadesDoErro(e);
      if (lista) setSuspeitas({ lista, mensagem: e instanceof Error ? e.message : "" });
      else setErro(e instanceof Error ? e.message : "Não foi possível salvar a classificação.");
    } finally {
      setSalvando(false);
    }
  }

  async function alternarHistorico() {
    if (historico) {
      setHistorico(null);
      return;
    }
    setAbrindoHistorico(true);
    try {
      setHistorico(await historicoEntrega(entregaId));
    } catch (e) {
      setErro(e instanceof Error ? e.message : "Não foi possível abrir o histórico.");
    } finally {
      setAbrindoHistorico(false);
    }
  }

  return (
    <div className="[flex-basis:100%] mt-2 p-3 border border-borda rounded-campo bg-papel">
      <p className="m-0 mb-2 text-tinta-2 text-xs leading-[1.5]">
        A classificação automática pode errar. Escolha o item do checklist e o tipo do documento:
        o checklist será ajustado, a classificação anterior fica no histórico e esta correção
        ajudará nas próximas leituras.
      </p>
      <div className="grid gap-2 grid-cols-[minmax(0,1fr)_minmax(0,1fr)] max-[640px]:grid-cols-1">
        <label className="min-w-0 text-xs text-tinta-3">
          Item do checklist
          <select
            className={CAMPO}
            value={destino}
            disabled={salvando}
            onChange={(evento) => escolherDestino(evento.target.value)}
          >
            <option value="">Escolha o item…</option>
            {itens.map((item) => (
              <option key={item.codigo} value={item.codigo}>
                {item.nome} ({item.codigo}){item.codigo === itemAtual ? " — atual" : ""}
              </option>
            ))}
          </select>
        </label>
        <label className="min-w-0 text-xs text-tinta-3">
          Tipo do documento
          <select
            className={CAMPO}
            value={tipo}
            disabled={salvando || !destino}
            onChange={(evento) => {
              setTipo(evento.target.value);
              setTipoEscolhidoAMao(true);
              setSuspeitas(null);
            }}
          >
            <option value="">O tipo que o item pede</option>
            {tipos.map((t) => (
              <option key={t.codigo} value={t.codigo}>
                {t.nome}
              </option>
            ))}
          </select>
        </label>
      </div>
      <label className="block mt-2 text-xs text-tinta-3">
        Motivo (opcional — fica no histórico)
        <input
          type="text"
          className={CAMPO}
          maxLength={600}
          value={motivo}
          disabled={salvando}
          onChange={(evento) => setMotivo(evento.target.value)}
        />
      </label>

      {suspeitas && (
        <div className="mt-3">
          <AvisoDuplicidade
            mensagem={suspeitas.mensagem}
            duplicidades={suspeitas.lista}
            itens={itens}
            confirmando={salvando}
            rotuloConfirmar="Reclassificar mesmo assim"
            onConfirmar={() => aplicar(destino, true)}
            onCancelar={() => setSuspeitas(null)}
          />
        </div>
      )}
      {erro && (
        <p className="mt-2 mb-0 text-critico text-xs" role="alert">
          {erro}
        </p>
      )}

      <div className="flex gap-2 items-end flex-wrap mt-3">
        <BotaoProcesso
          variante="primario"
          pequeno
          onClick={() => aplicar(destino)}
          textoProcessando="Salvando…"
          pendencia={
            !destino
              ? "Escolha ao lado o item do checklist."
              : suspeitas
                ? "Decida acima sobre o documento parecido."
                : null
          }
          pendenciaAoClicar
          aguardando={salvando}
        >
          Salvar classificação
        </BotaoProcesso>
        <BotaoProcesso
          variante="secundario"
          pequeno
          onClick={() => aplicar(null)}
          textoProcessando="Devolvendo…"
          aguardando={salvando}
        >
          Devolver à triagem
        </BotaoProcesso>
        <Botao
          variante="texto"
          pequeno
          carregando={abrindoHistorico}
          textoCarregando="Abrindo…"
          onClick={() => void alternarHistorico()}
        >
          {historico ? "Ocultar histórico" : "Histórico"}
        </Botao>
        <BotaoProcesso variante="texto" pequeno aguardando={salvando} onClick={fechar}>
          Cancelar
        </BotaoProcesso>
      </div>

      {historico && (
        <ol className="list-none m-0 mt-3 p-0 border-t border-borda">
          {historico.length === 0 ? (
            <li className="py-2 text-xs text-tinta-3">
              Nenhuma alteração registrada para este documento.
            </li>
          ) : (
            historico.map((evento) => (
              <li
                key={evento.id}
                className="py-2 border-b border-borda last:border-b-0 text-xs leading-[1.5] text-tinta-2"
              >
                <strong className="text-tinta">{ROTULO_ACAO[evento.acao] ?? evento.acao}</strong>
                {" · "}
                {quando(evento.criado_em)}
                {" · "}
                {evento.usuario}
                <span className="block">{descrever(evento)}</span>
                {evento.motivo && <span className="block text-tinta-3">Motivo: {evento.motivo}</span>}
              </li>
            ))
          )}
        </ol>
      )}
    </div>
  );
}
