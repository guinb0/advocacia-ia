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

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  ArrowLeft,
  ChevronDown,
  FileText,
  PenLine,
  RotateCcw,
  Upload,
} from "lucide-react";

import { Aviso, Botao, Cartao, Paginacao, Selo, Tabela, Th, Vazio } from "@/components/ui/Basicos";
import { BotaoProcesso } from "@/components/ui/BotaoProcesso";
import {
  ApiError,
  enviarModeloVisualPeticao,
  enviarLogoModeloVisualPeticao,
  obterConfiguracaoVisualPeticao,
  salvarConfiguracaoVisualPeticao,
  type ConfiguracaoVisualPeticao,
  type ModeloVisualPeticao,
  obterModeloVisualPeticao,
  obterSkillDePeticao,
  restaurarModeloVisualPeticao,
  salvarSkillDePeticao,
  type SkillDePeticao,
  urlApi,
} from "@/lib/api";

/* `.tabela th/td` era seletor descendente; sem equivalente no Tailwind, a regra
 * vira constante e cada célula a carrega. */
/** Um atributo captado do modelo do escritório: rótulo em cima, valor abaixo. */
function ItemIdentificado({ rotulo, valor }: { rotulo: string; valor: string }) {
  return (
    <div className="grid min-w-0 gap-[2px]">
      <dt className="text-[11px] font-medium uppercase tracking-wide text-tinta-3">{rotulo}</dt>
      <dd className="m-0 text-sm font-semibold text-tinta [overflow-wrap:anywhere]">{valor}</dd>
    </div>
  );
}

const CELULA = "px-3 py-2 text-left border-b border-borda";
const CABECALHO_CELULA =
  "px-3 py-2 text-tinta-3 text-xs font-semibold uppercase tracking-[0.03em] whitespace-nowrap";
const ITEM_TOPO = "flex min-w-0 items-center justify-between gap-[0.6rem]";
const CAMPO = "flex min-w-0 flex-1 flex-col gap-[0.28rem] text-xs text-tinta-3";
/* Cor explícita no select E no option não é redundância: no Windows a lista
 * aberta de um select sem cor própria pode herdar as do sistema — deu faixa
 * preta sem texto legível. */
const SELECT =
  "min-h-10 min-w-0 px-[0.6rem] py-[0.55rem] border border-borda-campo rounded-campo bg-papel text-tinta text-sm " +
  "[&>option]:bg-papel [&>option]:text-tinta";

import {
  ESCOPO_GERAL,
  type ConfigAgente,
  type ConfiguracaoDeGeracao,
  type PecaDeEstilo,
  type PerfilDeEstilo,
  configDoAgente,
  configuracaoDeGeracao,
  enviarPecaDeEstilo,
  pecasDeEstilo,
  perfilDeEstilo,
  removerPecaDeEstilo,
  salvarConfiguracaoDeGeracao,
} from "@/lib/agente";

const TIPOS = [{ codigo: "INITIAL_PETITION", rotulo: "Petição inicial" }];
const ITENS_POR_PAGINA = 8;

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
  /* O corpus deixou de ser separado por ação: é um acervo só.
   *
   * Com 5 peças divididas entre as ações, nenhum balde chegava à amostra mínima
   * que o perfil exige, e o padrão nunca se formava — o escritório cadastrava e
   * não via efeito. Num escopo único, toda peça enviada conta para o mesmo
   * padrão, que é o que "quanto mais colocarem, melhor" pressupõe.
   *
   * Constante, e não estado: a tela não escolhe mais escopo, mas as chamadas ao
   * agente continuam exigindo um código (a rota é de outro serviço). */
  const acao = ESCOPO_GERAL;
  const [tipo, setTipo] = useState(TIPOS[0].codigo);

  const [pecas, setPecas] = useState<PecaDeEstilo[]>([]);
  const [perfil, setPerfil] = useState<PerfilDeEstilo | null>(null);
  const [configuracao, setConfiguracao] = useState<ConfiguracaoDeGeracao | null>(null);
  const [documentoNovo, setDocumentoNovo] = useState("");
  const [salvandoConfiguracao, setSalvandoConfiguracao] = useState(false);

  const [enviando, setEnviando] = useState(false);
  const [arrastando, setArrastando] = useState(false);
  const [filaEnvio, setFilaEnvio] = useState<ItemEnvio[]>([]);
  const [removendo, setRemovendo] = useState<string | null>(null);
  const [erro, setErro] = useState<string | null>(null);
  const [erroCarregamento, setErroCarregamento] = useState<string | null>(null);
  const [recado, setRecado] = useState<string | null>(null);
  const [modeloVisual, setModeloVisual] = useState<ModeloVisualPeticao | null>(null);
  const [configVisual, setConfigVisual] = useState<ConfiguracaoVisualPeticao | null>(null);
  const [salvandoVisual, setSalvandoVisual] = useState(false);
  const [carregandoModeloVisual, setCarregandoModeloVisual] = useState(true);
  // Ligado, desligado ou ainda não sabemos — três estados, não dois: enquanto `null`, a
  // tela não decide nada (nem chama a taxonomia, nem mostra o aviso de "não ativado").
  const [configAgente, setConfigAgente] = useState<ConfigAgente | null>(null);

  // Orientação de redação do escritório — UMA, para toda peça. Era uma por
  // categoria de ação; virou única porque o que o escritório ensina sobre como
  // redigir não muda com o tipo da ação. Local ao Acervo, funciona com ou sem o
  // agente jurídico ligado.
  const [skill, setSkill] = useState<SkillDePeticao | null>(null);
  const [instrucoesSkill, setInstrucoesSkill] = useState("");
  const [carregandoSkills, setCarregandoSkills] = useState(true);
  const [salvandoSkill, setSalvandoSkill] = useState(false);
  const [erroSkill, setErroSkill] = useState<string | null>(null);
  const [recadoSkill, setRecadoSkill] = useState<string | null>(null);
  const [enviandoVisual, setEnviandoVisual] = useState(false);
  const [paginaPecas, setPaginaPecas] = useState(1);
  const [totalPecas, setTotalPecas] = useState(0);
  const [totalPaginasPecas, setTotalPaginasPecas] = useState(1);

  /* O aviso de erro nasce no alto da tela, e o erro que o produz costuma
   * acontecer lá embaixo — a recusa de um arquivo chega depois que a pessoa
   * rolou até a área de envio. Pior: um erro que derruba a integração esconde
   * tudo o que vem abaixo dele, a página encolhe e a rolagem antiga passa a
   * apontar para o vazio. Sem isto o sintoma é uma tela em branco sem
   * explicação; com isto, a explicação vem até os olhos. */
  const avisoDeErro = useRef<HTMLDivElement>(null);
  const avisoDeCarregamento = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const alvo = erro ? avisoDeErro.current : erroCarregamento ? avisoDeCarregamento.current : null;
    alvo?.scrollIntoView({ behavior: "smooth", block: "center" });
  }, [erro, erroCarregamento]);


  useEffect(() => {
    void obterModeloVisualPeticao()
      .then(setModeloVisual)
      .catch((falha) => setErro(
        falha instanceof ApiError ? falha.message : "Não foi possível carregar o modelo visual geral.",
      ))
      .finally(() => setCarregandoModeloVisual(false));
  }, []);

  useEffect(() => {
    void obterConfiguracaoVisualPeticao().then(setConfigVisual).catch((falha) => setErro(
      falha instanceof ApiError ? falha.message : "Não foi possível carregar a configuração visual.",
    ));
  }, []);

  async function salvarVisual() {
    if (!configVisual) return;
    setSalvandoVisual(true);
    setErro(null);
    try {
      setConfigVisual(await salvarConfiguracaoVisualPeticao(configVisual));
      setRecado("Modelo visual salvo. As próximas petições já sairão com este padrão.");
    } catch (falha) {
      setErro(falha instanceof ApiError ? falha.message : "Não foi possível salvar o modelo visual.");
    } finally {
      setSalvandoVisual(false);
    }
  }

  async function trocarLogo(arquivo: File) {
    setEnviandoVisual(true);
    try {
      await enviarLogoModeloVisualPeticao(arquivo);
      setModeloVisual((atual) => atual ? { ...atual, atualizado_em: new Date().toISOString() } : atual);
      setRecado("Logo do escritório atualizada.");
    } catch (falha) {
      setErro(falha instanceof ApiError ? falha.message : "Não foi possível enviar a logo.");
    } finally {
      setEnviandoVisual(false);
    }
  }

  async function trocarModeloVisual(arquivo: File) {
    setEnviandoVisual(true);
    setErro(null);
    setRecado(null);
    try {
      const salvo = await enviarModeloVisualPeticao(arquivo);
      setModeloVisual(salvo);
      setConfigVisual(await obterConfiguracaoVisualPeticao());
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
    void obterSkillDePeticao()
      .then((salva) => {
        setSkill(salva);
        setInstrucoesSkill(salva.instrucoes ?? "");
      })
      .catch((falha) =>
        setErroSkill(falha instanceof ApiError ? falha.message : "Não foi possível carregar a orientação."),
      )
      .finally(() => setCarregandoSkills(false));
  }, []);

  async function salvarSkill() {
    setSalvandoSkill(true);
    setErroSkill(null);
    setRecadoSkill(null);
    try {
      const salvo = await salvarSkillDePeticao(instrucoesSkill);
      setSkill(salvo);
      setRecadoSkill("Orientação salva. Toda petição gerada a partir de agora já a segue.");
    } catch (falha) {
      setErroSkill(falha instanceof ApiError ? falha.message : "Não foi possível salvar a orientação.");
    } finally {
      setSalvandoSkill(false);
    }
  }

  useEffect(() => {
    void configDoAgente()
      .then(setConfigAgente)
      // Falha na própria checagem também é "não ligado": sem isso a tela tentaria a
      // taxonomia mesmo assim e trocaria um aviso calmo por um erro vermelho.
      .catch(() => setConfigAgente({ ligado: false, disponivel: false, url: "", jurisdicao_padrao: "" }));
  }, []);

  /* A taxonomia de ações e o checklist por ação saíram junto com o seletor:
   * não há mais escopo a escolher, então não há lista a carregar nem categoria
   * do Acervo a casar com ela. Uma chamada a menos ao agente na abertura. */

  useEffect(() => {
    setPaginaPecas(1);
  }, [tipo]);

  const recarregar = useCallback(async () => {
    if (!acao) return;
    setErroCarregamento(null);
    const [resultadoPecas, resultadoPerfil, resultadoConfig] = await Promise.allSettled([
      pecasDeEstilo(acao, {
        documentType: tipo,
        pagina: paginaPecas,
        tamanho: ITENS_POR_PAGINA,
      }),
      perfilDeEstilo(acao, tipo),
      configuracaoDeGeracao(acao, tipo),
    ]);
    const falhas: string[] = [];

    if (resultadoPecas.status === "fulfilled") {
      setPecas(resultadoPecas.value.items);
      setTotalPecas(resultadoPecas.value.total);
      setTotalPaginasPecas(resultadoPecas.value.paginas);
      if (paginaPecas > resultadoPecas.value.paginas) {
        setPaginaPecas(resultadoPecas.value.paginas);
      }
    } else {
      setPecas([]);
      setTotalPecas(0);
      setTotalPaginasPecas(1);
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
      // `acao` é constante agora (o escopo único), então esta conferência deixou
      // de separar ações e passou a separar ESCOPOS: um perfil global antigo,
      // devolvido por versão antiga do agente, continua não sendo exibido como
      // se fosse deste acervo.
    } else if (resultadoPerfil.reason instanceof ApiError && resultadoPerfil.reason.status === 404) {
      setPerfil(null);
    } else {
      setPerfil(null);
      falhas.push(
        resultadoPerfil.reason instanceof ApiError
          ? resultadoPerfil.reason.message
          : "Não foi possível medir o padrão do escritório.",
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
          : "Não foi possível carregar a configuração das peças.",
      );
    }

    if (falhas.length) setErroCarregamento([...new Set(falhas)].join(" "));
  }, [acao, paginaPecas, tipo]);

  useEffect(() => {
    void recarregar();
  }, [recarregar]);

  async function enviar(arquivos: File[]) {
    if (!arquivos.length) return;
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
        await enviarPecaDeEstilo(arquivo, tipo);
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

  /* As sugestões vinham do checklist da AÇÃO escolhida. Sem escopo por ação não
   * há checklist a oferecer: os documentos exigidos passam a ser digitados, que
   * é o que já acontecia para qualquer nome fora do checklist. */

  const semSecoes = useMemo(
    () => pecas.filter((peca) => !peca.eligibility.eligible_for_section_profile).length,
    [pecas],
  );
  const documentosObrigatorios = configuracao?.required_documents.length ?? 0;
  const inicioPecas = totalPecas ? (paginaPecas - 1) * ITENS_POR_PAGINA : 0;
  const fimPecas = Math.min(inicioPecas + pecas.length, totalPecas);

  return (
    <div className="flex min-w-0 max-w-full flex-col gap-5">
      <section className="overflow-hidden rounded-cartao border border-borda-forte bg-papel shadow-cartao">
        <div className="flex min-w-0 flex-wrap items-start justify-between gap-4 border-b border-borda bg-papel-2 px-5 py-4">
          <div className="min-w-0">
            <Botao variante="texto" onClick={onVoltar}>
              <ArrowLeft size={15} aria-hidden /> Voltar
            </Botao>
            <p className="mt-3 text-xs font-semibold uppercase tracking-[0.14em] text-tinta-3">
              Produção jurídica
            </p>
            <div className="mt-1 flex min-w-0 items-center gap-3">
              <span className="grid h-10 w-10 shrink-0 place-items-center rounded-campo border border-acao-borda bg-acao-clara text-acao">
                <PenLine size={20} aria-hidden />
              </span>
              <h1 className="m-0 min-w-0 truncate font-titulo text-[1.7rem] font-semibold leading-[1.15] text-tinta">
                Modelos de petição do escritório
              </h1>
            </div>
            <p className="mt-2 mb-0 max-w-[72ch] text-sm leading-[1.55] text-tinta-3">
              Cadastre as peças do escritório, mantenha os documentos exigidos e acompanhe a qualidade das amostras. Quanto mais peças, mais firme o padrão medido.
            </p>
          </div>
          <div className="grid min-w-[220px] grid-cols-3 gap-2 rounded-campo border border-borda bg-papel p-2 text-center">
            <div className="min-w-0 px-2 py-1">
              <span className="block truncate text-[11px] text-tinta-3">Amostras</span>
              <strong className="block font-codigo text-lg text-tinta">{totalPecas}</strong>
            </div>
            <div className="min-w-0 border-x border-borda px-2 py-1">
              <span className="block truncate text-[11px] text-tinta-3">Padrão</span>
              <strong className="block truncate text-sm leading-7 text-tinta">
                {perfil ? "Medido" : "Em formação"}
              </strong>
            </div>
            <div className="min-w-0 px-2 py-1">
              <span className="block truncate text-[11px] text-tinta-3">Docs</span>
              <strong className="block font-codigo text-lg text-tinta">{documentosObrigatorios}</strong>
            </div>
          </div>
        </div>
      </section>

      {erro && (
        <div ref={avisoDeErro}>
          <Aviso tom="critico" titulo="A ação não foi concluída">
            {erro}
          </Aviso>
        </div>
      )}
      {recado && <Aviso tom="ok">{recado}</Aviso>}

      <div className="grid min-w-0 grid-cols-[minmax(0,1.15fr)_minmax(300px,0.85fr)] items-start gap-4 max-[980px]:grid-cols-1">
      <div className="flex min-w-0 flex-col gap-4">
      <Cartao titulo="Identidade dos documentos" className="min-w-0 overflow-hidden">
        <p className="mt-2 mb-4 text-tinta-3 text-sm leading-[1.5]">
          Selecione um documento com a logo e o padrão do seu escritório que vamos captar o
          modelo — logo, fonte, tamanho, espaçamento, alinhamento e margens. O conteúdo
          jurídico do arquivo de referência não é copiado.
        </p>
        <div className="flex min-w-0 flex-wrap items-center justify-between gap-4 rounded-campo border border-borda bg-papel-2 p-4">
          <div className="flex min-w-0 items-center gap-3">
            <span className="grid h-10 w-10 shrink-0 place-items-center rounded-campo border border-borda bg-papel text-acao">
              <FileText size={18} aria-hidden />
            </span>
            <div className="min-w-0">
              <div className="truncate font-semibold text-tinta" title={modeloVisual?.arquivo ?? undefined}>
                {carregandoModeloVisual ? "Carregando padrão visual…" : modeloVisual?.arquivo ?? "Padrão indisponível"}
              </div>
              <div className="mt-1 truncate text-xs text-tinta-3">
                Fonte: {modeloVisual?.fonte ?? "—"}
                {modeloVisual
                  ? modeloVisual.origem === "embutido"
                    ? " · padrão atual Lara & Melo"
                    : " · modelo substituível do escritório"
                  : ""}
              </div>
              <div className="mt-1 text-[11px] text-tinta-3">
                É esta logo que será carimbada no cabeçalho das próximas petições.
              </div>
            </div>
          </div>
          <div className="flex flex-wrap gap-2">
            <label className="inline-flex min-h-10 cursor-pointer items-center gap-2 rounded-campo bg-acao px-4 py-2 text-sm font-semibold text-white hover:bg-acao-forte">
              <Upload size={16} aria-hidden />
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
              <BotaoProcesso
                variante="texto"
                aguardando={enviandoVisual ? "Aguarde: o modelo enviado ainda está sendo processado." : false}
                textoProcessando="Restaurando…"
                onClick={() => restaurarVisual()}
              >
                <RotateCcw size={15} aria-hidden /> Restaurar Lara & Melo
              </BotaoProcesso>
            )}
          </div>
        </div>

        {modeloVisual && (
          <div className="mt-4 rounded-campo border border-borda bg-papel-2 p-4">
            <div className="mb-3 flex items-center gap-2">
              <span className="grid h-6 w-6 place-items-center rounded-full bg-ok-claro text-ok" aria-hidden>
                ✓
              </span>
              <h4 className="m-0 text-sm font-semibold text-tinta">O que identificamos no seu modelo</h4>
            </div>
            <dl className="grid grid-cols-2 gap-x-6 gap-y-3 max-[560px]:grid-cols-1">
              <ItemIdentificado rotulo="Fonte" valor={modeloVisual.fonte || "—"} />
              {modeloVisual.atributos?.tamanho_fonte_pt != null && (
                <ItemIdentificado rotulo="Tamanho" valor={`${modeloVisual.atributos.tamanho_fonte_pt} pt`} />
              )}
              {modeloVisual.atributos?.espacamento_linha != null && (
                <ItemIdentificado rotulo="Espaçamento" valor={`${modeloVisual.atributos.espacamento_linha} linha(s)`} />
              )}
              {modeloVisual.atributos?.alinhamento && (
                <ItemIdentificado rotulo="Alinhamento" valor={modeloVisual.atributos.alinhamento} />
              )}
              {modeloVisual.atributos?.margens_cm &&
                Object.values(modeloVisual.atributos.margens_cm).some((v) => v != null) && (
                  <ItemIdentificado
                    rotulo="Margens (cm)"
                    valor={(["top", "right", "bottom", "left"] as const)
                      .map((l) => {
                        const v = modeloVisual.atributos?.margens_cm?.[l];
                        const nome = { top: "sup", right: "dir", bottom: "inf", left: "esq" }[l];
                        return v != null ? `${nome} ${v}` : null;
                      })
                      .filter(Boolean)
                      .join(" · ")}
                  />
                )}
              <ItemIdentificado rotulo="Logo" valor="captada do cabeçalho (veja a prévia)" />
            </dl>
          </div>
        )}

        {modeloVisual && (
          <div className="mt-4 grid gap-4 rounded-campo border border-borda bg-papel-2 p-4 lg:grid-cols-[minmax(0,1fr)_320px]">
            <div className="min-w-0">
              <h4 className="m-0 text-sm font-semibold text-tinta">Prévia integral do documento importado</h4>
              <p className="mt-1 text-xs text-tinta-3">É o próprio modelo convertido para PDF, sem trocar o conteúdo ou o layout.</p>
              {modeloVisual.origem === "banco" ? (
                <iframe
                  className="mt-3 h-[680px] w-full rounded border border-borda bg-white"
                  src={urlApi(`/api/modelos/peticao/visual/preview?v=${encodeURIComponent(modeloVisual.atualizado_em ?? modeloVisual.arquivo)}`)}
                  title="Prévia integral do modelo visual"
                />
              ) : <p className="mt-3 rounded border border-dashed border-borda p-6 text-sm text-tinta-3">Envie um .docx do escritório para conferir todas as páginas aqui.</p>}
            </div>
            <div className="min-w-0">
              <h4 className="m-0 text-sm font-semibold text-tinta">Formatação editável</h4>
              <p className="mt-1 text-xs text-tinta-3">A IA extrai o padrão inicial; o escritório confirma ou altera cada medida.</p>
              {configVisual && <div className="mt-3 grid gap-3">
                <label className={CAMPO}>Fonte<input className={SELECT} value={configVisual.fonte} placeholder={modeloVisual.fonte} onChange={(e) => setConfigVisual({ ...configVisual, fonte: e.target.value })} /></label>
                {([
                  ["tamanho_fonte_pt", "Tamanho da fonte (pt)", 0.5],
                  ["espacamento_linha", "Espaçamento entre linhas", 0.1],
                  ["recuo_primeira_linha_cm", "Recuo da primeira linha (cm)", 0.1],
                  ["margem_superior_cm", "Margem superior (cm)", 0.1],
                  ["margem_direita_cm", "Margem direita (cm)", 0.1],
                  ["margem_inferior_cm", "Margem inferior (cm)", 0.1],
                  ["margem_esquerda_cm", "Margem esquerda (cm)", 0.1],
                  ["altura_logo_cm", "Altura da logo (cm)", 0.1],
                ] as const).map(([campo, rotulo, passo]) => <label className={CAMPO} key={campo}>{rotulo}<input type="number" step={passo} className={SELECT} value={configVisual[campo]} onChange={(e) => setConfigVisual({ ...configVisual, [campo]: Number(e.target.value) })} /></label>)}
                <label className={CAMPO}>Corpo do texto<select className={SELECT} value={configVisual.alinhamento_corpo} onChange={(e) => setConfigVisual({ ...configVisual, alinhamento_corpo: e.target.value as ConfiguracaoVisualPeticao["alinhamento_corpo"] })}><option value="justificado">Justificado</option><option value="esquerda">À esquerda</option><option value="direita">À direita</option></select></label>
                <label className={CAMPO}>Títulos<select className={SELECT} value={configVisual.alinhamento_titulos} onChange={(e) => setConfigVisual({ ...configVisual, alinhamento_titulos: e.target.value as ConfiguracaoVisualPeticao["alinhamento_titulos"] })}><option value="esquerda">À esquerda</option><option value="centralizado">Centralizado</option></select></label>
                <label className="inline-flex min-h-10 cursor-pointer items-center justify-center gap-2 rounded-campo border border-borda bg-papel px-3 text-sm font-semibold text-acao"><Upload size={15} />Trocar logo<input className="sr-only" type="file" accept=".png,.jpg,.jpeg" onChange={(e) => { const arquivo = e.target.files?.[0]; e.target.value = ""; if (arquivo) void trocarLogo(arquivo); }} /></label>
                <BotaoProcesso variante="primario" processando={salvandoVisual} textoProcessando="Salvando…" onClick={() => void salvarVisual()}>Salvar modelo visual</BotaoProcesso>
              </div>}
            </div>
          </div>
        )}

        {modeloVisual && (
          <details className="group mt-4 overflow-hidden rounded-campo border border-borda bg-papel-2">
            <summary className="flex min-h-11 cursor-pointer list-none items-center justify-between gap-3 px-4 py-2 text-sm font-semibold text-tinta marker:content-none">
              Conferir prévia do documento
              <ChevronDown className="shrink-0 text-tinta-3 transition-transform group-open:rotate-180" size={17} aria-hidden />
            </summary>
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
          </details>
        )}
      </Cartao>

      <Cartao titulo="Orientação de redação do escritório" className="min-w-0 overflow-hidden">
        <p className="mt-2 mb-4 text-tinta-3 text-sm leading-[1.5]">
          Uma orientação que a IA segue ao analisar e redigir <strong>qualquer</strong> petição —
          o que destacar, como abordar a tese, o que nunca pode faltar. Vale para toda peça
          gerada a partir de agora, sem separar por tipo de ação, e funciona independente do
          agente jurídico.
        </p>

        {erroSkill && (
          <Aviso tom="critico" titulo="Não foi possível carregar ou salvar">
            {erroSkill}
          </Aviso>
        )}
        {recadoSkill && <Aviso tom="ok">{recadoSkill}</Aviso>}

        <label className="flex flex-col gap-2 text-tinta-3 text-xs">
          <span>Instruções de redação</span>
          <textarea
            className={`${SELECT} min-h-32 resize-y`}
            value={instrucoesSkill}
            disabled={carregandoSkills}
            placeholder="Ex.: dar ênfase ao nexo causal entre a doença e a função exercida, sempre pedir dano moral em separado do material."
            onChange={(evento) => setInstrucoesSkill(evento.target.value)}
          />
        </label>

        {skill?.atualizado_por && (
          <p className="mt-2 mb-0 text-[11px] text-tinta-3">
            Última alteração por <strong>{skill.atualizado_por}</strong>.
          </p>
        )}

        <div className="mt-4 flex justify-end">
          <BotaoProcesso
            variante="primario"
            onClick={() => salvarSkill()}
            processando={salvandoSkill}
            textoProcessando="Salvando…"
          >
            Salvar orientação
          </BotaoProcesso>
        </div>
      </Cartao>

      {configAgente && !configAgente.ligado && (
        <Aviso tom="atencao" titulo="Padrão de escrita por ação ainda não ativado">
          O aprendizado do estilo do escritório por ação (peças de exemplo, padrão medido e
          orientações de redação) depende do agente jurídico, que ainda não está ativo neste
          ambiente. A logo e a fonte acima continuam funcionando normalmente — só esta parte
          fica pendente até a integração ser ligada.
        </Aviso>
      )}

      {configAgente?.ligado && erroCarregamento && (
        <div ref={avisoDeCarregamento}>
          <Aviso tom="critico" titulo="Não foi possível carregar esta ação">
            {erroCarregamento} Tente novamente antes de alterar os modelos ou a configuração.
          </Aviso>
        </div>
      )}

      {configAgente?.ligado && (
      <>
      <Cartao titulo="Adicionar peças" className="min-w-0 overflow-hidden">
        <p className="mt-2 mb-[0.9rem] text-tinta-3 text-sm leading-[1.5]">
          Cada peça adicionada atualiza o perfil de escrita. As correções feitas pelo
          advogado ao aprovar uma minuta também viram aprendizado supervisionado: o sistema
          compara o texto gerado com a versão final, sem copiar fatos de um processo para outro.
        </p>

        <div className="mb-[0.9rem] grid min-w-0 grid-cols-[repeat(auto-fit,minmax(min(100%,220px),1fr))] gap-[0.9rem]">
          {/* O seletor de Ação saiu: toda peça entra no mesmo acervo. */}
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
            "[&>span]:block [&>span]:text-sm " +
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
            className="sr-only"
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
          <span className="flex flex-col items-center">
            <Upload className="mb-2 text-acao" size={24} aria-hidden />
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
                  <small className="max-w-[45%] truncate text-right text-[11px] text-tinta-3" title={item.detalhe}>
                    {item.detalhe ?? ({ aguardando: "aguardando", enviando: "analisando…", concluido: "adicionada", repetido: "repetida", recusado: "recusada" }[item.estado])}
                  </small>
                </li>
              ))}
            </ul>
          </div>
        )}

      </Cartao>

      {configuracao && (
        <Cartao titulo="Configuração da peça" className="min-w-0 overflow-hidden">
          <p className="mt-2 mb-4 text-tinta-3 text-sm leading-[1.5]">
            Configure este tipo de documento. As regras e a lista de documentos acompanham o
            estilo aprendido e entram diretamente na geração da IA Jurídica.
          </p>
          <div className="grid min-w-0 grid-cols-[repeat(auto-fit,minmax(min(100%,220px),1fr))] gap-[0.9rem]">
            <label className={CAMPO}>
              <span>Nome do tipo de documento</span>
              <input className={SELECT} value={configuracao.display_name}
                onChange={(evento) => setConfiguracao({ ...configuracao, display_name: evento.target.value })} />
            </label>
          </div>
          <label className="mt-4 flex flex-col gap-2 text-tinta-3 text-xs">
            <span>Orientações de conteúdo e redação</span>
            <textarea className={`${SELECT} min-h-28 resize-y`} value={configuracao.drafting_instructions}
              placeholder="Ex.: destacar a incapacidade laboral e separar os pedidos subsidiários."
              onChange={(evento) => setConfiguracao({ ...configuracao, drafting_instructions: evento.target.value })} />
          </label>
          <div className="mt-4 rounded-campo border border-borda-forte bg-papel-2 px-4 py-3">
            <strong className="text-sm text-tinta">Documentos relacionados a esta petição</strong>
            <p className="mt-1 mb-0 text-xs text-tinta-3 leading-[1.5]">
              Liste o que a IA precisa ter no dossiê para gerar a peça: digite um nome e use
              Adicionar. Depois clique em <strong>Salvar configuração</strong> — sem salvar, a
              lista não fica gravada.
            </p>

            <div className="mt-3 flex min-w-0 flex-wrap gap-2">
              <input
                className={`${SELECT} min-w-[220px] flex-1`}
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
                    className="flex max-w-full items-center gap-2 rounded-pill border border-borda bg-papel px-3 py-1.5 text-xs text-tinta"
                  >
                    <span className="min-w-0 truncate" title={documento}>{documento}</span>
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
                Nenhum documento exigido foi cadastrado ainda.
              </p>
            )}
          </div>
          <div className="mt-4 flex flex-col items-stretch gap-2 sm:flex-row sm:items-center sm:justify-between">
            <div className="flex justify-end sm:ml-auto">
              <BotaoProcesso
                variante="primario"
                onClick={() => salvarConfiguracao()}
                processando={salvandoConfiguracao}
                textoProcessando="Salvando…"
                pendencia={configuracao.display_name.trim() ? null : "Preencha o nome do tipo de documento."}
                pendenciaAoClicar
              >
                Salvar configuração
              </BotaoProcesso>
            </div>
          </div>
        </Cartao>
      )}
      </>
      )}

      </div>

      {configAgente?.ligado && (
      <aside className="flex min-w-0 flex-col gap-4">
      <PainelPerfil perfil={perfil} total={totalPecas} />

      <Cartao className="min-w-0 overflow-hidden">
        <div className={ITEM_TOPO}>
          <h2 className="m-0 min-w-0 truncate text-tinta font-titulo text-lg font-semibold">Peças cadastradas nesta ação</h2>
          <span className="px-2 py-[0.1rem] rounded-pill bg-papel-3 text-tinta-2 text-xs tabular-nums">{totalPecas}</span>
        </div>

        {semSecoes > 0 && (
          <Aviso tom="atencao" titulo={`${semSecoes} peça(s) sem seções reconhecidas`}>
            Elas continuam ensinando extensão, ritmo de frase e vocabulário — mas não entram
            no padrão de cada seção. Costuma ser documento que não é petição, ou peça cujos
            títulos fogem do usual.
          </Aviso>
        )}

        {pecas.length === 0 ? (
          <Vazio className="mt-3">
            Nenhuma peça nesta ação ainda. O sistema não mistura amostras de outras ações;
            enquanto não houver exemplos próprios, escreve sem um padrão medido para esta ação.
          </Vazio>
        ) : (
          <ul className="list-none mt-[0.7rem] mb-0 p-0 flex flex-col gap-2">
            {pecas.map((peca) => {
              const seg = SEGMENTACAO[peca.segmentation.quality];
              return (
                <li key={peca.id} className="min-w-0 rounded-campo border border-borda px-3 py-[0.65rem]">
                  <div className="grid min-w-0 grid-cols-[minmax(0,1fr)_auto] items-start gap-3 max-[520px]:grid-cols-1">
                    <strong className="min-w-0 flex-1 overflow-hidden text-ellipsis whitespace-nowrap text-sm text-tinta" title={peca.filename ?? "(sem nome)"}>
                      {peca.filename ?? "(sem nome)"}
                    </strong>
                    <div className="flex min-w-0 shrink-0 flex-wrap items-center justify-end gap-2 max-[520px]:justify-start">
                      <Selo tom={seg.tom} simbolo={peca.segmentation.quality === "FULL" ? "✓" : "!"}>
                        {seg.texto}
                      </Selo>
                      <Botao
                        variante="texto"
                        pequeno
                        carregando={removendo === peca.id}
                        textoCarregando="Removendo…"
                        onClick={() => void remover(peca)}
                      >
                        Remover
                      </Botao>
                    </div>
                  </div>
                  <div className="mt-1 truncate text-tinta-3 text-xs tabular-nums">
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
        <Paginacao
          pagina={paginaPecas}
          totalPaginas={totalPaginasPecas}
          total={totalPecas}
          inicio={inicioPecas}
          fim={fimPecas}
          rotulo="peças"
          onPagina={setPaginaPecas}
        />
      </Cartao>
      </aside>
      )}
      </div>
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
      <Cartao titulo="Padrão medido" className="min-w-0 overflow-hidden">
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
    <Cartao className="min-w-0 overflow-hidden">
      <div className={ITEM_TOPO}>
        <h2 className="m-0 min-w-0 truncate text-tinta font-titulo text-lg font-semibold">Padrão medido</h2>
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
        <ul className="my-2 flex list-none flex-col gap-2 p-0">
          {diretrizesDoPadrao(perfil).map((diretriz) => (
            <li key={diretriz} className="line-clamp-2 rounded-campo bg-papel px-3 py-2 text-xs" title={diretriz}>
              {diretriz}
            </li>
          ))}
        </ul>
        <p className="mb-0 mt-2">
          No caso concreto, o sistema manterá essa forma de escrever e adaptará o conteúdo aos
          fatos, provas, pedidos, teses e riscos do dossiê daquele cliente. Para cada seção,
          buscará as passagens mais próximas entre as amostras desta mesma ação. O padrão de
          forma será seguido; nomes, valores e fatos das petições de exemplo nunca serão copiados.
        </p>
      </div>

      <div className="max-w-full overflow-x-auto">
      <Tabela className="min-w-[460px] text-tinta-2">
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
      </div>

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
