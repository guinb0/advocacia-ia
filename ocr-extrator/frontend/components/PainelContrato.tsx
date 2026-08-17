"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import {
  baixarContratoAssinado,
  configAssinatura,
  DOCUMENTOS_DO_CLIENTE,
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
  /** Qual documento está sendo gerado agora — só um botão fica ocupado. */
  const [gerando, setGerando] = useState<DocumentoDoCliente | null>(null);
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
  async function gerar(codigo: DocumentoDoCliente) {
    if (requisitosContrato.length > 0) {
      setErro(`Documentos não gerados: informe ${requisitosContrato.join(" e ")}.`);
      return;
    }
    setGerando(codigo);
    setErro(null);
    try {
      const gerado = await gerarContrato(respostas, "", codigo);
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
    <div className={estilos.bloco}>
      <span className={estilos.rotulo}>DOCUMENTOS PARA O CLIENTE ASSINAR</span>

      <p className={estilos.texto}>
        Preenche os <strong>três modelos do escritório</strong> — contrato de honorários,
        procuração <em>ad judicia</em> e declaração de hipossuficiência — com a
        qualificação que a entrevista trouxe: nome, CPF, RG, endereço, telefone e e-mail.
        As cláusulas, os poderes, os percentuais e o foro vêm dos modelos, sem alteração.
      </p>

      {requisitosContrato.length > 0 && (
        <div className={estilos.faltando}>
          <strong>Os documentos ainda não podem ser gerados.</strong>
          <br />
          Informe {requisitosContrato.join(" e ")}. Nenhum arquivo será criado antes disso.
        </div>
      )}

      {cliente && <p className={estilos.cliente}>para {cliente}</p>}

      {/* Um botão por documento. Eles formam uma papelada só, mas na mesa do
        * escritório são três arquivos com três destinos — e quase sempre se
        * quer um deles, não os três. */}
      <ul className={estilos.documentos}>
        {DOCUMENTOS_DO_CLIENTE.map((doc) => {
          const feito = porDocumento[doc.codigo];
          return (
            <li key={doc.codigo} className={estilos.documento}>
              <div className={estilos.documentoLinha}>
                <button
                  type="button"
                  className={estilos.botao}
                  onClick={() => void gerar(doc.codigo)}
                  disabled={gerando !== null || requisitosContrato.length > 0}
                >
                  {gerando === doc.codigo
                    ? "Gerando…"
                    : feito
                      ? `Baixar ${doc.rotulo} de novo`
                      : `Baixar ${doc.rotulo}`}
                </button>
                {feito && feito.faltando.length === 0 && (
                  <span className={estilos.completo}>✓ sem campo em branco</span>
                )}
              </div>

              {/* O que falta é DESTE modelo: o contrato pede telefone e e-mail,
                * a procuração não. Somar os três sugeriria buraco onde não há. */}
              {feito && feito.faltando.length > 0 && (
                <div className={estilos.faltando}>
                  <strong>
                    A entrevista não respondeu {feito.faltando.length} campo(s) deste
                    documento:
                  </strong>{" "}
                  {feito.faltando.map(legivel).join(", ")}.
                  <span className={estilos.explicacao}>
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

      {erro && <div className={estilos.erro}>{erro}</div>}

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

        {config?.ativa && assinaturas.length === 0 && (
          <>
            <p className={estilos.texto}>
              Manda os <strong>três documentos</strong> para a ZapSign, que envia um link
              por documento a cada signatário e devolve cada um assinado com a trilha de
              auditoria. O cliente recebe três convites.
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
                {enviando ? "Enviando…" : "Mandar os três para assinatura"}
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

        {parcial && <div className={estilos.faltando}>{parcial}</div>}

        {/* Um acompanhamento por documento: "1 de 2 assinaram" somado dos três
          * esconderia justamente o que o escritório precisa saber — QUAL deles
          * está parado. */}
        {assinaturas.map((a) => (
          <div key={a.id}>
            <span className={estilos.rotulo}>{a.nome}</span>
            <Acompanhamento
              assinatura={a}
              desatualizado={desatualizado}
              baixando={baixandoAssinado}
              onAtualizar={() => void atualizar(a.id)}
              onBaixar={() => void baixarAssinado(a.id)}
            />
          </div>
        ))}
      </div>

      {(Object.keys(porDocumento).length > 0 ||
        assinaturas.some((a) => a.estado === "assinado")) && (
        <p className={estilos.proximo}>
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
