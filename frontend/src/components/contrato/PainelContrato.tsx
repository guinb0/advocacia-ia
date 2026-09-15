"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import {
  baixarContratoAssinado,
  configAssinatura,
  DOCUMENTOS_DO_CLIENTE,
  enviarAssinaturaPeloSite,
  enviarLinkAssinatura,
  enviarParaAssinatura,
  enviarTodosParaAssinaturaSite,
  gerarContrato,
  listarAssinaturas,
  obterAssinatura,
  reenviarLinkAssinaturaSite,
  requisitosDoContrato,
} from "@/lib/api";
import type {
  Assinatura,
  ConfigAssinatura,
  DocumentoDoCliente,
  Signatario,
} from "@/lib/types";
import { Botao } from "@/components/ui/Basicos";
import { BotaoProcesso } from "@/components/ui/BotaoProcesso";
import { baixarArquivo as baixarBlob } from "@/lib/baixar";

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

function texto(valor: string | string[] | undefined): string {
  return typeof valor === "string" ? valor.trim() : "";
}

/* Enquanto houver quem não assinou, a tela se atualiza sozinha. 20s porque cada
 * volta é uma consulta à ZapSign: contrato assinado leva minutos ou horas, e
 * bater de 3 em 3 segundos (como o polling do OCR faz) só gastaria o limite de
 * requisições da conta do escritório sem antecipar nada. */
const INTERVALO_MS = 20_000;

/* Integração preservada, mas fora do fluxo enquanto o escritório não dispõe da
 * API da ZapSign. A flag também impede consultas e polling em segundo plano —
 * esconder só o HTML continuaria chamando uma API que não existe. Quando a
 * integração oficial estiver disponível, basta reativar este ponto. */
const ASSINATURA_ELETRONICA_ATIVA = false;

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
  /** `origem` é o botão que falhou (`"contrato:pdf"`, `"todos"`): o erro aparece junto dele. */
  const [erro, setErro] = useState<{ origem: string; texto: string } | null>(null);

  const [config, setConfig] = useState<ConfigAssinatura | null>(null);
  /* Por que não basta `config === null`: sem separar "ainda não perguntei" de
   * "perguntei e falhou", a seção fica MUDA quando a consulta dá erro — só o
   * rótulo, sem botão e sem explicação, e não há como saber se a assinatura está
   * desligada, quebrada ou carregando. */
  const [configErro, setConfigErro] = useState<string | null>(null);
  const [tentativaConfig, setTentativaConfig] = useState(0);
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
  /* Envio dos TRÊS de uma vez (um clique, um login): gera os PDFs no servidor e
   * sobe pela automação do site, sem baixar/reanexar. `resultadoTodos` guarda o
   * link de cada documento devolvido pela ZapSign. */
  const [enviandoTodos, setEnviandoTodos] = useState(false);
  const [resultadoTodos, setResultadoTodos] = useState<
    { documentos: { rotulo: string; link: string }[]; whatsapp_enviado: boolean } | null
  >(null);
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
    const chave = `${codigo}:${formato}`;
    if (requisitosContrato.length > 0) {
      setErro({ origem: chave, texto: `Documentos não gerados: informe ${requisitosContrato.join(" e ")}.` });
      return;
    }
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
      setErro({ origem: chave, texto: e instanceof Error ? e.message : "Não foi possível gerar o documento." });
    } finally {
      setGerando(null);
    }
  }

  /* Um clique: gera os TRÊS documentos no servidor e os manda assinar pela conta
   * ZapSign (site), num login só, sem baixar/reanexar. Havendo telefone, cada
   * link vai por WhatsApp. */
  async function enviarTodos() {
    if (requisitosContrato.length > 0) {
      setErro({ origem: "todos", texto: `Não é possível enviar: informe ${requisitosContrato.join(" e ")}.` });
      return;
    }
    if (!email) {
      setErro({
        origem: "todos",
        texto: "A ZapSign precisa do e-mail do cliente para enviar o convite. Preencha o e-mail na entrevista.",
      });
      return;
    }
    setEnviandoTodos(true);
    setErro(null);
    setResultadoTodos(null);
    try {
      const r = await enviarTodosParaAssinaturaSite({ respostas, clienteWhatsapp: telefone });
      setResultadoTodos({ documentos: r.documentos, whatsapp_enviado: r.whatsapp_enviado });
    } catch (e) {
      setErro({ origem: "todos", texto: e instanceof Error ? e.message : "Não foi possível enviar para assinatura." });
    } finally {
      setEnviandoTodos(false);
    }
  }

  useEffect(() => {
    // A config precisa ser buscada SEMPRE: o envio pela conta ZapSign (site) só
    // depende de `config.navegador`, e é independente do fluxo de API (desligado
    // por `ASSINATURA_ELETRONICA_ATIVA`). Travar a busca atrás dessa flag deixava
    // `config` nulo e ESCONDIA o botão de enviar para assinatura — o escritório
    // via só os downloads e nenhum jeito de mandar o cliente assinar.
    let vivo = true;
    setConfigErro(null);
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
  }, [tentativaConfig]);

  /* Retoma o contrato deste cliente depois de um F5. Sem isto, recarregar a
   * página deixaria o contrato tramitando na ZapSign sem nada na tela — e o
   * advogado o mandaria assinar de novo, criando um segundo documento. */
  useEffect(() => {
    if (!ASSINATURA_ELETRONICA_ATIVA) return;
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
    if (!ASSINATURA_ELETRONICA_ATIVA) return;
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

  /* O quadro âmbar acima já diz o que falta; nos botões a frase só aparece ao
   * clicar, para não repetir a mesma linha seis vezes. */
  const pendenciaContrato = requisitosContrato.length
    ? `Informe ${requisitosContrato.join(" e ")} na entrevista.`
    : null;

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

      {/* Primeiro os três documentos para baixar: uma linha por documento, com
        * PDF e DOCX lado a lado. A assinatura é uma etapa diferente e começa
        * somente depois da lista inteira, ocupando a largura do painel. */}
      <div className="flex flex-col">
        <div className="min-w-0">
      {/* Uma linha por documento; cada formato mantém seu próprio download. */}
      <ul className="list-none m-0 p-0">
        {DOCUMENTOS_DO_CLIENTE.map((doc) => {
          const feito = porDocumento[doc.codigo];
          return (
            <li
              key={doc.codigo}
              className="py-3 first:pt-0 last:pb-0 [&+&]:border-t [&+&]:border-borda"
            >
              <div className="grid grid-cols-2 items-stretch gap-3 max-[640px]:grid-cols-1">
                {(["pdf", "docx"] as const).map((formato) => {
                  const chave = `${doc.codigo}:${formato}`;
                  const rotulo = `Baixar ${doc.rotulo} em ${formato.toUpperCase()}`;
                  return (
                    <BotaoProcesso
                      key={formato}
                      variante="secundario"
                      bloco
                      classeBotao="min-h-12 px-3"
                      onClick={() => gerar(doc.codigo, formato)}
                      processando={gerando === chave}
                      textoProcessando={`Gerando o ${formato.toUpperCase()}…`}
                      pendencia={pendenciaContrato}
                      pendenciaAoClicar
                      aguardando={gerando !== null ? "Aguarde: outro documento está sendo gerado." : false}
                      erro={erro?.origem === chave ? erro.texto : null}
                      aria-label={rotulo}
                    >
                      {rotulo}
                    </BotaoProcesso>
                  );
                })}
                {feito && feito.faltando.length === 0 && (
                  <span className="col-span-2 mt-1 font-normal text-[11.5px] leading-[1.5] font-ui text-ok max-[640px]:col-span-1">
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

      {/* UM clique para os TRÊS: gera contrato + procuração + declaração e os
        * manda assinar pela conta ZapSign, num login só. Só aparece com o login
        * do site configurado. */}
      {!config && !configErro && (
        <div className="mt-4 border-t border-borda pt-4">
          <BotaoProcesso
            variante="primario"
            bloco
            classeBotao="min-h-12 px-3"
            onClick={() => undefined}
            processando
            textoProcessando="Verificando a ZapSign…"
          >
            Enviar para o cliente assinar em um só link (ZapSign + WhatsApp)
          </BotaoProcesso>
        </div>
      )}

      {!config && configErro && (
        <div className={FALTANDO}>
          <strong>Não foi possível verificar o envio pela ZapSign.</strong> {configErro}
          <div className="mt-2">
            <Botao variante="secundario" pequeno onClick={() => setTentativaConfig((n) => n + 1)}>
              Tentar de novo
            </Botao>
          </div>
        </div>
      )}

      {config?.navegador && (
        <div className="mt-4 border-t border-borda pt-4">
          <BotaoProcesso
            variante="primario"
            bloco
            classeBotao="min-h-12 px-3"
            onClick={enviarTodos}
            processando={enviandoTodos}
            textoProcessando="Enviando os documentos para assinatura…"
            dica="Pode levar alguns minutos — mantenha esta página aberta"
            pendencia={
              pendenciaContrato ??
              (email ? null : "Preencha o e-mail do cliente na entrevista: a ZapSign precisa dele para o convite.")
            }
            erro={erro?.origem === "todos" ? erro.texto : null}
          >
            Enviar para o cliente assinar em um só link (ZapSign + WhatsApp)
          </BotaoProcesso>
          <p className="mt-2 mb-0 font-normal text-[11.5px] leading-[1.5] font-ui text-tinta-3">
            Contrato, procuração e declaração vão juntos em um único documento: o cliente
            assina uma vez só. O convite vai por e-mail para {email || "o e-mail do cliente"}
            {telefone ? " e o link também pelo WhatsApp" : ""}.
          </p>

          {resultadoTodos && (
            <div className="mt-3 border-l-[3px] border-ok bg-papel-2 px-3 py-2 text-[12px] leading-[1.5] text-tinta-2">
              <strong className="text-ok">Enviado para assinatura ✓</strong>
              <span className="block mt-1 text-tinta-3">
                Convite por e-mail para {email}.{" "}
                {resultadoTodos.whatsapp_enviado
                  ? "Links também enviados pelo WhatsApp."
                  : telefone
                    ? "Os links por WhatsApp não saíram — confira o número/conexão."
                    : "Sem telefone: convite só por e-mail."}
              </span>
              <ul className="mt-2 mb-0 grid gap-1 list-none p-0">
                {resultadoTodos.documentos.map((d, i) => (
                  <li key={i} className="[overflow-wrap:anywhere]">
                    <span className="text-tinta">{d.rotulo}:</span>{" "}
                    {d.link ? (
                      <a href={d.link} target="_blank" rel="noreferrer" className="text-acao underline">
                        abrir link de assinatura
                      </a>
                    ) : (
                      <span className="text-atencao">link não capturado</span>
                    )}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}

        </div>

      {/* Integração mantida no código, mas deliberadamente fora da tela até o
        * escritório possuir uma API de assinatura. */}
      {ASSINATURA_ELETRONICA_ATIVA && (
      <div className="min-w-0 mt-6 border-t border-borda pt-5">
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

            <BotaoProcesso
              variante="primario"
              onClick={mandarAssinar}
              processando={enviando}
              textoProcessando="Enviando para a ZapSign…"
              pendencia={
                podeEnviar
                  ? null
                  : (pendenciaContrato ??
                    `Volte ao roteiro e preencha o e-mail${config.whatsapp ? " ou o telefone" : ""} do cliente.`)
              }
            >
              Mandar os três para assinatura
            </BotaoProcesso>
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
      )}

      {config?.navegador && (
        <EnvioPeloSiteZapSign
          clienteNome={cliente}
          clienteEmail={email}
          clienteTelefone={telefone}
        />
      )}
      </div>

      {Object.keys(porDocumento).length > 0 && (
        <p className="mt-[14px] mb-0 pt-3 border-t border-borda font-normal text-[12px] leading-[1.6] font-ui text-tinta-3">
          Gerada a papelada, crie o caso abaixo: é ele que abre o checklist e o portal
          para o cliente enviar os demais documentos.
        </p>
      )}
    </div>
  );
}

/* Envio pelo SITE do ZapSign (plano sem API). Sobe um PDF já pronto (o contrato
 * baixado, a procuração, ou qualquer documento) e a automação entra na conta do
 * escritório, cria o documento e dispara o convite por e-mail; havendo telefone,
 * o link também vai pela nossa Evolution. Ver app/assinatura_navegador.py. */
function EnvioPeloSiteZapSign({
  clienteNome,
  clienteEmail,
  clienteTelefone,
}: {
  clienteNome: string;
  clienteEmail: string;
  clienteTelefone: string;
}) {
  const [arquivo, setArquivo] = useState<File | null>(null);
  const [email, setEmail] = useState(clienteEmail);
  const [whatsapp, setWhatsapp] = useState(clienteTelefone);
  const [enviando, setEnviando] = useState(false);
  const [resultado, setResultado] = useState<{ link: string; whatsapp_enviado: boolean } | null>(null);
  const [erro, setErro] = useState<string | null>(null);
  /* Reenvio manual do link pelo WhatsApp, separado do envio inicial: o convite
   * cai no spam, ou o telefone só aparece depois de o documento já ter subido. */
  const [reenviandoWa, setReenviandoWa] = useState(false);
  const [envioWa, setEnvioWa] = useState<{ tom: "ok" | "erro"; texto: string } | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  useEffect(() => {
    if (clienteEmail) setEmail((atual) => atual.trim() || clienteEmail);
  }, [clienteEmail]);
  useEffect(() => {
    if (clienteTelefone) setWhatsapp((atual) => atual.trim() || clienteTelefone);
  }, [clienteTelefone]);
  const CAMPO =
    "w-full rounded-[6px] border border-borda bg-papel px-3 py-2 text-sm text-tinta placeholder:text-tinta-3";

  async function enviar() {
    if (!arquivo || !email.trim() || enviando) return;
    setEnviando(true);
    setErro(null);
    setResultado(null);
    try {
      const r = await enviarAssinaturaPeloSite({
        arquivo,
        clienteNome,
        clienteEmail: email.trim(),
        clienteWhatsapp: whatsapp.trim(),
      });
      setResultado({ link: r.link, whatsapp_enviado: r.whatsapp_enviado });
    } catch (e) {
      setErro(e instanceof Error ? e.message : "Não foi possível enviar pelo site do ZapSign.");
    } finally {
      setEnviando(false);
    }
  }

  /* Manda (ou reenvia) só o link de assinatura pelo WhatsApp — sem recriar o
   * documento na ZapSign. Usa o número digitado no campo acima. */
  async function enviarLinkWhatsapp() {
    if (!resultado?.link || !whatsapp.trim() || reenviandoWa) return;
    setReenviandoWa(true);
    setEnvioWa(null);
    try {
      await reenviarLinkAssinaturaSite(whatsapp.trim(), resultado.link);
      setEnvioWa({ tom: "ok", texto: "Link enviado pelo WhatsApp." });
    } catch (e) {
      setEnvioWa({ tom: "erro", texto: e instanceof Error ? e.message : "Falha ao enviar pelo WhatsApp." });
    } finally {
      setReenviandoWa(false);
    }
  }

  return (
    <div className="mt-4 rounded-[10px] border border-borda-forte bg-papel-2 p-4">
      <h3 className="m-0 text-sm font-semibold text-tinta">Enviar para o cliente assinar (ZapSign + WhatsApp)</h3>
      <p className="mt-1 mb-3 text-xs leading-[1.55] text-tinta-3">
        Baixe acima o documento (contrato, procuração ou declaração), selecione o PDF aqui e
        envie: o escritório sobe na ZapSign e dispara o convite por e-mail; havendo telefone,
        o link de assinatura também vai pelo <strong>WhatsApp</strong> do cliente. Depois de
        enviar, dá para reenviar o link por WhatsApp com um clique.
      </p>

      <div className="grid gap-2">
        <button
          type="button"
          onClick={() => fileRef.current?.click()}
          disabled={enviando}
          className="rounded-[6px] border border-dashed border-acao-borda bg-papel px-3 py-3 text-sm text-tinta-2 hover:border-acao hover:text-acao"
        >
          {arquivo ? `Documento: ${arquivo.name}` : "Escolher o PDF a assinar"}
        </button>
        <input
          ref={fileRef}
          type="file"
          accept=".pdf"
          hidden
          onChange={(e) => {
            setArquivo(e.target.files?.[0] ?? null);
            e.target.value = "";
          }}
        />
        <input
          className={CAMPO}
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          placeholder="E-mail do cliente"
          type="email"
        />
        <input
          className={CAMPO}
          value={whatsapp}
          onChange={(e) => setWhatsapp(e.target.value)}
          placeholder="WhatsApp do cliente (opcional)"
        />
        <BotaoProcesso
          variante="primario"
          bloco
          onClick={enviar}
          processando={enviando}
          textoProcessando="Enviando pelo site do ZapSign…"
          dica="A automação entra na conta do escritório — pode levar um minuto"
          pendencia={
            !arquivo
              ? "Escolha o PDF a assinar."
              : !email.trim()
                ? "Informe o e-mail do cliente."
                : null
          }
          onPendencia={() => !arquivo && fileRef.current?.click()}
          erro={erro}
        >
          Enviar para assinatura
        </BotaoProcesso>
      </div>
      {resultado && (
        <div className="mt-2 rounded-[6px] border border-ok-borda bg-ok-claro p-3 text-sm text-tinta">
          <p className="m-0 font-semibold text-ok">Enviado ✓</p>
          {resultado.link ? (
            <p className="mt-1 mb-0 [overflow-wrap:anywhere]">
              Link de assinatura: <a href={resultado.link} target="_blank" rel="noreferrer">{resultado.link}</a>
            </p>
          ) : (
            <p className="mt-1 mb-0 text-tinta-3">O convite por e-mail saiu; o site não expôs o link direto.</p>
          )}
          <p className="mt-1 mb-0 text-tinta-3">
            WhatsApp: {resultado.whatsapp_enviado ? "link enviado ao cliente" : "não enviado"}
          </p>
          {resultado.link && (
            <div className="mt-3 border-t border-ok-borda pt-3">
              <div className="grid gap-2 sm:grid-cols-[1fr_auto] sm:items-start">
                <input
                  className={CAMPO}
                  value={whatsapp}
                  onChange={(e) => setWhatsapp(e.target.value)}
                  placeholder="WhatsApp do cliente (com DDD)"
                  inputMode="tel"
                />
                <BotaoProcesso
                  variante="primario"
                  onClick={enviarLinkWhatsapp}
                  processando={reenviandoWa}
                  textoProcessando="Enviando…"
                  pendencia={whatsapp.trim() ? null : "Informe o WhatsApp com DDD."}
                  pendenciaAoClicar
                  erro={envioWa?.tom === "erro" ? envioWa.texto : null}
                  concluido={envioWa?.tom === "ok" ? envioWa.texto : null}
                >
                  {resultado.whatsapp_enviado ? "Reenviar link por WhatsApp" : "Enviar link por WhatsApp"}
                </BotaoProcesso>
              </div>
            </div>
          )}
        </div>
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

      <div className="flex gap-3 items-start flex-wrap">
        <Botao variante="secundario" onClick={onAtualizar}>
          Atualizar agora
        </Botao>
        {concluido && (
          <BotaoProcesso
            variante="primario"
            onClick={onBaixar}
            processando={baixando}
            textoProcessando="Baixando…"
          >
            Baixar assinado (PDF)
          </BotaoProcesso>
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
        <Botao
          variante="texto"
          pequeno
          carregando={enviando}
          textoCarregando="enviando…"
          onClick={() => void enviarWhatsApp()}
        >
          enviar por WhatsApp
        </Botao>
      )}
      {envio && (
        <span className={`font-normal text-[11px] leading-[1.4] font-ui ${envio.tom === "ok" ? "text-ok" : "text-critico"}`}>
          {envio.texto}
        </span>
      )}
    </li>
  );
}
