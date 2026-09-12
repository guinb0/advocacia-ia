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
} from "@/lib/api";
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
  }, [recarregar]);

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
