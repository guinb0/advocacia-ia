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

import FluxoPeticao, { type ControlesGeracaoPeticao } from "@/components/admin/FluxoPeticao";
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
  lerEntrevistaNoAgente,
  pesquisarNoAgente,
  progressoPeticao,
  resolverContradicao,
  salvarRascunhoPeticao,
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
const DOSSIE_SHELL = "flex w-full min-w-0 max-w-full flex-col gap-5";
const TITULO_CARTAO = "mb-1 min-w-0 truncate text-tinta font-titulo text-lg font-semibold leading-[1.25]";
const ITEM_TOPO = "flex min-w-0 items-center justify-between gap-[10px] flex-wrap";
const ITEM = "min-w-0 overflow-hidden border border-borda bg-papel p-[12px_14px] grid gap-[6px]";
const LISTA = "list-none m-0 p-0 grid min-w-0 gap-3";
const EXPLICACAO = "-mt-1 mb-3 text-tinta-3 text-sm leading-[1.5] max-w-[62ch]";
const TEXTO_VAZIO = "mt-[6px] text-tinta-3 text-sm";
const ORIGEM = "text-tinta-3 text-xs";
const RAZAO = "mt-[2px] text-tinta-2 text-sm leading-[1.55]";
const VALOR = "font-codigo tabular-nums text-sm text-tinta";
const TRECHO =
  "mt-[6px] p-[8px_12px] bg-papel-2 border-l-[3px] border-borda-forte text-tinta-2 text-sm leading-[1.55] [overflow-wrap:anywhere]";
const PONTOS = "mt-[2px] p-0 list-none grid min-w-0 gap-1 text-sm leading-[1.5]";
const SECAO_TITULO = "mt-[18px] mb-[6px] font-ui text-sm font-bold tracking-[0.02em] text-tinta first:mt-0";
const FICHA_LINHA =
  "grid grid-cols-1 sm:grid-cols-[150px_1fr] gap-x-3 gap-y-[2px] bg-papel p-[9px_12px]";
const INDICADOR = "min-w-0 overflow-hidden border border-borda bg-papel-2 p-[12px_14px] mb-[14px] grid gap-2";
const MINUTA = "mt-[14px] p-[16px_18px] bg-papel-2 border border-borda max-h-[520px] overflow-auto";
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
  const [geracaoPeticao, setGeracaoPeticao] = useState<ControlesGeracaoPeticao | null>(null);
  const [aviso, setAviso] = useState<string | null>(null);
  const [camposFaltandoContrato, setCamposFaltandoContrato] = useState<string[] | null>(null);

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

  const ultimaPesquisa = dados?.agente.pesquisas[0] ?? null;

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
      <div className={DOSSIE_SHELL}>
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
      <div className="rounded-cartao border border-borda bg-papel px-5 py-10 text-center text-tinta-3 shadow-cartao">
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
    <div className={DOSSIE_SHELL}>
      <header className="overflow-hidden rounded-cartao border border-borda-forte bg-papel shadow-cartao">
        <div className="flex min-w-0 flex-col gap-4 border-b border-borda bg-papel-2 px-4 py-4 sm:px-5 lg:flex-row lg:items-end lg:justify-between">
          <div className="min-w-0">
            <Botao variante="texto" pequeno onClick={onVoltar}>
              ← Carteira
            </Botao>
            <span className="mt-3 block text-[11px] font-bold uppercase tracking-[0.12em] text-tinta-3">
              Dossiê do caso
            </span>
            <h1 className="mt-1 truncate text-xl font-semibold tracking-[-0.01em] text-tinta" title={dados.caso.cliente}>
              {dados.caso.cliente}
            </h1>
            <p className="mt-1 truncate text-sm text-tinta-3" title={dados.checklist.categoria ?? dados.caso.categoria}>
              {dados.checklist.categoria ?? dados.caso.categoria} · aberto em{" "}
              {new Date(dados.caso.criado_em).toLocaleDateString("pt-BR")}
            </p>
          </div>

          <div className="flex min-w-0 flex-wrap gap-2">
            {onAbrirPainel && (
              <Botao variante="secundario" pequeno onClick={onAbrirPainel}>
                Painel
              </Botao>
            )}
            {onAbrirJurimetria && (
              <Botao variante="secundario" pequeno onClick={onAbrirJurimetria}>
                Jurimetria
              </Botao>
            )}
            <Botao
              variante="primario"
              disabled={
                !geracaoPeticao?.podeGerar || geracaoPeticao?.ocupado || ocupado !== null
              }
              onClick={() => geracaoPeticao?.gerar()}
            >
              <span className="min-w-0 truncate">{geracaoPeticao?.rotulo ?? "Gerar análise e petição"}</span>
            </Botao>
          </div>
        </div>
      </header>

      {aviso && <Aviso tom="ok">{aviso}</Aviso>}
      {erro && (
        <Aviso tom="critico" titulo="A última ação falhou">
          {erro}
        </Aviso>
      )}

      <div className="grid min-w-0 grid-cols-1 items-start gap-[18px] xl:grid-cols-[minmax(260px,320px)_minmax(0,1fr)]">
        <aside className="grid min-w-0 content-start gap-[18px] order-2 xl:order-1">
          <Cartao titulo="Documentos do checklist">
            <p className={EXPLICACAO}>
              {dados.checklist.progresso?.obrigatorios_entregues ?? 0} de{" "}
              {dados.checklist.progresso?.obrigatorios_total ?? "?"} itens obrigatórios entregues.
            </p>
            <ul className="m-0 p-0 list-none grid gap-1 text-sm text-tinta-2">
              {(dados.checklist.itens ?? [])
                .filter((item) => item.obrigatorio && item.status !== "entregue")
                .slice(0, 6)
                .map((item) => (
                  <li key={item.codigo} className="truncate" title={item.rotulo || item.nome || item.codigo}>
                    • {item.rotulo || item.nome || item.codigo}
                  </li>
                ))}
            </ul>
            {(dados.checklist.itens ?? []).filter(
              (item) => item.obrigatorio && item.status !== "entregue",
            ).length === 0 && (
              <p className={TEXTO_VAZIO}>Todos os obrigatórios entregues.</p>
            )}
          </Cartao>

          <PainelEntrevista
            casoId={casoId}
            entrevistas={dados.entrevistas ?? []}
          />
        </aside>

        <div className="grid min-w-0 content-start gap-[18px] order-1 xl:order-2">
          <FluxoPeticao
            casoId={casoId}
            temEntrevista={(dados.entrevistas ?? []).some((e) => (e.caracteres ?? 0) > 0)}
            onControlesGeracao={setGeracaoPeticao}
          />
        </div>
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
        <strong className="min-w-0 truncate">Resumo do conjunto</strong>
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
        <p className="m-0 text-tinta-2 text-xs leading-[1.6] [overflow-wrap:anywhere]">
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
                    <strong className="min-w-0 truncate" title={a.informacao}>{a.informacao}</strong>
                    {a.contradiz && (
                      <Selo tom="critico" simbolo="!">
                        contradiz a entrevista
                      </Selo>
                    )}
                  </div>
                  <div className={`${ORIGEM} truncate`} title={a.documento}>{a.documento}</div>
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
              <div className="grid min-w-0 gap-[6px]">
                {indicadores.indicators.map((item) => (
                  <div key={item.label} className="grid min-w-0 grid-cols-[minmax(0,1fr)_auto] items-center gap-[10px] text-xs text-tinta-2 sm:grid-cols-[130px_minmax(0,1fr)_auto]">
                    <span className="truncate" title={item.label.toLowerCase()}>{item.label.toLowerCase()}</span>
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
      <details className="group grid min-w-0 gap-[6px]">
        <summary className="grid min-w-0 cursor-pointer list-none gap-[6px] [&::-webkit-details-marker]:hidden">
          <div className={ITEM_TOPO}>
            <span className="flex items-center gap-[8px] min-w-0">
              <span
                aria-hidden
                className="text-tinta-3 text-[10px] leading-none transition-transform group-open:rotate-90"
              >
                ▶
              </span>
              <strong className="min-w-0 truncate font-codigo tabular-nums" title={precedente.process_number}>
                {precedente.process_number}
              </strong>
            </span>
            {visual && (
              <Selo tom={visual.tom} simbolo={visual.simbolo}>
                {visual.texto}
              </Selo>
            )}
          </div>
          <div className={`${ORIGEM} truncate`} title={[precedente.court, precedente.judging_body, precedente.document_type, precedente.outcome]
              .filter(Boolean)
              .join(" · ")}>
            {[precedente.court, precedente.judging_body, precedente.document_type, precedente.outcome]
              .filter(Boolean)
              .join(" · ")}
            {precedente.decided_at
              ? ` · ${new Date(precedente.decided_at).toLocaleDateString("pt-BR")}`
              : ""}
          </div>
          {/* Some ao abrir: repetida acima do resumo inteiro, viraria eco. */}
          {analise && (
            <p className="m-0 line-clamp-2 text-sm leading-[1.5] text-tinta-2 group-open:hidden" title={primeiraFrase(analise.summary)}>
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
        <p className={`${RAZAO} line-clamp-3`} title={precedente.excerpt}>{precedente.excerpt.slice(0, 320)}…</p>
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
    <div className="mt-[14px] max-w-full overflow-hidden border border-borda bg-papel-2">
      <div className={`${ITEM_TOPO} p-[10px_12px] border-b border-borda bg-papel sticky top-0 z-10`}>
        <strong className="min-w-0 truncate text-sm">Petição em PDF — versão {versao}</strong>
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
  const [edicao, setEdicao] = useState<Record<string, string>>({});
  const [salvando, setSalvando] = useState(false);
  const [erroEdicao, setErroEdicao] = useState<string | null>(null);
  const [pdfKey, setPdfKey] = useState(0);

  useEffect(() => {
    setEdicao(
      Object.fromEntries((peticao?.sections ?? []).map((secao) => [secao.code, secao.content])),
    );
  }, [peticao?.id, peticao?.sections]);

  async function salvarEdicao(baixarPdf = false) {
    if (!peticao) return;
    setSalvando(true);
    setErroEdicao(null);
    try {
      const secoes = (peticao.sections ?? []).map((secao) => ({
        code: secao.code,
        content: edicao[secao.code] ?? secao.content,
      }));
      await salvarRascunhoPeticao(casoId, peticao.id, secoes);
      setPdfKey((valor) => valor + 1);
      if (baixarPdf) {
        const arquivo = await baixarArquivoDaPeticao(casoId, peticao.id, "pdf");
        baixarArquivo(arquivo, `Peticao inicial editada - v${peticao.version}.pdf`);
      }
    } catch (erro) {
      setErroEdicao(erro instanceof Error ? erro.message : "Não foi possível salvar a edição.");
    } finally {
      setSalvando(false);
    }
  }

  if (!peticao) {
    return (
      <Cartao titulo="Petição inicial">
        {redacao ? (
          <BarraDeRedacao passos={redacao.passos} esperadas={redacao.esperadas} />
        ) : (
          <p className={TEXTO_VAZIO}>
            {disponivel
              ? "Nenhuma minuta gerada. Use o fluxo acima — análise da entrevista, escolha da estratégia e redação com os modelos treinados."
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
                <strong className="min-w-0 truncate" title={achado.section || "peça"}>
                  {achado.section || "peça"}
                </strong>
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
          {aberta ? "Fechar editor" : "Editar a petição"}
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

      {aberta && (
        <div className="grid min-w-0 gap-4 border border-borda bg-papel-2 p-4">
          <p className="m-0 text-sm text-tinta-3">
            Edite as seções abaixo. A versão gerada pela IA permanece guardada para auditoria.
          </p>
          {(peticao!.sections ?? []).map((secao) => (
            <label key={secao.code} className="grid min-w-0 gap-2">
              <strong className="truncate text-sm" title={secao.label}>{secao.label}</strong>
              <textarea
                className="min-h-48 w-full min-w-0 resize-y border border-borda bg-papel p-3 text-sm leading-relaxed text-tinta"
                value={edicao[secao.code] ?? secao.content}
                onChange={(evento) =>
                  setEdicao((atual) => ({ ...atual, [secao.code]: evento.target.value }))
                }
              />
            </label>
          ))}
          {erroEdicao && <Aviso tom="critico">{erroEdicao}</Aviso>}
          <div className="flex flex-wrap gap-2">
            <Botao variante="secundario" disabled={salvando} onClick={() => void salvarEdicao()}>
              {salvando ? "Salvando…" : "Salvar rascunho"}
            </Botao>
            <Botao variante="primario" disabled={salvando} onClick={() => void salvarEdicao(true)}>
              {salvando ? "Preparando PDF…" : "Salvar e baixar PDF"}
            </Botao>
          </div>
        </div>
      )}

      <VisualizadorPeticao
        key={`${peticao.id}-${pdfKey}`}
        casoId={casoId}
        pecaId={peticao.id}
        versao={peticao.version}
      />

      {false && aberta && peticao && (
        <div className={MINUTA}>
          {(peticao!.sections ?? []).map((secao) => (
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
        <strong className="min-w-0 truncate" title={hipotese.statement}>{hipotese.statement}</strong>
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
      <div className={`${ORIGEM} [overflow-wrap:anywhere]`}>
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
                <strong className="min-w-0 truncate" title={item.possible_resolution?.split(".")[0] ?? item.type}>
                  {item.possible_resolution?.split(".")[0] ?? item.type}
                </strong>
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
}: {
  casoId: string;
  entrevistas: EntrevistaResumo[];
}) {
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
              <strong className="min-w-0 truncate" title={item.arquivo}>{item.arquivo}</strong>
              {item.caracteres > 0 ? (
                <Selo tom="ok" simbolo="✓">
                  transcrita
                </Selo>
              ) : (
                <Selo tom="atencao" simbolo="!">
                  sem texto
                </Selo>
              )}
            </div>

            <div className={`${ORIGEM} truncate`} title={`${item.realizada_em || "data não informada"}${item.entrevistador ? ` · ${item.entrevistador}` : ""} · ${item.caracteres} caracteres`}>
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
                    <li key={pergunta} className="[overflow-wrap:anywhere]">{pergunta}</li>
                  ))}
                </ul>
              </>
            )}

            {lendo === item.id && texto[item.id] && (
              <blockquote className="mt-2 max-h-[420px] overflow-auto whitespace-pre-wrap border-l-[3px] border-borda-forte bg-papel-2 p-[12px_14px] text-sm leading-[1.6] text-tinta-2 [overflow-wrap:anywhere]">
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
            </div>
          </li>
        ))}
      </ul>

      {entrevistas.length === 0 && (
        <p className={TEXTO_VAZIO}>Nenhuma entrevista registrada neste caso.</p>
      )}
    </Cartao>
  );
}
