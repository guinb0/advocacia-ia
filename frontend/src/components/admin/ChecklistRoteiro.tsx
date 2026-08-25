"use client";

/* O checklist do roteiro, como o secretário confere uma entrevista.
 *
 * DUAS ORIGENS, E A DIFERENÇA IMPORTA
 *
 * Metade das linhas sai do REGISTRO — assinatura enviada, avaliação marcada,
 * documento recebido. É fato gravado, custa uma consulta e abre junto com a tela.
 *
 * A outra metade sai da LEITURA DA TRANSCRIÇÃO pelo modelo: abertura, perguntas,
 * encerramento. Custa uma ida ao DeepSeek, erra (a transcrição vem de
 * reconhecimento de voz) e só roda quando pedida. Antes de rodar, essas linhas
 * aparecem como "não conferido" em vez de sumirem — a lista precisa mostrar o que
 * FALTA CONFERIR, senão um checklist pela metade parece um checklist completo.
 *
 * Por isso cada seção diz de onde veio, e "não conferido" não conta como pendência
 * no progresso: acusar falta de trabalho onde houve falta de conferência seria
 * exatamente o erro que o módulo de auditoria evita (ver `app/auditoria.py`).
 *
 * NINGUÉM MARCA NADA AQUI
 *
 * O checklist do desenho original era clicável e guardava as marcas no navegador.
 * Aqui não: uma marca que o secretário pusesse à mão diria o que ele acha que
 * aconteceu, e a tela existe para dizer o que aconteceu. A única linha acionável é
 * a avaliação do Google — e ela é uma CORREÇÃO de marcação, não uma marcação.
 */

import { useMemo, useState, type ReactNode } from "react";

import { Aviso, Selo } from "@/components/ui/Basicos";
import type {
  Auditoria,
  ChecklistRegistro,
  ItemChecklist,
  ParteLida,
  SituacaoItem,
} from "@/lib/api";

/** Inclui os dois estados que só existem na tela, sobre os quatro do servidor. */
type Situacao = SituacaoItem | "nao_conferido";

interface Linha {
  id: string;
  titulo: string;
  detalhe: string;
  /** Pontos que faltaram, quando a linha resume uma parte lida em voz alta. */
  detalhes?: string[];
  etiqueta: string;
  situacao: Situacao;
  critico: boolean;
}

interface Secao {
  codigo: string;
  numero: string;
  titulo: string;
  descricao: string;
  origem: "registro" | "roteiro";
  linhas: Linha[];
}

/* ---------------------------------------------------------------- vocabulário */

const PALAVRA: Record<Situacao, string> = {
  feito: "feito",
  pendente: "não consta",
  incerto: "incerta",
  nao_aplica: "não se aplica",
  nao_conferido: "não conferido",
};

const TOM: Record<Situacao, "ok" | "atencao" | "critico" | "neutro"> = {
  feito: "ok",
  pendente: "atencao",
  incerto: "neutro",
  nao_aplica: "neutro",
  nao_conferido: "neutro",
};

/** Quadradinho à esquerda. A cor nunca vai sozinha — a pílula da direita traz a palavra. */
const CAIXA: Record<Situacao, string> = {
  feito: "border-transparent bg-ok text-papel",
  pendente: "border-atencao-borda bg-atencao-claro text-atencao",
  incerto: "border-borda-campo bg-papel-3 text-tinta-3",
  nao_aplica: "border-dashed border-borda-forte bg-papel-2 text-tinta-3",
  nao_conferido: "border-dashed border-borda-forte bg-papel-2 text-tinta-3",
};

const SIMBOLO: Record<Situacao, string> = {
  feito: "✓",
  pendente: "!",
  incerto: "?",
  nao_aplica: "—",
  nao_conferido: "·",
};

/** `ParteLida` fala em "feita/parcial/ausente"; o checklist, em feito/pendente. */
const DA_PARTE: Record<ParteLida["situacao"], Situacao> = {
  feita: "feito",
  parcial: "pendente",
  ausente: "pendente",
  incerta: "incerto",
};

/* ------------------------------------------------------------------- montagem */

function linhaDaParte(id: string, titulo: string, parte: ParteLida): Linha {
  const situacao = DA_PARTE[parte.situacao] ?? "incerto";
  return {
    id,
    titulo,
    detalhe:
      situacao === "feito"
        ? "Os pontos do roteiro aparecem na conversa."
        : parte.situacao === "ausente"
          ? "Não aparece na transcrição."
          : "Foi lida em parte. Faltaram os pontos abaixo.",
    detalhes: parte.faltou,
    etiqueta: "Leitura",
    // Abertura e encerramento são o que o escritório pediu para seguir à risca, e
    // é o primeiro a sumir quando a entrevista corre apertada.
    critico: true,
    situacao,
  };
}

/** As seções que dependem do modelo — vazias de conteúdo enquanto ele não roda. */
function secoesDoRoteiro(auditoria: Auditoria | null): Secao[] {
  if (!auditoria) {
    return [
      {
        codigo: "abertura",
        numero: "01",
        titulo: "Abertura",
        descricao: "O que a atendente lê ao começar: sigilo, gravação, o que vai acontecer.",
        origem: "roteiro",
        linhas: [
          {
            id: "abertura-pendente",
            titulo: "Abertura lida ao começar a entrevista",
            detalhe: "Depende da leitura da conversa.",
            etiqueta: "Leitura",
            situacao: "nao_conferido",
            critico: true,
          },
        ],
      },
      {
        codigo: "perguntas",
        numero: "02",
        titulo: "Perguntas do roteiro",
        descricao: "Cada pergunta do script, e se o assunto dela foi tratado na conversa.",
        origem: "roteiro",
        linhas: [
          {
            id: "perguntas-pendente",
            titulo: "Perguntas do roteiro percorridas",
            detalhe: "Depende da leitura da conversa.",
            etiqueta: "Perguntas",
            situacao: "nao_conferido",
            critico: false,
          },
        ],
      },
      {
        codigo: "encerramento",
        numero: "03",
        titulo: "Encerramento",
        descricao: "Agradecimento, próximos passos, quem assume o atendimento daqui.",
        origem: "roteiro",
        linhas: [
          {
            id: "encerramento-pendente",
            titulo: "Encerramento lido ao terminar",
            detalhe: "Depende da leitura da conversa.",
            etiqueta: "Leitura",
            situacao: "nao_conferido",
            critico: true,
          },
        ],
      },
    ];
  }

  /* A ordem dentro das perguntas não é a do roteiro: é a da urgência. Obrigatória
   * que não apareceu primeiro — é o que o secretário precisa cobrar hoje; coberta
   * por último, porque é o que ele não precisa ler. Com cinquenta linhas na seção,
   * deixar a ordem do script esconderia as três que importam no meio das outras. */
  const perguntas: Linha[] = [
    ...auditoria.nao_cobertas.map((p) => ({
      id: `p-${p.id}`,
      titulo: p.texto,
      detalhe: p.obrigatoria
        ? "Obrigatória, e não aparece na transcrição."
        : "Não aparece na transcrição.",
      etiqueta: p.bloco,
      situacao: "pendente" as Situacao,
      critico: p.obrigatoria,
    })),
    ...auditoria.incertas.map((p) => ({
      id: `p-${p.id}`,
      titulo: p.texto,
      detalhe: "O modelo não conseguiu dizer se o assunto foi tratado.",
      etiqueta: p.bloco,
      situacao: "incerto" as Situacao,
      critico: false,
    })),
    ...auditoria.cobertas.map((p) => ({
      id: `p-${p.id}`,
      titulo: p.texto,
      detalhe: "O assunto foi tratado na conversa.",
      etiqueta: p.bloco,
      situacao: "feito" as Situacao,
      critico: false,
    })),
  ];

  return [
    {
      codigo: "abertura",
      numero: "01",
      titulo: "Abertura",
      descricao: "O que a atendente lê ao começar: sigilo, gravação, o que vai acontecer.",
      origem: "roteiro",
      linhas: [linhaDaParte("abertura", "Abertura lida ao começar a entrevista", auditoria.abertura)],
    },
    {
      codigo: "perguntas",
      numero: "02",
      titulo: "Perguntas do roteiro",
      descricao: `${auditoria.total_obrigatorias} das ${auditoria.total_perguntas} perguntas são obrigatórias.`,
      origem: "roteiro",
      linhas: perguntas,
    },
    {
      codigo: "encerramento",
      numero: "03",
      titulo: "Encerramento",
      descricao: "Agradecimento, próximos passos, quem assume o atendimento daqui.",
      origem: "roteiro",
      linhas: [
        linhaDaParte("encerramento", "Encerramento lido ao terminar", auditoria.encerramento),
      ],
    },
  ];
}

function daFase(item: ItemChecklist): Linha {
  return {
    id: item.id,
    titulo: item.titulo,
    detalhe: item.detalhe,
    etiqueta: item.etiqueta,
    situacao: item.situacao,
    critico: item.critico,
  };
}

/* --------------------------------------------------------------------- peças */

function Quadradinho({ situacao }: { situacao: Situacao }) {
  return (
    <span
      className={`mt-[2px] grid size-[20px] shrink-0 place-items-center rounded-[6px] border text-xs font-bold leading-none ${CAIXA[situacao]}`}
      aria-hidden
    >
      {SIMBOLO[situacao]}
    </span>
  );
}

function LinhaChecklist({ linha, acao }: { linha: Linha; acao?: ReactNode }) {
  const apagada = linha.situacao === "feito" || linha.situacao === "nao_aplica";

  return (
    <li className="flex items-start gap-[14px] px-[18px] py-[13px] border-b border-borda last:border-b-0">
      <Quadradinho situacao={linha.situacao} />

      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-baseline gap-x-[10px] gap-y-1">
          <span
            className={`text-tinta text-sm font-semibold leading-[1.45] ${apagada ? "opacity-70" : ""}`}
          >
            {linha.titulo}
          </span>
          <span className="text-tinta-3 font-codigo text-xs uppercase tracking-[0.08em]">
            {linha.etiqueta}
          </span>
        </div>

        <p className="mt-[3px] mb-0 text-tinta-3 text-xs leading-[1.55]">{linha.detalhe}</p>

        {/* Os pontos que faltaram da abertura/encerramento. Ficam dentro da linha, e
          * não como linhas próprias, porque não são itens do roteiro — são o
          * detalhamento de um item só. */}
        {linha.detalhes && linha.detalhes.length > 0 && (
          <ul className="mt-2 mb-0 pl-0 list-none border-l-2 border-atencao-borda">
            {linha.detalhes.map((d, i) => (
              <li key={i} className="pl-[10px] py-[2px] text-tinta-2 text-xs leading-[1.55]">
                {d}
              </li>
            ))}
          </ul>
        )}

        {acao && <div className="mt-[10px]">{acao}</div>}
      </div>

      <span className="shrink-0 pt-[1px]">
        <Selo
          tom={linha.critico && linha.situacao === "pendente" ? "critico" : TOM[linha.situacao]}
          simbolo={SIMBOLO[linha.situacao]}
        >
          {linha.critico && linha.situacao === "pendente"
            ? "não consta · crítico"
            : PALAVRA[linha.situacao]}
        </Selo>
      </span>
    </li>
  );
}

/* -------------------------------------------------------------------- a tela */

interface Props {
  /** Sai do banco. `null` só enquanto carrega. */
  registro: ChecklistRegistro | null;
  /** Sai do modelo. `null` até o secretário pedir a conferência. */
  auditoria: Auditoria | null;
  auditando: boolean;
  erroAuditoria: string | null;
  onAuditar: () => void;
  /** Conserta a marcação da avaliação do Google (ver `app/supervisao.py`). */
  onCorrigirAvaliacao: (concluida: boolean) => void;
  corrigindoAvaliacao: boolean;
}

const BOTAO_PILULA =
  "inline-flex items-center gap-2 px-[14px] py-[7px] border border-borda-campo rounded-pill bg-papel " +
  "text-tinta-2 font-codigo text-xs uppercase tracking-[0.08em] cursor-pointer " +
  "hover:bg-papel-3 disabled:opacity-50 disabled:cursor-not-allowed";

export default function ChecklistRoteiro({
  registro,
  auditoria,
  auditando,
  erroAuditoria,
  onAuditar,
  onCorrigirAvaliacao,
  corrigindoAvaliacao,
}: Props) {
  const [ocultarFeitos, setOcultarFeitos] = useState(false);

  const secoes = useMemo<Secao[]>(() => {
    const doRegistro = (registro?.fases ?? []).map((f) => ({
      codigo: f.codigo,
      numero: "",
      titulo: f.titulo,
      descricao: f.descricao,
      origem: "registro" as const,
      linhas: f.itens.map(daFase),
    }));
    // A numeração sai da lista já montada. Derivá-la de "três seções de roteiro
    // + as do registro" quebraria em silêncio no dia em que o roteiro ganhasse
    // uma seção: as seções continuariam certas, e os números, não.
    return [...secoesDoRoteiro(auditoria), ...doRegistro].map((s, i) => ({
      ...s,
      numero: String(i + 1).padStart(2, "0"),
    }));
  }, [registro, auditoria]);

  /* O progresso conta só o que FOI CONFERIDO: "não conferido" e "não se aplica"
   * ficam fora do denominador. Um checklist que mostrasse 30% porque o secretário
   * ainda não rodou a conferência estaria acusando a entrevista de um buraco que é
   * da tela, não dela. */
  const contadas = secoes.flatMap((s) =>
    s.linhas.filter((l) => l.situacao !== "nao_aplica" && l.situacao !== "nao_conferido"),
  );
  const feitas = contadas.filter((l) => l.situacao === "feito").length;
  const percentual = contadas.length ? Math.round((feitas * 100) / contadas.length) : 0;
  const criticas = contadas.filter((l) => l.critico && l.situacao === "pendente");
  const porConferir = secoes.flatMap((s) => s.linhas).filter((l) => l.situacao === "nao_conferido");

  return (
    <div className="flex flex-col gap-5">
      {/* ------------------------------------------------------------ cabeçalho */}
      <header className="border border-borda-forte rounded-cartao bg-papel shadow-cartao p-5">
        <div className="flex flex-wrap items-end justify-between gap-5">
          <div className="min-w-0">
            <span className="block text-tinta-3 font-codigo text-xs uppercase tracking-[0.14em]">
              Conferência do atendimento
            </span>
            <h2 className="mt-2 mb-0 text-tinta font-titulo text-lg font-semibold leading-[1.2]">
              Checklist do roteiro
              {registro?.caso.cliente && (
                <span className="text-tinta-3 font-normal"> · {registro.caso.cliente}</span>
              )}
            </h2>
            <p className="mt-[6px] mb-0 max-w-[62ch] text-tinta-3 text-sm leading-[1.55]">
              O que o roteiro manda fazer, e o que ficou registrado de cada etapa. As
              três primeiras seções saem da leitura da conversa; as demais, do que
              está gravado no caso.
            </p>
          </div>

          <div className="text-right shrink-0">
            <span className="block text-tinta font-titulo text-xl font-semibold tabular-nums leading-none">
              {percentual}%
            </span>
            <span className="mt-[6px] block text-tinta-3 font-codigo text-xs uppercase tracking-[0.08em]">
              {feitas} de {contadas.length} conferidos
            </span>
          </div>
        </div>

        <div className="h-[6px] mt-4 rounded-pill bg-papel-3 overflow-hidden">
          <i
            className="block h-full rounded-pill bg-ok transition-[width] duration-500 ease-out"
            style={{ width: `${percentual}%` }}
          />
        </div>

        <div className="flex flex-wrap items-center gap-[10px] mt-4">
          <button
            type="button"
            className={BOTAO_PILULA}
            onClick={onAuditar}
            disabled={auditando}
          >
            {auditando
              ? "Lendo a conversa…"
              : auditoria
                ? "Conferir de novo"
                : "Conferir contra o roteiro"}
          </button>
          <button
            type="button"
            className={BOTAO_PILULA}
            onClick={() => setOcultarFeitos((v) => !v)}
          >
            {ocultarFeitos ? "Mostrar o que está feito" : "Ocultar o que está feito"}
          </button>
          {auditando && (
            <span className="text-tinta-3 text-xs leading-[1.5]">
              A leitura da conversa inteira leva alguns segundos.
            </span>
          )}
        </div>

        {/* O resumo em palavras, para quem não vai descer a lista inteira. */}
        <div className="flex flex-wrap gap-2 mt-4">
          {criticas.length > 0 ? (
            <Selo tom="critico" simbolo="✕">
              {criticas.length} etapa(s) crítica(s) sem registro
            </Selo>
          ) : (
            <Selo tom="ok" simbolo="✓">
              Nenhuma etapa crítica em aberto
            </Selo>
          )}
          {porConferir.length > 0 && (
            <Selo tom="neutro" simbolo="·">
              {porConferir.length} seção(ões) dependem da leitura da conversa
            </Selo>
          )}
          {registro?.caso.categoria && (
            <Selo tom="info" simbolo="i">
              {registro.caso.categoria}
            </Selo>
          )}
        </div>
      </header>

      {erroAuditoria && (
        <Aviso tom="critico" titulo="Não deu para conferir contra o roteiro">
          {erroAuditoria} O restante do checklist não depende do modelo e continua
          válido.
        </Aviso>
      )}

      {auditoria?.resumo && (
        <Aviso tom="info" titulo="Como a entrevista correu">
          {auditoria.resumo}
        </Aviso>
      )}

      {/* --------------------------------------------------------------- seções */}
      {secoes.map((secao) => {
        const visiveis = ocultarFeitos
          ? secao.linhas.filter((l) => l.situacao !== "feito")
          : secao.linhas;
        const feitasNaSecao = secao.linhas.filter((l) => l.situacao === "feito").length;

        return (
          <section
            key={secao.codigo}
            className="border border-borda-forte rounded-cartao bg-papel shadow-cartao overflow-hidden"
          >
            <div className="flex items-start justify-between gap-4 px-[18px] py-[14px] border-b border-borda bg-papel-2">
              <div className="min-w-0">
                <div className="flex items-baseline gap-[10px]">
                  <span className="text-tinta-3 font-codigo text-xs tabular-nums">
                    {secao.numero}
                  </span>
                  <h3 className="m-0 text-tinta font-titulo text-md font-semibold leading-[1.2]">
                    {secao.titulo}
                  </h3>
                  {secao.origem === "roteiro" && (
                    <span
                      className="text-tinta-3 font-codigo text-xs uppercase tracking-[0.08em]"
                      title="Sai da leitura da transcrição pelo modelo, que erra. Ver o aviso ao pé da tela."
                    >
                      leitura da conversa
                    </span>
                  )}
                </div>
                <p className="mt-1 mb-0 text-tinta-3 text-xs leading-[1.5]">{secao.descricao}</p>
              </div>
              <span className="shrink-0 text-tinta-3 font-codigo text-xs tabular-nums whitespace-nowrap">
                {feitasNaSecao}/{secao.linhas.length}
              </span>
            </div>

            {visiveis.length === 0 ? (
              <p className="m-0 px-[18px] py-4 text-tinta-3 text-xs leading-[1.55]">
                Tudo desta seção está feito.
              </p>
            ) : (
              <ul className="list-none m-0 p-0">
                {visiveis.map((linha) => (
                  <LinhaChecklist
                    key={linha.id}
                    linha={linha}
                    /* A única linha acionável da tela. Ver o cabeçalho do arquivo
                     * sobre por que as outras não são. */
                    acao={
                      linha.id === "avaliacao-confirmada" ? (
                        <button
                          type="button"
                          className={BOTAO_PILULA}
                          disabled={corrigindoAvaliacao}
                          onClick={() => onCorrigirAvaliacao(linha.situacao !== "feito")}
                        >
                          {corrigindoAvaliacao
                            ? "Gravando…"
                            : linha.situacao === "feito"
                              ? "Desfazer marcação"
                              : "Marcar como avaliada"}
                        </button>
                      ) : undefined
                    }
                  />
                ))}
              </ul>
            )}
          </section>
        );
      })}

      {/* ------------------------------------------------- observações do modelo */}
      {auditoria && (auditoria.observacoes.length > 0 || auditoria.pontos_fortes.length > 0) && (
        <section className="border border-borda-forte rounded-cartao bg-papel shadow-cartao p-5">
          {auditoria.observacoes.length > 0 && (
            <div>
              <h3 className="mt-0 mb-2 text-tinta font-titulo text-md font-semibold">
                Observações
              </h3>
              <ul className="list-none m-0 p-0">
                {auditoria.observacoes.map((o, i) => (
                  <li
                    key={i}
                    className="py-[7px] border-b border-borda last:border-b-0 text-tinta-2 text-sm leading-[1.55]"
                  >
                    <strong className="text-tinta">{o.item}</strong> — {o.porque}
                  </li>
                ))}
              </ul>
            </div>
          )}

          {auditoria.pontos_fortes.length > 0 && (
            <div className={auditoria.observacoes.length > 0 ? "mt-5" : undefined}>
              <h3 className="mt-0 mb-2 text-tinta font-titulo text-md font-semibold">
                Pontos fortes
              </h3>
              <ul className="list-none m-0 p-0">
                {auditoria.pontos_fortes.map((p, i) => (
                  <li
                    key={i}
                    className="py-[7px] border-b border-borda last:border-b-0 text-tinta-2 text-sm leading-[1.55]"
                  >
                    {p}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </section>
      )}

      {/* A ressalva fecha a tela, e não abre: quem chegou até aqui já viu as linhas
        * e é agora que precisa saber o quanto pode cobrar do que leu. */}
      <Aviso tom="atencao" titulo="O que este checklist não diz">
        {auditoria?.aviso ??
          "As seções que dependem da leitura da conversa ainda não foram conferidas."}{" "}
        Pergunta pode não ter sido feita por bom motivo — o cliente já tinha
        respondido, ou o caso não pedia. Nada aqui é nota, e nada aqui compara
        pessoas.
        {auditoria?.transcricao_truncada && (
          <>
            {" "}
            <strong>
              A transcrição é longa e foi lida até o limite do modelo: o fim da conversa
              pode não ter entrado.
            </strong>
          </>
        )}
      </Aviso>
    </div>
  );
}
