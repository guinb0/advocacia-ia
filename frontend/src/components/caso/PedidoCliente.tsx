"use client";

import { useCallback, useEffect, useState } from "react";

import {
  dispararTesteCobrancaDocumentos,
  enviarDocumentosWhatsApp,
  obterCobrancaDocumentos,
  obterPedido,
  salvarCobrancaDocumentos,
  statusWhatsapp,
} from "@/lib/api";
import type { StatusWhatsapp } from "@/lib/api";
import type { CobrancaDocumentos, Pedido, Progresso } from "@/lib/types";
import { AjudaCampo, Botao, Cartao, Marcacao, RotuloCampo, Vazio } from "@/components/ui/Basicos";
import { BotaoProcesso } from "@/components/ui/BotaoProcesso";
import { formatarTelefone, telefonePreenchido } from "@/lib/formato";

/** Resultado de uma ação, mostrado junto do botão que a disparou. */
type Retorno = { tom: "ok" | "erro"; texto: string } | null;

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
  const [cobranca, setCobranca] = useState<CobrancaDocumentos | null>(null);
  const [statusWa, setStatusWa] = useState<StatusWhatsapp | null>(null);
  const [salvando, setSalvando] = useState(false);
  const [enviando, setEnviando] = useState(false);
  const [testandoAutomacao, setTestandoAutomacao] = useState(false);
  /* Um retorno por ação: antes era uma frase só, embaixo do texto, e "salvo"
   * de um aparecia longe do botão do outro. */
  const [retornoAutomacao, setRetornoAutomacao] = useState<Retorno>(null);
  const [retornoWhatsApp, setRetornoWhatsApp] = useState<Retorno>(null);
  const [retornoTeste, setRetornoTeste] = useState<Retorno>(null);

  const chave = `${progresso.obrigatorios_entregues}-${progresso.itens_a_conferir}-${progresso.opcionais_entregues}`;
  const telefoneCobranca = cobranca?.telefone ?? "";
  const cobrancaSemTelefone = cobranca ? !telefonePreenchido(telefoneCobranca) : false;

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

  useEffect(() => {
    obterCobrancaDocumentos(casoId).then(setCobranca).catch(() => setCobranca(null));
  }, [casoId]);

  useEffect(() => {
    let cancelado = false;
    statusWhatsapp()
      .then((status) => {
        if (!cancelado) setStatusWa(status);
      })
      .catch(() => {
        if (!cancelado) setStatusWa(null);
      });
    return () => {
      cancelado = true;
    };
  }, []);

  const salvarAutomacao = useCallback(async () => {
    if (!cobranca) return;
    setSalvando(true);
    setRetornoAutomacao(null);
    try {
      const atualizada = await salvarCobrancaDocumentos(casoId, cobranca);
      setCobranca(atualizada);
      setRetornoAutomacao({
        tom: "ok",
        texto: atualizada.ativa ? "Cobrança automática ativada." : "Cobrança automática desativada.",
      });
    } catch (e) {
      setRetornoAutomacao({
        tom: "erro",
        texto: e instanceof Error ? e.message : "Não foi possível salvar a automação.",
      });
    } finally {
      setSalvando(false);
    }
  }, [casoId, cobranca]);

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

  const enviarWhatsApp = useCallback(async () => {
    if (cobrancaSemTelefone) {
      setRetornoWhatsApp({
        tom: "erro",
        texto: "Informe o telefone/WhatsApp do cliente no caso antes de enviar mensagem.",
      });
      return;
    }
    setEnviando(true);
    setRetornoWhatsApp(null);
    try {
      await enviarDocumentosWhatsApp(casoId, incluirOpcionais);
      setRetornoWhatsApp({ tom: "ok", texto: "Link e pedido de documentos enviados pelo WhatsApp." });
    } catch (e) {
      setRetornoWhatsApp({
        tom: "erro",
        texto: e instanceof Error ? e.message : "Não foi possível enviar pelo WhatsApp.",
      });
    } finally {
      setEnviando(false);
    }
  }, [casoId, cobrancaSemTelefone, incluirOpcionais]);

  const dispararTesteAutomacao = useCallback(async () => {
    if (!cobranca) return;
    if (cobrancaSemTelefone) {
      setRetornoTeste({
        tom: "erro",
        texto: "Informe o telefone/WhatsApp do cliente no caso antes de testar a automação.",
      });
      return;
    }
    setTestandoAutomacao(true);
    setRetornoTeste(null);
    try {
      const r = await dispararTesteCobrancaDocumentos(casoId, cobranca);
      setRetornoTeste(
        r.enviado
          ? { tom: "ok", texto: "Teste temporário enviado pelo mesmo fluxo do timer." }
          : {
              tom: "erro",
              texto:
                r.ultimo_erro ||
                "Teste temporário processado; nenhuma mensagem saiu pelas regras atuais.",
            },
      );
      obterCobrancaDocumentos(casoId).then(setCobranca).catch(() => {});
    } catch (e) {
      setRetornoTeste({
        tom: "erro",
        texto: e instanceof Error ? e.message : "Não foi possível disparar o teste da automação.",
      });
    } finally {
      setTestandoAutomacao(false);
    }
  }, [casoId, cobranca, cobrancaSemTelefone]);

  return (
    <Cartao
      titulo="Pedido para o cliente"
      subtitulo={
        naoResolvidos === 0
          ? "Nada pendente — o texto abaixo só confirma o que já foi recebido."
          : `${naoResolvidos} ${naoResolvidos === 1 ? "item pendente virou" : "itens pendentes viraram"} a mensagem abaixo. Cole no WhatsApp ou no e-mail do cliente.`
      }
    >
      {pedido === null ? (
        <Vazio>Montando o pedido…</Vazio>
      ) : (
        <>
          <div className="flex items-start gap-[14px] mb-[14px] flex-wrap">
            {/* A ação principal do bloco é copiar: é para isso que o bloco existe. */}
            <Botao variante="primario" onClick={copiar}>
              {copiado ? "✓ Mensagem copiada" : "Copiar a mensagem"}
            </Botao>
            <BotaoProcesso
              variante="secundario"
              onClick={enviarWhatsApp}
              processando={enviando}
              textoProcessando="Enviando pelo WhatsApp…"
              erro={retornoWhatsApp?.tom === "erro" ? retornoWhatsApp.texto : null}
              concluido={retornoWhatsApp?.tom === "ok" ? retornoWhatsApp.texto : null}
            >
              Enviar link pelo WhatsApp
            </BotaoProcesso>
            <Marcacao>
              <input
                type="checkbox"
                checked={incluirOpcionais}
                onChange={(e) => setIncluirOpcionais(e.target.checked)}
              />
              <span>Incluir também os documentos opcionais</span>
            </Marcacao>
          </div>

          <RotuloCampo htmlFor="texto-pedido">Mensagem gerada</RotuloCampo>
          <textarea
            id="texto-pedido"
            className="w-full p-[14px] border border-borda-campo rounded-campo bg-papel-2 text-tinta font-codigo text-xs leading-[1.65] resize-y focus:border-acao focus:shadow-[0_0_0_3px_var(--acao-clara)] focus:outline-none"
            value={pedido.texto}
            readOnly
            rows={12}
          />

          <AjudaCampo>
            O texto se refaz sozinho conforme os documentos chegam — não precisa editar aqui.
          </AjudaCampo>

          {cobranca && (
            <div className="mt-5 border-t border-borda pt-4">
              <div className="flex items-center gap-3 flex-wrap">
                <Marcacao>
                  <input
                    type="checkbox"
                    checked={cobranca.ativa}
                    onChange={(e) => setCobranca({ ...cobranca, ativa: e.target.checked })}
                  />
                  <span>Cobrar documentos automaticamente pelo WhatsApp</span>
                </Marcacao>
                {statusWa && (
                  <span className={`text-xs font-semibold ${statusWa.conectado ? "text-ok" : "text-atencao"}`}>
                    Evolution: {statusWa.conectado ? "conectado" : statusWa.configurado ? "desconectado" : "não configurado"}
                  </span>
                )}
              </div>
              <div className="grid grid-cols-[minmax(220px,1fr)_170px_170px] gap-3 mt-3 max-[780px]:grid-cols-1">
                <label className="text-xs text-tinta-3">
                  Destino automático
                  <input
                    className="block w-full mt-1 p-2 border border-borda-campo rounded-campo bg-papel-2 text-tinta"
                    value={telefonePreenchido(cobranca.telefone) ? formatarTelefone(cobranca.telefone) : "Sem telefone no cadastro do caso"}
                    readOnly
                  />
                  {cobrancaSemTelefone && (
                    <span className="mt-1 block text-[11.5px] leading-[1.4] text-atencao">
                      Preencha o telefone do caso para usar a cobrança por WhatsApp.
                    </span>
                  )}
                </label>
                <label className="text-xs text-tinta-3">
                  Intervalo mínimo
                  <select
                    className="block w-full mt-1 p-2 border border-borda-campo rounded-campo bg-papel text-tinta"
                    value={cobranca.intervalo_horas}
                    onChange={(e) => {
                      const horas = Number(e.target.value);
                      setCobranca({
                        ...cobranca,
                        intervalo_horas: horas,
                        intervalo_dias: Math.max(1, Math.ceil(horas / 24)),
                      });
                    }}
                  >
                    {[6, 12, 24, 48, 72, 168].map((horas) => (
                      <option key={horas} value={horas}>
                        {horas < 24 ? `${horas} horas` : `${horas / 24} ${horas === 24 ? "dia" : "dias"}`}
                      </option>
                    ))}
                  </select>
                </label>
                <label className="text-xs text-tinta-3">
                  Máximo por dia
                  <input
                    className="block w-full mt-1 p-2 border border-borda-campo rounded-campo bg-papel text-tinta"
                    type="number"
                    min={1}
                    max={6}
                    value={cobranca.max_envios_dia}
                    onChange={(e) => setCobranca({ ...cobranca, max_envios_dia: Number(e.target.value) })}
                  />
                </label>
              </div>
              <Marcacao className="mt-3">
                <input
                  type="checkbox"
                  checked={cobranca.incluir_opcionais}
                  onChange={(e) => setCobranca({ ...cobranca, incluir_opcionais: e.target.checked })}
                />
                <span>Incluir documentos opcionais nas cobranças</span>
              </Marcacao>
              <div className="mt-3 flex items-center gap-3 flex-wrap">
                <BotaoProcesso
                  variante="primario"
                  onClick={salvarAutomacao}
                  processando={salvando}
                  textoProcessando="Salvando…"
                  aguardando={testandoAutomacao}
                  erro={retornoAutomacao?.tom === "erro" ? retornoAutomacao.texto : null}
                  concluido={retornoAutomacao?.tom === "ok" ? retornoAutomacao.texto : null}
                >
                  Salvar automação
                </BotaoProcesso>
                <BotaoProcesso
                  variante="secundario"
                  onClick={dispararTesteAutomacao}
                  processando={testandoAutomacao}
                  textoProcessando="Testando…"
                  aguardando={salvando}
                  pendencia={
                    !cobranca.ativa
                      ? "Ative a cobrança automática para testar."
                      : cobrancaSemTelefone
                        ? "Preencha o telefone do caso para testar."
                        : null
                  }
                  erro={retornoTeste?.tom === "erro" ? retornoTeste.texto : null}
                  concluido={retornoTeste?.tom === "ok" ? retornoTeste.texto : null}
                >
                  Teste temporário: disparar agora
                </BotaoProcesso>
              </div>
              <AjudaCampo>
                Usa a mesma conexão Evolution do módulo Saúde do agente. O destinatário é o WhatsApp do cliente no cadastro/entrevista do caso; o gestor não precisa informar número aqui. O botão de teste é temporário e será removido do produto final.
              </AjudaCampo>
            </div>
          )}
        </>
      )}
    </Cartao>
  );
}
