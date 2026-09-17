"use client";

/**
 * Qual provedor manda os documentos para assinatura eletrônica.
 *
 * ZapSign continua sendo o padrão e não pede nada aqui — ele é configurado pelo
 * `.env` do servidor, como sempre foi. Clicksign e Autentique são opcionais: o
 * escritório cola o PRÓPRIO token da conta dele, testa a conexão e só então pode
 * ativar. O token nunca volta do servidor — esta tela só sabe dizer "configurado"
 * e o resultado do último teste (ver `app/assinatura_config.py`).
 */

import { useCallback, useEffect, useState } from "react";

import {
  ativarProvedorAssinatura,
  listarProvedoresAssinatura,
  salvarTokenProvedorAssinatura,
  testarProvedorAssinatura,
  conectarTactiq,
  statusTactiq,
} from "@/lib/api";
import type { StatusTactiq } from "@/lib/api";
import type { ProvedorAssinatura, StatusProvedorAssinatura } from "@/lib/types";
import { Aviso, BotaoAba, Botao, Cartao, Campo, RotuloCampo } from "@/components/ui/Basicos";

const NOME: Record<ProvedorAssinatura, string> = {
  zapsign: "ZapSign",
  clicksign: "Clicksign",
  autentique: "Autentique",
};

const DESCRICAO: Record<ProvedorAssinatura, string> = {
  zapsign:
    "Padrão do sistema. Entra pela conta do escritório configurada no servidor — nada a preencher aqui.",
  clicksign: "Envia pela conta Clicksign do escritório, usando o Access Token dele (Configurações → API na Clicksign).",
  autentique: "Envia pela conta Autentique do escritório, usando o token de API dele.",
};

export default function ConfiguracaoAssinatura() {
  const [provedores, setProvedores] = useState<StatusProvedorAssinatura[] | null>(null);
  const [selecionado, setSelecionado] = useState<ProvedorAssinatura>("zapsign");
  const [token, setToken] = useState("");
  const [testando, setTestando] = useState(false);
  const [salvando, setSalvando] = useState(false);
  const [ativando, setAtivando] = useState(false);
  const [erro, setErro] = useState<string | null>(null);
  const [aviso, setAviso] = useState<string | null>(null);
  const [tactiq, setTactiq] = useState<StatusTactiq | null>(null);
  const [conectandoTactiq, setConectandoTactiq] = useState(false);

  const recarregar = useCallback(async () => {
    try {
      const lista = await listarProvedoresAssinatura();
      setProvedores(lista);
      const ativo = lista.find((p) => p.ativo);
      if (ativo) setSelecionado(ativo.provedor);
    } catch (e) {
      setErro(e instanceof Error ? e.message : "Não foi possível carregar os provedores.");
    }
  }, []);

  useEffect(() => {
    void recarregar();
    void statusTactiq().then(setTactiq).catch((falha) => {
      setTactiq(null);
      setErro(falha instanceof Error ? `Tactiq: ${falha.message}` : "Tactiq está indisponível no momento.");
    });
  }, [recarregar]);

  useEffect(() => {
    const retorno = new URLSearchParams(window.location.search).get("tactiq");
    if (!retorno) return;
    if (retorno === "conectado") {
      setAviso("Tactiq conectado. As transcrições já podem ser importadas ao criar um caso.");
      void statusTactiq().then(setTactiq).catch(() => setErro("Não foi possível confirmar o vínculo com o Tactiq."));
    } else if (retorno === "cancelado") {
      setErro("A autorização do Tactiq foi cancelada. Você pode tentar conectar novamente.");
    } else {
      setErro("O Tactiq não concluiu a autorização. Tente conectar novamente.");
    }
    window.history.replaceState({}, "", window.location.pathname);
  }, []);

  async function conectarAoTactiq() {
    setConectandoTactiq(true);
    try { window.location.assign((await conectarTactiq()).url); }
    catch (e) { setErro(e instanceof Error ? e.message : "Não foi possível iniciar a conexão Tactiq."); setConectandoTactiq(false); }
  }

  const atual = provedores?.find((p) => p.provedor === selecionado);

  async function salvarToken() {
    if (selecionado === "zapsign") return;
    setErro(null);
    setAviso(null);
    setSalvando(true);
    try {
      await salvarTokenProvedorAssinatura(selecionado, token);
      setToken("");
      await recarregar();
      setAviso("Token salvo. Teste a conexão antes de ativar este provedor.");
    } catch (e) {
      setErro(e instanceof Error ? e.message : "Não foi possível salvar o token.");
    } finally {
      setSalvando(false);
    }
  }

  async function testar() {
    if (selecionado === "zapsign") return;
    setErro(null);
    setAviso(null);
    setTestando(true);
    try {
      const resultado = await testarProvedorAssinatura(selecionado);
      await recarregar();
      setAviso(resultado.mensagem);
    } catch (e) {
      setErro(e instanceof Error ? e.message : "A conexão falhou.");
      await recarregar();
    } finally {
      setTestando(false);
    }
  }

  async function ativar() {
    setErro(null);
    setAviso(null);
    setAtivando(true);
    try {
      await ativarProvedorAssinatura(selecionado);
      await recarregar();
      setAviso(`${NOME[selecionado]} passou a ser o provedor usado nos próximos envios.`);
    } catch (e) {
      setErro(e instanceof Error ? e.message : "Não foi possível ativar este provedor.");
    } finally {
      setAtivando(false);
    }
  }

  return (
    <Cartao
      titulo="Assinatura eletrônica"
      subtitulo="Escolha por qual provedor os contratos e petições saem para assinatura."
    >
      <div className="grid gap-4">
        {erro && (
          <Aviso tom="critico" titulo="Erro">
            {erro}
          </Aviso>
        )}
        {aviso && !erro && <Aviso tom="ok">{aviso}</Aviso>}

        <div className="rounded-xl border border-borda bg-fundo-2 p-4 grid gap-2">
          <div className="font-semibold text-tinta-1">Transcrições automáticas — Tactiq</div>
          <p className="text-sm leading-relaxed text-tinta-3 m-0">Conecte sua conta Team para importar transcrições completas de Google Meet, Zoom e Microsoft Teams.</p>
          <div className="flex items-center gap-3 flex-wrap">
            <Botao variante={tactiq?.conectado ? "secundario" : "primario"} carregando={conectandoTactiq} onClick={() => void conectarAoTactiq()}>
              {tactiq?.conectado ? "Reconectar Tactiq" : "Conectar Tactiq"}
            </Botao>
            {tactiq?.conectado && <span className="text-sm text-verde-700">Conta conectada — transcrições prontas para sincronizar.</span>}
          </div>
        </div>

        <div role="tablist" className="flex gap-2 flex-wrap">
          {(["zapsign", "clicksign", "autentique"] as ProvedorAssinatura[]).map((provedor) => {
            const status = provedores?.find((p) => p.provedor === provedor);
            return (
              <BotaoAba
                key={provedor}
                ativa={selecionado === provedor}
                onClick={() => {
                  setSelecionado(provedor);
                  setErro(null);
                  setAviso(null);
                }}
              >
                {NOME[provedor]}
                {status?.ativo ? " · em uso" : ""}
              </BotaoAba>
            );
          })}
        </div>

        <p className="text-sm leading-relaxed text-tinta-3 m-0">{DESCRICAO[selecionado]}</p>

        {selecionado === "zapsign" ? (
          <Botao
            variante={atual?.ativo ? "secundario" : "primario"}
            disabled={atual?.ativo || ativando}
            carregando={ativando}
            onClick={() => void ativar()}
          >
            {atual?.ativo ? "Já é o provedor em uso" : "Usar a ZapSign"}
          </Botao>
        ) : (
          <div className="grid gap-3">
            <div className="grid gap-1">
              <RotuloCampo htmlFor="token-provedor">Access Token da conta {NOME[selecionado]}</RotuloCampo>
              <Campo
                id="token-provedor"
                type="password"
                autoComplete="off"
                placeholder={atual?.configurado ? "Token salvo — cole outro para trocar" : "Cole o token aqui"}
                value={token}
                onChange={(e) => setToken(e.target.value)}
              />
            </div>

            <div className="flex gap-2 flex-wrap">
              <Botao
                variante="secundario"
                disabled={!token.trim() || salvando}
                carregando={salvando}
                onClick={() => void salvarToken()}
              >
                Salvar token
              </Botao>
              <Botao
                variante="secundario"
                disabled={!atual?.configurado || testando}
                carregando={testando}
                onClick={() => void testar()}
              >
                Testar conexão
              </Botao>
              <Botao
                variante="primario"
                disabled={!atual?.testado_ok || atual?.ativo || ativando}
                carregando={ativando}
                onClick={() => void ativar()}
              >
                {atual?.ativo ? "Já é o provedor em uso" : `Usar a ${NOME[selecionado]}`}
              </Botao>
            </div>

            {atual?.testado_em && (
              <p className="text-xs text-tinta-3 m-0">
                Último teste {atual.testado_ok ? "— conexão OK" : "— falhou"}
                {atual.testado_mensagem ? `: ${atual.testado_mensagem}` : ""} em{" "}
                {new Date(atual.testado_em).toLocaleString("pt-BR")}.
              </p>
            )}
          </div>
        )}
      </div>
    </Cartao>
  );
}
