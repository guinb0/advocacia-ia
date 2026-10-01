"use client";

import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { ArrowLeftRight, Download, FileText, History, NotebookPen, Plus } from "lucide-react";

import { Aviso, Botao, Cartao, Selo } from "@/components/ui/Basicos";
import {
  ativarSkillPeticao,
  baixarSkillPeticao,
  obterSkillPeticao,
  type EstadoSkillPeticao,
} from "@/lib/api";
import { baixarArquivo } from "@/lib/baixar";
import { cn } from "@/lib/utils";

import { EditarArquivosDaSkill, HistoricoDaSkill, InstrucoesParaIA, dataEHora } from "./EditarSkillDePeticao";

const O_QUE_O_PACOTE_TRAZ: { arquivo: string; papel: string; obrigatorio: boolean }[] = [
  { arquivo: "SKILL.md", papel: "instruções gerais e a tabela de assuntos", obrigatorio: true },
  { arquivo: "references/formatacao.md", papel: "o layout: fonte, margens, espaçamento, títulos (bloco estilo)", obrigatorio: true },
  { arquivo: "references/estrutura_peca.md", papel: "a ordem das partes da petição", obrigatorio: true },
  { arquivo: "references/validacoes.md", papel: "as conferências feitas antes de entregar a peça", obrigatorio: false },
  { arquivo: "references/<assunto>.md", papel: "as regras de cada tipo de ação", obrigatorio: false },
  { arquivo: "references/observacoes.md", papel: "as instruções do escritório, que prevalecem sobre o resto", obrigatorio: false },
  { arquivo: "assets/logo.png", papel: "a logo do cabeçalho", obrigatorio: false },
];

export type PainelDaSkill = "instrucoes" | "trocar" | "desfazer";

function numero(valor: number): string {
  return valor.toLocaleString("pt-BR", { maximumFractionDigits: 2 });
}

function mensagem(e: unknown, padrao: string): string {
  return e instanceof Error && e.message ? e.message : padrao;
}

function BotaoDePainel({
  ativo,
  icone,
  titulo,
  descricao,
  onClick,
}: {
  ativo: boolean;
  icone: ReactNode;
  titulo: string;
  descricao: string;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      aria-expanded={ativo}
      onClick={onClick}
      className={cn(
        "flex h-full cursor-pointer items-start gap-3 rounded-campo border p-4 text-left [font:inherit] transition-colors",
        ativo ? "border-acao bg-acao-clara" : "border-borda bg-papel hover:border-acao",
      )}
    >
      <span className="mt-0.5 shrink-0 text-acao" aria-hidden>
        {icone}
      </span>
      <span className="grid gap-1">
        <strong className="text-sm text-tinta">{titulo}</strong>
        <span className="text-xs leading-relaxed text-tinta-3">{descricao}</span>
      </span>
    </button>
  );
}

export default function SkillDePeticao({
  onMudou,
  painelInicial = null,
  onEnviarNova,
}: {
  onMudou: () => void;
  painelInicial?: PainelDaSkill | null;
  /** Abre o passo a passo de adicionar skill já na opção "para escrever petições". */
  onEnviarNova: () => void;
}) {
  const [estado, setEstado] = useState<EstadoSkillPeticao | null>(null);
  const [erroCarga, setErroCarga] = useState<string | null>(null);
  const [painel, setPainel] = useState<PainelDaSkill | null>(painelInicial);
  const topo = useRef<HTMLDivElement>(null);

  const carregar = useCallback(async () => {
    setErroCarga(null);
    try {
      setEstado(await obterSkillPeticao());
    } catch (e) {
      setErroCarga(mensagem(e, "Não foi possível ler a skill de petição."));
    }
  }, []);

  useEffect(() => {
    void carregar();
  }, [carregar]);

  useEffect(() => {
    if (painelInicial) topo.current?.scrollIntoView({ block: "start", behavior: "smooth" });
  }, [painelInicial]);

  function atualizar(novo: EstadoSkillPeticao) {
    setEstado(novo);
    window.dispatchEvent(new Event("skills-atualizadas"));
    onMudou();
  }

  const ativa = estado?.ativa;
  const verificacao = ativa?.verificacao;
  const alternar = (qual: PainelDaSkill) => setPainel((atual) => (atual === qual ? null : qual));

  return (
    <div ref={topo} className="scroll-mt-4">
      <Cartao
        titulo={
          <span className="flex flex-wrap items-center gap-2">
            <FileText aria-hidden className="size-5 text-acao" />
            Como as petições são escritas
          </span>
        }
        subtitulo="Toda petição que o sistema gera segue uma skill: ela define o texto, a ordem das partes e o visual da peça."
      >
        {erroCarga && <Aviso tom="critico" titulo="Não foi possível ler a skill em uso">{erroCarga}</Aviso>}
        {!estado && !erroCarga && <p className="text-sm text-tinta-2">Carregando…</p>}

        {ativa && verificacao && (
          <div className="grid gap-4">
            <div className="grid gap-1 rounded-campo border border-ok-borda bg-ok-claro px-4 py-3">
              <p className="m-0 flex flex-wrap items-center gap-2 text-sm text-tinta-2">
                Skill em uso agora:
                <strong className="text-base text-tinta">{ativa.nome}</strong>
                <Selo tom={ativa.do_sistema ? "neutro" : "ok"} simbolo="✓">
                  {ativa.do_sistema ? "padrão do sistema" : "do escritório"}
                </Selo>
              </p>
              <p className="m-0 text-xs text-tinta-3">
                Letra {verificacao.layout.fonte} {numero(verificacao.layout.tamanho_pt)} · petição em{" "}
                {verificacao.blocos.length} partes · {ativa.logo ? "logo da própria skill" : "logo do escritório"}
                {!ativa.do_sistema && ativa.ativada_em
                  ? ` · em uso desde ${dataEHora(ativa.ativada_em)}${ativa.ativada_por ? ` (${ativa.ativada_por})` : ""}`
                  : ""}
              </p>
            </div>

            {verificacao.avisos.length > 0 && (
              <Aviso tom="atencao" titulo="Esta skill tem pontos que merecem atenção">
                <ul className="m-0 grid gap-1 pl-4">
                  {verificacao.avisos.map((aviso) => (
                    <li key={aviso}>{aviso}</li>
                  ))}
                </ul>
              </Aviso>
            )}

            <div>
              <p className="m-0 mb-2 text-sm font-semibold text-tinta">O que você quer fazer?</p>
              <div className="grid gap-2 md:grid-cols-3">
                <BotaoDePainel
                  ativo={painel === "instrucoes"}
                  icone={<NotebookPen className="size-5" />}
                  titulo="Dar instruções para a IA"
                  descricao="Ex.: “sempre pedir justiça gratuita”. É o jeito mais fácil de mudar as petições."
                  onClick={() => alternar("instrucoes")}
                />
                <BotaoDePainel
                  ativo={painel === "trocar"}
                  icone={<ArrowLeftRight className="size-5" />}
                  titulo="Trocar por outra skill"
                  descricao="Usar outra skill que o escritório já enviou, ou voltar para a padrão."
                  onClick={() => alternar("trocar")}
                />
                <BotaoDePainel
                  ativo={painel === "desfazer"}
                  icone={<History className="size-5" />}
                  titulo="Desfazer uma mudança"
                  descricao="As petições pioraram depois de uma mudança? Volte para como estava."
                  onClick={() => alternar("desfazer")}
                />
              </div>
            </div>

            {painel && (
              <section className="rounded-campo border border-acao-borda bg-papel-2 p-4">
                {painel === "instrucoes" && <InstrucoesParaIA skillId={ativa.id} onSalvou={atualizar} />}
                {painel === "trocar" && <TrocarSkill estado={estado} onTrocou={atualizar} onEnviarNova={onEnviarNova} />}
                {painel === "desfazer" && <HistoricoDaSkill skillId={ativa.id} onSalvou={atualizar} />}
              </section>
            )}

            <OpcoesAvancadas estado={estado} onSalvou={atualizar} />
          </div>
        )}
      </Cartao>
    </div>
  );
}

function TrocarSkill({
  estado,
  onTrocou,
  onEnviarNova,
}: {
  estado: EstadoSkillPeticao;
  onTrocou: (novo: EstadoSkillPeticao) => void;
  onEnviarNova: () => void;
}) {
  const emUso = estado.ativa.do_sistema ? "" : estado.ativa.id;
  const [marcada, setMarcada] = useState(emUso);
  const [trocando, setTrocando] = useState(false);
  const [retorno, setRetorno] = useState<{ tom: "ok" | "critico"; texto: string } | null>(null);

  useEffect(() => setMarcada(emUso), [emUso]);

  const opcoes = [
    { id: "", nome: "Padrão do sistema", detalhe: "A skill que já vem com o sistema." },
    ...estado.disponiveis.map((s) => ({
      id: s.id,
      nome: s.nome,
      detalhe: s.atualizado_em ? `Enviada ou alterada em ${dataEHora(s.atualizado_em)}` : "",
    })),
  ];

  async function trocar() {
    setTrocando(true);
    setRetorno(null);
    try {
      const novo = await ativarSkillPeticao(marcada);
      onTrocou(novo);
      setRetorno({ tom: "ok", texto: `Pronto! As próximas petições vão usar "${novo.ativa.nome}".` });
    } catch (e) {
      setRetorno({ tom: "critico", texto: mensagem(e, "Não foi possível trocar a skill.") });
    } finally {
      setTrocando(false);
    }
  }

  return (
    <div className="grid gap-3">
      <p className="m-0 text-sm font-semibold text-tinta">Marque a skill que deve escrever as petições:</p>
      <div className="grid gap-2" role="radiogroup" aria-label="Skill de petição">
        {opcoes.map((opcao) => (
          <label
            key={opcao.id || "sistema"}
            className={cn(
              "flex cursor-pointer items-start gap-3 rounded-campo border px-3 py-2",
              marcada === opcao.id ? "border-acao bg-acao-clara" : "border-borda bg-papel hover:border-acao",
            )}
          >
            <input
              type="radio"
              name="skill-de-peticao"
              className="mt-1"
              checked={marcada === opcao.id}
              onChange={() => setMarcada(opcao.id)}
            />
            <span className="grid gap-0.5">
              <span className="text-sm text-tinta">
                <strong>{opcao.nome}</strong>
                {opcao.id === emUso && <span className="ml-2 text-xs font-semibold text-ok">✓ em uso agora</span>}
              </span>
              {opcao.detalhe && <span className="text-xs text-tinta-3">{opcao.detalhe}</span>}
            </span>
          </label>
        ))}
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <Botao variante="primario" disabled={marcada === emUso} carregando={trocando} textoCarregando="Trocando…" onClick={() => void trocar()}>
          Usar a skill marcada
        </Botao>
        <Botao variante="texto" onClick={onEnviarNova}>
          <Plus aria-hidden className="size-4" />
          A skill que eu quero não está na lista
        </Botao>
      </div>
      {retorno && (
        <Aviso tom={retorno.tom} titulo={retorno.tom === "critico" ? "A skill não foi trocada" : undefined}>
          {retorno.texto}
        </Aviso>
      )}
    </div>
  );
}

function OpcoesAvancadas({ estado, onSalvou }: { estado: EstadoSkillPeticao; onSalvou: (novo: EstadoSkillPeticao) => void }) {
  const [baixando, setBaixando] = useState(false);
  const [erro, setErro] = useState<string | null>(null);
  const { ativa } = estado;
  const { layout, blocos } = ativa.verificacao;

  async function baixar() {
    setBaixando(true);
    setErro(null);
    try {
      const { arquivo, nome } = await baixarSkillPeticao(ativa.do_sistema ? "" : ativa.id);
      baixarArquivo(arquivo, nome);
    } catch (e) {
      setErro(mensagem(e, "Não foi possível baixar a skill."));
    } finally {
      setBaixando(false);
    }
  }

  return (
    <details className="rounded-campo border border-borda p-4">
      <summary className="cursor-pointer text-sm font-semibold text-tinta-2">
        Opções avançadas <span className="font-normal text-tinta-3">(só para quem sabe montar arquivos de skill)</span>
      </summary>
      <div className="mt-4 grid gap-5">
        <section className="grid gap-2">
          <h3 className="m-0 text-sm font-semibold text-tinta">Detalhes da skill em uso</h3>
          <ul className="m-0 grid gap-1 pl-5 text-sm text-tinta-2">
            <li>
              Letra {layout.fonte} {numero(layout.tamanho_pt)} pt, espaçamento {numero(layout.espacamento_linha)}
            </li>
            <li>Margens (superior · direita · inferior · esquerda): {layout.margens_cm.map(numero).join(" · ")} cm</li>
            <li>
              {ativa.verificacao.assuntos} tipos de ação e {ativa.verificacao.validacoes} conferências antes de entregar
            </li>
          </ul>
          {blocos.length > 0 && (
            <details className="text-sm text-tinta-2">
              <summary className="cursor-pointer font-semibold text-acao">Ver a ordem das partes da petição</summary>
              <ol className="mt-2 mb-0 grid gap-1 pl-5">
                {blocos.map((bloco) => (
                  <li key={bloco}>{bloco}</li>
                ))}
              </ol>
            </details>
          )}
        </section>

        <section className="grid gap-2">
          <h3 className="m-0 text-sm font-semibold text-tinta">Baixar a skill em uso</h3>
          <p className="m-0 text-sm text-tinta-2">
            Serve de modelo para montar uma skill nova: já vem com todos os arquivos no lugar certo. Depois de editar,
            compacte de novo e envie pelo botão <strong>Adicionar uma skill</strong>, no topo da página.
          </p>
          <ul className="m-0 grid gap-1 pl-5 text-sm text-tinta-2">
            {O_QUE_O_PACOTE_TRAZ.map((item) => (
              <li key={item.arquivo}>
                <code className="text-tinta">{item.arquivo}</code> — {item.papel}
                {item.obrigatorio ? <strong> (obrigatório)</strong> : " (opcional)"}
              </li>
            ))}
          </ul>
          <div>
            <Botao variante="secundario" onClick={() => void baixar()} carregando={baixando} textoCarregando="Preparando o arquivo…">
              <Download aria-hidden className="size-4" />
              Baixar a skill em uso (.zip)
            </Botao>
          </div>
          {erro && <Aviso tom="critico">{erro}</Aviso>}
        </section>

        <section className="grid gap-2">
          <h3 className="m-0 text-sm font-semibold text-tinta">Editar os arquivos da skill aqui mesmo</h3>
          <EditarArquivosDaSkill skillId={ativa.id} onSalvou={onSalvou} />
        </section>
      </div>
    </details>
  );
}
