"use client";

/**
 * Marca a petição como protocolada, com o número e a data do protocolo.
 *
 * Fica fora do `status` de revisão: aprovar é decisão interna do escritório, protocolar
 * é o que aconteceu no tribunal. Uma petição pode ser protocolada sem ter passado pela
 * revisão formal, e gerar a peça de novo não desfaz o protocolo.
 *
 * Digitar o número é a confirmação: sem ele o botão não libera, e o servidor recusa.
 * As peças marcadas aparecem na tela "Peças protocoladas".
 */

import { useState } from "react";

import { Aviso, Botao, Campo, RotuloCampo, Selo } from "@/components/ui/Basicos";
import { marcarProtocoloDaPeticao, type Peticao, type ProtocoloDaPeticao } from "@/lib/agente";

function hoje(): string {
  const agora = new Date();
  return new Date(agora.getTime() - agora.getTimezoneOffset() * 60_000).toISOString().slice(0, 10);
}

function dataBr(iso: string): string {
  const [ano, mes, dia] = iso.split("-");
  return ano && mes && dia ? `${dia}/${mes}/${ano}` : iso;
}

type Props = {
  casoId: string;
  protocolo: ProtocoloDaPeticao | null | undefined;
  desabilitado?: boolean;
  onAtualizada: (peticao: Peticao) => void;
};

export default function ProtocoloDaPeticaoCartao({ casoId, protocolo, desabilitado, onAtualizada }: Props) {
  const [editando, setEditando] = useState(false);
  const [numero, setNumero] = useState("");
  const [data, setData] = useState(hoje);
  const [salvando, setSalvando] = useState(false);
  const [erro, setErro] = useState<string | null>(null);

  function abrir() {
    setNumero(protocolo?.numero ?? "");
    setData(protocolo?.data || hoje());
    setErro(null);
    setEditando(true);
  }

  const numeroDigitado = numero.trim();

  async function enviar(protocolada: boolean) {
    if (protocolada && !numeroDigitado) {
      setErro("Digite o número do protocolo para confirmar.");
      return;
    }
    setSalvando(true);
    setErro(null);
    try {
      const atualizada = await marcarProtocoloDaPeticao(casoId, {
        protocolada,
        numero: numeroDigitado,
        data,
      });
      onAtualizada(atualizada);
      setEditando(false);
    } catch (e) {
      setErro(e instanceof Error ? e.message : "Não foi possível registrar o protocolo.");
    } finally {
      setSalvando(false);
    }
  }

  function desmarcar() {
    if (!window.confirm("Desmarcar esta petição como protocolada? O número e a data registrados serão apagados.")) {
      return;
    }
    void enviar(false);
  }

  return (
    <div className="grid gap-2 rounded-campo border border-borda bg-papel p-3">
      {protocolo && !editando ? (
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="grid gap-1">
            <Selo tom="ok" simbolo="✓">
              Protocolada em {dataBr(protocolo.data)}
            </Selo>
            <p className="m-0 text-sm text-tinta-2">
              {protocolo.numero ? (
                <>
                  Nº do protocolo: <strong className="select-all">{protocolo.numero}</strong>
                </>
              ) : (
                <span className="text-tinta-3">Número do protocolo ainda não informado.</span>
              )}
              {protocolo.marcado_por && (
                <span className="text-tinta-3"> · marcado por {protocolo.marcado_por}</span>
              )}
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            <Botao variante="secundario" pequeno disabled={desabilitado || salvando} onClick={abrir}>
              {protocolo.numero ? "Editar" : "Informar o número"}
            </Botao>
            <Botao variante="texto" pequeno disabled={desabilitado || salvando} onClick={desmarcar}>
              Desmarcar
            </Botao>
          </div>
        </div>
      ) : !editando ? (
        <div className="flex flex-wrap items-center justify-between gap-2">
          <p className="m-0 text-sm text-tinta-3">Ainda não protocolada.</p>
          <Botao variante="secundario" pequeno disabled={desabilitado} onClick={abrir}>
            Marcar como protocolada
          </Botao>
        </div>
      ) : (
        <form
          className="grid gap-3"
          onSubmit={(evento) => {
            evento.preventDefault();
            void enviar(true);
          }}
        >
          <div className="grid gap-3 sm:grid-cols-[1fr_auto]">
            <div>
              <RotuloCampo htmlFor="numero-protocolo">Número do protocolo / processo</RotuloCampo>
              <Campo
                id="numero-protocolo"
                value={numero}
                maxLength={60}
                autoFocus
                required
                placeholder="Ex.: 0000123-45.2026.5.08.0001"
                onChange={(evento) => setNumero(evento.target.value)}
              />
              <p className="mt-1 mb-0 text-xs text-tinta-3">
                Digite o número que o tribunal deu ao protocolo para confirmar.
              </p>
            </div>
            <div>
              <RotuloCampo htmlFor="data-protocolo">Data do protocolo</RotuloCampo>
              <Campo
                id="data-protocolo"
                type="date"
                value={data}
                max={hoje()}
                required
                onChange={(evento) => setData(evento.target.value)}
              />
            </div>
          </div>
          <div className="flex flex-wrap gap-2">
            <Botao
              type="submit"
              variante="primario"
              pequeno
              disabled={!numeroDigitado}
              carregando={salvando}
              textoCarregando="Salvando…"
            >
              {protocolo ? "Salvar protocolo" : "Confirmar protocolo"}
            </Botao>
            <Botao type="button" variante="texto" pequeno disabled={salvando} onClick={() => setEditando(false)}>
              Cancelar
            </Botao>
          </div>
        </form>
      )}
      {erro && (
        <Aviso tom="critico" titulo="O protocolo não foi registrado">
          {erro}
        </Aviso>
      )}
    </div>
  );
}
