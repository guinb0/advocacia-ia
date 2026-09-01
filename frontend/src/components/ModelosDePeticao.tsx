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
import {
  ApiError,
  enviarModeloVisualPeticao,
  listarCategorias,
  type ModeloVisualPeticao,
  obterModeloVisualPeticao,
  restaurarModeloVisualPeticao,
  urlApi,
} from "@/lib/api";
import type { ItemChecklist } from "@/lib/types";

/* `.tabela th/td` era seletor descendente; sem equivalente no Tailwind, a regra
 * vira constante e cada célula a carrega. */
const CELULA = "px-[0.4rem] py-2 text-left border-b border-borda";
const CABECALHO_CELULA =
  "px-[0.4rem] py-2 text-tinta-3 text-xs font-semibold uppercase tracking-[0.03em]";
const ITEM_TOPO = "flex items-center justify-between gap-[0.6rem]";
const CAMPO = "flex flex-col gap-[0.28rem] min-w-[220px] flex-1 text-tinta-3 text-xs";
/* Cor explícita no select E no option não é redundância: no Windows a lista
 * aberta de um select sem cor própria pode herdar as do sistema — deu faixa
 * preta sem texto legível. */
const SELECT =
  "px-[0.6rem] py-[0.55rem] border border-borda-campo rounded-campo bg-papel text-tinta text-sm " +
  "[&>option]:bg-papel [&>option]:text-tinta";

import {
  type ConfiguracaoDeGeracao,
  type NoDaTaxonomia,
  type PecaDeEstilo,
  type PerfilDeEstilo,
  configuracaoDeGeracao,
  enviarPecaDeEstilo,
  pecasDeEstilo,
  perfilDeEstilo,
  removerPecaDeEstilo,
  salvarConfiguracaoDeGeracao,
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
  const [configuracao, setConfiguracao] = useState<ConfiguracaoDeGeracao | null>(null);
  const [documentoNovo, setDocumentoNovo] = useState("");
  const [salvandoConfiguracao, setSalvandoConfiguracao] = useState(false);
  /** Checklist do Acervo para a ação escolhida — sugestões clicáveis. */
  const [checklistAcao, setChecklistAcao] = useState<ItemChecklist[]>([]);

  const [enviando, setEnviando] = useState(false);
  const [arrastando, setArrastando] = useState(false);
  const [filaEnvio, setFilaEnvio] = useState<ItemEnvio[]>([]);
  const [removendo, setRemovendo] = useState<string | null>(null);
  const [erro, setErro] = useState<string | null>(null);
  const [erroCarregamento, setErroCarregamento] = useState<string | null>(null);
  const [recado, setRecado] = useState<string | null>(null);
  const [modeloVisual, setModeloVisual] = useState<ModeloVisualPeticao | null>(null);
  const [enviandoVisual, setEnviandoVisual] = useState(false);

  // Estado separado do `erro` de propósito. A primeira versão usava o mesmo, e o `setErro(null)`
  // do envio apagava a falha da taxonomia — a tela ficava com o seletor vazio e nenhuma
  // explicação, que foi exatamente como o defeito apareceu.
  const [erroDasAcoes, setErroDasAcoes] = useState<string | null>(null);

  useEffect(() => {
    void obterModeloVisualPeticao()
      .then(setModeloVisual)
      .catch((falha) => setErro(
        falha instanceof ApiError ? falha.message : "Não foi possível carregar o modelo visual geral.",
      ));
  }, []);

  async function trocarModeloVisual(arquivo: File) {
    setEnviandoVisual(true);
    setErro(null);
    setRecado(null);
    try {
      const salvo = await enviarModeloVisualPeticao(arquivo);
      setModeloVisual(salvo);
      setRecado("Modelo visual geral atualizado. As próximas petições usarão essa logo e fonte.");
    } catch (falha) {
      setErro(falha instanceof ApiError ? falha.message : "Não foi possível salvar o modelo visual.");
    } finally {
      setEnviandoVisual(false);
    }
  }

  async function restaurarVisual() {
    if (!window.confirm("Restaurar a logo e a fonte padrão da Lara & Melo?")) return;
    setEnviandoVisual(true);
    setErro(null);
    try {
      setModeloVisual(await restaurarModeloVisualPeticao());
      setRecado("Padrão visual Lara & Melo restaurado.");
    } catch (falha) {
      setErro(falha instanceof ApiError ? falha.message : "Não foi possível restaurar o padrão.");
    } finally {
      setEnviandoVisual(false);
    }
  }

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

  /* O checklist do caso (Acervo) e a taxonomia do agente usam o mesmo código de
   * ação (`auxilio_acidente`, etc.). Quando bate, oferecemos os documentos do
   * checklist como atalho — em vez de digitar "CNIS" / "laudo" à mão. */
  useEffect(() => {
    if (!acao) {
      setChecklistAcao([]);
      return;
    }
    let cancelado = false;
    void listarCategorias()
      .then((categorias) => {
        if (cancelado) return;
        const chave = acao.trim().toLowerCase();
        const categoria =
          categorias.find((c) => c.codigo.toLowerCase() === chave) ??
          categorias.find((c) => c.codigo.toLowerCase().replace(/-/g, "_") === chave.replace(/-/g, "_"));
        setChecklistAcao(categoria?.itens ?? []);
      })
      .catch(() => {
        if (!cancelado) setChecklistAcao([]);
      });
    return () => {
      cancelado = true;
    };
  }, [acao]);

  const recarregar = useCallback(async () => {
    if (!acao) return;
    setErroCarregamento(null);
    const [resultadoPecas, resultadoPerfil, resultadoConfig] = await Promise.allSettled([
      pecasDeEstilo(acao, tipo),
      perfilDeEstilo(acao, tipo),
      configuracaoDeGeracao(acao, tipo),
    ]);
    const falhas: string[] = [];

    if (resultadoPecas.status === "fulfilled") {
      setPecas(resultadoPecas.value);
    } else {
      setPecas([]);
      falhas.push(
        resultadoPecas.reason instanceof ApiError
          ? resultadoPecas.reason.message
          : "Não foi possível carregar as peças cadastradas.",
      );
    }

    // 404 é resposta legítima: ainda não existe amostra suficiente nem configuração salva.
    if (resultadoPerfil.status === "fulfilled") {
      // Algumas versões antigas do serviço ignoravam `taxonomy_code` e
      // devolviam o perfil global. Isso produzia a contradição "8 desta ação"
      // e "0 cadastradas" logo abaixo. Perfil de outro escopo não é exibido
      // como se pertencesse à ação selecionada.
      setPerfil(
        resultadoPerfil.value.taxonomy_code === acao &&
        resultadoPerfil.value.document_type === tipo
          ? resultadoPerfil.value
          : null,
      );
    } else if (resultadoPerfil.reason instanceof ApiError && resultadoPerfil.reason.status === 404) {
      setPerfil(null);
    } else {
      setPerfil(null);
      falhas.push(
        resultadoPerfil.reason instanceof ApiError
          ? resultadoPerfil.reason.message
          : "Não foi possível medir o padrão desta ação.",
      );
    }

    if (resultadoConfig.status === "fulfilled") {
      setConfiguracao(resultadoConfig.value);
    } else if (resultadoConfig.reason instanceof ApiError && resultadoConfig.reason.status === 404) {
      setConfiguracao({
        taxonomy_code: acao,
        document_type: tipo,
        display_name: TIPOS.find((item) => item.codigo === tipo)?.rotulo ?? "Petição",
        drafting_instructions: "",
        required_documents: [],
      });
    } else {
      setConfiguracao(null);
      falhas.push(
        resultadoConfig.reason instanceof ApiError
          ? resultadoConfig.reason.message
          : "Não foi possível carregar a configuração desta ação.",
      );
    }

    if (falhas.length) setErroCarregamento([...new Set(falhas)].join(" "));
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

  async function salvarConfiguracao() {
    if (!configuracao) return;
    setSalvandoConfiguracao(true);
    setErro(null);
    try {
      setConfiguracao(await salvarConfiguracaoDeGeracao(configuracao));
      setRecado("Configuração da peça salva e pronta para orientar a IA Jurídica.");
    } catch (falha) {
      const mensagem = falha instanceof ApiError ? falha.message : "Não foi possível salvar a configuração.";
      setErro(
        /404|not found/i.test(mensagem)
          ? "O agente jurídico ainda não tem a rota de configuração desta peça (404). Atualize o serviço ia-juridica ou confira AGENTE_API_URL."
          : mensagem,
      );
    } finally {
      setSalvandoConfiguracao(false);
    }
  }

  function incluirDocumento(nomeBruto: string) {
    const nome = nomeBruto.trim();
    if (!nome || !configuracao) return;
    if (configuracao.required_documents.some((item) => item.toLocaleLowerCase() === nome.toLocaleLowerCase())) {
      return;
    }
    setConfiguracao({ ...configuracao, required_documents: [...configuracao.required_documents, nome] });
  }

  function adicionarDocumento() {
    incluirDocumento(documentoNovo);
    setDocumentoNovo("");
  }

  const sugestoesChecklist = useMemo(() => {
    if (!configuracao) return [];
    const ja = new Set(configuracao.required_documents.map((d) => d.toLocaleLowerCase()));
    return checklistAcao.filter((item) => !ja.has(item.nome.toLocaleLowerCase()));
  }, [checklistAcao, configuracao]);

  const semSecoes = useMemo(
    () => pecas.filter((peca) => !peca.eligibility.eligible_for_section_profile).length,
    [pecas],
  );

  return (
    <div className="flex flex-col gap-[1.1rem] max-w-[980px] mx-auto px-4 pt-[1.4rem] pb-12">
      {/* "Voltar" acima do título, como nos demais módulos: ao lado do `<h1>`,
        * numa tela estreita, o título quebrava em duas linhas e o botão sentava
        * por cima. */}
      <div>
        <Botao variante="texto" onClick={onVoltar}>
          ← Voltar
        </Botao>
        <h1 className="mt-[0.45rem] mb-0 font-titulo text-[1.45rem] leading-[1.2] text-tinta">Modelos de petição do escritório</h1>
        <p className="mt-[0.45rem] mb-0 max-w-[62ch] text-tinta-3 text-sm leading-[1.5]">
          Quanto mais petições reais e revisões finais você cadastrar, melhor o sistema
          mede o vocabulário, a estrutura, o tamanho e o ritmo do escritório. Com poucas
          peças ele usa um perfil aproximado; a resposta melhora progressivamente conforme
          recebe exemplos variados da mesma ação.
        </p>
      </div>

      <Cartao titulo="Modelo visual geral dos documentos">
        <p className="mt-2 mb-4 text-tinta-3 text-sm leading-[1.5]">
          Envie um documento institucional em <code>.docx</code>. O sistema extrai somente
          a logo do cabeçalho e a fonte-base e aplica essa identidade às novas petições;
          o conteúdo jurídico do arquivo não é copiado.
        </p>
        <div className="flex flex-wrap items-center justify-between gap-4 rounded-campo border border-borda bg-papel-2 p-4">
          <div className="flex min-w-0 items-center gap-4">
            {/* A LOGO QUE VAI SAIR NA PETIÇÃO, à vista.
              *
              * O cartão dizia o nome do arquivo e a fonte, e mais nada — quem
              * trocava o modelo só descobria qual imagem o extrator escolheu ao
              * abrir a primeira petição pronta. E há o que escolher: um .docx
              * institucional costuma ter várias imagens, e a heurística prefere
              * a que está relacionada por um cabeçalho.
              *
              * A chave força o navegador a rebuscar quando o modelo muda; sem
              * ela a logo antiga ficaria na tela justamente no momento em que
              * ela existe para confirmar a troca. */}
            {modeloVisual && (
              /* eslint-disable-next-line @next/next/no-img-element -- vem da
                 API com `no-store`, e o otimizador do Next a cachearia. */
              <img
                key={modeloVisual.atualizado_em ?? modeloVisual.arquivo}
                className="h-14 w-auto max-w-[180px] flex-none rounded-campo border border-borda bg-papel object-contain p-1"
                src={urlApi(
                  `/api/modelos/peticao/visual/logo?v=${encodeURIComponent(
                    modeloVisual.atualizado_em ?? modeloVisual.arquivo,
                  )}`,
                )}
                alt={`Logo de ${modeloVisual.arquivo}, como sairá no cabeçalho das petições`}
              />
            )}
            <div className="min-w-0">
            <div className="font-semibold text-tinta">
              {modeloVisual?.arquivo ?? "Carregando padrão visual…"}
            </div>
            <div className="mt-1 text-xs text-tinta-3">
              Fonte: {modeloVisual?.fonte ?? "—"}
              {modeloVisual?.origem === "embutido" ? " · padrão atual Lara & Melo" : " · modelo substituível do escritório"}
            </div>
            <div className="mt-1 text-[11px] text-tinta-3">
              É esta logo que será carimbada no cabeçalho das próximas petições.
            </div>
            </div>
          </div>
          <div className="flex flex-wrap gap-2">
            <label className="inline-flex cursor-pointer items-center rounded-campo bg-acao px-4 py-2 text-sm font-semibold text-white hover:opacity-90">
              {enviandoVisual ? "Processando…" : modeloVisual?.origem === "banco" ? "Trocar modelo" : "Enviar novo modelo"}
              <input
                className="sr-only"
                type="file"
                accept=".docx"
                disabled={enviandoVisual}
                onChange={(evento) => {
                  const arquivo = evento.target.files?.[0];
                  evento.target.value = "";
                  if (arquivo) void trocarModeloVisual(arquivo);
                }}
              />
            </label>
            {modeloVisual?.origem === "banco" && (
              <Botao variante="texto" disabled={enviandoVisual} onClick={() => void restaurarVisual()}>
                Restaurar Lara & Melo
              </Botao>
            )}
          </div>
        </div>

        {modeloVisual && (
          <div className="mt-4">
            <div className="mb-2 flex items-center justify-between gap-3">
              <strong className="text-sm text-tinta">Prévia do documento</strong>
              <span className="text-[11px] text-tinta-3">Cabeçalho e fonte aplicados às novas petições</span>
            </div>
            <div className="overflow-x-auto rounded-campo border border-borda bg-papel-3 p-3 sm:p-5">
              <article
                className="mx-auto min-h-[430px] w-full max-w-[610px] bg-white px-[9%] py-[7%] text-[#202020] shadow-cartao"
                style={{ fontFamily: `"${modeloVisual.fonte || "Arial"}", Arial, sans-serif` }}
                aria-label="Prévia do modelo visual do escritório"
              >
                <header className="mb-10 border-b border-[#d7d7d7] pb-4">
                  {/* eslint-disable-next-line @next/next/no-img-element -- mesma imagem
                     dinâmica e sem cache exibida acima. */}
                  <img
                    className="h-16 max-w-[220px] object-contain object-left"
                    src={urlApi(
                      `/api/modelos/peticao/visual/logo?v=${encodeURIComponent(
                        modeloVisual.atualizado_em ?? modeloVisual.arquivo,
                      )}`,
                    )}
                    alt="Logo no cabeçalho da prévia"
                  />
                </header>
                <p className="mb-8 text-center text-[11px] font-bold uppercase leading-relaxed">
                  Excelentíssimo(a) Senhor(a) Doutor(a) Juiz(a) da Vara do Trabalho
                </p>
                <h4 className="mb-4 text-center text-sm font-bold uppercase">Petição inicial</h4>
                <p className="mb-3 text-justify text-[11px] leading-[1.75]">
                  Nome do cliente, já qualificado nos autos, por seus advogados, apresenta a
                  presente petição conforme os fatos, fundamentos e documentos do caso.
                </p>
                <p className="text-justify text-[11px] leading-[1.75]">
                  Esta é somente uma prévia visual. Nenhum conteúdo jurídico deste exemplo será
                  incluído nas peças geradas.
                </p>
              </article>
            </div>
          </div>
        )}
      </Cartao>

      {erroCarregamento && (
        <Aviso tom="critico" titulo="Não foi possível carregar esta ação">
          {erroCarregamento} Tente novamente antes de alterar os modelos ou a configuração.
        </Aviso>
      )}

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

      {configuracao && (
        <Cartao titulo="Configuração da peça">
          <p className="mt-2 mb-4 text-tinta-3 text-sm leading-[1.5]">
            Configure este tipo de documento para a ação escolhida. As regras e a checklist
            acompanham o estilo aprendido e entram diretamente na geração da IA Jurídica.
          </p>
          <div className="flex flex-wrap gap-[0.9rem]">
            <label className={CAMPO}>
              <span>Nome do tipo de documento</span>
              <input className={SELECT} value={configuracao.display_name}
                onChange={(evento) => setConfiguracao({ ...configuracao, display_name: evento.target.value })} />
            </label>
            <label className={CAMPO}>
              <span>Ação vinculada</span>
              <input className={SELECT} value={acoes.find((item) => item.code === acao)?.label ?? acao} disabled />
            </label>
          </div>
          <label className="mt-4 flex flex-col gap-2 text-tinta-3 text-xs">
            <span>Orientações de conteúdo e redação</span>
            <textarea className={`${SELECT} min-h-28 resize-y`} value={configuracao.drafting_instructions}
              placeholder="Ex.: destacar a incapacidade laboral e separar os pedidos subsidiários."
              onChange={(evento) => setConfiguracao({ ...configuracao, drafting_instructions: evento.target.value })} />
          </label>
          <div className="mt-4 rounded-campo border border-borda-forte bg-papel-2 px-4 py-3">
            <strong className="text-sm text-tinta">Documentos relacionados a esta petição / ação</strong>
            <p className="mt-1 mb-0 text-xs text-tinta-3 leading-[1.5]">
              Liste o que a IA precisa ter no dossiê para gerar a peça. Clique nas
              sugestões do checklist desta ação, ou digite um nome e use Adicionar.
              Depois clique em <strong>Salvar configuração</strong> — sem salvar, a lista
              não fica gravada.
            </p>

            {sugestoesChecklist.length > 0 && (
              <div className="mt-3">
                <span className="text-[11px] font-semibold uppercase tracking-[0.08em] text-tinta-3">
                  Checklist desta ação — clique para incluir
                </span>
                <ul className="mt-2 flex list-none flex-wrap gap-2 p-0">
                  {sugestoesChecklist.map((item) => (
                    <li key={item.codigo}>
                      <button
                        type="button"
                        className={
                          "rounded-pill border px-3 py-1.5 text-xs cursor-pointer transition-colors " +
                          (item.obrigatorio
                            ? "border-acao-borda bg-acao-clara text-acao hover:bg-acao hover:text-papel"
                            : "border-borda bg-papel text-tinta hover:border-borda-forte hover:bg-papel-3")
                        }
                        onClick={() => incluirDocumento(item.nome)}
                        title={item.obrigatorio ? "Obrigatório no checklist do caso" : "Opcional no checklist do caso"}
                      >
                        {item.obrigatorio ? "● " : ""}
                        {item.nome}
                      </button>
                    </li>
                  ))}
                </ul>
              </div>
            )}

            <div className="mt-3 flex gap-2">
              <input
                className={`${SELECT} flex-1`}
                value={documentoNovo}
                placeholder="Ex.: laudo médico, CNIS, procuração"
                onChange={(evento) => setDocumentoNovo(evento.target.value)}
                onKeyDown={(evento) => {
                  if (evento.key === "Enter") {
                    evento.preventDefault();
                    adicionarDocumento();
                  }
                }}
              />
              <Botao variante="secundario" onClick={adicionarDocumento}>
                Adicionar
              </Botao>
            </div>

            {configuracao.required_documents.length ? (
              <ul className="mt-3 flex list-none flex-wrap gap-2 p-0">
                {configuracao.required_documents.map((documento) => (
                  <li
                    key={documento}
                    className="flex items-center gap-2 rounded-pill border border-borda bg-papel px-3 py-1.5 text-xs text-tinta"
                  >
                    {documento}
                    <button
                      type="button"
                      className="text-critico cursor-pointer"
                      aria-label={`Remover ${documento}`}
                      onClick={() =>
                        setConfiguracao({
                          ...configuracao,
                          required_documents: configuracao.required_documents.filter(
                            (item) => item !== documento,
                          ),
                        })
                      }
                    >
                      ×
                    </button>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="mt-3 mb-0 text-xs text-tinta-3">
                Nenhum documento exigido foi cadastrado ainda
                {checklistAcao.length
                  ? " — use as sugestões do checklist acima."
                  : "."}
              </p>
            )}
          </div>
          <div className="mt-4 flex flex-col items-stretch gap-2 sm:flex-row sm:items-center sm:justify-between">
            {erro && (
              <Aviso tom="critico" titulo="Não salvou">
                {erro}
              </Aviso>
            )}
            <div className="flex justify-end sm:ml-auto">
              <Botao
                onClick={() => void salvarConfiguracao()}
                disabled={salvandoConfiguracao || !configuracao.display_name.trim()}
              >
                {salvandoConfiguracao ? "Salvando…" : "Salvar configuração"}
              </Botao>
            </div>
          </div>
        </Cartao>
      )}

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
