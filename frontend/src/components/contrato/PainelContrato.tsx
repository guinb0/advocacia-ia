"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import {
  baixarContratoAssinado,
  configAssinatura,
  DOCUMENTOS_DO_CLIENTE,
  enviarLinkAssinatura,
  enviarParaAssinatura,
  gerarContrato,
  listarAssinaturas,
  obterAssinatura,
  requisitosDoContrato,
} from "@/lib/api";
import type {
  Assinatura,
  ConfigAssinatura,
  DocumentoDoCliente,
  Signatario,
} from "@/lib/types";

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

const BOTAO =
  "border-[1.5px] border-tinta bg-transparent text-tinta text-[11px] font-semibold leading-none font-ui " +
  "tracking-[0.1em] uppercase px-[14px] py-[10px] cursor-pointer disabled:cursor-not-allowed " +
  "disabled:border-borda-forte disabled:bg-papel-3 disabled:text-tinta-desabilitada " +
  "enabled:hover:bg-tinta enabled:hover:text-papel";
const BOTAO_SECUNDARIO =
  "border border-borda-forte bg-transparent text-tinta-3 text-[11px] font-semibold leading-none font-ui " +
  "tracking-[0.1em] uppercase px-[14px] py-[10px] cursor-pointer disabled:cursor-not-allowed " +
  "disabled:bg-papel-3 disabled:text-tinta-desabilitada " +
  "enabled:hover:bg-tinta enabled:hover:text-papel";
const ROTULO = "block text-[11px] font-semibold leading-none font-ui tracking-[0.14em] text-tinta-3 mb-2";
/* Campo que ficou em branco no contrato: âmbar, não vermelho. Não é erro do
 * sistema — é entrevista incompleta, e quem resolve é o entrevistador. */
const FALTANDO = "mt-3 border-l-[3px] border-atencao px-3 py-[10px] bg-papel-2 font-normal text-[12.5px] leading-[1.6] font-ui";
const ERRO = "mt-3 border-[1.5px] border-critico text-critico p-[10px] font-normal text-[12px] leading-[1.5] font-ui";
const CODIGO = "font-normal text-[11.5px] leading-none font-codigo text-tinta";

export default function PainelContrato({ respostas }: Props) {
  /** Qual documento está sendo gerado agora — só um botão fica ocupado. */
  const [gerando, setGerando] = useState<string | null>(null);
  /** O que já foi baixado, por documento: nome do arquivo e campos em branco. */
  const [porDocumento, setPorDocumento] = useState<
    Partial<Record<DocumentoDoCliente, { nome: string; faltando: string[] }>>
  >({});
  const [erro, setErro] = useState<string | null>(null);

  const [config, setConfig] = useState<ConfigAssinatura | null>(null);
  /* Por que não basta `config === null`: sem separar "ainda não perguntei" de
   * "perguntei e falhou", a seção fica MUDA quando a consulta dá erro — só o
   * rótulo, sem botão e sem explicação, e não há como saber se a assinatura está
   * desligada, quebrada ou carregando. */
  const [configErro, setConfigErro] = useState<string | null>(null);
  /* Uma assinatura POR DOCUMENTO: contrato, procuração e declaração.
   *
   * A ZapSign trabalha com um envelope por documento — cada um tem o seu link,
   * o seu estado e a sua trilha de auditoria. Guardar só o contrato deixava as
   * outras duas tramitando sem nada na tela, e o escritório as mandava de novo. */
  const [assinaturas, setAssinaturas] = useState<Assinatura[]>([]);
  /* Um documento recusado DEPOIS de outros já terem subido. Não é erro comum:
   * o que já foi enviado vale, e reenviar tudo duplicaria convites. */
  const [parcial, setParcial] = useState<string | null>(null);
  const [enviando, setEnviando] = useState(false);
  const [baixandoAssinado, setBaixandoAssinado] = useState(false);
  const [erroAssinatura, setErroAssinatura] = useState<string | null>(null);
  /* Separado do erro: a ZapSign não respondeu, mas o que está na tela continua
   * valendo. Some o contrato da tela seria pior que mostrá-lo desatualizado. */
  const [desatualizado, setDesatualizado] = useState<string | null>(null);

  // O backend também colapsa espaços antes de persistir. Usar exatamente a
  // mesma chave evita que "Maria   Silva" suma da listagem após um F5.
  const cliente = texto(respostas.nome).replace(/\s+/g, " ");
  const cpf = texto(respostas.cpf).normalize("NFKC").replace(/[^0-9]/g, "");
  const email = texto(respostas.email);
  const telefone = texto(respostas.telefone);
  const requisitosContrato = requisitosDoContrato(respostas);

  /* Gera a papelada INTEIRA, na ordem em que o escritório a junta.
   *
   * Sem procuração o advogado não peticiona, e sem declaração de
   * hipossuficiência não há gratuidade de justiça. Baixar um de cada vez
   * convidava a esquecer os outros dois — e o esquecimento só aparecia na hora
   * de protocolar, com o cliente já fora da chamada.
   *
   * Os campos que faltam são a UNIÃO dos três: cada modelo pede um conjunto
   * diferente (o contrato quer telefone e e-mail; a procuração, não). */
  /* Um documento de cada vez, com o seu próprio botão.
   *
   * Os três formam uma papelada só, mas na mesa do escritório eles são três
   * arquivos com três destinos — e o atendente muitas vezes quer só um (a
   * procuração para protocolar hoje, o contrato para reenviar ao cliente que
   * apagou o e-mail). Um botão único obrigava a baixar os três para ter um.
   *
   * O `faltando` é POR documento porque cada modelo pede um conjunto diferente:
   * o contrato quer telefone e e-mail, a procuração não. Somados, sugeririam
   * buracos onde não há. */
  async function gerar(codigo: DocumentoDoCliente, formato: "docx" | "pdf") {
    if (requisitosContrato.length > 0) {
      setErro(`Documentos não gerados: informe ${requisitosContrato.join(" e ")}.`);
      return;
    }
    const chave = `${codigo}:${formato}`;
    setGerando(chave);
    setErro(null);
    try {
      const gerado = await gerarContrato(respostas, "", codigo, formato);
      setPorDocumento((atuais) => ({
        ...atuais,
        [codigo]: { nome: gerado.nome, faltando: gerado.faltando },
      }));
      baixarBlob(gerado.arquivo, gerado.nome);
    } catch (e) {
      setErro(e instanceof Error ? e.message : "Não foi possível gerar o documento.");
    } finally {
      setGerando(null);
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
    if (!cliente || !cpf || requisitosContrato.length > 0) return;
    let vivo = true;
    void listarAssinaturas({ cliente, cpf })
      .then((achadas) => {
        // Uma por documento: a listagem vem da mais recente para a mais antiga,
        // e as três da mesma papelada saem juntas no topo.
        if (vivo && achadas.length) setAssinaturas(achadas.slice(0, DOCUMENTOS_DO_CLIENTE.length));
      })
      .catch(() => undefined);
    return () => {
      vivo = false;
    };
  }, [cliente, cpf, requisitosContrato.length]);

  const atualizar = useCallback(async (id: string) => {
    try {
      const resposta = await obterAssinatura(id);
      setAssinaturas((atuais) =>
        atuais.map((a) => (a.id === id ? resposta.assinatura : a)),
      );
      setDesatualizado(resposta.atualizado ? null : (resposta.aviso ?? "Estado não confirmado."));
    } catch (e) {
      setDesatualizado(e instanceof Error ? e.message : "Falha ao consultar a ZapSign.");
    }
  }, []);

  /* Só os pendentes voltam a ser consultados: documento assinado não muda mais,
   * e três consultas de 20 em 20 segundos gastariam o triplo do limite da conta
   * do escritório para reconfirmar o que já está fechado. */
  const pendentes = assinaturas.filter((a) => a.estado === "pendente").map((a) => a.id);
  const chavePendentes = pendentes.join(",");

  useEffect(() => {
    if (!chavePendentes) return;
    const ids = chavePendentes.split(",");
    const id = setInterval(() => {
      for (const cada of ids) void atualizar(cada);
    }, INTERVALO_MS);
    return () => clearInterval(id);
  }, [chavePendentes, atualizar]);

  async function mandarAssinar() {
    if (requisitosContrato.length > 0) {
      setErroAssinatura(`Documentos não gerados: informe ${requisitosContrato.join(" e ")}.`);
      return;
    }
    setEnviando(true);
    setErroAssinatura(null);
    setDesatualizado(null);
    setParcial(null);
    try {
      const resposta = await enviarParaAssinatura(respostas);
      setAssinaturas(resposta.assinaturas);
      // O backend só manda `parcial` quando parte da papelada subiu e o resto
      // não: é aviso, não erro — o que subiu já está com o cliente.
      if (resposta.parcial) setParcial(resposta.parcial);
    } catch (e) {
      setErroAssinatura(
        e instanceof Error ? e.message : "Não foi possível mandar os documentos para assinatura.",
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

  const podeEnviar =
    Boolean(config?.ativa) && requisitosContrato.length === 0 && destinos.length > 0;

  return (
    <div className="mt-6 border-t border-borda pt-[14px] mb-[18px]">
      <span className={ROTULO}>DOCUMENTOS PARA O CLIENTE ASSINAR</span>

      <p className="mb-[14px] mt-0 font-normal text-[12px] leading-[1.6] font-ui text-tinta-3 max-w-[64ch]">
        Preenche os <strong>três modelos do escritório</strong> — contrato de honorários,
        procuração <em>ad judicia</em> e declaração de hipossuficiência — com a
        qualificação que a entrevista trouxe: nome, CPF, RG, endereço, telefone e e-mail.
        As cláusulas, os poderes, os percentuais e o foro vêm dos modelos, sem alteração.
      </p>

      {requisitosContrato.length > 0 && (
        <div className={FALTANDO}>
          <strong>Os documentos ainda não podem ser gerados.</strong>
          <br />
          Informe {requisitosContrato.join(" e ")}. Nenhum arquivo será criado antes disso.
          {cliente && requisitosContrato.includes("nome completo do cliente") && (
            <span className="block mt-[6px] text-[11.5px] text-tinta-3">
              Nome recebido: “{cliente}”. Preencha nome e sobrenome na identificação da entrevista.
            </span>
          )}
        </div>
      )}

      {cliente && (
        <p className="mb-3 mt-0 italic font-normal text-[13px] leading-[1.4] font-titulo text-tinta-3">
          para {cliente}
        </p>
      )}

      {/* Baixar e assinar, LADO A LADO.
        *
        * As duas colunas são a mesma decisão: baixar o .docx para assinar à mão
        * e mandar para a assinatura eletrônica são os dois caminhos do MESMO
        * documento, e quem está com o cliente na linha escolhe um deles. Uma
        * embaixo da outra, a assinatura eletrônica caía fora da tela atrás de
        * seis botões de download — e o escritório acabava baixando o arquivo
        * por não ver que havia a outra saída.
        *
        * Abaixo de 900px voltam a empilhar: em coluna estreita, duas colunas de
        * botões com rótulo longo viram duas colunas de texto quebrado. */}
      <div className="grid grid-cols-2 gap-6 items-start max-[900px]:grid-cols-1 max-[900px]:gap-0">
        <div className="min-w-0">
      {/* Um botão por documento. Eles formam uma papelada só, mas na mesa do
        * escritório são três arquivos com três destinos — e quase sempre se
        * quer um deles, não os três. */}
      <ul className="list-none m-0 p-0">
        {DOCUMENTOS_DO_CLIENTE.map((doc) => {
          const feito = porDocumento[doc.codigo];
          return (
            <li
              key={doc.codigo}
              className="py-3 first:pt-0 last:pb-0 [&+&]:border-t [&+&]:border-borda"
            >
              <div className="grid grid-cols-[minmax(0,1fr)_76px_86px] items-center gap-2 max-[560px]:grid-cols-2">
                <strong className="min-w-0 text-[13px] leading-[1.35] text-tinta max-[560px]:col-span-2">
                  {doc.rotulo}
                </strong>
                <button
                  type="button"
                  className={`${BOTAO} w-full px-2`}
                  onClick={() => void gerar(doc.codigo, "pdf")}
                  disabled={gerando !== null || requisitosContrato.length > 0}
                  aria-label={`Baixar ${doc.rotulo} em PDF`}
                >
                  {gerando === `${doc.codigo}:pdf`
                    ? "Gerando…"
                    : "PDF"}
                </button>
                <button
                  type="button"
                  className={`${BOTAO_SECUNDARIO} w-full px-2`}
                  onClick={() => void gerar(doc.codigo, "docx")}
                  disabled={gerando !== null || requisitosContrato.length > 0}
                  aria-label={`Baixar ${doc.rotulo} em DOCX`}
                >
                  {gerando === `${doc.codigo}:docx`
                    ? "Gerando…"
                    : "DOCX"}
                </button>
                {feito && feito.faltando.length === 0 && (
                  <span className="col-span-3 mt-1 font-normal text-[11.5px] leading-[1.5] font-ui text-ok max-[560px]:col-span-2">
                    ✓ sem campo em branco
                  </span>
                )}
              </div>

              {/* O que falta é DESTE modelo: o contrato pede telefone e e-mail,
                * a procuração não. Somar os três sugeriria buraco onde não há. */}
              {feito && feito.faltando.length > 0 && (
                <div className={FALTANDO}>
                  <strong>
                    A entrevista não respondeu {feito.faltando.length} campo(s) deste
                    documento:
                  </strong>{" "}
                  {feito.faltando.map(legivel).join(", ")}.
                  <span className="block mt-[6px] font-normal text-[11.5px] leading-[1.5] font-ui text-tinta-3">
                    No arquivo eles continuam entre colchetes, à vista. Volte ao roteiro e
                    complete, ou preencha à mão antes da assinatura — em branco passariam
                    despercebidos na revisão.
                  </span>
                </div>
              )}
            </li>
          );
        })}
      </ul>

      {erro && <div className={ERRO}>{erro}</div>}
        </div>

      {/* ------------------------------------------------ assinatura eletrônica */}
      <div className="min-w-0 pl-6 border-l border-borda max-[900px]:pl-0 max-[900px]:border-l-0 max-[900px]:mt-[18px] max-[900px]:pt-4 max-[900px]:border-t">
        <span className={ROTULO}>ASSINATURA ELETRÔNICA</span>

        {config === null && configErro === null && (
          <p className="m-0 font-normal text-[12px] leading-[1.6] font-ui text-tinta-3 max-w-[64ch]">
            Verificando…
          </p>
        )}

        {configErro !== null && (
          <div className={FALTANDO}>
            <strong>Não foi possível verificar a assinatura eletrônica:</strong>{" "}
            {configErro}
            <span className="block mt-[6px] font-normal text-[11.5px] leading-[1.5] font-ui text-tinta-3">
              Se a API responde no resto da tela, o servidor provavelmente está rodando
              uma versão anterior a esta rota — pare e suba de novo com{" "}
              <code className={CODIGO}>.\iniciar.ps1</code>. O contrato continua podendo ser
              baixado acima e assinado à mão.
            </span>
          </div>
        )}

        {config !== null && !config.ativa && (
          <p className="m-0 font-normal text-[12px] leading-[1.6] font-ui text-tinta-3 max-w-[64ch]">
            Envio desligado: falta <code className={CODIGO}>ZAPSIGN_API_TOKEN</code> no{" "}
            <code className={CODIGO}>.env</code>. O contrato continua podendo ser baixado
            acima e assinado à mão.
          </p>
        )}

        {config?.ativa && assinaturas.length === 0 && (
          <>
            <p className="mb-[14px] mt-0 font-normal text-[12px] leading-[1.6] font-ui text-tinta-3 max-w-[64ch]">
              Manda os <strong>três documentos</strong> para a ZapSign, que envia um link
              por documento a cada signatário e devolve cada um assinado com a trilha de
              auditoria. O cliente recebe três convites.
            </p>

            <ul className="mb-[14px] mt-0 p-0 list-none flex flex-col gap-2">
              <li className="border-l-2 border-borda-forte py-1 pl-[10px] font-normal text-[12.5px] leading-[1.5] font-ui">
                <strong>{cliente || "— sem nome na entrevista —"}</strong>{" "}
                <span className="inline-block ml-[6px] text-[9.5px] font-semibold leading-none font-ui tracking-[0.12em] uppercase text-tinta-3 border border-borda-forte px-[5px] py-[3px] align-middle">
                  cliente
                </span>
                <br />
                {destinos.length > 0 ? (
                  destinos.join(" · ")
                ) : (
                  <span className="text-atencao">
                    sem e-mail e sem WhatsApp — não há para onde mandar o convite
                  </span>
                )}
              </li>
              {config.signatario_escritorio && (
                <li className="border-l-2 border-borda-forte py-1 pl-[10px] font-normal text-[12.5px] leading-[1.5] font-ui">
                  <strong>{config.signatario_escritorio.nome}</strong>{" "}
                  <span className="inline-block ml-[6px] text-[9.5px] font-semibold leading-none font-ui tracking-[0.12em] uppercase text-tinta-3 border border-borda-forte px-[5px] py-[3px] align-middle">
                    escritório
                  </span>
                  <br />
                  {config.signatario_escritorio.email}
                </li>
              )}
            </ul>

            <div className="flex gap-3 items-center flex-wrap">
              <button
                type="button"
                className={BOTAO}
                onClick={mandarAssinar}
                disabled={enviando || !podeEnviar}
              >
                {enviando ? "Enviando…" : "Mandar os três para assinatura"}
              </button>
            </div>

            {!podeEnviar && cliente && destinos.length === 0 && (
              <p className="block mt-[6px] font-normal text-[11.5px] leading-[1.5] font-ui text-tinta-3">
                Volte ao roteiro e preencha o e-mail{config.whatsapp ? " ou o telefone" : ""}{" "}
                do cliente.
              </p>
            )}
          </>
        )}

        {erroAssinatura && <div className={ERRO}>{erroAssinatura}</div>}

        {parcial && <div className={FALTANDO}>{parcial}</div>}

        {/* Um acompanhamento por documento: "1 de 2 assinaram" somado dos três
          * esconderia justamente o que o escritório precisa saber — QUAL deles
          * está parado. */}
        {assinaturas.map((a) => (
          <div key={a.id}>
            <span className={ROTULO}>{a.nome}</span>
            <Acompanhamento
              assinatura={a}
              whatsappProprio={Boolean(config?.whatsapp_proprio)}
              desatualizado={desatualizado}
              baixando={baixandoAssinado}
              onAtualizar={() => void atualizar(a.id)}
              onBaixar={() => void baixarAssinado(a.id)}
            />
          </div>
        ))}
      </div>
      </div>

      {(Object.keys(porDocumento).length > 0 ||
        assinaturas.some((a) => a.estado === "assinado")) && (
        <p className="mt-[14px] mb-0 pt-3 border-t border-borda font-normal text-[12px] leading-[1.6] font-ui text-tinta-3">
          Assinada a papelada, crie o caso abaixo: é ele que abre o checklist e o portal
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
  whatsappProprio,
  desatualizado,
  baixando,
  onAtualizar,
  onBaixar,
}: {
  assinatura: Assinatura;
  /** O WhatsApp do escritório está pareado. Falso enquanto ninguém escaneou o
   *  QR Code — e aí o convite do cliente sai só pelo e-mail da ZapSign. */
  whatsappProprio: boolean;
  desatualizado: string | null;
  baixando: boolean;
  onAtualizar: () => void;
  onBaixar: () => void;
}) {
  const concluido = assinatura.estado === "assinado";

  return (
    <div className="mt-[14px]">
      <p className="mb-[10px] mt-0 font-normal text-[12.5px] leading-[1.5] font-ui">
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

      <ul className="mb-3 mt-0 p-0 list-none border-t border-borda">
        {assinatura.signatarios.map((s) => (
          <LinhaSignatario
            key={s.token}
            signatario={s}
            assinaturaId={assinatura.id}
            whatsappProprio={whatsappProprio}
          />
        ))}
      </ul>

      {desatualizado && (
        <p className="mb-3 mt-0 border-l-[3px] border-atencao px-[10px] py-2 bg-papel-2 font-normal text-[11.5px] leading-[1.5] font-ui text-tinta-3">
          Estado abaixo pode estar desatualizado: {desatualizado}
        </p>
      )}

      <div className="flex gap-3 items-center flex-wrap">
        <button type="button" className={BOTAO_SECUNDARIO} onClick={onAtualizar}>
          Atualizar agora
        </button>
        {concluido && (
          <button type="button" className={BOTAO} onClick={onBaixar} disabled={baixando}>
            {baixando ? "Baixando…" : "Baixar assinado (PDF)"}
          </button>
        )}
      </div>

      {!concluido && (
        <p className="block mt-[6px] font-normal text-[11.5px] leading-[1.5] font-ui text-tinta-3">
          A tela se atualiza sozinha a cada 20 segundos. O PDF assinado só existe depois
          que o último signatário assina.
        </p>
      )}
    </div>
  );
}

/* Cor da marca e do texto de estado. Assimetria de propósito herdada do CSS
 * original: a marca (✓/✕/○) fica crítica em recusou/expirou/cancelado, mas o
 * texto do estado só em recusou — os outros dois mantêm o tom neutro. */
const COR_MARCA: Partial<Record<Signatario["estado"], string>> = {
  assinou: "text-ok",
  recusou: "text-critico",
  expirou: "text-critico",
  cancelado: "text-critico",
};
const COR_ESTADO: Partial<Record<Signatario["estado"], string>> = {
  assinou: "text-ok",
  recusou: "text-critico",
};

function LinhaSignatario({
  signatario,
  assinaturaId,
  whatsappProprio,
}: {
  signatario: Signatario;
  assinaturaId: string;
  whatsappProprio: boolean;
}) {
  const [copiado, setCopiado] = useState(false);
  const [enviando, setEnviando] = useState(false);
  const [envio, setEnvio] = useState<{ tom: "ok" | "erro"; texto: string } | null>(null);

  async function copiar() {
    try {
      await navigator.clipboard.writeText(signatario.url_assinatura);
      setCopiado(true);
      setTimeout(() => setCopiado(false), 2000);
    } catch {
      /* navegador sem permissão de área de transferência: o link segue à vista */
    }
  }

  /* Um documento por mensagem, e o servidor é quem sabe o link e o número: a
   * tela manda só quem e qual. Ver o cabeçalho de `app/whatsapp.py`. */
  async function enviarWhatsApp() {
    setEnviando(true);
    setEnvio(null);
    try {
      await enviarLinkAssinatura(assinaturaId, signatario.token);
      setEnvio({ tom: "ok", texto: "link enviado" });
    } catch (e) {
      setEnvio({ tom: "erro", texto: e instanceof Error ? e.message : "falha no envio" });
    } finally {
      setEnviando(false);
    }
  }

  return (
    <li className="flex items-baseline gap-[10px] flex-wrap py-[9px] border-b border-borda font-normal text-[12.5px] leading-[1.4] font-ui">
      <span
        className={`font-normal text-[13px] leading-none font-codigo w-[1ch] ${COR_MARCA[signatario.estado] ?? "text-tinta-3"}`}
        aria-hidden="true"
      >
        {signatario.estado === "assinou" ? "✓" : signatario.estado === "recusou" ? "✕" : "○"}
      </span>
      <span className="flex-1">
        {signatario.nome}
        {signatario.papel && (
          <span className="inline-block ml-[6px] text-[9.5px] font-semibold leading-none font-ui tracking-[0.12em] uppercase text-tinta-3 border border-borda-forte px-[5px] py-[3px] align-middle">
            {signatario.papel}
          </span>
        )}
      </span>
      <span className={`font-normal text-[11.5px] leading-[1.4] font-ui ${COR_ESTADO[signatario.estado] ?? "text-tinta-3"}`}>
        {signatario.rotulo}
      </span>
      {/* O link individual resolve o caso mais comum de contrato parado: o
        * convite caiu no spam e o cliente jura que não recebeu nada. */}
      {signatario.url_assinatura && signatario.estado !== "assinou" && (
        <button
          type="button"
          className="border-none bg-transparent p-0 text-tinta-3 font-normal text-[11px] leading-[1.4] font-ui underline underline-offset-[3px] cursor-pointer hover:text-tinta"
          onClick={() => void copiar()}
        >
          {copiado ? "link copiado" : "copiar link"}
        </button>
      )}
      {/* O reenvio por WhatsApp resolve o mesmo caso que o "copiar link", sem
        * o atendente ter de abrir o WhatsApp e achar a conversa. Só aparece
        * para quem tem telefone: sem número não há para onde mandar. */}
      {whatsappProprio && signatario.url_assinatura && signatario.estado !== "assinou" && signatario.telefone && (
        <button
          type="button"
          className="border-none bg-transparent p-0 text-tinta-3 font-normal text-[11px] leading-[1.4] font-ui underline underline-offset-[3px] cursor-pointer hover:text-tinta disabled:cursor-wait disabled:text-tinta-desabilitada"
          disabled={enviando}
          onClick={() => void enviarWhatsApp()}
        >
          {enviando ? "enviando…" : "enviar por WhatsApp"}
        </button>
      )}
      {envio && (
        <span className={`font-normal text-[11px] leading-[1.4] font-ui ${envio.tom === "ok" ? "text-ok" : "text-critico"}`}>
          {envio.texto}
        </span>
      )}
    </li>
  );
}
