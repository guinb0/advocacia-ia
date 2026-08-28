"use client";

/**
 * Dossiê do caso — a tela onde o advogado acompanha o processo inteiro.
 *
 * Reúne o que o Acervo apurou (cliente, checklist, contrato) e o que o agente
 * jurídico concluiu (fatos com origem, leitura jurídica, pendências do playbook,
 * jurisprudência). É leitura: nenhuma conclusão nasce aqui.
 *
 * Três regras de desenho, todas do `docs/GUIA-VISUAL.md`:
 *
 * - **cor nunca sozinha.** Toda etapa e todo estado trazem símbolo + palavra;
 * - **uma única ação principal por bloco.** "Analisar" e "Pesquisar" são secundárias
 *   ao lado de "Enviar ao agente", que é a que destrava as demais;
 * - **ausência declarada.** Agente fora do ar aparece como aviso com o motivo, nunca
 *   como lista vazia — as duas coisas se parecem e significam o oposto.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import AjudanteDoCaso from "@/components/AjudanteDoCaso";
/* O trilho recolhido é desenhado por quem hospeda o painel, e não pelo painel: só o
 * dossiê sabe que existe uma coluna para devolver ao conteúdo quando ele se fecha. */
import trilho from "@/components/AjudanteDoCaso.module.css";
import { Aviso, Botao, Campo, Cartao, LinkBotao, RotuloCampo, Selo } from "@/components/ui/Basicos";
import {
  gerarContratoDoCaso as solicitarContratoDoCaso,
  requisitosDoContrato,
  analisarDocumentosDoCaso,
  type AnaliseDocumentos,
} from "@/lib/api";
import type { TomSelo } from "@/lib/formato";
import { ESTADO_DO_FATO, ORIGEM_DO_FATO, valorDoFato } from "@/lib/painel";
import {
  analisarNoAgente,
  anexarEntrevista,
  baixarArquivoDaPeticao,
  buscarDossie,
  buscarEntrevista,
  buscarPeticao,
  buscarPesquisa,
  decidirEstrategia,
  decidirHipotese,
  decidirPeticao,
  gerarEstrategia,
  gerarPeticao,
  lerEntrevistaNoAgente,
  pesquisarNoAgente,
  progressoPeticao,
  resolverContradicao,
  sincronizarComAgente,
  urlDaEntrevista,
  type Contradicao,
  type Dossie as DossieDados,
  type EntrevistaResumo,
  type EstadoEtapa,
  type Estrategia,
  type Hipotese,
  type Peticao,
  type PesquisaDetalhe,
  type Precedente,
} from "@/lib/agente";

/* Vocabulário de estado do guia: símbolo + palavra + cor, nesta ordem. */
const ETAPA: Record<EstadoEtapa, { simbolo: string; palavra: string; tom: TomSelo }> = {
  pronto: { simbolo: "✓", palavra: "Pronto", tom: "ok" },
  andamento: { simbolo: "→", palavra: "Em andamento", tom: "info" },
  atencao: { simbolo: "!", palavra: "Conferir", tom: "atencao" },
  pendente: { simbolo: "•", palavra: "Falta fazer", tom: "neutro" },
  indisponivel: { simbolo: "✕", palavra: "Sem resposta", tom: "critico" },
};

/* A faixa da esquerda repete o estado que o símbolo já diz — reforço, nunca a
 * única pista. `borda` e `cor` (aplicada ao símbolo e à palavra do estado)
 * não são sempre o mesmo token: "atencao" usa uma marca mais forte na borda
 * do que no texto. */
const ESTILO_ETAPA: Record<EstadoEtapa, { borda: string; cor: string }> = {
  pronto: { borda: "var(--ok)", cor: "text-ok" },
  andamento: { borda: "var(--acao)", cor: "text-acao" },
  atencao: { borda: "var(--atencao-marca)", cor: "text-atencao" },
  pendente: { borda: "var(--borda-forte)", cor: "text-tinta-3" },
  indisponivel: { borda: "var(--critico)", cor: "text-critico" },
};

const APLICABILIDADE: Record<string, { texto: string; tom: TomSelo; simbolo: string }> = {
  HIGH: { texto: "Aplica-se ao caso", tom: "ok", simbolo: "✓" },
  MEDIUM: { texto: "Aplica-se em parte", tom: "info", simbolo: "→" },
  LOW: { texto: "Pouco aplicável", tom: "neutro", simbolo: "•" },
  NOT_APPLICABLE: { texto: "Não se aplica", tom: "neutro", simbolo: "•" },
};

/** Tipo de fato no vocabulário de quem lê a tela, não no do banco. */
const ROTULO_FATO: Record<string, string> = {
  "PERSON.NAME": "Nome",
  "PERSON.CPF": "CPF",
  "PERSON.RG": "RG",
  "PERSON.PIS": "PIS/PASEP",
  "PERSON.BIRTH_DATE": "Nascimento",
  "PERSON.ADDRESS": "Endereço",
  "EMPLOYMENT.RELATIONSHIP": "Vínculo de emprego",
  "EMPLOYMENT.ADMISSION_DATE": "Admissão",
  "EMPLOYMENT.TERMINATION_DATE": "Saída",
  "EMPLOYMENT.MONTHLY_SALARY": "Salário",
  "EMPLOYMENT.WORK_SCHEDULE": "Jornada",
  "EMPLOYMENT.LEAVE": "Afastamento",
  "SOCIAL_SECURITY.INSS_BENEFIT": "Benefício do INSS",
};

/* Classes reutilizadas nos vários blocos de listagem do dossiê (fatos,
 * precedentes, pendências, contradições…) — todas vêm do mesmo desenho de
 * `.item`/`.itemTopo`/`.origem`/`.razao` que existia em Dossie.module.css. */
const TITULO_CARTAO = "mb-1 text-tinta font-titulo text-lg font-semibold leading-[1.25]";
const ITEM_TOPO = "flex items-center justify-between gap-[10px] flex-wrap";
const ITEM = "border border-borda bg-papel p-[12px_14px] grid gap-[6px]";
const LISTA = "list-none m-0 p-0 grid gap-3";
const EXPLICACAO = "-mt-1 mb-3 text-tinta-3 text-sm leading-[1.5] max-w-[62ch]";
const TEXTO_VAZIO = "mt-[6px] text-tinta-3 text-sm";
const ORIGEM = "text-tinta-3 text-xs";
const RAZAO = "mt-[2px] text-tinta-2 text-sm leading-[1.55]";
const VALOR = "font-codigo tabular-nums text-sm text-tinta";
const TRECHO =
  "mt-[6px] p-[8px_12px] bg-papel-2 border-l-[3px] border-borda-forte text-tinta-2 text-sm leading-[1.55]";
const PONTOS = "mt-[2px] p-0 list-none grid gap-1 text-sm leading-[1.5]";
const SECAO_TITULO = "mt-[18px] mb-[6px] font-ui text-sm font-bold tracking-[0.02em] text-tinta first:mt-0";
const FICHA_LINHA =
  "grid grid-cols-1 sm:grid-cols-[150px_1fr] gap-x-3 gap-y-[2px] bg-papel p-[9px_12px]";
const INDICADOR = "border border-borda bg-papel-2 p-[12px_14px] mb-[14px] grid gap-2";
const MINUTA = "mt-[14px] p-[16px_18px] bg-papel-2 border border-borda max-h-[520px] overflow-y-auto";
const PARAGRAFO_MINUTA = "m-0 mb-2 font-titulo text-base leading-[1.7] text-justify text-tinta-2 max-w-[72ch]";
const CAMPO_ENTREVISTA = "grid gap-1 text-tinta-2 text-sm";
const INPUT_ENTREVISTA = "p-[7px_10px] border border-borda rounded-[6px] bg-papel text-tinta";

function cpfCanonicoDoFato(valor: string): string | null {
  const normalizado = valor.normalize("NFKC");
  if (!/^[0-9.\-\s]+$/.test(normalizado)) return null;
  return normalizado.replace(/[^0-9]/g, "");
}

/** Dados que o contrato consegue reaproveitar do caso sem inventar informação.
 *
 * O nome vem do cadastro. Os demais valores vieram dos documentos e carregam
 * proveniência no dossiê; campos que ainda não existem ficam ausentes para o
 * gerador manter o marcador entre colchetes no documento. */
export function respostasDoDossie(dados: DossieDados): Record<string, string> {
  const camposAtuais = dados.cliente.campos.filter(
    (campo) => !["REJECTED", "SUPERSEDED", "CONTESTED", "CONTRADICTED"].includes(campo.status),
  );
  const valor = (rotulo: string) =>
    camposAtuais.find((campo) => campo.rotulo === rotulo)?.valor.trim() ?? "";

  const cpfs = new Map<string, string>();
  for (const campo of camposAtuais.filter((item) => item.rotulo === "CPF")) {
    const canonico = cpfCanonicoDoFato(campo.valor);
    if (canonico) cpfs.set(canonico, campo.valor.trim());
  }

  return {
    nome: dados.cliente.nome.trim(),
    nacionalidade: valor("Nacionalidade"),
    estado_civil: valor("Estado civil"),
    profissao: valor("Profissão"),
    // Mais de um valor atual representa divergência documental, não permissão
    // para escolher silenciosamente o fato que chegou primeiro.
    cpf: cpfs.size === 1 ? ([...cpfs.values()][0] ?? "") : "",
    rg: valor("RG"),
    rg_orgao: valor("Órgão emissor"),
    rg_uf: valor("UF do RG"),
    endereco: valor("Endereço"),
    telefone: valor("Telefone"),
    email: valor("E-mail"),
  };
}

function chaveDeNome(nome: string): string {
  return nome
    .normalize("NFKD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLocaleLowerCase("pt-BR")
    .replace(/[^\p{L}]/gu, "");
}

function alertasIdentificacaoDoDossie(dados: DossieDados): string[] {
  const alertas: string[] = [];
  const fatosCpf = dados.cliente.campos.filter(
    (campo) => campo.rotulo === "CPF" && !["REJECTED", "SUPERSEDED"].includes(campo.status),
  );
  if (fatosCpf.some((campo) => ["CONTESTED", "CONTRADICTED"].includes(campo.status))) {
    alertas.push("O CPF está contestado ou contraditado no dossiê; resolva o fato antes de gerar.");
  }
  if (fatosCpf.some((campo) => cpfCanonicoDoFato(campo.valor) === null)) {
    alertas.push("Há um CPF em formato inválido nos documentos; corrija o fato antes de gerar.");
  }
  const cpfsDistintos = new Set(
    fatosCpf.map((campo) => cpfCanonicoDoFato(campo.valor)).filter(Boolean),
  );
  if (cpfsDistintos.size > 1) {
    alertas.push(
      "Há CPFs divergentes nos documentos; rejeite ou substitua o fato incorreto antes de gerar.",
    );
  }

  const fatosNome = dados.cliente.campos.filter(
    (campo) =>
      campo.rotulo === "Nome no documento" &&
      !["REJECTED", "SUPERSEDED"].includes(campo.status),
  );
  if (fatosNome.some((campo) => ["CONTESTED", "CONTRADICTED"].includes(campo.status))) {
    alertas.push(
      "O nome do cliente está contestado ou contraditado no dossiê; resolva o fato antes de gerar.",
    );
  }
  const nomesDistintos = new Set(fatosNome.map((campo) => chaveDeNome(campo.valor)).filter(Boolean));
  if (nomesDistintos.size > 1) {
    alertas.push(
      "Há nomes divergentes nos documentos; rejeite ou substitua o fato incorreto antes de gerar.",
    );
  } else if (
    nomesDistintos.size === 1 &&
    !nomesDistintos.has(chaveDeNome(dados.cliente.nome))
  ) {
    alertas.push(
      "O nome do cadastro diverge do nome encontrado nos documentos; corrija o cadastro ou o fato antes de gerar.",
    );
  }
  return alertas;
}

function baixarArquivo(arquivo: Blob, nome: string): void {
  const url = URL.createObjectURL(arquivo);
  const link = document.createElement("a");
  link.href = url;
  link.download = nome;
  link.click();
  URL.revokeObjectURL(url);
}

function campoLegivel(campo: string): string {
  const texto = campo
    .replace(/\brg\b/gi, "RG")
    .replace(/\bcpf\b/gi, "CPF")
    .replace(/\be mail\b/gi, "e-mail");
  return texto.charAt(0).toUpperCase() + texto.slice(1);
}

export default function Dossie({
  casoId,
  onVoltar,
  onAbrirPainel,
  onAbrirJurimetria,
}: {
  casoId: string;
  onVoltar: () => void;
  /** Abre o painel analítico do mesmo caso. Opcional: o dossiê continua de pé sozinho. */
  onAbrirPainel?: () => void;
  /** Opcional pelo mesmo motivo do painel: o dossiê é aberto de mais de um lugar, e
   *  nem todos têm para onde navegar depois. */
  onAbrirJurimetria?: () => void;
}) {
  const [dados, setDados] = useState<DossieDados | null>(null);
  const [erro, setErro] = useState<string | null>(null);
  const [ocupado, setOcupado] = useState<string | null>(null);
  const [pesquisa, setPesquisa] = useState<PesquisaDetalhe | null>(null);
  const [peticao, setPeticao] = useState<Peticao | null>(null);
  /* A redação em curso. Enquanto existir, a tela mostra a barra de progresso em vez do
   * "ficou pronta" — que era falso: o POST responde 202, e a peça só aparece minutos
   * depois. `desde` é a marca que separa esta geração da anterior. */
  const [redacao, setRedacao] = useState<{
    desde: string;
    esperadas: number;
    passos: number;
  } | null>(null);
  /** Versão da estratégia antes do pedido — polling até subir ou estourar o prazo. */
  const [estrategiaEmCurso, setEstrategiaEmCurso] = useState<number | null>(null);
  const [aviso, setAviso] = useState<string | null>(null);
  const [camposFaltandoContrato, setCamposFaltandoContrato] = useState<string[] | null>(null);
  /* Começa recolhido: o dossiê é o que o advogado veio ver, e abrir por cima dele uma
   * coluna de 400px em toda visita decidiria por ele. Recolhido não é escondido — o
   * trilho ao lado continua anunciando que o agente está ali, a um clique. */
  const [agenteAberto, setAgenteAberto] = useState(false);
  /* Qual fato a citação da resposta está apontando. Sem o destaque, seguir a referência
   * rola a página e nada muda na tela: o advogado não sabe qual dos cartões era. */
  const [fatoCitado, setFatoCitado] = useState<string | null>(null);

  const carregar = useCallback(async () => {
    try {
      const resposta = await buscarDossie(casoId);
      setDados(resposta);
      setErro(null);
    } catch (falha) {
      setErro(falha instanceof Error ? falha.message : "Não foi possível abrir o dossiê.");
    }
  }, [casoId]);

  useEffect(() => {
    void carregar();
  }, [carregar]);

  /* O agente trabalha em segundo plano: classificar e pesquisar rodam em worker do
   * outro lado. Enquanto houver etapa em andamento, a tela se atualiza sozinha —
   * sem isso o advogado ficaria apertando F5 para saber se terminou. */
  const emAndamento = dados?.etapas.some((etapa) => etapa.estado === "andamento") ?? false;
  useEffect(() => {
    if (!emAndamento && !ocupado) return;
    const timer = setInterval(() => void carregar(), 5000);
    return () => clearInterval(timer);
  }, [emAndamento, ocupado, carregar]);

  /* Acompanha a redação até a peça existir de verdade.
   *
   * O que se lê é execução de IA já gravada — seção redigida e revisão —, não relógio
   * correndo na tela: uma barra que anda sozinha mentiria do mesmo jeito que o aviso
   * antigo, só mais devagar.
   *
   * Falha de leitura é engolida de propósito: a redação continua no worker do outro lado,
   * e derrubar o acompanhamento por uma consulta que não voltou deixaria o advogado sem
   * saber de nada. O prazo máximo abaixo é o do próprio worker (`time_limit`, 15 min); dali
   * em diante o silêncio é defeito, e aí sim ele precisa ser dito.
   */
  const redigindoDesde = redacao?.desde ?? null;
  useEffect(() => {
    if (!redigindoDesde) return;
    let ativo = true;
    const limite = Date.now() + 16 * 60 * 1000;

    const timer = setInterval(() => {
      void (async () => {
        try {
          const andamento = await progressoPeticao(casoId, redigindoDesde);
          if (!ativo) return;
          if (andamento.status === "DONE") {
            /* Busque a peça antes de anunciar o fim. Atualizar primeiro o aviso e só depois
             * recarregar o dossiê ainda deixava uma janela em que "ficou pronta" aparecia
             * sobre a versão antiga (ou sobre cartão vazio), que é justamente o falso
             * positivo que este acompanhamento elimina. */
            if (!andamento.generation_id) {
              throw new Error("A geração terminou sem identificar a petição criada.");
            }
            const pronta = await buscarPeticao(casoId, andamento.generation_id);
            if (!ativo) return;
            setPeticao(pronta);
            setRedacao(null);
            try {
              const arquivo = await baixarArquivoDaPeticao(casoId, pronta.id, "docx");
              if (ativo) {
                baixarArquivo(arquivo, `Peticao inicial - v${pronta.version}.docx`);
              }
            } catch {
              /* a peça continua na tela; o advogado pode baixar pelo botão abaixo */
            }
            setAviso(
              andamento.blocking_findings > 0
                ? "A minuta ficou pronta e foi baixada. A revisão a reteve — o motivo está abaixo."
                : "A petição foi baixada e está aberta abaixo.",
            );
            /* Sincroniza também o resumo/lista, sem bloquear a exibição que acabou de
             * receber o documento completo pelo identificador exato. */
            void carregar();
            return;
          }
          setRedacao((atual) =>
            atual ? { ...atual, passos: andamento.completed_steps } : atual,
          );
          if (andamento.completed_steps === 0) {
            void carregar();
          }
        } catch {
          /* leitura perdida; a próxima tentativa vem em três segundos */
        }
        if (ativo && Date.now() > limite) {
          setRedacao(null);
          setErro(
            "A redação passou do prazo do agente sem devolver a peça. Verifique o worker de geração antes de pedir outra.",
          );
        }
      })();
    }, 3000);

    return () => {
      ativo = false;
      clearInterval(timer);
    };
  }, [casoId, redigindoDesde, carregar]);

  const ultimaPesquisa = dados?.agente.pesquisas[0] ?? null;
  const ultimaPeticao = dados?.agente.peticoes?.[0] ?? null;

  /* A lista do dossiê traz o resumo; as seções vêm só quando a peça é aberta — é o
   * texto inteiro da petição, e carregá-lo em toda atualização da tela seria caro. */
  useEffect(() => {
    if (!ultimaPeticao) {
      setPeticao(null);
      return;
    }
    let ativo = true;
    void buscarPeticao(casoId, ultimaPeticao.id)
      .then((detalhe) => ativo && setPeticao(detalhe))
      .catch(() => ativo && setPeticao(ultimaPeticao));
    return () => {
      ativo = false;
    };
  }, [casoId, ultimaPeticao]);

  useEffect(() => {
    if (!ultimaPesquisa || ultimaPesquisa.status !== "COMPLETED") {
      setPesquisa(null);
      return;
    }
    let ativo = true;
    void buscarPesquisa(casoId, ultimaPesquisa.id)
      .then((detalhe) => ativo && setPesquisa(detalhe))
      .catch(() => ativo && setPesquisa(null));
    return () => {
      ativo = false;
    };
  }, [casoId, ultimaPesquisa]);

  const versaoEstrategia = dados?.agente.estrategia?.version ?? 0;

  useEffect(() => {
    if (estrategiaEmCurso === null) return;
    let ativo = true;
    const limite = Date.now() + 11 * 60 * 1000;

    const timer = setInterval(() => {
      void carregar();
      if (ativo && Date.now() > limite) {
        setEstrategiaEmCurso(null);
        setErro(
          "A estratégia passou do prazo do agente sem aparecer. Verifique o worker de estratégia antes de pedir outra.",
        );
      }
    }, 3000);

    return () => {
      ativo = false;
      clearInterval(timer);
    };
  }, [estrategiaEmCurso, carregar]);

  useEffect(() => {
    if (estrategiaEmCurso === null) return;
    if (versaoEstrategia > estrategiaEmCurso) {
      setEstrategiaEmCurso(null);
      setAviso("Estratégia proposta — revise as teses abaixo e aprove se concordar.");
    }
  }, [versaoEstrategia, estrategiaEmCurso]);

  async function executar(nome: string, acao: () => Promise<unknown>, mensagem: string) {
    setOcupado(nome);
    setAviso(null);
    try {
      await acao();
      setAviso(mensagem);
      await carregar();
    } catch (falha) {
      setErro(falha instanceof Error ? falha.message : "A ação não pôde ser concluída.");
    } finally {
      setOcupado(null);
    }
  }

  /* A petição tem caminho próprio, e não o `executar` das demais ações: as outras
   * terminam quando o pedido é aceito, esta só termina quando a peça existe. É a diferença
   * entre "enfileirada" e "pronta", e era ela que o aviso antigo apagava. */
  async function pedirEstrategia() {
    const versaoAntes = dados?.agente.estrategia?.version ?? 0;
    setOcupado("estrategia");
    setAviso("Preparando classificação, pesquisa e estratégia…");
    setErro(null);
    try {
      if (dados?.agente.ultimo_erro) {
        await sincronizarComAgente(casoId);
      }
      await gerarEstrategia(casoId);
      setEstrategiaEmCurso(versaoAntes);
      setAviso(
        "Estratégia enfileirada. O worker classifica, pesquisa jurisprudência e propõe as teses — aparecem aqui quando terminar.",
      );
    } catch (falha) {
      setErro(falha instanceof Error ? falha.message : "Não foi possível propor a estratégia.");
    } finally {
      setOcupado(null);
    }
  }

  async function pedirPeticao() {
    setOcupado("peticao");
    setAviso("Preparando classificação, pesquisa e redação…");
    setErro(null);
    try {
      if (dados?.agente.ultimo_erro) {
        await sincronizarComAgente(casoId);
      }
      const pedido = await gerarPeticao(casoId);
      setAviso(
        pedido.preparo?.pesquisa
          ? "Pesquisa pronta. Quando terminar, a petição baixa sozinha em .docx."
          : "Petição enfileirada. Quando ficar pronta, o .docx baixa automaticamente.",
      );
      setRedacao({
        desde: pedido.requested_at,
        // Piso, não previsão: seção com subtítulos vira mais de uma chamada de modelo. A
        // barra respeita isso e não fecha por contagem — só quando a peça aparece.
        esperadas: Math.max(1, pedido.expected_sections + 1),
        passos: 0,
      });
    } catch (falha) {
      setErro(falha instanceof Error ? falha.message : "Não foi possível gerar a petição.");
    } finally {
      setOcupado(null);
    }
  }

  async function gerarContratoDoCaso(dossie: DossieDados) {
    const alertasIdentificacao = alertasIdentificacaoDoDossie(dossie);
    const requisitos = requisitosDoContrato(respostasDoDossie(dossie));
    if (alertasIdentificacao.length > 0) {
      setErro(alertasIdentificacao.join(" "));
      return;
    }
    if (requisitos.length > 0) {
      setErro(`Contrato não gerado: informe ${requisitos.join(" e ")}.`);
      return;
    }
    setOcupado("contrato");
    setAviso(null);
    setErro(null);
    setCamposFaltandoContrato(null);
    try {
      const contrato = await solicitarContratoDoCaso(dossie.caso.id);
      baixarArquivo(contrato.arquivo, contrato.nome);
      setCamposFaltandoContrato(contrato.faltando);
      setAviso(`${contrato.nome} foi baixado. Confira o documento antes de assinar.`);
    } catch (falha) {
      setErro(falha instanceof Error ? falha.message : "Não foi possível gerar o contrato.");
    } finally {
      setOcupado(null);
    }
  }

  if (erro && !dados) {
    return (
      <div className="max-w-[1240px] mx-auto px-4 sm:px-7 pt-6 pb-16 grid gap-[18px]">
        <Botao variante="secundario" pequeno onClick={onVoltar}>
          ← Voltar
        </Botao>
        <Aviso tom="critico" titulo="Não foi possível abrir o dossiê">
          {erro}
        </Aviso>
      </div>
    );
  }

  if (!dados)
    return (
      <div className="max-w-[1240px] mx-auto px-4 sm:px-7 pt-6 pb-16 grid gap-[18px]">
        Carregando o dossiê…
      </div>
    );

  const { agente } = dados;
  const pendencias = agente.pendencias.filter((item) => item.status === "OPEN");
  const requisitosContrato = requisitosDoContrato(respostasDoDossie(dados));
  const alertasIdentificacaoContrato = alertasIdentificacaoDoDossie(dados);
  const temAlertaCpf = alertasIdentificacaoContrato.some((alerta) => alerta.includes("CPF"));
  const requisitosVisiveis = temAlertaCpf
    ? requisitosContrato.filter((requisito) => requisito !== "CPF válido")
    : requisitosContrato;
  const bloqueantes = pendencias.filter((item) => item.severity === "BLOCKING");

  return (
    /* Duas colunas: o dossiê e o agente. O caso NÃO sai da tela quando se fala com ele —
     * antes isso era uma aba que substituía o dossiê inteiro, e a citação da resposta
     * ("Entrevista · falta fazer") apontava para algo que o advogado não estava mais
     * vendo. Ao lado, ela vira caminho de ida e volta.
     *
     * A coluna só existe a partir de `lg`: em 400px de painel sobre uma tela de celular
     * não sobra dossiê nenhum para a citação apontar, e aí ela não serviria para nada. */
    <div className="flex items-start">
      <div className="min-w-0 flex-1 max-w-[1240px] mx-auto px-4 sm:px-7 pt-6 pb-16 grid gap-[18px]">
      <header className="flex justify-between items-end gap-5 flex-wrap">
        <div>
          <Botao variante="secundario" pequeno onClick={onVoltar}>
            ← Voltar para a carteira
          </Botao>
          {onAbrirPainel && (
            <Botao variante="texto" pequeno onClick={onAbrirPainel}>
              Painel analítico →
            </Botao>
          )}
          {onAbrirJurimetria && (
            <Botao variante="texto" pequeno onClick={onAbrirJurimetria}>
              Jurisprudência e jurimetria →
            </Botao>
          )}
          <h1 className="mt-2 text-xl tracking-[-0.01em]">Dossiê de {dados.caso.cliente}</h1>
          <p className="mt-1 text-tinta-3 text-sm">
            {dados.checklist.categoria ?? dados.caso.categoria} · caso aberto em{" "}
            {new Date(dados.caso.criado_em).toLocaleDateString("pt-BR")}
            {agente.caso_ref ? ` · agente ${agente.caso_ref}` : ""}
          </p>
        </div>

        <div className="flex gap-2 flex-wrap">
          <Botao
            variante="primario"
            disabled={!agente.ligado || ocupado !== null}
            onClick={() =>
              void executar(
                "sincronizar",
                () => sincronizarComAgente(casoId),
                "Caso e documentos enviados ao agente.",
              )
            }
          >
            {ocupado === "sincronizar"
              ? "Enviando…"
              : agente.vinculado
                ? "Enviar documentos novos"
                : "Enviar ao agente"}
          </Botao>
          <Botao
            variante="secundario"
            disabled={!agente.ligado || ocupado !== null}
            onClick={() =>
              void executar(
                "analisar",
                () => analisarNoAgente(casoId),
                "Análise enfileirada. O resultado aparece aqui em instantes.",
              )
            }
          >
            {ocupado === "analisar" ? "Analisando…" : "Classificar o caso"}
          </Botao>
          <Botao
            variante="secundario"
            disabled={!agente.ligado || ocupado !== null}
            onClick={() =>
              void executar(
                "pesquisar",
                () => pesquisarNoAgente(casoId),
                "Pesquisa de jurisprudência enfileirada.",
              )
            }
          >
            {ocupado === "pesquisar" ? "Pesquisando…" : "Pesquisar jurisprudência"}
          </Botao>
          <Botao
            variante="secundario"
            disabled={!agente.ligado || ocupado !== null || estrategiaEmCurso !== null}
            onClick={() => void pedirEstrategia()}
          >
            {ocupado === "estrategia" || estrategiaEmCurso !== null
              ? "Propondo…"
              : "Propor estratégia"}
          </Botao>
          <Botao
            variante="secundario"
            disabled={!agente.ligado || ocupado !== null || redacao !== null}
            onClick={() => void pedirPeticao()}
          >
            {ocupado === "peticao" || redacao ? "Redigindo…" : "Gerar petição"}
          </Botao>
        </div>
      </header>

      {aviso && <Aviso tom="ok">{aviso}</Aviso>}
      {erro && (
        <Aviso tom="critico" titulo="A última ação falhou">
          {erro}
        </Aviso>
      )}
      {!agente.ligado && (
        <Aviso tom="atencao" titulo="Agente jurídico não configurado">
          {agente.motivo ?? "Defina AGENTE_API_URL no .env para ligar a análise jurídica."} O
          restante do caso continua funcionando normalmente.
        </Aviso>
      )}
      {agente.ligado && !agente.disponivel && agente.vinculado && (
        <Aviso tom="critico" titulo="O agente não respondeu">
          {agente.motivo ?? "Serviço indisponível."} O que aparece abaixo é só o que o Acervo
          guarda — não significa que o caso esteja sem fatos.
        </Aviso>
      )}
      {agente.ultimo_erro && agente.disponivel && (
        <Aviso tom="atencao" titulo="Um envio anterior falhou">
          {agente.ultimo_erro} Use “Enviar documentos novos” para tentar de novo.
        </Aviso>
      )}

      {/* ------------------------------------------------ linha do processo */}
      <section className="grid grid-cols-[repeat(auto-fit,minmax(190px,1fr))] gap-[10px]" aria-label="Etapas do caso">
        {dados.etapas.map((etapa) => {
          const visual = ETAPA[etapa.estado];
          const cor = ESTILO_ETAPA[etapa.estado];
          return (
            <article
              key={etapa.codigo}
              className="bg-papel border border-borda p-[12px_14px] grid gap-[2px] content-start"
              style={{ borderLeftWidth: "3px", borderLeftColor: cor.borda }}
            >
              <div className="flex items-baseline gap-2">
                <span aria-hidden className={`font-codigo text-base ${cor.cor}`}>
                  {visual.simbolo}
                </span>
                <h2 className="m-0 font-ui text-sm font-semibold">{etapa.titulo}</h2>
              </div>
              <p className={`m-0 text-xs font-semibold tracking-[0.01em] ${cor.cor}`}>{visual.palavra}</p>
              <p className="mt-[2px] text-tinta-3 text-xs leading-[1.45]">{etapa.detalhe}</p>
            </article>
          );
        })}
      </section>

      <div className="grid min-w-0 grid-cols-[minmax(min(100%,320px),1fr)_minmax(min(100%,360px),1.2fr)] items-start gap-[18px] max-[900px]:grid-cols-1">
        {/* ------------------------------------------------ coluna esquerda */}
        <div className="grid gap-[18px] content-start">
          <Cartao titulo="Ficha do cliente">
            <p className={EXPLICACAO}>
              O nome vem do cadastro; os demais campos foram lidos dos documentos enviados, com
              a origem registrada.
            </p>
            <dl className="m-0 grid gap-px bg-borda border border-borda">
              <div className={FICHA_LINHA}>
                <dt className="text-tinta-3 text-sm">Nome</dt>
                <dd className="m-0 grid gap-[2px]">{dados.cliente.nome}</dd>
              </div>
              {dados.cliente.campos.map((campo, indice) => (
                <div
                  key={`${campo.rotulo}-${campo.valor}-${campo.status}-${indice}`}
                  className={FICHA_LINHA}
                >
                  <dt className="text-tinta-3 text-sm">{campo.rotulo}</dt>
                  <dd className="m-0 grid gap-[2px]">
                    <span className={VALOR}>{campo.valor}</span>
                    {campo.fontes.length > 0 && (
                      <span className={ORIGEM}>
                        origem: {campo.fontes.join(", ").toLowerCase()}
                      </span>
                    )}
                    {(campo.anexos ?? []).map((anexo) => (
                      <a
                        key={anexo.url}
                        href={anexo.url}
                        target="_blank"
                        rel="noreferrer"
                        className="text-azul-claro text-sm underline underline-offset-2"
                      >
                        Prova: {anexo.nome}
                        {anexo.pagina ? ` · página ${anexo.pagina}` : ""}
                        {anexo.campo && anexo.campo !== "__document__" ? ` · campo ${anexo.campo}` : ""}
                      </a>
                    ))}
                  </dd>
                </div>
              ))}
            </dl>
            {dados.cliente.campos.length === 0 && (
              <p className={TEXTO_VAZIO}>
                {agente.disponivel
                  ? "Nenhum documento lido produziu dado pessoal ainda."
                  : "Sem resposta do agente — os dados do cliente não puderam ser lidos."}
              </p>
            )}
          </Cartao>

          <PainelEntrevista
            casoId={casoId}
            entrevistas={dados.entrevistas ?? []}
            ocupado={ocupado !== null}
            agenteLigado={agente.ligado}
            onAnexar={(arquivo, data, quem) =>
              executar(
                "entrevista",
                () => anexarEntrevista(casoId, arquivo, data, quem),
                "Entrevista anexada ao caso. Use “Ler no agente” para virar fato.",
              )
            }
            onLer={(entrevistaId) =>
              executar(
                "entrevista",
                () => lerEntrevistaNoAgente(casoId, entrevistaId),
                "Entrevista lida. Os fatos relatados entram como alegados.",
              )
            }
          />

          <PainelContradicoes
            contradicoes={agente.contradicoes}
            ocupado={ocupado !== null}
            onResolver={(id, estado, resolucao, justificativa) =>
              executar(
                "contradicao",
                () => resolverContradicao(casoId, id, estado, resolucao, justificativa),
                "Divergência decidida. O histórico guarda quem decidiu e por quê.",
              )
            }
          />

          <Cartao titulo="Contrato de honorários">
            <p className={EXPLICACAO}>
              Preenche o modelo oficial com o nome do cadastro e os dados pessoais apurados nos
              documentos deste caso. As cláusulas do escritório não são alteradas, e cada caso
              recebe seus próprios dados.
            </p>
            {(requisitosContrato.length > 0 || alertasIdentificacaoContrato.length > 0) && (
              <Aviso tom="atencao" titulo="Contrato ainda não pode ser gerado">
                {alertasIdentificacaoContrato.length > 0 ? (
                  <>
                    {requisitosVisiveis.length > 0 && (
                      <>Informe {requisitosVisiveis.join(" e ")} neste caso. </>
                    )}
                    {alertasIdentificacaoContrato.join(" ")}{" "}
                  </>
                ) : (
                  <>Informe {requisitosContrato.join(" e ")} neste caso. </>
                )}
                Nenhum arquivo será criado enquanto esses dados obrigatórios não estiverem
                válidos.
              </Aviso>
            )}
            <div className="flex gap-2 flex-wrap">
              <Botao
                variante="primario"
                disabled={
                  ocupado !== null ||
                  requisitosContrato.length > 0 ||
                  alertasIdentificacaoContrato.length > 0
                }
                onClick={() => void gerarContratoDoCaso(dados)}
              >
                {ocupado === "contrato" ? "Gerando…" : "Gerar contrato do caso"}
              </Botao>
              {dados.contrato.assinado ? (
                <Selo tom="ok" simbolo="✓">
                  contrato assinado
                </Selo>
              ) : dados.contrato.assinaturas.length > 0 ? (
                <Selo tom="info" simbolo="→">
                  assinatura em andamento
                </Selo>
              ) : (
                <Selo tom="neutro" simbolo="•">
                  ainda não enviado para assinatura
                </Selo>
              )}
            </div>

            {camposFaltandoContrato && camposFaltandoContrato.length > 0 && (
              <Aviso tom="atencao" titulo="Confira os campos que ficaram em aberto">
                O arquivo foi gerado com marcadores visíveis para: {" "}
                {camposFaltandoContrato.map(campoLegivel).join(", ")}.
              </Aviso>
            )}
            {camposFaltandoContrato?.length === 0 && (
              <Aviso tom="ok">✓ Todos os campos do modelo foram preenchidos.</Aviso>
            )}
          </Cartao>

          <Cartao titulo={`Fatos apurados (${agente.fatos.length})`}>
            <p className={EXPLICACAO}>
              Cada fato aponta o documento de onde saiu. Fato sem origem não é registrado.
            </p>
            <ul className={LISTA}>
              {agente.fatos.map((fato) => (
                /* O `id` é o que a citação da resposta do agente procura: ela chega com o
                 * identificador do fato, e sem âncora no cartão o "ver no dossiê" seria
                 * um botão que não leva a lugar nenhum. */
                <li
                  key={fato.id}
                  id={`fato-${fato.id}`}
                  className={
                    fatoCitado === fato.id
                      ? `${ITEM} border-acao-borda bg-acao-clara`
                      : ITEM
                  }
                >
                  <div className={ITEM_TOPO}>
                    <strong>{ROTULO_FATO[fato.type] ?? fato.type}</strong>
                    {/* O estado sai do mesmo mapa que o painel do caso usa. Antes
                      * era `status.toLowerCase()`, e o advogado lia "alleged" e
                      * "extracted" na tela — que é justamente a distinção que
                      * decide se a alegação precisa de prova. */}
                    <Selo
                      tom={ESTADO_DO_FATO[fato.status]?.tom ?? "neutro"}
                      simbolo={ESTADO_DO_FATO[fato.status]?.simbolo}
                    >
                      {ESTADO_DO_FATO[fato.status]?.palavra ?? fato.status.toLowerCase()}
                    </Selo>
                  </div>
                  <div className={VALOR} title={ESTADO_DO_FATO[fato.status]?.explicacao}>
                    {valorDoFato(fato.value)}
                  </div>
                  <div className={ORIGEM}>
                    confiança {Math.round((fato.confidence ?? 0) * 100)}%
                    {fato.sources?.length
                      ? ` · ${fato.sources
                          .map((fonte) =>
                            [
                              fonte.source_type
                                ? ORIGEM_DO_FATO[fonte.source_type.toUpperCase()] ??
                                  fonte.source_type.toLowerCase()
                                : null,
                              fonte.page ? `página ${fonte.page}` : null,
                              fonte.ocr_field ? `campo ${fonte.ocr_field}` : null,
                            ]
                              .filter(Boolean)
                              .join(", "),
                          )
                          .join(" · ")}`
                      : ""}
                  </div>
                </li>
              ))}
            </ul>
            {agente.fatos.length === 0 && (
              <p className={TEXTO_VAZIO}>
                {agente.disponivel
                  ? "Envie os documentos ao agente para que eles virem fatos."
                  : "Sem resposta do agente."}
              </p>
            )}
          </Cartao>
        </div>

        {/* -------------------------------------------------- coluna direita */}
        <div className="grid gap-[18px] content-start">
          <Cartao titulo="Leitura jurídica">
            {agente.classificacoes.length === 0 ? (
              <p className={TEXTO_VAZIO}>
                {agente.disponivel
                  ? "O caso ainda não foi classificado. Use “Classificar o caso”."
                  : "Sem resposta do agente."}
              </p>
            ) : (
              <ul className={LISTA}>
                {agente.classificacoes.map((item) => (
                  <li key={item.code} className={ITEM}>
                    <div className={ITEM_TOPO}>
                      <strong>{item.label}</strong>
                      <Selo tom="info">{Math.round(item.confidence * 100)}% de confiança</Selo>
                    </div>
                    {item.rationale && <p className={RAZAO}>{item.rationale}</p>}
                    {item.issues && item.issues.length > 0 && (
                      <div className="flex gap-[6px] flex-wrap mt-1">
                        {item.issues.map((questao) => (
                          <Selo key={questao.code} tom="neutro">
                            {questao.label}
                          </Selo>
                        ))}
                      </div>
                    )}
                  </li>
                ))}
              </ul>
            )}
          </Cartao>

          <Cartao titulo={`O que falta (${pendencias.length})`}>
            <p className={EXPLICACAO}>
              Lista derivada do playbook do escritório — cada item diz qual exigência o
              originou.
            </p>
            <ul className={LISTA}>
              {pendencias.map((item) => (
                <li key={item.id} className={ITEM}>
                  <div className={ITEM_TOPO}>
                    <strong>{item.label}</strong>
                    <Selo
                      tom={item.severity === "BLOCKING" ? "critico" : "atencao"}
                      simbolo={item.severity === "BLOCKING" ? "✕" : "!"}
                    >
                      {item.severity === "BLOCKING" ? "Indispensável" : "Recomendado"}
                    </Selo>
                  </div>
                  <div className={ORIGEM}>
                    {item.playbook_id ? `playbook ${item.playbook_id}` : ""}
                    {item.requirement ? ` · ${item.requirement}` : ""}
                  </div>
                  {item.question && <p className={RAZAO}>“{item.question}”</p>}
                </li>
              ))}
            </ul>
            {pendencias.length === 0 && (
              <p className={TEXTO_VAZIO}>
                {agente.classificacoes.length
                  ? "Nada pendente no playbook."
                  : "A lista de pendências só existe depois da classificação."}
              </p>
            )}
            {bloqueantes.length > 0 && (
              <Aviso tom="critico" titulo={`${bloqueantes.length} itens travam a instrução`}>
                Sem eles a peça não pode ser protocolada com segurança.
              </Aviso>
            )}
          </Cartao>

          <PainelAnaliseDocumentos casoId={casoId} />

          <PainelJurisprudencia
            pesquisa={pesquisa}
            resumo={ultimaPesquisa}
            disponivel={agente.disponivel}
          />

          <PainelEstrategia
            estrategia={agente.estrategia}
            disponivel={agente.disponivel}
            gerando={estrategiaEmCurso !== null}
            ocupado={ocupado !== null}
            onDecidirEstrategia={(aprovada) =>
              executar(
                "decisao",
                () => decidirEstrategia(casoId, agente.estrategia!.version, aprovada),
                aprovada
                  ? "Estratégia aprovada: os pedidos da petição passam a sair dela."
                  : "Estratégia rejeitada.",
              )
            }
            onDecidirHipotese={(id, aceita) =>
              executar(
                "decisao",
                () => decidirHipotese(casoId, id, aceita),
                aceita ? "Tese aceita." : "Tese descartada.",
              )
            }
          />

          <PainelPeticao
            casoId={casoId}
            peticao={peticao}
            redacao={redacao}
            disponivel={agente.disponivel}
            ocupado={ocupado !== null}
            onDecidir={(aprovada, nota) =>
              executar(
                "decisao",
                () => decidirPeticao(casoId, peticao!.id, aprovada, nota),
                aprovada ? "Minuta aprovada." : "Minuta rejeitada.",
              )
            }
          />
        </div>
      </div>
      </div>

      <div className="hidden lg:flex sticky top-0 h-screen">
        {agenteAberto ? (
          <AjudanteDoCaso
            casoId={casoId}
            aoRecolher={() => setAgenteAberto(false)}
            /* O destaque some sozinho: um cartão marcado para sempre viraria ruído no
             * dossiê, e a próxima citação não teria como se distinguir dele. */
            aoAbrirReferencia={(referencia) => {
              setFatoCitado(referencia);
              window.setTimeout(
                () => setFatoCitado((atual) => (atual === referencia ? null : atual)),
                2600,
              );
            }}
          />
        ) : (
          <div className={trilho.trilho}>
            <button
              type="button"
              className={trilho.iconeBotao}
              onClick={() => setAgenteAberto(true)}
              aria-label="Abrir o agente do caso"
              title="Agente do caso"
            >
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
                <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
              </svg>
            </button>
            {/* O rótulo na vertical existe para o trilho não ser um ícone mudo: quem
              * nunca abriu não tem como adivinhar o que há atrás dele. */}
            <span className="[writing-mode:vertical-rl] text-tinta-3 text-xs font-semibold tracking-[0.04em]">
              Agente do caso
            </span>
          </div>
        )}
      </div>
    </div>
  );
}

/* ------------------------------------------------------------- precedentes */

/* O conjunto recuperado — o que dá para dizer dele ANTES de abrir um a um.
 *
 * Não confundir com o Panorama (`app/panorama.py`), que é o painel analítico do
 * escritório inteiro. Aqui o recorte é uma pesquisa de um caso.
 *
 * Dez precedentes abertos na tela não são leitura, são rolagem: o advogado
 * chegava ao terceiro e já não sabia se o quarto acrescentava algo. O que ele
 * pergunta primeiro é do conjunto — "quantos me servem, de que assunto, de
 * quando" —, e só depois escolhe qual ler.
 *
 * Só agrega o que já vem estruturado: aplicabilidade, assunto, ano. Os pontos
 * favoráveis e desfavoráveis são frase livre do modelo — duas frases sobre a
 * mesma tese não se parecem o bastante para agrupar por texto, e um agrupamento
 * errado aqui inventaria consenso onde não há. Quem quiser a tese lê o
 * precedente, que está a um clique. */
function resumirConjunto(precedentes: Precedente[]) {
  const porAplicabilidade = new Map<string, number>();
  const porAssunto = new Map<string, number>();
  const anos: number[] = [];
  let semAnalise = 0;

  for (const p of precedentes) {
    const analise = p.analyses[0];
    if (analise) {
      porAplicabilidade.set(analise.applicability, (porAplicabilidade.get(analise.applicability) ?? 0) + 1);
    } else {
      semAnalise += 1;
    }
    for (const assunto of p.subjects) {
      porAssunto.set(assunto, (porAssunto.get(assunto) ?? 0) + 1);
    }
    const ano = p.decided_at ? new Date(p.decided_at).getFullYear() : NaN;
    if (!Number.isNaN(ano)) anos.push(ano);
  }

  /* A ordem é a do vocabulário, não a da contagem: "aplica-se" antes de "não se
   * aplica" se lê como escala, e uma ordem que dança a cada pesquisa obriga a
   * reler os rótulos toda vez. */
  const aplicabilidade = (["HIGH", "MEDIUM", "LOW", "NOT_APPLICABLE"] as const)
    .map((chave) => ({ chave, rotulo: APLICABILIDADE[chave], quantidade: porAplicabilidade.get(chave) ?? 0 }))
    .filter((linha) => linha.quantidade > 0);

  const assuntos = [...porAssunto.entries()]
    .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0], "pt-BR"))
    .slice(0, 4);

  return {
    total: precedentes.length,
    aplicabilidade,
    assuntos,
    semAnalise,
    periodo: anos.length ? { de: Math.min(...anos), ate: Math.max(...anos) } : null,
  };
}

function ResumoDoConjunto({ precedentes }: { precedentes: Precedente[] }) {
  const dados = resumirConjunto(precedentes);
  if (!dados.total) return null;

  return (
    <div className={INDICADOR}>
      <div className={ITEM_TOPO}>
        <strong>Resumo do conjunto</strong>
        <span className={ORIGEM}>
          {dados.total} precedente{dados.total > 1 ? "s" : ""} recuperado
          {dados.total > 1 ? "s" : ""}
        </span>
      </div>

      {dados.aplicabilidade.length > 0 && (
        <div className="flex flex-wrap items-center gap-[8px]">
          {dados.aplicabilidade.map(({ chave, rotulo, quantidade }) => (
            <Selo key={chave} tom={rotulo.tom} simbolo={rotulo.simbolo}>
              {quantidade} {rotulo.texto.toLowerCase()}
            </Selo>
          ))}
          {dados.semAnalise > 0 && (
            <Selo tom="neutro" simbolo="•">
              {dados.semAnalise} sem análise
            </Selo>
          )}
        </div>
      )}

      {dados.assuntos.length > 0 && (
        <p className="m-0 text-tinta-2 text-xs leading-[1.6]">
          <span className="text-tinta-3">assuntos: </span>
          {dados.assuntos.map(([assunto, quantidade], i) => (
            <span key={assunto}>
              {i > 0 && " · "}
              {assunto} <span className="font-codigo tabular-nums text-tinta-3">({quantidade})</span>
            </span>
          ))}
        </p>
      )}

      {dados.periodo && (
        <p className="m-0 text-tinta-3 text-xs leading-[1.6]">
          julgados entre {dados.periodo.de}
          {dados.periodo.ate !== dados.periodo.de ? ` e ${dados.periodo.ate}` : ""}.
        </p>
      )}
    </div>
  );
}

/* O que os anexos dizem e a entrevista não registrou.
 *
 * O OCR lê a página inteira e o formulário guarda meia dúzia de campos. Todo o
 * resto — o CID no laudo, a data de afastamento no CNIS, o valor no
 * contracheque — fica no texto lido e não chega a lugar nenhum. Ninguém abre
 * vinte documentos para conferir se algum diz algo que a conversa não pegou, e
 * é aí que costuma estar o fato que sustenta a peça.
 *
 * Sob demanda, com botão, e não a cada upload: num caso de vinte documentos
 * seriam vinte chamadas de modelo para responder a mesma pergunta.
 *
 * A citação de cada achado é conferida NO SERVIDOR contra o texto do documento
 * apontado. O que não confere não chega aqui — e o número de recusas aparece,
 * porque silenciá-lo esconderia um modelo alucinando com frequência. */
export function PainelAnaliseDocumentos({ casoId }: { casoId: string }) {
  const [analise, setAnalise] = useState<AnaliseDocumentos | null>(null);
  const [carregando, setCarregando] = useState(false);
  const [erro, setErro] = useState<string | null>(null);

  async function analisar() {
    setCarregando(true);
    setErro(null);
    try {
      setAnalise(await analisarDocumentosDoCaso(casoId));
    } catch (e) {
      setErro(e instanceof Error ? e.message : "Não foi possível analisar os documentos.");
    } finally {
      setCarregando(false);
    }
  }

  return (
    <Cartao titulo="O que os documentos dizem">
      <p className={EXPLICACAO}>
        Lê o texto de todos os anexos e aponta o que eles trazem e a entrevista não
        registrou. Cada achado cita o trecho literal do documento.
      </p>

      <Botao onClick={() => void analisar()} disabled={carregando}>
        {carregando ? "Lendo os documentos…" : analise ? "Analisar de novo" : "Analisar documentos"}
      </Botao>

      {erro && (
        <Aviso tom="critico" titulo="A análise não foi concluída">
          {erro}
        </Aviso>
      )}

      {analise?.aviso && <Aviso tom="atencao">{analise.aviso}</Aviso>}

      {analise && !analise.aviso && (
        <>
          <p className={ORIGEM}>
            {analise.documentos_lidos} documento{analise.documentos_lidos === 1 ? "" : "s"} lido
            {analise.documentos_lidos === 1 ? "" : "s"}
            {analise.recusados ? ` · ${analise.recusados} achado(s) recusados na conferência da citação` : ""}
          </p>

          {analise.achados.length === 0 ? (
            <p className={TEXTO_VAZIO}>
              Nada nos documentos que a entrevista já não tenha registrado.
            </p>
          ) : (
            <ul className={LISTA}>
              {analise.achados.map((a, i) => (
                <li key={i} className={ITEM}>
                  <div className={ITEM_TOPO}>
                    <strong>{a.informacao}</strong>
                    {a.contradiz && (
                      <Selo tom="critico" simbolo="!">
                        contradiz a entrevista
                      </Selo>
                    )}
                  </div>
                  <div className={ORIGEM}>{a.documento}</div>
                  {a.relevancia && <p className={RAZAO}>{a.relevancia}</p>}
                  <blockquote className={TRECHO}>{a.citacao}</blockquote>
                </li>
              ))}
            </ul>
          )}
        </>
      )}
    </Cartao>
  );
}

function PainelJurisprudencia({
  pesquisa,
  resumo,
  disponivel,
}: {
  pesquisa: PesquisaDetalhe | null;
  resumo: DossieDados["agente"]["pesquisas"][number] | null;
  disponivel: boolean;
}) {
  const indicadores = pesquisa?.outcome_indicators ?? null;

  return (
    <Cartao titulo="Jurisprudência">
      {!resumo && (
        <p className={TEXTO_VAZIO}>
          {disponivel
            ? "Nenhuma pesquisa executada. Use “Pesquisar jurisprudência”."
            : "Sem resposta do agente."}
        </p>
      )}

      {resumo?.status === "FAILED" && (
        /* Falha explícita: "não consegui olhar" nunca é apresentado como
         * "não há jurisprudência sobre o caso". */
        <Aviso tom="critico" titulo="A pesquisa não pôde ser concluída">
          {resumo.failure_reason}
        </Aviso>
      )}

      {resumo?.status === "RUNNING" && <Aviso tom="info">Pesquisa em andamento…</Aviso>}

      {resumo?.status === "COMPLETED" && (
        <>
          <p className={EXPLICACAO}>
            Filtrada por jurisdição e matéria antes da busca por similaridade. Cada citação
            aponta um precedente realmente recuperado.
          </p>

          {resumo.corpus_coverage && !resumo.corpus_coverage.complete && (
            <Aviso tom="atencao" titulo="O acervo não está inteiramente indexado">
              {Math.round(resumo.corpus_coverage.ratio * 100)}% dos trechos estão vetorizados —
              a busca alcançou essa fatia.
            </Aviso>
          )}

          <ResumoDoConjunto precedentes={pesquisa?.precedents ?? []} />

          {indicadores && indicadores.sample_size > 0 && (
            <div className={INDICADOR}>
              <div className="flex items-center justify-between gap-[10px]">
                <strong>Desfechos da amostra recuperada</strong>
                {indicadores.small_sample && (
                  <Selo tom="atencao" simbolo="!">
                    amostra pequena
                  </Selo>
                )}
              </div>
              <div className="grid gap-[6px]">
                {indicadores.indicators.map((item) => (
                  <div key={item.label} className="grid grid-cols-[1fr_auto] sm:grid-cols-[130px_1fr_auto] items-center gap-[10px] text-xs text-tinta-2">
                    <span>{item.label.toLowerCase()}</span>
                    <span className="block h-2 bg-papel-3 border border-borda">
                      <i className="block h-full bg-acao" style={{ width: `${Math.round(item.share * 100)}%` }} />
                    </span>
                    <span className="font-codigo tabular-nums">
                      {item.count} de {indicadores.sample_size}
                    </span>
                  </div>
                ))}
              </div>
              <p className="m-0 text-tinta-3 text-xs leading-[1.5]">{indicadores.nature}</p>
            </div>
          )}

          {(pesquisa?.precedents ?? []).length > 0 && (
            <p className="m-0 mb-2 text-tinta-3 text-xs">
              Cada precedente abre a análise completa no clique.
            </p>
          )}
          <ul className={LISTA}>
            {(pesquisa?.precedents ?? []).map((precedente) => (
              <CartaoPrecedente key={precedente.id} precedente={precedente} />
            ))}
          </ul>
        </>
      )}
    </Cartao>
  );
}

/* Primeira frase do resumo — o bastante para escolher qual precedente abrir.
 *
 * Fechado, o cartão precisa dizer mais que o número do processo; aberto, o
 * resumo inteiro aparece logo abaixo. Corta na pontuação e não no caractere:
 * meia frase terminada em "…" o advogado lê como texto truncado por bug. */
function primeiraFrase(texto: string): string {
  const fim = texto.search(/[.!?](\s|$)/);
  return fim === -1 ? texto : texto.slice(0, fim + 1);
}

/* Um precedente por vez, fechado por padrão.
 *
 * `<details>` e não estado em React: são dez na tela, o navegador já sabe abrir
 * e fechar, responde a teclado e a Ctrl+F encontra texto dentro do que está
 * fechado. Um `useState` por cartão daria o mesmo com mais código e sem a
 * busca da página. */
function CartaoPrecedente({ precedente }: { precedente: Precedente }) {
  const analise = precedente.analyses[0];
  const visual = analise ? APLICABILIDADE[analise.applicability] : null;

  return (
    <li className={ITEM}>
      {/* `grid` no <details>: o espaçamento entre resumo, pontos e trechos vinha
        * do gap de ITEM, e eles deixaram de ser filhos dele ao entrar aqui. */}
      <details className="group grid gap-[6px]">
        <summary className="cursor-pointer list-none grid gap-[6px] [&::-webkit-details-marker]:hidden">
          <div className={ITEM_TOPO}>
            <span className="flex items-center gap-[8px] min-w-0">
              <span
                aria-hidden
                className="text-tinta-3 text-[10px] leading-none transition-transform group-open:rotate-90"
              >
                ▶
              </span>
              <strong className="font-codigo tabular-nums">{precedente.process_number}</strong>
            </span>
            {visual && (
              <Selo tom={visual.tom} simbolo={visual.simbolo}>
                {visual.texto}
              </Selo>
            )}
          </div>
          <div className={ORIGEM}>
            {[precedente.court, precedente.judging_body, precedente.document_type, precedente.outcome]
              .filter(Boolean)
              .join(" · ")}
            {precedente.decided_at
              ? ` · ${new Date(precedente.decided_at).toLocaleDateString("pt-BR")}`
              : ""}
          </div>
          {/* Some ao abrir: repetida acima do resumo inteiro, viraria eco. */}
          {analise && (
            <p className="m-0 text-tinta-2 text-sm leading-[1.5] group-open:hidden">
              {primeiraFrase(analise.summary)}
            </p>
          )}
        </summary>

      {analise ? (
        <>
          <p className={RAZAO}>{analise.summary}</p>
          {analise.favorable_points.length > 0 && (
            <ul className={PONTOS}>
              {analise.favorable_points.map((ponto, i) => (
                <li key={i}>
                  <span aria-hidden className="text-ok font-bold mr-[6px]">
                    ✓
                  </span>{" "}
                  {ponto}
                </li>
              ))}
            </ul>
          )}
          {analise.unfavorable_points.length > 0 && (
            <ul className={PONTOS}>
              {analise.unfavorable_points.map((ponto, i) => (
                <li key={i}>
                  <span aria-hidden className="text-atencao font-bold mr-[6px]">
                    !
                  </span>{" "}
                  {ponto}
                </li>
              ))}
            </ul>
          )}
          {analise.cited_excerpts.map((trecho, i) => (
            <blockquote key={i} className={TRECHO}>
              {trecho}
            </blockquote>
          ))}
        </>
      ) : (
        <p className={RAZAO}>{precedente.excerpt.slice(0, 320)}…</p>
      )}

      {precedente.rank_reason && (
        <div className={ORIGEM}>por que apareceu: {precedente.rank_reason}</div>
      )}
      </details>
    </li>
  );
}

/* ------------------------------------------------------------------ petição */

/* Rótulo humano para o código de bloqueio do readiness (`§21`). O código é estável e
 * serve à máquina; o advogado precisa da frase. Código sem tradução aparece como está —
 * melhor um código estranho na tela do que esconder que ele existe. */
const MOTIVO_READINESS: Record<string, string> = {
  CASE_NOT_CLASSIFIED: "o caso ainda não foi classificado",
  PARTIES_MISSING: "o caso não tem partes cadastradas",
  RESEARCH_MISSING: "sem pesquisa de jurisprudência concluída",
  STRATEGY_NOT_APPROVED: "gerada sem estratégia aprovada",
  CONTRADICTION_OPEN_MINOR: "há contradição de baixa relevância em aberto",
  FACT_MISSING: "nenhum documento entregou este dado",
  // Faltava no mapa, e é o mais frequente desde que a entrevista alimenta o caso:
  // o cliente contou e nenhum documento confirmou.
  FACT_ONLY_ALLEGED: "só o relato do cliente sustenta; falta o documento",
  FACT_UNUSABLE: "fato não confirmado o bastante para sustentar a peça",
  FACT_UNCONFIRMED: "fato ainda não conferido por pessoa",
  FACT_ABSENT: "fato recomendado ausente",
  PARTY_FIELD_MISSING: "falta um dado da parte",
  CHECKLIST_BLOCKING: "documento indispensável do checklist não entregue",
  CONTRADICTION_OPEN: "contradição relevante em aberto",
  SECTION_SKIPPED: "seção não redigida",
  SECTION_SKIPPED_NO_PROVIDER: "seção não redigida: modelo indisponível",
};

function motivoLegivel(codigo: string): string {
  const [chave, complemento] = codigo.split(":");
  const texto = MOTIVO_READINESS[chave] ?? chave;
  return complemento ? `${texto} (${complemento})` : texto;
}

/* A barra da redação em curso.
 *
 * Anda por etapa MEDIDA (seção redigida, revisão), e não por tempo. Por isso ela para
 * quando o agente para — que é exatamente a informação que o advogado precisa ter.
 *
 * O teto de 92% é deliberado: seção com subtítulos vira mais de uma chamada de modelo, e a
 * contagem esperada é um piso. Deixar a barra encostar em 100% antes de a peça existir
 * recriaria, em forma de desenho, o mesmo "pronto" falso que ela veio substituir. */
function BarraDeRedacao({ passos, esperadas }: { passos: number; esperadas: number }) {
  const proporcao = Math.min(0.92, esperadas > 0 ? passos / esperadas : 0);
  const preparando = passos === 0;

  return (
    <div className={INDICADOR} aria-live="polite">
      <div className={ITEM_TOPO}>
        <strong>
          <span aria-hidden className="text-acao font-bold mr-[6px]">
            →
          </span>
          {preparando ? "Preparando a petição" : "Redigindo a petição"}
        </strong>
        <span className={VALOR}>
          {preparando ? "Classificando e pesquisando…" : `${passos} de ~${esperadas} etapas`}
        </span>
      </div>
      <div
        className="h-[6px] rounded-pill bg-papel-3 overflow-hidden"
        role="progressbar"
        aria-valuemin={0}
        aria-valuemax={esperadas}
        /* Subtítulos podem gerar mais passos que o piso estimado. O texto pode mostrar
         * isso, mas ARIA não pode anunciar um valor maior que o seu próprio máximo. */
        aria-valuenow={Math.min(passos, esperadas)}
        aria-label="Progresso da redação da petição"
      >
        <i
          className="block h-full rounded-pill transition-[width] duration-500"
          style={{ width: `${Math.round(proporcao * 100)}%`, background: "var(--acao)" }}
        />
      </div>
      <p className={RAZAO}>
        {preparando
          ? "O worker classifica o caso, pesquisa jurisprudência com embeddings e só então redige seção a seção."
          : "Uma chamada de modelo por seção, mais a revisão. A peça aparece aqui sozinha quando terminar — não é preciso recarregar a tela."}
      </p>
    </div>
  );
}

/* O PDF da peça, dentro do dossiê.
 *
 * O arquivo vem por `fetch` e vira `blob:` porque a sessão está num cookie `HttpOnly` de
 * outra origem, e o navegador não o manda numa moldura apontada direto para a API — o
 * visualizador abriria em branco. De quebra, o mesmo objeto serve ao botão de baixar, sem
 * uma segunda viagem ao servidor.
 *
 * `URL.revokeObjectURL` na limpeza não é zelo: sem ele, cada nova versão da peça deixa um
 * PDF inteiro preso na memória da aba, que o advogado mantém aberta o dia todo. */
function VisualizadorPeticao({
  casoId,
  pecaId,
  versao,
}: {
  casoId: string;
  pecaId: string;
  versao: number;
}) {
  const [endereco, setEndereco] = useState<string | null>(null);
  const [falha, setFalha] = useState<string | null>(null);
  const [baixandoDocx, setBaixandoDocx] = useState(false);
  const nome = useMemo(() => `Peticao inicial - v${versao}.pdf`, [versao]);
  const nomeDocx = useMemo(() => `Peticao inicial - v${versao}.docx`, [versao]);
  const ancora = useRef<HTMLAnchorElement | null>(null);

  async function baixarDocx() {
    setBaixandoDocx(true);
    try {
      const arquivo = await baixarArquivoDaPeticao(casoId, pecaId, "docx");
      baixarArquivo(arquivo, nomeDocx);
    } catch (erro) {
      setFalha(erro instanceof Error ? erro.message : "Não foi possível baixar o .docx.");
    } finally {
      setBaixandoDocx(false);
    }
  }

  useEffect(() => {
    let ativo = true;
    let atual: string | null = null;
    setEndereco(null);
    setFalha(null);

    void baixarArquivoDaPeticao(casoId, pecaId, "pdf")
      .then((arquivo) => {
        if (!ativo) return;
        atual = URL.createObjectURL(arquivo);
        setEndereco(atual);
      })
      .catch((erro) =>
        ativo && setFalha(erro instanceof Error ? erro.message : "Não foi possível abrir o PDF."),
      );

    return () => {
      ativo = false;
      if (atual) URL.revokeObjectURL(atual);
    };
  }, [casoId, pecaId]);

  if (falha) {
    return (
      <Aviso tom="atencao" titulo="O PDF não abriu">
        {falha} O texto continua legível em “Ler a minuta”, e o .docx continua disponível.
      </Aviso>
    );
  }

  return (
    <div className="mt-[14px] border border-borda bg-papel-2">
      <div className={`${ITEM_TOPO} p-[10px_12px] border-b border-borda bg-papel sticky top-0 z-10`}>
        <strong className="text-sm">Petição em PDF — versão {versao}</strong>
        <div className="flex gap-2 flex-wrap">
          {/* Baixa o mesmo arquivo que está na tela: o `blob:` já está em memória, e um
            * link para a API abriria outra requisição — e, sendo `inline`, o navegador o
            * exibiria numa aba nova em vez de salvar. */}
          <a ref={ancora} href={endereco ?? undefined} download={nome} className="hidden" />
          <Botao
            variante="secundario"
            pequeno
            disabled={!endereco}
            onClick={() => ancora.current?.click()}
          >
            Baixar PDF
          </Botao>
          <Botao
            variante="secundario"
            pequeno
            disabled={baixandoDocx}
            onClick={() => void baixarDocx()}
          >
            {baixandoDocx ? "Baixando…" : "Baixar .docx"}
          </Botao>
        </div>
      </div>
      {endereco ? (
        <iframe
          src={endereco}
          title={`Petição inicial, versão ${versao}`}
          className="block w-full h-[70vh] min-h-[520px] border-0 bg-papel"
        />
      ) : (
        <p className="p-[16px_18px] text-tinta-3 text-sm">Abrindo o PDF da peça…</p>
      )}
    </div>
  );
}

function PainelPeticao({
  casoId,
  peticao,
  redacao,
  disponivel,
  ocupado,
  onDecidir,
}: {
  casoId: string;
  peticao: Peticao | null;
  /** A geração em curso, quando há uma. É ela que substitui o aviso de "pronta". */
  redacao: { desde: string; esperadas: number; passos: number } | null;
  disponivel: boolean;
  ocupado: boolean;
  onDecidir: (aprovada: boolean, nota?: string) => Promise<void>;
}) {
  const [aberta, setAberta] = useState(false);

  if (!peticao) {
    return (
      <Cartao titulo="Petição inicial">
        {redacao ? (
          <BarraDeRedacao passos={redacao.passos} esperadas={redacao.esperadas} />
        ) : (
          <p className={TEXTO_VAZIO}>
            {disponivel
              ? "Nenhuma minuta gerada. Use “Gerar petição” — ela sai mesmo com prova faltando, marcando o que falta comprovar."
              : "Sem resposta do agente."}
          </p>
        )}
      </Cartao>
    );
  }

  const achados = peticao.review?.findings ?? [];
  const bloqueantes = achados.filter((item) => item.severity === "BLOCKING");
  const avisos = achados.filter((item) => item.severity !== "BLOCKING");
  const retida = peticao.blocking_findings > 0;
  const ressalvas = peticao.readiness?.warnings ?? [];
  /* O que a peça AFIRMA sem ter documento por trás.
   *
   * Isto antes RECUSAVA a geração: o advogado ficava sem minuta nenhuma. Agora a peça
   * sai e a lista vem junto — na tela, aqui, e carimbada dentro do próprio arquivo (ver
   * `aviso_de_pendencia`, no agente), porque o `.docx` circula por e-mail e o aviso
   * precisa acompanhá-lo. */
  const pendencias = peticao.readiness?.pendencias ?? [];

  return (
    <Cartao>
      <div className={ITEM_TOPO}>
        <h2 className={TITULO_CARTAO}>Petição inicial — versão {peticao.version}</h2>
        <Selo
          tom={retida ? "critico" : peticao.status === "APPROVED" ? "ok" : "info"}
          simbolo={retida ? "✕" : peticao.status === "APPROVED" ? "✓" : "→"}
        >
          {retida
            ? "Retida na revisão"
            : peticao.status === "APPROVED"
              ? "Aprovada"
              : peticao.status === "REJECTED"
                ? "Rejeitada"
                : "Aguardando revisão"}
        </Selo>
      </div>

      <p className={EXPLICACAO}>
        Minuta de apoio: exige revisão e assinatura de advogado. Cada afirmação aponta o fato
        que a sustenta, e cada citação foi conferida contra a pesquisa deste caso.
      </p>

      {/* Nova versão sendo redigida sobre uma que já existe: a barra vem primeiro, senão a
        * peça velha na tela se passa pela nova enquanto o modelo ainda escreve. */}
      {redacao && <BarraDeRedacao passos={redacao.passos} esperadas={redacao.esperadas} />}

      {retida && (
        <Aviso tom="critico" titulo={`${bloqueantes.length} achado(s) impedem a entrega`}>
          O sistema não entrega peça que ele mesmo sabe defeituosa. Corrija o caso e gere
          outra versão.
        </Aviso>
      )}

      {/* O CHECKLIST DO QUE FALTA COMPROVAR.
        *
        * Vem ANTES das ressalvas e em tom crítico porque não é a mesma coisa: ressalva é
        * "gerada sem estratégia aprovada"; isto é a peça AFIRMANDO fato que nenhum
        * documento sustenta. Protocolar assim é o risco que a recusa antiga evitava — e,
        * já que ela saiu, o aviso precisa ser impossível de não ver. */}
      {pendencias.length > 0 && (
        <Aviso tom="critico" titulo={`Falta comprovar ${pendencias.length} ponto(s)`}>
          Esta minuta afirma fatos que só o relato do cliente sustenta. Junte os
          documentos e gere nova versão antes de protocolar — o mesmo aviso vai dentro
          do arquivo.
          <ul className={PONTOS}>
            {pendencias.map((codigo) => (
              <li key={codigo}>
                <span aria-hidden className="text-critico font-bold mr-[6px]">
                  ✕
                </span>{" "}
                {motivoLegivel(codigo)}
              </li>
            ))}
          </ul>
        </Aviso>
      )}

      {ressalvas.length > 0 && (
        <div className={INDICADOR}>
          <strong>O que faltava quando a peça foi gerada</strong>
          <ul className={PONTOS}>
            {ressalvas.map((codigo) => (
              <li key={codigo}>
                <span aria-hidden className="text-atencao font-bold mr-[6px]">
                  !
                </span>{" "}
                {motivoLegivel(codigo)}
              </li>
            ))}
          </ul>
        </div>
      )}

      {achados.length > 0 && (
        <ul className={LISTA}>
          {[...bloqueantes, ...avisos].map((achado, indice) => (
            <li key={indice} className={ITEM}>
              <div className={ITEM_TOPO}>
                <strong>{achado.section || "peça"}</strong>
                <Selo
                  tom={achado.severity === "BLOCKING" ? "critico" : "atencao"}
                  simbolo={achado.severity === "BLOCKING" ? "✕" : "!"}
                >
                  {achado.category.toLowerCase().replace(/_/g, " ")}
                </Selo>
              </div>
              <p className={RAZAO}>{achado.message}</p>
              {achado.detail && <blockquote className={TRECHO}>{achado.detail}</blockquote>}
            </li>
          ))}
        </ul>
      )}

      <div className="flex gap-2 flex-wrap">
        {/* Os botões de arquivo saíram daqui e foram para o topo do visualizador: é lá que
          * a peça está, e é lá que se decide levá-la. O que sobra nesta linha é decisão
          * sobre a peça, não sobre o arquivo. */}
        <Botao variante="texto" onClick={() => setAberta((valor) => !valor)}>
          {aberta ? "Ocultar o texto corrido" : "Ler o texto corrido"}
        </Botao>
        {!retida && peticao.status === "IN_REVIEW" && (
          <>
            <Botao variante="primario" disabled={ocupado} onClick={() => void onDecidir(true)}>
              Aprovar
            </Botao>
            <Botao variante="secundario" disabled={ocupado} onClick={() => void onDecidir(false)}>
              Rejeitar
            </Botao>
          </>
        )}
      </div>

      <VisualizadorPeticao casoId={casoId} pecaId={peticao.id} versao={peticao.version} />

      {aberta && (
        <div className={MINUTA}>
          {(peticao.sections ?? []).map((secao) => (
            <article key={secao.code}>
              <h3 className={SECAO_TITULO}>{secao.label.toUpperCase()}</h3>
              {secao.content.split("\n").map((paragrafo, indice) => (
                <p key={indice} className={PARAGRAFO_MINUTA}>
                  {paragrafo}
                </p>
              ))}
              {secao.written_by === "agent" && (
                <div className={ORIGEM}>
                  {secao.supporting_fact_ids.length} fato(s) de suporte
                  {secao.cited_precedent_ids.length
                    ? ` · ${secao.cited_precedent_ids.length} precedente(s) citado(s)`
                    : ""}
                </div>
              )}
            </article>
          ))}
        </div>
      )}
    </Cartao>
  );
}

/* --------------------------------------------------------------- estratégia */

/* As sete naturezas do `§47`, no vocabulário de quem lê a tela. O rótulo existe porque
 * "recomendação" e "fato provado" numa mesma lista, sem distinção, viram a mesma coisa na
 * leitura apressada — e é assim que uma sugestão do sistema vira afirmação na petição. */
const NATUREZA: Record<string, { texto: string; tom: TomSelo }> = {
  PROVEN_FACT: { texto: "fato provado", tom: "ok" },
  ALLEGED_FACT: { texto: "fato alegado", tom: "atencao" },
  HYPOTHESIS: { texto: "hipótese", tom: "info" },
  INFERENCE: { texto: "inferência", tom: "info" },
  RECOMMENDATION: { texto: "recomendação", tom: "neutro" },
  STATISTICAL_PATTERN: { texto: "padrão histórico", tom: "neutro" },
  PRECEDENT: { texto: "precedente", tom: "neutro" },
};

function PainelEstrategia({
  estrategia,
  disponivel,
  gerando,
  ocupado,
  onDecidirEstrategia,
  onDecidirHipotese,
}: {
  estrategia: Estrategia | null;
  disponivel: boolean;
  gerando: boolean;
  ocupado: boolean;
  onDecidirEstrategia: (aprovada: boolean) => Promise<void>;
  onDecidirHipotese: (id: string, aceita: boolean) => Promise<void>;
}) {
  if (gerando && !estrategia) {
    return (
      <Cartao titulo="Estratégia do caso">
        <p className={TEXTO_VAZIO}>Classificando o caso, pesquisando jurisprudência e propondo teses…</p>
      </Cartao>
    );
  }

  if (!estrategia) {
    return (
      <Cartao titulo="Estratégia do caso">
        <p className={TEXTO_VAZIO}>
          {disponivel
            ? "Nenhuma estratégia proposta. Use “Propor estratégia” — as teses saem do que os fatos e os precedentes deste caso sustentam."
            : "Sem resposta do agente."}
        </p>
      </Cartao>
    );
  }

  const aprovada = estrategia.status === "APPROVED";

  return (
    <Cartao>
      <div className={ITEM_TOPO}>
        <h2 className={TITULO_CARTAO}>Estratégia — versão {estrategia.version}</h2>
        <Selo
          tom={aprovada ? "ok" : estrategia.status === "REJECTED" ? "critico" : "info"}
          simbolo={aprovada ? "✓" : estrategia.status === "REJECTED" ? "✕" : "→"}
        >
          {aprovada
            ? "Aprovada"
            : estrategia.status === "REJECTED"
              ? "Rejeitada"
              : "Aguardando sua decisão"}
        </Selo>
      </div>

      {estrategia.summary && <p className={RAZAO}>{estrategia.summary}</p>}

      {gerando && (
        <Aviso tom="info">Nova versão em elaboração — o que aparece abaixo é a versão anterior.</Aviso>
      )}

      {!aprovada && (
        <Aviso tom="atencao" titulo="A petição ainda não usa esta estratégia">
          Enquanto ela não for aprovada, os pedidos da peça saem do playbook do escritório, e
          não das teses abaixo.
        </Aviso>
      )}

      {estrategia.rejected_items.length > 0 && (
        <Aviso
          tom="atencao"
          titulo={`${estrategia.rejected_items.length} item(ns) descartado(s)`}
        >
          O sistema recusou o que não estava ancorado em fato deste caso ou em precedente
          recuperado — tese sem origem não é registrada.
        </Aviso>
      )}

      <ul className={LISTA}>
        {estrategia.hypotheses.map((hipotese) => (
          <CartaoHipotese
            key={hipotese.id}
            hipotese={hipotese}
            ocupado={ocupado}
            onDecidir={(aceita) => onDecidirHipotese(hipotese.id, aceita)}
          />
        ))}
      </ul>

      {estrategia.claims.length > 0 && (
        <>
          <h3 className={SECAO_TITULO}>PEDIDOS SUGERIDOS</h3>
          <ul className={PONTOS}>
            {estrategia.claims.map((ponto, indice) => (
              <li key={indice}>
                <Selo tom={NATUREZA[ponto.nature]?.tom ?? "neutro"}>
                  {NATUREZA[ponto.nature]?.texto ?? ponto.nature.toLowerCase()}
                </Selo>{" "}
                {ponto.statement}
              </li>
            ))}
          </ul>
        </>
      )}

      {estrategia.risks.length > 0 && (
        <>
          <h3 className={SECAO_TITULO}>RISCOS</h3>
          <ul className={PONTOS}>
            {estrategia.risks.map((ponto, indice) => (
              <li key={indice}>
                <span aria-hidden className="text-atencao font-bold mr-[6px]">
                  !
                </span>{" "}
                {ponto.statement}
              </li>
            ))}
          </ul>
        </>
      )}

      {estrategia.pending_points.length > 0 && (
        <>
          <h3 className={SECAO_TITULO}>ANTES DE AJUIZAR</h3>
          <ul className={PONTOS}>
            {estrategia.pending_points.map((ponto, indice) => (
              <li key={indice}>→ {ponto.statement}</li>
            ))}
          </ul>
        </>
      )}

      {estrategia.status === "PROPOSED" && (
        <div className="flex gap-2 flex-wrap">
          <Botao variante="primario" disabled={ocupado} onClick={() => void onDecidirEstrategia(true)}>
            Aprovar estratégia
          </Botao>
          <Botao variante="secundario" disabled={ocupado} onClick={() => void onDecidirEstrategia(false)}>
            Rejeitar
          </Botao>
        </div>
      )}
      {aprovada && estrategia.reviewed_by && (
        <div className={ORIGEM}>aprovada por {estrategia.reviewed_by}</div>
      )}
    </Cartao>
  );
}

function CartaoHipotese({
  hipotese,
  ocupado,
  onDecidir,
}: {
  hipotese: Hipotese;
  ocupado: boolean;
  onDecidir: (aceita: boolean) => Promise<void>;
}) {
  return (
    <li className={ITEM}>
      <div className={ITEM_TOPO}>
        <strong>{hipotese.statement}</strong>
        <Selo
          tom={
            hipotese.status === "ACCEPTED"
              ? "ok"
              : hipotese.status === "DISCARDED"
                ? "neutro"
                : "info"
          }
          simbolo={
            hipotese.status === "ACCEPTED" ? "✓" : hipotese.status === "DISCARDED" ? "•" : "→"
          }
        >
          {hipotese.status === "ACCEPTED"
            ? "Aceita"
            : hipotese.status === "DISCARDED"
              ? "Descartada"
              : "Proposta"}
        </Selo>
      </div>

      {hipotese.rationale && <p className={RAZAO}>{hipotese.rationale}</p>}

      {/* O que sustenta e o que enfraquece, lado a lado: mostrar só o primeiro
          transformaria a estratégia em propaganda da própria tese. */}
      <div className={ORIGEM}>
        {hipotese.supporting_fact_ids.length} fato(s) sustentam
        {hipotese.weakening_fact_ids.length
          ? ` · ${hipotese.weakening_fact_ids.length} enfraquece(m)`
          : ""}
        {hipotese.supporting_precedent_ids.length
          ? ` · ${hipotese.supporting_precedent_ids.length} precedente(s)`
          : ""}
        {hipotese.contradiction_ids.length
          ? ` · apoia-se em ${hipotese.contradiction_ids.length} contradição(ões)`
          : ""}
        {` · força ${Math.round(hipotese.strength * 100)}%`}
      </div>

      {hipotese.missing_requirements.length > 0 && (
        <ul className={PONTOS}>
          {hipotese.missing_requirements.map((item, indice) => (
            <li key={indice}>
              <span aria-hidden className="text-atencao font-bold mr-[6px]">
                !
              </span>{" "}
              falta provar: {item}
            </li>
          ))}
        </ul>
      )}

      {hipotese.status === "PROPOSED" && (
        <div className="flex gap-2 flex-wrap">
          <Botao variante="secundario" pequeno disabled={ocupado} onClick={() => void onDecidir(true)}>
            Aceitar tese
          </Botao>
          <Botao variante="texto" pequeno disabled={ocupado} onClick={() => void onDecidir(false)}>
            Descartar
          </Botao>
        </div>
      )}
    </li>
  );
}

/* ----------------------------------------------------------- contradições */

/* Divergência **não é erro** (`§10`). O cliente diz que foi admitido em fevereiro e a CTPS
 * registra maio: um sistema que "corrige" pelo documento apaga três meses de trabalho sem
 * registro — que costuma ser a tese. Por isso esta tela mostra os dois lados e oferece
 * "manter as duas versões" como decisão de primeira classe. */
const GRAVIDADE: Record<string, { texto: string; tom: TomSelo; simbolo: string }> = {
  CRITICAL: { texto: "crítica", tom: "critico", simbolo: "✕" },
  HIGH: { texto: "alta", tom: "critico", simbolo: "✕" },
  MEDIUM: { texto: "média", tom: "atencao", simbolo: "!" },
  LOW: { texto: "baixa", tom: "neutro", simbolo: "•" },
};

function PainelContradicoes({
  contradicoes,
  ocupado,
  onResolver,
}: {
  contradicoes: Contradicao[];
  ocupado: boolean;
  onResolver: (
    id: string,
    estado: "RESOLVED" | "DISMISSED",
    resolucao: string,
    justificativa: string,
  ) => Promise<void>;
}) {
  const [aberta, setAberta] = useState<string | null>(null);
  const [justificativa, setJustificativa] = useState("");

  const emAberto = contradicoes.filter((item) => item.status === "OPEN");
  if (contradicoes.length === 0) return null;

  return (
    <Cartao>
      <div className={ITEM_TOPO}>
        <h2 className={TITULO_CARTAO}>Divergências ({emAberto.length} em aberto)</h2>
      </div>
      <p className={EXPLICACAO}>
        Duas fontes dizem coisas diferentes sobre o mesmo ponto. Isso não é erro de leitura: a
        divergência entre o que o cliente conta e o que o documento registra pode ser a tese
        do caso. Nenhum dos dois fatos foi apagado.
      </p>

      <ul className={LISTA}>
        {contradicoes.map((item) => {
          const visual = GRAVIDADE[item.severity] ?? GRAVIDADE.LOW;
          const decidida = item.status !== "OPEN";
          return (
            <li key={item.id} className={ITEM}>
              <div className={ITEM_TOPO}>
                <strong>{item.possible_resolution?.split(".")[0] ?? item.type}</strong>
                <Selo
                  tom={decidida ? "ok" : visual.tom}
                  simbolo={decidida ? "✓" : visual.simbolo}
                >
                  {decidida ? "decidida" : `gravidade ${visual.texto}`}
                </Selo>
              </div>

              {item.possible_resolution && (
                <p className={RAZAO}>{item.possible_resolution}</p>
              )}

              <div className={ORIGEM}>
                {item.facts.length} fato(s) envolvidos · relevância {item.legal_relevance.toLowerCase()}
              </div>

              {item.resolutions.length > 0 && (
                <blockquote className={TRECHO}>
                  {item.resolutions[item.resolutions.length - 1].resolution}
                  <br />
                  <span className={ORIGEM}>
                    {item.resolutions[item.resolutions.length - 1].justification} —{" "}
                    {item.resolutions[item.resolutions.length - 1].resolved_by_subject}
                  </span>
                </blockquote>
              )}

              {!decidida && aberta !== item.id && (
                <div className="flex gap-2 flex-wrap">
                  <Botao
                    variante="secundario"
                    pequeno
                    disabled={ocupado}
                    onClick={() => {
                      setAberta(item.id);
                      setJustificativa("");
                    }}
                  >
                    Decidir
                  </Botao>
                </div>
              )}

              {!decidida && aberta === item.id && (
                <div className="grid gap-2 mt-2 pt-[10px] border-t border-borda">
                  <RotuloCampo htmlFor={`just-${item.id}`}>
                    Por que você está decidindo assim?
                  </RotuloCampo>
                  <Campo
                    area
                    id={`just-${item.id}`}
                    rows={2}
                    value={justificativa}
                    onChange={(evento) => setJustificativa(evento.target.value)}
                    placeholder="Ex.: o cliente comprova trabalho desde 02/2022 com recibos."
                  />
                  <div className="flex gap-2 flex-wrap">
                    <Botao
                      variante="primario"
                      pequeno
                      disabled={ocupado || justificativa.trim().length < 3}
                      onClick={() =>
                        void onResolver(
                          item.id,
                          "RESOLVED",
                          "Ambos os fatos permanecem: a divergência é a tese do caso.",
                          justificativa,
                        ).then(() => setAberta(null))
                      }
                    >
                      Manter as duas versões (é a tese)
                    </Botao>
                    <Botao
                      variante="secundario"
                      pequeno
                      disabled={ocupado || justificativa.trim().length < 3}
                      onClick={() =>
                        void onResolver(
                          item.id,
                          "RESOLVED",
                          "Prevalece o que o documento registra.",
                          justificativa,
                        ).then(() => setAberta(null))
                      }
                    >
                      Prevalece o documento
                    </Botao>
                    <Botao
                      variante="texto"
                      pequeno
                      disabled={ocupado || justificativa.trim().length < 3}
                      onClick={() =>
                        void onResolver(
                          item.id,
                          "DISMISSED",
                          "Não era divergência.",
                          justificativa,
                        ).then(() => setAberta(null))
                      }
                    >
                      Não era divergência
                    </Botao>
                  </div>
                </div>
              )}
            </li>
          );
        })}
      </ul>
    </Cartao>
  );
}

/* ------------------------------------------------------------------ entrevista */

/**
 * O atendimento: o arquivo que o advogado usou, o que a IA leu dele, e o que ficou
 * por perguntar.
 *
 * O arquivo original fica sempre a um clique — é dele que sai a fala que sustenta cada
 * fato, e é ele que o advogado quer reler antes de uma audiência. O texto extraído é
 * mostrado sob demanda: são páginas, e carregá-las a cada atualização da tela seria caro.
 */
function PainelEntrevista({
  casoId,
  entrevistas,
  ocupado,
  agenteLigado,
  onAnexar,
  onLer,
}: {
  casoId: string;
  entrevistas: EntrevistaResumo[];
  ocupado: boolean;
  agenteLigado: boolean;
  onAnexar: (arquivo: File, realizadaEm: string, entrevistador: string) => Promise<void>;
  onLer: (entrevistaId: string) => Promise<void>;
}) {
  const [arquivo, setArquivo] = useState<File | null>(null);
  const [arrastando, setArrastando] = useState(false);
  const [realizadaEm, setRealizadaEm] = useState("");
  const [entrevistador, setEntrevistador] = useState("");
  const [lendo, setLendo] = useState<string | null>(null);
  const [texto, setTexto] = useState<Record<string, string>>({});

  async function abrirTexto(entrevistaId: string) {
    if (texto[entrevistaId]) {
      setLendo(lendo === entrevistaId ? null : entrevistaId);
      return;
    }
    const completa = await buscarEntrevista(casoId, entrevistaId);
    setTexto((atual) => ({ ...atual, [entrevistaId]: completa.texto }));
    setLendo(entrevistaId);
  }

  return (
    <Cartao titulo="Entrevista do atendimento">
      <p className={EXPLICACAO}>
        O que o cliente contou. Os fatos que saem daqui entram como <strong>alegados</strong>:
        ninguém conferiu ainda, e a petição não os afirma até um documento confirmar. O
        arquivo original continua disponível para download.
      </p>

      <ul className={LISTA}>
        {entrevistas.map((item) => (
          <li key={item.id} className={ITEM}>
            <div className={ITEM_TOPO}>
              <strong>{item.arquivo}</strong>
              {item.enviada ? (
                <Selo tom="ok" simbolo="✓">
                  {item.fatos_gerados} fato(s) relatado(s)
                </Selo>
              ) : (
                <Selo tom="atencao" simbolo="!">
                  ainda não lida pelo agente
                </Selo>
              )}
            </div>

            <div className={ORIGEM}>
              {item.realizada_em || "data não informada"}
              {item.entrevistador ? ` · ${item.entrevistador}` : ""} · {item.caracteres}{" "}
              caracteres
            </div>

            {item.resumo && <p className={RAZAO}>{item.resumo}</p>}

            {item.perguntas.length > 0 && (
              <>
                <p className={EXPLICACAO}>A confirmar em documento:</p>
                <ul className="list-disc mt-1 pl-[18px] text-tinta-2 text-sm leading-[1.55]">
                  {item.perguntas.map((pergunta) => (
                    <li key={pergunta}>{pergunta}</li>
                  ))}
                </ul>
              </>
            )}

            {lendo === item.id && texto[item.id] && (
              <blockquote className="mt-2 p-[12px_14px] max-h-[420px] overflow-y-auto bg-papel-2 border-l-[3px] border-borda-forte text-tinta-2 text-sm leading-[1.6] whitespace-pre-wrap">
                {texto[item.id]}
              </blockquote>
            )}

            <div className="flex gap-2 flex-wrap">
              <Botao variante="secundario" pequeno onClick={() => void abrirTexto(item.id)}>
                {lendo === item.id ? "Fechar o texto" : "Ler a entrevista"}
              </Botao>
              <LinkBotao
                variante="texto"
                pequeno
                href={urlDaEntrevista(casoId, item.id)}
                download={item.arquivo}
              >
                Baixar o arquivo
              </LinkBotao>
              {!item.enviada && (
                <Botao
                  variante="primario"
                  pequeno
                  disabled={ocupado || !agenteLigado}
                  onClick={() => void onLer(item.id)}
                >
                  Ler no agente
                </Botao>
              )}
            </div>
          </li>
        ))}
      </ul>

      {entrevistas.length === 0 && (
        <p className={TEXTO_VAZIO}>
          Nenhuma entrevista anexada. Envie as anotações do atendimento em .txt, .md, .docx
          ou .pdf.
        </p>
      )}

      <div className="grid gap-[10px] mt-[14px] pt-3 border-t border-borda">
        <label
          className={`${CAMPO_ENTREVISTA} border-2 border-dashed rounded-[6px] p-3 transition-colors ${
            arrastando ? "border-tinta bg-papel-2" : "border-borda"
          }`}
          onDragEnter={(evento) => { evento.preventDefault(); setArrastando(true); }}
          onDragOver={(evento) => { evento.preventDefault(); evento.dataTransfer.dropEffect = "copy"; }}
          onDragLeave={(evento) => {
            if (!evento.currentTarget.contains(evento.relatedTarget as Node | null)) setArrastando(false);
          }}
          onDrop={(evento) => {
            evento.preventDefault();
            setArrastando(false);
            setArquivo(evento.dataTransfer.files?.[0] ?? null);
          }}
        >
          <span>{arrastando ? "Solte a entrevista aqui" : "Arraste a entrevista pronta ou escolha o arquivo"}</span>
          <input
            type="file"
            className="p-[6px] border border-borda rounded-[6px] bg-papel text-tinta"
            onChange={(evento) => setArquivo(evento.target.files?.[0] ?? null)}
          />
          {arquivo && <small className="text-tinta-3">Selecionado: {arquivo.name}</small>}
        </label>
        <label className={CAMPO_ENTREVISTA}>
          <span>Data do atendimento</span>
          <input
            type="text"
            placeholder="12/08/2026"
            className={INPUT_ENTREVISTA}
            value={realizadaEm}
            onChange={(evento) => setRealizadaEm(evento.target.value)}
          />
        </label>
        <label className={CAMPO_ENTREVISTA}>
          <span>Quem atendeu</span>
          <input
            type="text"
            placeholder="Dra. Helena Prado"
            className={INPUT_ENTREVISTA}
            value={entrevistador}
            onChange={(evento) => setEntrevistador(evento.target.value)}
          />
        </label>
        <Botao
          variante="primario"
          pequeno
          disabled={ocupado || arquivo === null}
          onClick={() => {
            if (!arquivo) return;
            void onAnexar(arquivo, realizadaEm, entrevistador).then(() => setArquivo(null));
          }}
        >
          Anexar entrevista
        </Botao>
      </div>
    </Cartao>
  );
}
