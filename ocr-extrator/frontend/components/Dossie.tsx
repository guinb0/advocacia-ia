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

import { useCallback, useEffect, useState } from "react";

import { Aviso, Selo } from "@/components/Basicos";
import {
  gerarContratoDoCaso as solicitarContratoDoCaso,
  requisitosDoContrato,
} from "@/lib/api";
import type { TomSelo } from "@/lib/formato";
import {
  analisarNoAgente,
  anexarEntrevista,
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
  resolverContradicao,
  sincronizarComAgente,
  urlDaEntrevista,
  urlDaPeticao,
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
import estilos from "./Dossie.module.css";

/* Vocabulário de estado do guia: símbolo + palavra + cor, nesta ordem. */
const ETAPA: Record<EstadoEtapa, { simbolo: string; palavra: string; tom: TomSelo }> = {
  pronto: { simbolo: "✓", palavra: "Pronto", tom: "ok" },
  andamento: { simbolo: "→", palavra: "Em andamento", tom: "info" },
  atencao: { simbolo: "!", palavra: "Conferir", tom: "atencao" },
  pendente: { simbolo: "•", palavra: "Falta fazer", tom: "neutro" },
  indisponivel: { simbolo: "✕", palavra: "Sem resposta", tom: "critico" },
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

function valorLegivel(valor: Record<string, unknown>): string {
  return Object.values(valor)
    .filter((item) => item !== null && item !== "")
    .map((item) => (typeof item === "object" ? JSON.stringify(item) : String(item)))
    .join(" · ");
}

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

  /* O agente trabalha em segundo plano: classificar e pesquisar rodam em worker do
   * outro lado. Enquanto houver etapa em andamento, a tela se atualiza sozinha —
   * sem isso o advogado ficaria apertando F5 para saber se terminou. */
  const emAndamento = dados?.etapas.some((etapa) => etapa.estado === "andamento") ?? false;
  useEffect(() => {
    if (!emAndamento && !ocupado) return;
    const timer = setInterval(() => void carregar(), 5000);
    return () => clearInterval(timer);
  }, [emAndamento, ocupado, carregar]);

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
      <div className={estilos.pagina}>
        <button type="button" className="botao botao--secundario botao--pequeno" onClick={onVoltar}>
          ← Voltar
        </button>
        <Aviso tom="critico" titulo="Não foi possível abrir o dossiê">
          {erro}
        </Aviso>
      </div>
    );
  }

  if (!dados) return <div className={estilos.pagina}>Carregando o dossiê…</div>;

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
    <div className={estilos.pagina}>
      <button
        type="button"
        className="botao botao--secundario botao--pequeno"
        onClick={onVoltar}
        style={{ marginBottom: 12 }}
      >
        ← Voltar para a carteira
      </button>

      {(onAbrirPainel || onAbrirJurimetria) && (
        <div className="abas-modulo" style={{ marginBottom: 16 }}>
          {onAbrirPainel && (
            <button type="button" className="aba-modulo" onClick={onAbrirPainel}>
              <span className="aba-modulo__titulo">Painel analítico →</span>
              <span className="aba-modulo__detalhe">
                Tempo de cada etapa e comparação com outros casos
              </span>
            </button>
          )}
          {onAbrirJurimetria && (
            <button type="button" className="aba-modulo" onClick={onAbrirJurimetria}>
              <span className="aba-modulo__titulo">Jurisprudência e jurimetria →</span>
              <span className="aba-modulo__detalhe">
                Como o foro decide casos parecidos com este
              </span>
            </button>
          )}
        </div>
      )}

      <header className={estilos.cabecalho}>
        <div>
          <h1 className={estilos.titulo}>Dossiê de {dados.caso.cliente}</h1>
          <p className={estilos.subtitulo}>
            {dados.checklist.categoria ?? dados.caso.categoria} · caso aberto em{" "}
            {new Date(dados.caso.criado_em).toLocaleDateString("pt-BR")}
            {agente.caso_ref ? ` · agente ${agente.caso_ref}` : ""}
          </p>
        </div>

        <div className={estilos.acoes}>
          <button
            type="button"
            className="botao botao--primario"
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
          </button>
          <button
            type="button"
            className="botao botao--secundario"
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
          </button>
          <button
            type="button"
            className="botao botao--secundario"
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
          </button>
          <button
            type="button"
            className="botao botao--secundario"
            disabled={!agente.ligado || ocupado !== null}
            onClick={() =>
              void executar(
                "estrategia",
                () => gerarEstrategia(casoId),
                "Estratégia enfileirada. As teses aparecem aqui para a sua decisão.",
              )
            }
          >
            {ocupado === "estrategia" ? "Analisando…" : "Propor estratégia"}
          </button>
          <button
            type="button"
            className="botao botao--secundario"
            disabled={!agente.ligado || ocupado !== null}
            onClick={() =>
              void executar(
                "peticao",
                () => gerarPeticao(casoId),
                "Minuta enfileirada. Ela aparece aqui com o relatório da revisão.",
              )
            }
          >
            {ocupado === "peticao" ? "Redigindo…" : "Gerar petição"}
          </button>
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
      <section className={estilos.linha} aria-label="Etapas do caso">
        {dados.etapas.map((etapa) => {
          const visual = ETAPA[etapa.estado];
          return (
            <article key={etapa.codigo} className={`${estilos.etapa} ${estilos[etapa.estado]}`}>
              <div className={estilos.etapaTopo}>
                <span aria-hidden className={estilos.etapaSimbolo}>
                  {visual.simbolo}
                </span>
                <h2 className={estilos.etapaTitulo}>{etapa.titulo}</h2>
              </div>
              <p className={estilos.etapaEstado}>{visual.palavra}</p>
              <p className={estilos.etapaDetalhe}>{etapa.detalhe}</p>
            </article>
          );
        })}
      </section>

      <div className={estilos.grade}>
        {/* ------------------------------------------------ coluna esquerda */}
        <div className={estilos.coluna}>
          <section className="cartao">
            <h2 className="tituloCartao">Ficha do cliente</h2>
            <p className={estilos.explicacao}>
              O nome vem do cadastro; os demais campos foram lidos dos documentos enviados, com
              a origem registrada.
            </p>
            <dl className={estilos.ficha}>
              <div className={estilos.fichaLinha}>
                <dt>Nome</dt>
                <dd>{dados.cliente.nome}</dd>
              </div>
              {dados.cliente.campos.map((campo, indice) => (
                <div
                  key={`${campo.rotulo}-${campo.valor}-${campo.status}-${indice}`}
                  className={estilos.fichaLinha}
                >
                  <dt>{campo.rotulo}</dt>
                  <dd>
                    <span className={estilos.valor}>{campo.valor}</span>
                    {campo.fontes.length > 0 && (
                      <span className={estilos.origem}>
                        origem: {campo.fontes.join(", ").toLowerCase()}
                      </span>
                    )}
                  </dd>
                </div>
              ))}
            </dl>
            {dados.cliente.campos.length === 0 && (
              <p className={estilos.vazio}>
                {agente.disponivel
                  ? "Nenhum documento lido produziu dado pessoal ainda."
                  : "Sem resposta do agente — os dados do cliente não puderam ser lidos."}
              </p>
            )}
          </section>

          <PainelEntrevista
            casoId={casoId}
            entrevistas={dados.entrevistas ?? []}
            ocupado={ocupado !== null}
            agenteLigado={agente.ligado}
            onAnexar={(arquivo, data, quem) =>
              executar(
                "entrevista",
                () => anexarEntrevista(casoId, arquivo, data, quem),
                "Entrevista anexada ao caso e enviada ao agente. Se o agente estiver fora do ar, use “Ler no agente” para reenviar.",
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

          <section className="cartao">
            <h2 className="tituloCartao">Contrato de honorários</h2>
            <p className={estilos.explicacao}>
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
            <div className={estilos.acoes}>
              <button
                type="button"
                className="botao botao--primario"
                disabled={
                  ocupado !== null ||
                  requisitosContrato.length > 0 ||
                  alertasIdentificacaoContrato.length > 0
                }
                onClick={() => void gerarContratoDoCaso(dados)}
              >
                {ocupado === "contrato" ? "Gerando…" : "Gerar contrato do caso"}
              </button>
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
          </section>

          <section className="cartao">
            <h2 className="tituloCartao">Fatos apurados ({agente.fatos.length})</h2>
            <p className={estilos.explicacao}>
              Cada fato aponta o documento de onde saiu. Fato sem origem não é registrado.
            </p>
            <ul className={estilos.lista}>
              {agente.fatos.map((fato) => (
                <li key={fato.id} className={estilos.item}>
                  <div className={estilos.itemTopo}>
                    <strong>{ROTULO_FATO[fato.type] ?? fato.type}</strong>
                    <Selo tom={fato.status === "CONTRADICTED" ? "critico" : "neutro"}>
                      {fato.status === "CONTRADICTED" ? "em contradição" : fato.status.toLowerCase()}
                    </Selo>
                  </div>
                  <div className={estilos.valor}>{valorLegivel(fato.value)}</div>
                  <div className={estilos.origem}>
                    confiança {Math.round((fato.confidence ?? 0) * 100)}%
                    {fato.sources?.length
                      ? ` · ${fato.sources
                          .map((fonte) =>
                            [
                              fonte.source_type?.toLowerCase(),
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
              <p className={estilos.vazio}>
                {agente.disponivel
                  ? "Envie os documentos ao agente para que eles virem fatos."
                  : "Sem resposta do agente."}
              </p>
            )}
          </section>
        </div>

        {/* -------------------------------------------------- coluna direita */}
        <div className={estilos.coluna}>
          <section className="cartao">
            <h2 className="tituloCartao">Leitura jurídica</h2>
            {agente.classificacoes.length === 0 ? (
              <p className={estilos.vazio}>
                {agente.disponivel
                  ? "O caso ainda não foi classificado. Use “Classificar o caso”."
                  : "Sem resposta do agente."}
              </p>
            ) : (
              <ul className={estilos.lista}>
                {agente.classificacoes.map((item) => (
                  <li key={item.code} className={estilos.item}>
                    <div className={estilos.itemTopo}>
                      <strong>{item.label}</strong>
                      <Selo tom="info">{Math.round(item.confidence * 100)}% de confiança</Selo>
                    </div>
                    {item.rationale && <p className={estilos.razao}>{item.rationale}</p>}
                    {item.issues && item.issues.length > 0 && (
                      <div className={estilos.questoes}>
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
          </section>

          <section className="cartao">
            <h2 className="tituloCartao">O que falta ({pendencias.length})</h2>
            <p className={estilos.explicacao}>
              Lista derivada do playbook do escritório — cada item diz qual exigência o
              originou.
            </p>
            <ul className={estilos.lista}>
              {pendencias.map((item) => (
                <li key={item.id} className={estilos.item}>
                  <div className={estilos.itemTopo}>
                    <strong>{item.label}</strong>
                    <Selo
                      tom={item.severity === "BLOCKING" ? "critico" : "atencao"}
                      simbolo={item.severity === "BLOCKING" ? "✕" : "!"}
                    >
                      {item.severity === "BLOCKING" ? "Indispensável" : "Recomendado"}
                    </Selo>
                  </div>
                  <div className={estilos.origem}>
                    {item.playbook_id ? `playbook ${item.playbook_id}` : ""}
                    {item.requirement ? ` · ${item.requirement}` : ""}
                  </div>
                  {item.question && <p className={estilos.razao}>“{item.question}”</p>}
                </li>
              ))}
            </ul>
            {pendencias.length === 0 && (
              <p className={estilos.vazio}>
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
          </section>

          <PainelJurisprudencia
            pesquisa={pesquisa}
            resumo={ultimaPesquisa}
            disponivel={agente.disponivel}
          />

          <PainelEstrategia
            estrategia={agente.estrategia}
            disponivel={agente.disponivel}
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
  );
}

/* ------------------------------------------------------------- precedentes */

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
    <section className="cartao">
      <h2 className="tituloCartao">Jurisprudência</h2>

      {!resumo && (
        <p className={estilos.vazio}>
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
          <p className={estilos.explicacao}>
            Filtrada por jurisdição e matéria antes de comparar o texto do caso com decisões já
            publicadas. Cada citação aponta um precedente realmente recuperado.
          </p>

          {resumo.corpus_coverage && !resumo.corpus_coverage.complete && (
            <Aviso tom="atencao" titulo="Parte do acervo ainda não foi organizada pelo sistema">
              A busca alcançou {Math.round(resumo.corpus_coverage.ratio * 100)}% do acervo —
              o restante ainda está sendo processado e pode trazer precedentes a mais.
            </Aviso>
          )}

          {indicadores && indicadores.sample_size > 0 && (
            <div className={estilos.indicador}>
              <div className={estilos.indicadorTopo}>
                <strong>Desfechos da amostra recuperada</strong>
                {indicadores.small_sample && (
                  <Selo tom="atencao" simbolo="!">
                    amostra pequena
                  </Selo>
                )}
              </div>
              <div className={estilos.barras}>
                {indicadores.indicators.map((item) => (
                  <div key={item.label} className={estilos.barraLinha}>
                    <span>{item.label.toLowerCase()}</span>
                    <span className={estilos.barraTrilho}>
                      <i style={{ width: `${Math.round(item.share * 100)}%` }} />
                    </span>
                    <span className={estilos.barraValor}>
                      {item.count} de {indicadores.sample_size}
                    </span>
                  </div>
                ))}
              </div>
              <p className={estilos.ressalva}>{indicadores.nature}</p>
            </div>
          )}

          <ul className={estilos.lista}>
            {(pesquisa?.precedents ?? []).map((precedente) => (
              <CartaoPrecedente key={precedente.id} precedente={precedente} />
            ))}
          </ul>
        </>
      )}
    </section>
  );
}

function CartaoPrecedente({ precedente }: { precedente: Precedente }) {
  const analise = precedente.analyses[0];
  const visual = analise ? APLICABILIDADE[analise.applicability] : null;

  return (
    <li className={estilos.item}>
      <div className={estilos.itemTopo}>
        <strong className={estilos.processo}>{precedente.process_number}</strong>
        {visual && (
          <Selo tom={visual.tom} simbolo={visual.simbolo}>
            {visual.texto}
          </Selo>
        )}
      </div>
      <div className={estilos.origem}>
        {[precedente.court, precedente.judging_body, precedente.document_type, precedente.outcome]
          .filter(Boolean)
          .join(" · ")}
        {precedente.decided_at
          ? ` · ${new Date(precedente.decided_at).toLocaleDateString("pt-BR")}`
          : ""}
      </div>

      {analise ? (
        <>
          <p className={estilos.razao}>{analise.summary}</p>
          {analise.favorable_points.length > 0 && (
            <ul className={estilos.pontos}>
              {analise.favorable_points.map((ponto, i) => (
                <li key={i} className={estilos.favoravel}>
                  <span aria-hidden>✓</span> {ponto}
                </li>
              ))}
            </ul>
          )}
          {analise.unfavorable_points.length > 0 && (
            <ul className={estilos.pontos}>
              {analise.unfavorable_points.map((ponto, i) => (
                <li key={i} className={estilos.contrario}>
                  <span aria-hidden>!</span> {ponto}
                </li>
              ))}
            </ul>
          )}
          {analise.cited_excerpts.map((trecho, i) => (
            <blockquote key={i} className={estilos.trecho}>
              {trecho}
            </blockquote>
          ))}
        </>
      ) : (
        <p className={estilos.razao}>{precedente.excerpt.slice(0, 320)}…</p>
      )}
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
  FACT_MISSING: "falta o fato",
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

function PainelPeticao({
  casoId,
  peticao,
  disponivel,
  ocupado,
  onDecidir,
}: {
  casoId: string;
  peticao: Peticao | null;
  disponivel: boolean;
  ocupado: boolean;
  onDecidir: (aprovada: boolean, nota?: string) => Promise<void>;
}) {
  const [aberta, setAberta] = useState(false);

  if (!peticao) {
    return (
      <section className="cartao">
        <h2 className="tituloCartao">Petição inicial</h2>
        <p className={estilos.vazio}>
          {disponivel
            ? "Nenhuma minuta gerada. Use “Gerar petição” — ela só sai com o caso classificado e os fatos essenciais confirmados."
            : "Sem resposta do agente."}
        </p>
      </section>
    );
  }

  const achados = peticao.review?.findings ?? [];
  const bloqueantes = achados.filter((item) => item.severity === "BLOCKING");
  const avisos = achados.filter((item) => item.severity !== "BLOCKING");
  const retida = peticao.blocking_findings > 0;
  const ressalvas = peticao.readiness?.warnings ?? [];

  return (
    <section className="cartao">
      <div className={estilos.itemTopo}>
        <h2 className="tituloCartao">Petição inicial — versão {peticao.version}</h2>
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

      <p className={estilos.explicacao}>
        Minuta de apoio: exige revisão e assinatura de advogado. Cada afirmação aponta o fato
        que a sustenta, e cada citação foi conferida contra a pesquisa deste caso.
      </p>

      {retida && (
        <Aviso tom="critico" titulo={`${bloqueantes.length} achado(s) impedem a entrega`}>
          O sistema não entrega peça que ele mesmo sabe defeituosa. Corrija o caso e gere
          outra versão.
        </Aviso>
      )}

      {ressalvas.length > 0 && (
        <div className={estilos.indicador}>
          <strong>O que faltava quando a peça foi gerada</strong>
          <ul className={estilos.pontos}>
            {ressalvas.map((codigo) => (
              <li key={codigo} className={estilos.contrario}>
                <span aria-hidden>!</span> {motivoLegivel(codigo)}
              </li>
            ))}
          </ul>
        </div>
      )}

      {achados.length > 0 && (
        <ul className={estilos.lista}>
          {[...bloqueantes, ...avisos].map((achado, indice) => (
            <li key={indice} className={estilos.item}>
              <div className={estilos.itemTopo}>
                <strong>{achado.section || "peça"}</strong>
                <Selo
                  tom={achado.severity === "BLOCKING" ? "critico" : "atencao"}
                  simbolo={achado.severity === "BLOCKING" ? "✕" : "!"}
                >
                  {achado.category.toLowerCase().replace(/_/g, " ")}
                </Selo>
              </div>
              <p className={estilos.razao}>{achado.message}</p>
              {achado.detail && (
                <blockquote className={estilos.trecho}>{achado.detail}</blockquote>
              )}
            </li>
          ))}
        </ul>
      )}

      <div className={estilos.acoes}>
        <a className="botao botao--secundario" href={urlDaPeticao(casoId, peticao.id)} download>
          Baixar .docx
        </a>
        <button
          type="button"
          className="botao botao--texto"
          onClick={() => setAberta((valor) => !valor)}
        >
          {aberta ? "Ocultar o texto" : "Ler a minuta"}
        </button>
        {!retida && peticao.status === "IN_REVIEW" && (
          <>
            <button
              type="button"
              className="botao botao--primario"
              disabled={ocupado}
              onClick={() => void onDecidir(true)}
            >
              Aprovar
            </button>
            <button
              type="button"
              className="botao botao--secundario"
              disabled={ocupado}
              onClick={() => void onDecidir(false)}
            >
              Rejeitar
            </button>
          </>
        )}
      </div>

      {aberta && (
        <div className={estilos.minuta}>
          {(peticao.sections ?? []).map((secao) => (
            <article key={secao.code}>
              <h3 className={estilos.secaoTitulo}>{secao.label.toUpperCase()}</h3>
              {secao.content.split("\n").map((paragrafo, indice) => (
                <p key={indice} className={estilos.paragrafo}>
                  {paragrafo}
                </p>
              ))}
              {secao.written_by === "agent" && (
                <div className={estilos.origem}>
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
    </section>
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
  ocupado,
  onDecidirEstrategia,
  onDecidirHipotese,
}: {
  estrategia: Estrategia | null;
  disponivel: boolean;
  ocupado: boolean;
  onDecidirEstrategia: (aprovada: boolean) => Promise<void>;
  onDecidirHipotese: (id: string, aceita: boolean) => Promise<void>;
}) {
  if (!estrategia) {
    return (
      <section className="cartao">
        <h2 className="tituloCartao">Estratégia do caso</h2>
        <p className={estilos.vazio}>
          {disponivel
            ? "Nenhuma estratégia proposta. Use “Propor estratégia” — as teses saem do que os fatos e os precedentes deste caso sustentam."
            : "Sem resposta do agente."}
        </p>
      </section>
    );
  }

  const aprovada = estrategia.status === "APPROVED";

  return (
    <section className="cartao">
      <div className={estilos.itemTopo}>
        <h2 className="tituloCartao">Estratégia — versão {estrategia.version}</h2>
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

      {estrategia.summary && <p className={estilos.razao}>{estrategia.summary}</p>}

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

      <ul className={estilos.lista}>
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
          <h3 className={estilos.secaoTitulo}>PEDIDOS SUGERIDOS</h3>
          <ul className={estilos.pontos}>
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
          <h3 className={estilos.secaoTitulo}>RISCOS</h3>
          <ul className={estilos.pontos}>
            {estrategia.risks.map((ponto, indice) => (
              <li key={indice} className={estilos.contrario}>
                <span aria-hidden>!</span> {ponto.statement}
              </li>
            ))}
          </ul>
        </>
      )}

      {estrategia.pending_points.length > 0 && (
        <>
          <h3 className={estilos.secaoTitulo}>ANTES DE AJUIZAR</h3>
          <ul className={estilos.pontos}>
            {estrategia.pending_points.map((ponto, indice) => (
              <li key={indice}>→ {ponto.statement}</li>
            ))}
          </ul>
        </>
      )}

      {estrategia.status === "PROPOSED" && (
        <div className={estilos.acoes}>
          <button
            type="button"
            className="botao botao--primario"
            disabled={ocupado}
            onClick={() => void onDecidirEstrategia(true)}
          >
            Aprovar estratégia
          </button>
          <button
            type="button"
            className="botao botao--secundario"
            disabled={ocupado}
            onClick={() => void onDecidirEstrategia(false)}
          >
            Rejeitar
          </button>
        </div>
      )}
      {aprovada && estrategia.reviewed_by && (
        <div className={estilos.origem}>aprovada por {estrategia.reviewed_by}</div>
      )}
    </section>
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
    <li className={estilos.item}>
      <div className={estilos.itemTopo}>
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

      {hipotese.rationale && <p className={estilos.razao}>{hipotese.rationale}</p>}

      {/* O que sustenta e o que enfraquece, lado a lado: mostrar só o primeiro
          transformaria a estratégia em propaganda da própria tese. */}
      <div className={estilos.origem}>
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
        <ul className={estilos.pontos}>
          {hipotese.missing_requirements.map((item, indice) => (
            <li key={indice} className={estilos.contrario}>
              <span aria-hidden>!</span> falta provar: {item}
            </li>
          ))}
        </ul>
      )}

      {hipotese.status === "PROPOSED" && (
        <div className={estilos.acoes}>
          <button
            type="button"
            className="botao botao--secundario botao--pequeno"
            disabled={ocupado}
            onClick={() => void onDecidir(true)}
          >
            Aceitar tese
          </button>
          <button
            type="button"
            className="botao botao--texto botao--pequeno"
            disabled={ocupado}
            onClick={() => void onDecidir(false)}
          >
            Descartar
          </button>
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
    <section className="cartao">
      <div className={estilos.itemTopo}>
        <h2 className="tituloCartao">Divergências ({emAberto.length} em aberto)</h2>
      </div>
      <p className={estilos.explicacao}>
        Duas fontes dizem coisas diferentes sobre o mesmo ponto. Isso não é erro de leitura: a
        divergência entre o que o cliente conta e o que o documento registra pode ser a tese
        do caso. Nenhum dos dois fatos foi apagado.
      </p>

      <ul className={estilos.lista}>
        {contradicoes.map((item) => {
          const visual = GRAVIDADE[item.severity] ?? GRAVIDADE.LOW;
          const decidida = item.status !== "OPEN";
          return (
            <li key={item.id} className={estilos.item}>
              <div className={estilos.itemTopo}>
                <strong>{item.possible_resolution?.split(".")[0] ?? item.type}</strong>
                <Selo
                  tom={decidida ? "ok" : visual.tom}
                  simbolo={decidida ? "✓" : visual.simbolo}
                >
                  {decidida ? "decidida" : `gravidade ${visual.texto}`}
                </Selo>
              </div>

              {item.possible_resolution && (
                <p className={estilos.razao}>{item.possible_resolution}</p>
              )}

              <div className={estilos.origem}>
                {item.facts.length} fato(s) envolvidos · relevância {item.legal_relevance.toLowerCase()}
              </div>

              {item.resolutions.length > 0 && (
                <blockquote className={estilos.trecho}>
                  {item.resolutions[item.resolutions.length - 1].resolution}
                  <br />
                  <span className={estilos.origem}>
                    {item.resolutions[item.resolutions.length - 1].justification} —{" "}
                    {item.resolutions[item.resolutions.length - 1].resolved_by_subject}
                  </span>
                </blockquote>
              )}

              {!decidida && aberta !== item.id && (
                <div className={estilos.acoes}>
                  <button
                    type="button"
                    className="botao botao--secundario botao--pequeno"
                    disabled={ocupado}
                    onClick={() => {
                      setAberta(item.id);
                      setJustificativa("");
                    }}
                  >
                    Decidir
                  </button>
                </div>
              )}

              {!decidida && aberta === item.id && (
                <div className={estilos.decisao}>
                  <label className="rotuloCampo" htmlFor={`just-${item.id}`}>
                    Por que você está decidindo assim?
                  </label>
                  <textarea
                    id={`just-${item.id}`}
                    className="campo campo--area"
                    rows={2}
                    value={justificativa}
                    onChange={(evento) => setJustificativa(evento.target.value)}
                    placeholder="Ex.: o cliente comprova trabalho desde 02/2022 com recibos."
                  />
                  <div className={estilos.acoes}>
                    <button
                      type="button"
                      className="botao botao--primario botao--pequeno"
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
                    </button>
                    <button
                      type="button"
                      className="botao botao--secundario botao--pequeno"
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
                    </button>
                    <button
                      type="button"
                      className="botao botao--texto botao--pequeno"
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
                    </button>
                  </div>
                </div>
              )}
            </li>
          );
        })}
      </ul>
    </section>
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
    <section className="cartao">
      <h2 className="tituloCartao">Entrevista do atendimento</h2>
      <p className={estilos.explicacao}>
        O que o cliente contou. Os fatos que saem daqui entram como <strong>alegados</strong>:
        ninguém conferiu ainda, e a petição não os afirma até um documento confirmar. O
        arquivo original continua disponível para download.
      </p>

      <ul className={estilos.lista}>
        {entrevistas.map((item) => (
          <li key={item.id} className={estilos.item}>
            <div className={estilos.itemTopo}>
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

            <div className={estilos.origem}>
              {item.realizada_em || "data não informada"}
              {item.entrevistador ? ` · ${item.entrevistador}` : ""} · {item.caracteres}{" "}
              caracteres
            </div>

            {item.resumo && <p className={estilos.razao}>{item.resumo}</p>}

            {item.perguntas.length > 0 && (
              <>
                <p className={estilos.explicacao}>A confirmar em documento:</p>
                <ul className={estilos.listaSimples}>
                  {item.perguntas.map((pergunta) => (
                    <li key={pergunta}>{pergunta}</li>
                  ))}
                </ul>
              </>
            )}

            {lendo === item.id && texto[item.id] && (
              <blockquote className={estilos.transcricao}>{texto[item.id]}</blockquote>
            )}

            <div className={estilos.acoes}>
              <button
                type="button"
                className="botao botao--secundario botao--pequeno"
                onClick={() => void abrirTexto(item.id)}
              >
                {lendo === item.id ? "Fechar o texto" : "Ler a entrevista"}
              </button>
              <a
                className="botao botao--texto botao--pequeno"
                href={urlDaEntrevista(casoId, item.id)}
                download={item.arquivo}
              >
                Baixar o arquivo
              </a>
              {!item.enviada && (
                <button
                  type="button"
                  className="botao botao--primario botao--pequeno"
                  disabled={ocupado || !agenteLigado}
                  onClick={() => void onLer(item.id)}
                >
                  Ler no agente
                </button>
              )}
            </div>
          </li>
        ))}
      </ul>

      {entrevistas.length === 0 && (
        <p className={estilos.vazio}>
          Nenhuma entrevista anexada. Envie as anotações do atendimento em .txt, .md, .docx
          ou .pdf.
        </p>
      )}

      <div className={estilos.formulario}>
        <label className={estilos.campo}>
          <span>Arquivo da entrevista</span>
          <input
            type="file"
            accept=".txt,.md,.docx,.pdf"
            onChange={(evento) => setArquivo(evento.target.files?.[0] ?? null)}
          />
        </label>
        <label className={estilos.campo}>
          <span>Data do atendimento</span>
          <input
            type="text"
            placeholder="12/08/2026"
            value={realizadaEm}
            onChange={(evento) => setRealizadaEm(evento.target.value)}
          />
        </label>
        <label className={estilos.campo}>
          <span>Quem atendeu</span>
          <input
            type="text"
            placeholder="Dra. Helena Prado"
            value={entrevistador}
            onChange={(evento) => setEntrevistador(evento.target.value)}
          />
        </label>
        <button
          type="button"
          className="botao botao--primario botao--pequeno"
          disabled={ocupado || arquivo === null}
          onClick={() => {
            if (!arquivo) return;
            void onAnexar(arquivo, realizadaEm, entrevistador).then(() => setArquivo(null));
          }}
        >
          Anexar entrevista
        </button>
      </div>
    </section>
  );
}