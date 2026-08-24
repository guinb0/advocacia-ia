"use client";

/**
 * Modelos de petição do escritório — a tela que alimenta o Style Engine.
 *
 * É por aqui que o sistema aprende a escrever como o escritório. Sem peça cadastrada ele
 * gera no estilo do modelo de linguagem, que é indistinguível entre dois escritórios com o
 * mesmo playbook.
 *
 * A tela mostra três coisas, e a terceira é a que costuma faltar em telas assim: **o que o
 * sistema entendeu de cada peça**. Um `.docx` que não teve nenhuma seção reconhecida ainda
 * ensina extensão e vocabulário, mas não ensina como o escritório escreve a fundamentação —
 * e quem cadastrou precisa saber disso na hora, não descobrir meses depois pelo resultado.
 */

import { useCallback, useEffect, useMemo, useState } from "react";

import { Aviso, Botao, Cartao, Selo, Tabela, Th } from "@/components/ui/Basicos";
import { ApiError } from "@/lib/api";

/* `.tabela th/td` era seletor descendente; sem equivalente no Tailwind, a regra
 * vira constante e cada célula a carrega. */
const CELULA = "px-[0.4rem] py-2 text-left border-b border-borda";
const CABECALHO_CELULA =
  "px-[0.4rem] py-2 text-tinta-3 text-xs font-semibold uppercase tracking-[0.03em]";
const ITEM_TOPO = "flex items-center justify-between gap-[0.6rem]";
const CAMPO = "flex flex-col gap-[0.28rem] min-w-[220px] flex-1 text-tinta-3 text-xs";
/* Cor explícita no select E no option não é redundância: o `globals.css` põe
 * `color: inherit` em todo select, e no Windows a lista aberta de um select sem
 * cor própria herda as do sistema — deu faixa preta sem texto legível. */
const SELECT =
  "px-[0.6rem] py-[0.55rem] border border-borda-campo rounded-campo bg-papel text-tinta text-sm " +
  "[&>option]:bg-papel [&>option]:text-tinta";

import {
  type NoDaTaxonomia,
  type PecaDeEstilo,
  type PerfilDeEstilo,
  enviarPecaDeEstilo,
  pecasDeEstilo,
  perfilDeEstilo,
  removerPecaDeEstilo,
  taxonomiaDeEstilo,
} from "@/lib/agente";

const TIPOS = [{ codigo: "INITIAL_PETITION", rotulo: "Petição inicial" }];

/** Como cada estado da segmentação se explica para quem cadastrou a peça. */
const SEGMENTACAO: Record<string, { texto: string; tom: "ok" | "atencao" | "critico" }> = {
  FULL: { texto: "seções reconhecidas", tom: "ok" },
  PARTIAL: { texto: "seções em parte", tom: "atencao" },
  POOR: { texto: "sem seções reconhecidas", tom: "critico" },
};

type ItemEnvio = {
  id: string;
  nome: string;
  estado: "aguardando" | "enviando" | "concluido" | "repetido" | "recusado";
  detalhe?: string;
};

export default function ModelosDePeticao({ onVoltar }: { onVoltar: () => void }) {
  const [acoes, setAcoes] = useState<NoDaTaxonomia[]>([]);
  const [acao, setAcao] = useState("");
  const [tipo, setTipo] = useState(TIPOS[0].codigo);

  const [pecas, setPecas] = useState<PecaDeEstilo[]>([]);
  const [perfil, setPerfil] = useState<PerfilDeEstilo | null>(null);

  const [enviando, setEnviando] = useState(false);
  const [arrastando, setArrastando] = useState(false);
  const [filaEnvio, setFilaEnvio] = useState<ItemEnvio[]>([]);
  const [removendo, setRemovendo] = useState<string | null>(null);
  const [erro, setErro] = useState<string | null>(null);
  const [recado, setRecado] = useState<string | null>(null);

  // Estado separado do `erro` de propósito. A primeira versão usava o mesmo, e o `setErro(null)`
  // do envio apagava a falha da taxonomia — a tela ficava com o seletor vazio e nenhuma
  // explicação, que foi exatamente como o defeito apareceu.
  const [erroDasAcoes, setErroDasAcoes] = useState<string | null>(null);

  useEffect(() => {
    void taxonomiaDeEstilo()
      .then((itens) => {
        setAcoes(itens);
        if (!itens.length) {
          setErroDasAcoes("O agente respondeu, mas não devolveu nenhuma ação cadastrada.");
          return;
        }
        // A primeira, e não a última: a taxonomia vem ordenada por código, e a última é um
        // nó folha arbitrário — abrir a tela já apontando para ele confunde mais que ajuda.
        setAcao((atual) => atual || itens[0].code);
      })
      .catch((falha) =>
        setErroDasAcoes(
          falha instanceof ApiError
            ? `Não foi possível carregar as ações: ${falha.message}`
            : "Não foi possível carregar as ações. O agente jurídico está no ar?",
        ),
      );
    // Uma vez só: a taxonomia é YAML versionado, não muda entre requisições.
  }, []);

  const recarregar = useCallback(async () => {
    if (!acao) return;
    const [lista, encontrado] = await Promise.all([
      pecasDeEstilo(acao).catch(() => [] as PecaDeEstilo[]),
      // 404 aqui é resposta legítima: o grupo ainda não tem padrão. Não é erro de tela.
      perfilDeEstilo(acao, tipo).catch(() => null),
    ]);
    setPecas(lista);
    setPerfil(encontrado);
  }, [acao, tipo]);

  useEffect(() => {
    void recarregar();
  }, [recarregar]);

  async function enviar(arquivos: File[]) {
    if (!arquivos.length || !acao) return;
    setEnviando(true);
    setErro(null);
    setRecado(null);

    let enviadas = 0;
    const repetidas: string[] = [];
    const recusadas: string[] = [];

    const lote = arquivos.map((arquivo, indice) => ({
      id: `${Date.now()}-${indice}`,
      nome: arquivo.name,
      estado: "aguardando" as const,
    }));
    setFilaEnvio(lote);

    for (const [indice, arquivo] of arquivos.entries()) {
      const id = lote[indice].id;
      setFilaEnvio((fila) => fila.map((item) => item.id === id ? { ...item, estado: "enviando" } : item));
      try {
        await enviarPecaDeEstilo(arquivo, acao, tipo);
        enviadas += 1;
        setFilaEnvio((fila) => fila.map((item) => item.id === id ? { ...item, estado: "concluido" } : item));
      } catch (falha) {
        const detalhe = falha instanceof ApiError ? falha.message : String(falha);
        // Peça repetida não é erro do usuário: é o sistema evitando contar a mesma peça
        // duas vezes no padrão. Vale dizer, não vale alarmar.
        if (/já faz parte|duplicate/i.test(detalhe)) {
          repetidas.push(arquivo.name);
          setFilaEnvio((fila) => fila.map((item) => item.id === id ? { ...item, estado: "repetido", detalhe: "Já estava cadastrada" } : item));
        } else {
          recusadas.push(`${arquivo.name}: ${detalhe}`);
          setFilaEnvio((fila) => fila.map((item) => item.id === id ? { ...item, estado: "recusado", detalhe } : item));
        }
      }
    }

    setEnviando(false);
    if (recusadas.length) setErro(recusadas.join(" · "));
    const partes = [
      enviadas ? `${enviadas} peça(s) adicionada(s)` : "",
      repetidas.length ? `${repetidas.length} já estavam cadastradas` : "",
    ].filter(Boolean);
    if (partes.length) setRecado(partes.join(" · ") + ".");
    await recarregar();
  }

  function receberArquivos(arquivos: File[]) {
    if (enviando || !acao || !arquivos.length) return;
    const aceitos = arquivos.filter((arquivo) => /\.(docx|pdf)$/i.test(arquivo.name));
    const invalidos = arquivos.filter((arquivo) => !/\.(docx|pdf)$/i.test(arquivo.name));
    if (invalidos.length) {
      setErro(`${invalidos.map((arquivo) => arquivo.name).join(", ")}: formato não aceito. Use .docx ou .pdf.`);
    }
    if (aceitos.length) void enviar(aceitos);
  }

  async function remover(peca: PecaDeEstilo) {
    if (!window.confirm(`Remover "${peca.filename ?? "esta amostra"}" do padrão desta ação?`)) return;
    setRemovendo(peca.id);
    setErro(null);
    setRecado(null);
    try {
      await removerPecaDeEstilo(peca.id);
      setRecado("Amostra removida. O padrão desta ação foi atualizado.");
      await recarregar();
    } catch (falha) {
      setErro(falha instanceof ApiError ? falha.message : "Não foi possível remover a amostra.");
    } finally {
      setRemovendo(null);
    }
  }

  const semSecoes = useMemo(
    () => pecas.filter((peca) => !peca.eligibility.eligible_for_section_profile).length,
    [pecas],
  );

  return (
    <div className="flex flex-col gap-[1.1rem] max-w-[980px] mx-auto px-4 pt-[1.4rem] pb-12">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="m-0 font-titulo text-[1.45rem] leading-[1.2] text-tinta">Modelos de petição do escritório</h1>
          <p className="mt-[0.45rem] mb-0 max-w-[62ch] text-tinta-3 text-sm leading-[1.5]">
            Quanto mais petições reais e revisões finais você cadastrar, melhor o sistema
            mede o vocabulário, a estrutura, o tamanho e o ritmo do escritório. Com poucas
            peças ele usa um perfil aproximado; a resposta melhora progressivamente conforme
            recebe exemplos variados da mesma ação.
          </p>
        </div>
        <Botao variante="texto" onClick={onVoltar}>
          ← Voltar
        </Botao>
      </div>

      <Cartao titulo="Adicionar peças">
        <p className="mt-2 mb-[0.9rem] text-tinta-3 text-sm leading-[1.5]">
          Cada peça adicionada atualiza o perfil de escrita. As correções feitas pelo
          advogado ao aprovar uma minuta também viram aprendizado supervisionado: o sistema
          compara o texto gerado com a versão final, sem copiar fatos de um processo para outro.
        </p>

        <div className="flex flex-wrap gap-[0.9rem] mb-[0.9rem]">
          <label className={CAMPO}>
            <span>Ação</span>
            <select className={SELECT}
              value={acao}
              disabled={!acoes.length}
              onChange={(evento) => setAcao(evento.target.value)}
            >
              {!acoes.length && <option value="">carregando as ações…</option>}
              {acoes.map((item) => (
                <option key={item.code} value={item.code}>
                  {item.label}
                </option>
              ))}
            </select>
          </label>

          <label className={CAMPO}>
            <span>Tipo de peça</span>
            <select className={SELECT} value={tipo} onChange={(evento) => setTipo(evento.target.value)}>
              {TIPOS.map((item) => (
                <option key={item.codigo} value={item.codigo}>
                  {item.rotulo}
                </option>
              ))}
            </select>
          </label>
        </div>

        <label
          className={
            "block p-[1.1rem] border-[1.5px] border-dashed rounded-cartao text-center cursor-pointer " +
            "transition-[border-color,background-color,transform,box-shadow] duration-200 " +
            "[&>input]:block [&>input]:mx-auto [&>input]:mb-[0.6rem] [&>span]:block [&>span]:text-sm " +
            "[&>span]:text-tinta-2 [&>small]:block [&>small]:mt-[0.35rem] [&>small]:max-w-[54ch] " +
            "[&>small]:mx-auto [&>small]:text-tinta-3 [&>small]:text-xs [&>small]:leading-[1.45] " +
            (arrastando
              ? "border-acao bg-acao-clara scale-[1.01] shadow-[0_0_0_3px_rgba(37,99,235,0.12)]"
              : "border-borda-forte bg-papel-2 hover:border-acao hover:bg-acao-clara")
          }
          onDragEnter={(evento) => { evento.preventDefault(); if (!enviando && acao) setArrastando(true); }}
          onDragOver={(evento) => { evento.preventDefault(); evento.dataTransfer.dropEffect = "copy"; }}
          onDragLeave={(evento) => {
            evento.preventDefault();
            if (!evento.currentTarget.contains(evento.relatedTarget as Node | null)) setArrastando(false);
          }}
          onDrop={(evento) => {
            evento.preventDefault();
            setArrastando(false);
            receberArquivos(Array.from(evento.dataTransfer.files));
          }}
        >
          <input
            type="file"
            accept=".docx,.pdf"
            multiple
            disabled={enviando || !acao}
            onChange={(evento) => {
              const arquivos = Array.from(evento.target.files ?? []);
              // Limpa o input antes de enviar: se um arquivo falhar, a pessoa
              // consegue selecionar exatamente o mesmo lote outra vez.
              evento.target.value = "";
              receberArquivos(arquivos);
            }}
          />
          <span>
            {enviando
              ? "Enviando os arquivos…"
              : arrastando
                ? "Solte os arquivos aqui"
                : "Arraste os arquivos para cá ou clique para escolher"}
            <small>
              Selecione vários de uma vez com Ctrl ou Shift. Cada arquivo é processado
              separadamente: se um falhar, os demais continuam. PDF precisa ter texto
              selecionável — cópia digitalizada é recusada.
            </small>
          </span>
        </label>

        {filaEnvio.length > 0 && (
          <div className="mt-3 overflow-hidden rounded-campo border border-borda bg-papel" aria-live="polite">
            <div className="h-1 bg-papel-3">
              <div
                className="h-full bg-acao transition-[width] duration-500 ease-out"
                style={{ width: `${(filaEnvio.filter((item) => !["aguardando", "enviando"].includes(item.estado)).length / filaEnvio.length) * 100}%` }}
              />
            </div>
            <ul className="m-0 list-none p-0">
              {filaEnvio.map((item) => (
                <li key={item.id} className="flex items-center gap-3 border-b border-borda px-3 py-2 last:border-b-0">
                  <span className={
                    "grid h-5 w-5 flex-none place-items-center rounded-full text-[10px] font-bold " +
                    (item.estado === "enviando" ? "animate-pulse bg-acao text-papel" :
                      item.estado === "concluido" ? "bg-ok text-papel" :
                        item.estado === "recusado" ? "bg-critico text-papel" :
                          item.estado === "repetido" ? "bg-atencao text-papel" : "bg-papel-3 text-tinta-3")
                  }>
                    {item.estado === "concluido" ? "✓" : item.estado === "recusado" ? "×" : item.estado === "repetido" ? "!" : "•"}
                  </span>
                  <span className="min-w-0 flex-1 overflow-hidden text-ellipsis whitespace-nowrap text-xs text-tinta">{item.nome}</span>
                  <small className="text-right text-[11px] text-tinta-3">
                    {item.detalhe ?? ({ aguardando: "aguardando", enviando: "analisando…", concluido: "adicionada", repetido: "repetida", recusado: "recusada" }[item.estado])}
                  </small>
                </li>
              ))}
            </ul>
          </div>
        )}

        {erroDasAcoes && (
          <Aviso tom="critico" titulo="Sem a lista de ações não dá para enviar">
            {erroDasAcoes}
          </Aviso>
        )}
        {recado && <p className="mt-[0.8rem] mb-0 text-tinta-2 text-sm">{recado}</p>}
        {erro && (
          <Aviso tom="critico" titulo="Alguns arquivos não entraram">
            {erro}
          </Aviso>
        )}
      </Cartao>

      <PainelPerfil perfil={perfil} total={pecas.length} />

      <Cartao>
        <div className={ITEM_TOPO}>
          <h2 className="m-0 text-tinta font-titulo text-lg font-semibold">Peças cadastradas nesta ação</h2>
          <span className="px-2 py-[0.1rem] rounded-pill bg-papel-3 text-tinta-2 text-xs tabular-nums">{pecas.length}</span>
        </div>

        {semSecoes > 0 && (
          <Aviso tom="atencao" titulo={`${semSecoes} peça(s) sem seções reconhecidas`}>
            Elas continuam ensinando extensão, ritmo de frase e vocabulário — mas não entram
            no padrão de cada seção. Costuma ser documento que não é petição, ou peça cujos
            títulos fogem do usual.
          </Aviso>
        )}

        {pecas.length === 0 ? (
          <p className="mt-[0.6rem] mb-0 text-tinta-3 text-sm leading-[1.5]">
            Nenhuma peça nesta ação ainda. O sistema não mistura amostras de outras ações;
            enquanto não houver exemplos próprios, escreve sem um padrão medido para esta ação.
          </p>
        ) : (
          <ul className="list-none mt-[0.7rem] mb-0 p-0 flex flex-col gap-2">
            {pecas.map((peca) => {
              const seg = SEGMENTACAO[peca.segmentation.quality];
              return (
                <li key={peca.id} className="px-3 py-[0.65rem] border border-borda rounded-campo">
                  <div className={ITEM_TOPO}>
                    <strong className="overflow-hidden text-ellipsis whitespace-nowrap text-sm text-tinta">{peca.filename ?? "(sem nome)"}</strong>
                    <div className="flex items-center gap-2">
                      <Selo tom={seg.tom} simbolo={peca.segmentation.quality === "FULL" ? "✓" : "!"}>
                        {seg.texto}
                      </Selo>
                      <Botao variante="texto" pequeno disabled={removendo === peca.id} onClick={() => void remover(peca)}>
                        {removendo === peca.id ? "Removendo…" : "Remover"}
                      </Botao>
                    </div>
                  </div>
                  <div className="mt-1 text-tinta-3 text-xs tabular-nums">
                    {peca.word_count.toLocaleString("pt-BR")} palavras
                    {peca.document_format ? ` · ${peca.document_format}` : ""}
                    {peca.source === "LAWYER_EDITED_GENERATION"
                      ? " · escrita na revisão"
                      : " · enviada pelo escritório"}
                  </div>
                </li>
              );
            })}
          </ul>
        )}
      </Cartao>
    </div>
  );
}

/**
 * O padrão medido, com a amostra à vista.
 *
 * `n` e o nível acompanham todo número por uma razão que aparece na primeira reunião: "6.800
 * palavras" a partir de três peças e a partir de trezentas são afirmações muito diferentes, e
 * quem lê precisa poder distingui-las sem perguntar.
 */
function PainelPerfil({ perfil, total }: { perfil: PerfilDeEstilo | null; total: number }) {
  if (!perfil) {
    return (
      <Cartao titulo="Padrão medido">
        <p className="mt-[0.6rem] mb-0 text-tinta-3 text-sm leading-[1.5]">
          {total < 5
            ? `Há ${total} de 5 petições necessárias nesta ação. Até completar a amostra mínima, os textos ficam cadastrados, mas não orientam novas peças.`
            : "As amostras ainda não produziram medidas válidas suficientes. Confira os avisos de segmentação acima."}
        </p>
      </Cartao>
    );
  }

  const proprias = perfil.n;
  const linhas: { rotulo: string; feature: string; sufixo?: string }[] = [
    { rotulo: "Extensão da peça", feature: "word_count", sufixo: "palavras" },
    { rotulo: "Tamanho do parágrafo", feature: "median_paragraph_words", sufixo: "palavras" },
    { rotulo: "Tamanho da frase", feature: "median_sentence_words", sufixo: "palavras" },
  ];

  return (
    <Cartao>
      <div className={ITEM_TOPO}>
        <h2 className="m-0 text-tinta font-titulo text-lg font-semibold">Padrão medido</h2>
        <Selo tom={proprias >= 5 ? "ok" : "atencao"} simbolo={proprias >= 5 ? "✓" : "!"}>
          {proprias} peça(s) desta ação
        </Selo>
      </div>

      <p className="mt-2 mb-[0.9rem] text-tinta-3 text-sm leading-[1.5]">
        Padrão formado exclusivamente por {proprias} peça(s) desta ação. Nenhuma amostra de
        outra ação entra nestas medidas.
      </p>

      <div className="mb-4 border-l-[3px] border-ok bg-ok-claro px-4 py-3 text-sm leading-[1.6] text-tinta-2">
        <strong className="block text-tinta">Padrão que será seguido nas próximas petições</strong>
        <p className="my-2">
          As petições desta ação <strong>serão redigidas conforme este padrão do escritório</strong>:
        </p>
        <ul className="my-2 pl-5">
          {diretrizesDoPadrao(perfil).map((diretriz) => <li key={diretriz}>{diretriz}</li>)}
        </ul>
        <p className="mb-0 mt-2">
          No caso concreto, o sistema manterá essa forma de escrever e adaptará o conteúdo aos
          fatos, provas, pedidos, teses e riscos do dossiê daquele cliente. Para cada seção,
          buscará as passagens mais próximas entre as amostras desta mesma ação. O padrão de
          forma será seguido; nomes, valores e fatos das petições de exemplo nunca serão copiados.
        </p>
      </div>

      <Tabela className="text-tinta-2">
        <thead>
          <tr>
            <Th className={CABECALHO_CELULA}>
              Medida
            </Th>
            <Th className={CABECALHO_CELULA}>
              Nesta ação
            </Th>
            <Th className={CABECALHO_CELULA}>
              Padrão desta ação
            </Th>
          </tr>
        </thead>
        <tbody>
          {linhas.map(({ rotulo, feature, sufixo }) => {
            const bruto = perfil.raw[feature];
            const efetivo = perfil.effective[feature];
            if (!efetivo) return null;
            return (
              <tr key={feature}>
                <td className={CELULA}>{rotulo}</td>
                <td className={`${CELULA} tabular-nums whitespace-nowrap text-tinta`}>
                  {bruto ? `${Math.round(bruto.median).toLocaleString("pt-BR")} ${sufixo ?? ""}` : "—"}
                </td>
                <td className={`${CELULA} tabular-nums whitespace-nowrap text-tinta`}>
                  {Math.round(efetivo.median).toLocaleString("pt-BR")} {sufixo ?? ""}
                </td>
              </tr>
            );
          })}
        </tbody>
      </Tabela>

      <p className="mt-[0.8rem] mb-0 text-tinta-3 text-xs leading-[1.5]">
        A coluna da direita é a que entra na geração e usa somente esta ação. São {total}
        peça(s) cadastradas nesta ação.
      </p>
    </Cartao>
  );
}

function diretrizesDoPadrao(perfil: PerfilDeEstilo): string[] {
  const mediana = (nome: string) => perfil.raw[nome]?.median;
  const palavras = mediana("word_count");
  const frase = mediana("median_sentence_words");
  const paragrafo = mediana("median_paragraph_words");
  const titulos = mediana("heading_count");
  const faixa = (valor: number) => {
    const inferior = Math.max(1, Math.round(valor * 0.8));
    const superior = Math.max(inferior + 1, Math.round(valor * 1.2));
    return `${inferior.toLocaleString("pt-BR")} a ${superior.toLocaleString("pt-BR")}`;
  };
  const paragrafoConfiavel = Boolean(
    paragrafo && palavras && paragrafo <= 400 && paragrafo <= palavras * 0.4,
  );
  const marcadores = Object.entries(perfil.raw)
    .filter(([nome, estatistica]) => nome.startsWith("marker.") && estatistica.median > 0)
    .sort((a, b) => b[1].median - a[1].median)
    .slice(0, 5)
    .map(([nome]) => nome.slice("marker.".length).replaceAll("_", " "));

  return [
    palavras
      ? `Extensão: peça completa normalmente entre ${faixa(palavras)} palavras, sem aumentar texto apenas para atingir a faixa.`
      : "Extensão: seguirá a dimensão recorrente das petições analisadas.",
    frase
      ? `Ritmo: frases predominantemente entre ${faixa(frase)} palavras, preservando a cadência medida no escritório.`
      : "Ritmo: seguirá a cadência de frases observada nas amostras.",
    paragrafoConfiavel
      ? `Parágrafos: blocos normalmente entre ${faixa(paragrafo!)} palavras.`
      : "Parágrafos: a métrica foi desconsiderada porque alguns PDFs perderam as quebras de linha; o sistema não reproduzirá blocos artificiais de milhares de palavras.",
    titulos
      ? `Organização: cerca de ${Math.max(1, Math.round(titulos))} títulos e subtítulos, separando qualificação, fatos, fundamentos, pedidos e fechamento.`
      : "Organização: estrutura por títulos e seções conforme as divisões recorrentes das amostras.",
    marcadores.length
      ? `Linguagem: manterá, com naturalidade, expressões recorrentes como ${marcadores.join(", ")}.`
      : "Linguagem: tom técnico, coeso e compatível com o vocabulário recorrente do escritório.",
  ];
}
