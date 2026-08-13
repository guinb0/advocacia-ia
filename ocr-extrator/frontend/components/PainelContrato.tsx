"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import {
  baixarContratoAssinado,
  configAssinatura,
  enviarParaAssinatura,
  gerarContrato,
  listarAssinaturas,
  obterAssinatura,
} from "@/lib/api";
import type { Assinatura, ConfigAssinatura, Signatario } from "@/lib/types";
import estilos from "./PainelContrato.module.css";

/* Contrato de honorários, preenchido com o que a entrevista respondeu.
 *
 * O documento é o modelo oficial do escritório (`docs/CONTRATO oficial.docx`):
 * cláusulas, percentuais e inscrições na OAB saem de lá palavra por palavra. O
 * que este painel faz é levar os dados da qualificação para os colchetes e
 * devolver o arquivo — para baixar e assinar à mão, ou para mandar assinar
 * eletronicamente pela ZapSign.
 *
 * As duas saídas convivem de propósito. O envio eletrônico depende de chave, de
 * internet e de o cliente ter e-mail ou WhatsApp; nada disso é garantido numa
 * entrevista de escritório trabalhista. Quando falha, o botão de baixar continua
 * ali e o atendimento não para. */

interface Props {
  /** Respostas do roteiro, como o `Roteiro` as devolve ao concluir. */
  respostas: Record<string, string | string[]>;
}

/** "nome da pessoa" → "Nome da pessoa", para o aviso de campo faltando. */
function legivel(campo: string): string {
  const texto = campo.replace(/\brg\b/i, "RG").replace(/\bcpf\b/i, "CPF");
  return texto.charAt(0).toUpperCase() + texto.slice(1);
}

/** Dispara o download de um blob que já veio pela API com o Bearer anexado. */
function baixarBlob(arquivo: Blob, nome: string): void {
  const url = URL.createObjectURL(arquivo);
  const link = document.createElement("a");
  link.href = url;
  link.download = nome;
  link.click();
  URL.revokeObjectURL(url);
}

function texto(valor: string | string[] | undefined): string {
  return typeof valor === "string" ? valor.trim() : "";
}

/* Enquanto houver quem não assinou, a tela se atualiza sozinha. 20s porque cada
 * volta é uma consulta à ZapSign: contrato assinado leva minutos ou horas, e
 * bater de 3 em 3 segundos (como o polling do OCR faz) só gastaria o limite de
 * requisições da conta do escritório sem antecipar nada. */
const INTERVALO_MS = 20_000;

export default function PainelContrato({ respostas }: Props) {
  const [gerando, setGerando] = useState(false);
  const [faltando, setFaltando] = useState<string[] | null>(null);
  const [baixado, setBaixado] = useState<string | null>(null);
  const [erro, setErro] = useState<string | null>(null);

  const [config, setConfig] = useState<ConfigAssinatura | null>(null);
  /* Por que não basta `config === null`: sem separar "ainda não perguntei" de
   * "perguntei e falhou", a seção fica MUDA quando a consulta dá erro — só o
   * rótulo, sem botão e sem explicação, e não há como saber se a assinatura está
   * desligada, quebrada ou carregando. */
  const [configErro, setConfigErro] = useState<string | null>(null);
  const [assinatura, setAssinatura] = useState<Assinatura | null>(null);
  const [enviando, setEnviando] = useState(false);
  const [baixandoAssinado, setBaixandoAssinado] = useState(false);
  const [erroAssinatura, setErroAssinatura] = useState<string | null>(null);
  /* Separado do erro: a ZapSign não respondeu, mas o que está na tela continua
   * valendo. Some o contrato da tela seria pior que mostrá-lo desatualizado. */
  const [desatualizado, setDesatualizado] = useState<string | null>(null);

  const cliente = texto(respostas.nome);
  const email = texto(respostas.email);
  const telefone = texto(respostas.telefone);

  async function gerar() {
    setGerando(true);
    setErro(null);
    try {
      const contrato = await gerarContrato(respostas);
      setFaltando(contrato.faltando);
      setBaixado(contrato.nome);
      baixarBlob(contrato.arquivo, contrato.nome);
    } catch (e) {
      setErro(e instanceof Error ? e.message : "Não foi possível gerar o contrato.");
    } finally {
      setGerando(false);
    }
  }

  useEffect(() => {
    let vivo = true;
    void configAssinatura()
      .then((c) => {
        if (!vivo) return;
        setConfig(c);
        setConfigErro(null);
      })
      .catch((e) => {
        if (!vivo) return;
        setConfig(null);
        setConfigErro(e instanceof Error ? e.message : "Falha ao consultar a API.");
      });
    return () => {
      vivo = false;
    };
  }, []);

  /* Retoma o contrato deste cliente depois de um F5. Sem isto, recarregar a
   * página deixaria o contrato tramitando na ZapSign sem nada na tela — e o
   * advogado o mandaria assinar de novo, criando um segundo documento. */
  useEffect(() => {
    if (!cliente) return;
    let vivo = true;
    void listarAssinaturas({ cliente })
      .then(([maisRecente]) => {
        if (vivo && maisRecente) setAssinatura(maisRecente);
      })
      .catch(() => undefined);
    return () => {
      vivo = false;
    };
  }, [cliente]);

  const atualizar = useCallback(async (id: string) => {
    try {
      const resposta = await obterAssinatura(id);
      setAssinatura(resposta.assinatura);
      setDesatualizado(resposta.atualizado ? null : (resposta.aviso ?? "Estado não confirmado."));
    } catch (e) {
      setDesatualizado(e instanceof Error ? e.message : "Falha ao consultar a ZapSign.");
    }
  }, []);

  const pendente = assinatura !== null && assinatura.estado === "pendente";
  const assinaturaId = assinatura?.id ?? null;

  useEffect(() => {
    if (!pendente || !assinaturaId) return;
    const id = setInterval(() => void atualizar(assinaturaId), INTERVALO_MS);
    return () => clearInterval(id);
  }, [pendente, assinaturaId, atualizar]);

  async function mandarAssinar() {
    setEnviando(true);
    setErroAssinatura(null);
    setDesatualizado(null);
    try {
      const resposta = await enviarParaAssinatura(respostas);
      setAssinatura(resposta.assinatura);
      setFaltando(resposta.faltando);
    } catch (e) {
      setErroAssinatura(
        e instanceof Error ? e.message : "Não foi possível mandar o contrato para assinatura.",
      );
    } finally {
      setEnviando(false);
    }
  }

  async function baixarAssinado(id: string) {
    setBaixandoAssinado(true);
    setErroAssinatura(null);
    try {
      const { arquivo, nome } = await baixarContratoAssinado(id);
      baixarBlob(arquivo, nome);
    } catch (e) {
      setErroAssinatura(
        e instanceof Error ? e.message : "Não foi possível baixar o contrato assinado.",
      );
    } finally {
      setBaixandoAssinado(false);
    }
  }

  /* Quem vai receber o convite — mostrado ANTES de enviar. Contrato mandado ao
   * e-mail errado é contrato oferecido a estranho, e não se recolhe depois. */
  const destinos = useMemo(() => {
    const lista: string[] = [];
    if (email) lista.push(email);
    if (telefone && config?.whatsapp) lista.push(`${telefone} (WhatsApp)`);
    return lista;
  }, [email, telefone, config?.whatsapp]);

  const podeEnviar = Boolean(config?.ativa) && Boolean(cliente) && destinos.length > 0;

  return (
    <div className={estilos.bloco}>
      <span className={estilos.rotulo}>CONTRATO DE HONORÁRIOS</span>

      <p className={estilos.texto}>
        Preenche o modelo do escritório com a qualificação que a entrevista trouxe — nome,
        CPF, RG, endereço, telefone e e-mail. As cláusulas, os percentuais e o foro vêm do
        modelo, sem alteração.
      </p>

      <div className={estilos.acoes}>
        <button type="button" className={estilos.botao} onClick={gerar} disabled={gerando}>
          {gerando ? "Gerando…" : baixado ? "Gerar de novo" : "Gerar contrato"}
        </button>
        {cliente && <span className={estilos.cliente}>para {cliente}</span>}
      </div>

      {erro && <div className={estilos.erro}>{erro}</div>}

      {baixado && !erro && (
        <p className={estilos.baixado}>
          <strong>{baixado}</strong> foi baixado. Confira antes de mandar assinar.
        </p>
      )}

      {faltando && faltando.length > 0 && (
        <div className={estilos.faltando}>
          <strong>A entrevista não respondeu {faltando.length} campo(s):</strong>{" "}
          {faltando.map(legivel).join(", ")}.
          <span className={estilos.explicacao}>
            No documento eles continuam entre colchetes, à vista. Volte ao roteiro e
            complete, ou preencha à mão antes da assinatura — em branco passariam
            despercebidos na revisão.
          </span>
        </div>
      )}

      {faltando?.length === 0 && (
        <p className={estilos.completo}>
          ✓ Todos os campos do modelo foram preenchidos pela entrevista.
        </p>
      )}

      {/* ------------------------------------------------ assinatura eletrônica */}
      <div className={estilos.assinatura}>
        <span className={estilos.rotulo}>ASSINATURA ELETRÔNICA</span>

        {config === null && configErro === null && (
          <p className={estilos.desligado}>Verificando…</p>
        )}

        {configErro !== null && (
          <div className={estilos.faltando}>
            <strong>Não foi possível verificar a assinatura eletrônica:</strong>{" "}
            {configErro}
            <span className={estilos.explicacao}>
              Se a API responde no resto da tela, o servidor provavelmente está rodando
              uma versão anterior a esta rota — pare e suba de novo com{" "}
              <code>.\iniciar.ps1</code>. O contrato continua podendo ser baixado acima e
              assinado à mão.
            </span>
          </div>
        )}

        {config !== null && !config.ativa && (
          <p className={estilos.desligado}>
            Envio desligado: falta <code>ZAPSIGN_API_TOKEN</code> no <code>.env</code>. O
            contrato continua podendo ser baixado acima e assinado à mão.
          </p>
        )}

        {config?.ativa && !assinatura && (
          <>
            <p className={estilos.texto}>
              Manda o mesmo documento para a ZapSign, que envia o link a cada signatário e
              devolve o contrato assinado com a trilha de auditoria.
            </p>

            <ul className={estilos.destinos}>
              <li>
                <strong>{cliente || "— sem nome na entrevista —"}</strong>{" "}
                <span className={estilos.papel}>cliente</span>
                <br />
                {destinos.length > 0 ? (
                  destinos.join(" · ")
                ) : (
                  <span className={estilos.semContato}>
                    sem e-mail e sem WhatsApp — não há para onde mandar o convite
                  </span>
                )}
              </li>
              {config.signatario_escritorio && (
                <li>
                  <strong>{config.signatario_escritorio.nome}</strong>{" "}
                  <span className={estilos.papel}>escritório</span>
                  <br />
                  {config.signatario_escritorio.email}
                </li>
              )}
            </ul>

            <div className={estilos.acoes}>
              <button
                type="button"
                className={estilos.botao}
                onClick={mandarAssinar}
                disabled={enviando || !podeEnviar}
              >
                {enviando ? "Enviando…" : "Mandar assinar"}
              </button>
            </div>

            {!podeEnviar && cliente && destinos.length === 0 && (
              <p className={estilos.explicacao}>
                Volte ao roteiro e preencha o e-mail{config.whatsapp ? " ou o telefone" : ""}{" "}
                do cliente.
              </p>
            )}
          </>
        )}

        {erroAssinatura && <div className={estilos.erro}>{erroAssinatura}</div>}

        {assinatura && (
          <Acompanhamento
            assinatura={assinatura}
            desatualizado={desatualizado}
            baixando={baixandoAssinado}
            onAtualizar={() => void atualizar(assinatura.id)}
            onBaixar={() => void baixarAssinado(assinatura.id)}
          />
        )}
      </div>

      {(baixado || assinatura?.estado === "assinado") && (
        <p className={estilos.proximo}>
          Assinado o contrato, crie o caso abaixo: é ele que abre o checklist e o portal
          para o cliente enviar os documentos.
        </p>
      )}
    </div>
  );
}

/* Quem já assinou e quem falta. Cada signatário aparece com o próprio estado —
 * um contador "1 de 2" não diz se quem falta é o cliente ou o sócio, e é essa a
 * pergunta que o escritório faz. */
function Acompanhamento({
  assinatura,
  desatualizado,
  baixando,
  onAtualizar,
  onBaixar,
}: {
  assinatura: Assinatura;
  desatualizado: string | null;
  baixando: boolean;
  onAtualizar: () => void;
  onBaixar: () => void;
}) {
  const concluido = assinatura.estado === "assinado";

  return (
    <div className={estilos.acompanhamento}>
      <p className={estilos.situacao}>
        <strong>
          {concluido
            ? "✓ Assinado por todos"
            : assinatura.estado === "recusado"
              ? "Assinatura recusada"
              : `${assinatura.assinaram} de ${assinatura.total} assinaram`}
        </strong>
        {!concluido && assinatura.faltam.length > 0 && (
          <> — falta {assinatura.faltam.join(", ")}.</>
        )}
      </p>

      <ul className={estilos.signatarios}>
        {assinatura.signatarios.map((s) => (
          <LinhaSignatario key={s.token} signatario={s} />
        ))}
      </ul>

      {desatualizado && (
        <p className={estilos.desatualizado}>
          Estado abaixo pode estar desatualizado: {desatualizado}
        </p>
      )}

      <div className={estilos.acoes}>
        <button type="button" className={estilos.botaoSecundario} onClick={onAtualizar}>
          Atualizar agora
        </button>
        {concluido && (
          <button
            type="button"
            className={estilos.botao}
            onClick={onBaixar}
            disabled={baixando}
          >
            {baixando ? "Baixando…" : "Baixar assinado (PDF)"}
          </button>
        )}
      </div>

      {!concluido && (
        <p className={estilos.explicacao}>
          A tela se atualiza sozinha a cada 20 segundos. O PDF assinado só existe depois
          que o último signatário assina.
        </p>
      )}
    </div>
  );
}

function LinhaSignatario({ signatario }: { signatario: Signatario }) {
  const [copiado, setCopiado] = useState(false);

  async function copiar() {
    try {
      await navigator.clipboard.writeText(signatario.url_assinatura);
      setCopiado(true);
      setTimeout(() => setCopiado(false), 2000);
    } catch {
      /* navegador sem permissão de área de transferência: o link segue à vista */
    }
  }

  return (
    <li className={estilos.signatario} data-estado={signatario.estado}>
      <span className={estilos.marca} aria-hidden="true">
        {signatario.estado === "assinou" ? "✓" : signatario.estado === "recusou" ? "✕" : "○"}
      </span>
      <span className={estilos.nomeSignatario}>
        {signatario.nome}
        {signatario.papel && <span className={estilos.papel}>{signatario.papel}</span>}
      </span>
      <span className={estilos.estadoSignatario}>{signatario.rotulo}</span>
      {/* O link individual resolve o caso mais comum de contrato parado: o
        * convite caiu no spam e o cliente jura que não recebeu nada. */}
      {signatario.url_assinatura && signatario.estado !== "assinou" && (
        <button type="button" className={estilos.copiar} onClick={() => void copiar()}>
          {copiado ? "link copiado" : "copiar link"}
        </button>
      )}
    </li>
  );
}
