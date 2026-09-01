"use client";

/* A tela do secretário: quem entrevistou, quanto, e como conduziu.
 *
 * Três níveis, e a ordem é a das perguntas que ele faz de verdade: quem fez
 * quantas → quais foram → como foi esta. Cada nível só carrega quando é aberto;
 * a conferência contra o roteiro, em especial, custa uma ida ao modelo e por isso
 * nunca dispara sozinha ao abrir a tela.
 *
 * O TERCEIRO NÍVEL É O CHECKLIST, NÃO A TRANSCRIÇÃO
 *
 * Era a transcrição que abria primeiro, e ela é quarenta minutos de texto: na
 * prática ninguém lia, e a conferência não acontecia. Agora abre o checklist do
 * roteiro (`ChecklistRoteiro`), que responde em uma tela o que a leitura responderia
 * em meia hora — assinaturas, avaliação do Google, perguntas, abertura e
 * encerramento. A transcrição continua a um clique, na outra aba, porque é ela que
 * resolve a dúvida quando o checklist aponta algo que o secretário quer conferir
 * com os próprios olhos.
 */

import { useCallback, useEffect, useState } from "react";
import { ArrowLeft, ClipboardCheck, Headphones, UsersRound } from "lucide-react";

import AudioDaEntrevista from "@/components/entrevista/AudioDaEntrevista";
import ChecklistRoteiro from "@/components/admin/ChecklistRoteiro";
import PainelSupervisao from "@/components/admin/PainelSupervisao";
import { Aviso, BarraAbas, Botao, BotaoAba, Cartao, Paginacao, Selo, Vazio } from "@/components/ui/Basicos";
import {
  ApiError,
  auditarEntrevista,
  corrigirAvaliacaoGoogle,
  listarSupervisaoPaginada,
  obterChecklist,
  obterTranscricao,
  type Auditoria,
  type ChecklistRegistro,
  type EntrevistaResumo,
  type EntrevistasSupervisaoPaginadas,
  type PendenciasSupervisao,
  type PessoaSupervisao,
} from "@/lib/api";

const SEM_PENDENCIAS: PendenciasSupervisao = {
  sem_avaliacao: 0,
  sem_dossie: 0,
  sem_quem_conduziu: 0,
  ao_vivo: 0,
  anexadas: 0,
};

interface Props {
  onVoltar: () => void;
}

const ITEM_BASE =
  "flex flex-col gap-[5px] w-full px-[11px] py-[9px] border border-transparent rounded-campo " +
  "[font:inherit] text-left cursor-pointer";
const ITEM_RESTING = "bg-transparent hover:bg-papel-3";
const ITEM_ABERTO = "bg-acao-clara border-acao-borda";
const ENTREVISTAS_POR_PAGINA = 8;
const SEM_ENTREVISTAS: EntrevistasSupervisaoPaginadas = {
  entrevistador: "",
  itens: [],
  total: 0,
  pagina: 1,
  tamanho: ENTREVISTAS_POR_PAGINA,
  paginas: 1,
};

export default function Supervisao({ onVoltar }: Props) {
  const [pessoas, setPessoas] = useState<PessoaSupervisao[]>([]);
  const [totais, setTotais] = useState({ entrevistas: 0, pessoas: 0, sem: 0 });
  const [pendencias, setPendencias] = useState<PendenciasSupervisao>(SEM_PENDENCIAS);
  const [entrevistas, setEntrevistas] =
    useState<EntrevistasSupervisaoPaginadas>(SEM_ENTREVISTAS);
  /* Quem está aberto na tabela do painel. `null` = ninguém, e aí a coluna da
   * esquerda mostra todos — é o estado em que a tela abre, porque escolher uma
   * pessoa por padrão esconderia as outras quatro sem o secretário ter pedido. */
  const [pessoaAberta, setPessoaAberta] = useState<string | null>(null);
  const [carregando, setCarregando] = useState(true);
  const [erro, setErro] = useState<string | null>(null);

  const [aberta, setAberta] = useState<string | null>(null);
  const [aba, setAba] = useState<"checklist" | "transcricao">("checklist");

  const [texto, setTexto] = useState<string>("");
  const [carregandoTexto, setCarregandoTexto] = useState(false);

  const [registro, setRegistro] = useState<ChecklistRegistro | null>(null);
  const [erroRegistro, setErroRegistro] = useState<string | null>(null);
  const [corrigindo, setCorrigindo] = useState(false);

  const [relatorio, setRelatorio] = useState<Auditoria | null>(null);
  const [auditando, setAuditando] = useState(false);
  const [erroAuditoria, setErroAuditoria] = useState<string | null>(null);

  const carregar = useCallback(async (entrevistador?: string | null, pagina = 1) => {
    try {
      const d = await listarSupervisaoPaginada({
        entrevistador,
        pagina,
        tamanho: ENTREVISTAS_POR_PAGINA,
      });
      setPessoas(d.itens);
      setEntrevistas(d.entrevistas);
      if (d.entrevistas.entrevistador) {
        setPessoaAberta(d.entrevistas.entrevistador);
      }
      setPendencias(d.pendencias ?? SEM_PENDENCIAS);
      setTotais({
        entrevistas: d.total_entrevistas,
        pessoas: d.total_pessoas,
        sem: d.sem_atribuicao,
      });
      setErro(null);
    } catch (e) {
      setErro(e instanceof ApiError ? e.message : "Não foi possível carregar.");
    } finally {
      setCarregando(false);
    }
  }, []);

  useEffect(() => {
    void carregar();
  }, [carregar]);

  const carregarEntrevistas = useCallback((entrevistador: string, pagina = 1) => {
    setCarregando(true);
    setAberta(null);
    setTexto("");
    setRegistro(null);
    setRelatorio(null);
    setErroRegistro(null);
    setErroAuditoria(null);
    void carregar(entrevistador, pagina);
  }, [carregar]);

  async function abrir(id: string) {
    // Trocar de entrevista limpa a conferência: um relatório de OUTRA entrevista
    // ao lado deste checklist é pior que relatório nenhum.
    setAberta(id);
    setAba("checklist");
    setRelatorio(null);
    setErroAuditoria(null);
    setTexto("");
    setRegistro(null);
    setErroRegistro(null);

    // O checklist do registro é uma consulta ao banco e abre junto. A transcrição
    // vem no mesmo passo porque é o mesmo custo — o que NÃO vem é a leitura pelo
    // modelo, que espera o secretário pedir.
    setCarregandoTexto(true);
    try {
      setRegistro(await obterChecklist(id));
    } catch (e) {
      setErroRegistro(e instanceof ApiError ? e.message : "Erro ao montar o checklist.");
    }
    try {
      setTexto((await obterTranscricao(id)).texto);
    } catch (e) {
      setTexto("");
      setErroRegistro(e instanceof ApiError ? e.message : "Erro ao ler a transcrição.");
    } finally {
      setCarregandoTexto(false);
    }
  }

  async function auditar(id: string) {
    setAuditando(true);
    setErroAuditoria(null);
    try {
      setRelatorio(await auditarEntrevista(id));
    } catch (e) {
      setErroAuditoria(e instanceof ApiError ? e.message : "Não foi possível conferir.");
    } finally {
      setAuditando(false);
    }
  }

  async function corrigirAvaliacao(id: string, concluida: boolean) {
    setCorrigindo(true);
    try {
      setRegistro(await corrigirAvaliacaoGoogle(id, concluida));
      // A lista à esquerda mostra o mesmo sinal; deixá-la desatualizada faria o
      // secretário achar que a correção não pegou.
      await carregar(pessoaAberta, entrevistas.pagina);
    } catch (e) {
      setErroRegistro(
        e instanceof ApiError ? e.message : "Não foi possível gravar a marcação.",
      );
    } finally {
      setCorrigindo(false);
    }
  }

  const pessoaSelecionada = pessoas.find((p) => p.entrevistador === pessoaAberta);
  const listaVaziaInesperada =
    !carregando &&
    Boolean(pessoaSelecionada) &&
    (pessoaSelecionada?.quantidade ?? 0) > 0 &&
    entrevistas.total === 0;

  return (
    <div className="min-w-0 space-y-5">
      <Botao variante="texto" onClick={onVoltar} className="inline-flex items-center gap-2">
        <ArrowLeft size={16} aria-hidden />
        Voltar para a carteira
      </Botao>

      <header className="flex min-w-0 flex-wrap items-end justify-between gap-4">
        <div className="min-w-0">
          <p className="mb-2 mt-0 font-ui text-xs font-bold uppercase tracking-[0.12em] text-tinta-3">
            Gestão operacional
          </p>
          <h1 className="mb-[6px] mt-0 text-tinta font-titulo text-xl font-semibold">
            Supervisão
          </h1>
          <p className="m-0 max-w-[66ch] text-tinta-3 leading-[1.5]">
            Entrevistas por condução, pendências verificáveis e conferência de roteiro.
            Abra um atendimento para ver checklist, áudio e transcrição quando existirem.
          </p>
        </div>
        <div className="grid min-w-[260px] grid-cols-2 gap-2 max-[560px]:w-full">
          <div className="rounded-campo border border-borda bg-papel-2 px-3 py-2">
            <div className="flex items-center gap-2 text-xs font-semibold text-tinta-3">
              <Headphones size={14} aria-hidden />
              Entrevistas
            </div>
            <div className="mt-1 font-titulo text-lg font-semibold text-tinta tabular-nums">
              {totais.entrevistas}
            </div>
          </div>
          <div className="rounded-campo border border-borda bg-papel-2 px-3 py-2">
            <div className="flex items-center gap-2 text-xs font-semibold text-tinta-3">
              <UsersRound size={14} aria-hidden />
              Pessoas
            </div>
            <div className="mt-1 font-titulo text-lg font-semibold text-tinta tabular-nums">
              {totais.pessoas}
            </div>
          </div>
        </div>
      </header>

      {erro && (
        <Aviso tom="critico" titulo="Não foi possível carregar">
          {erro}
        </Aviso>
      )}

      {/* A atribuição passou a ser automática, mas o que já estava gravado antes
        * disso não tem como ser recuperado. Dizer isto evita que o secretário
        * leia o buraco como alguém que não trabalhou. */}
      {totais.sem > 0 && (
        <Aviso tom="atencao" titulo="Entrevistas sem quem conduziu">
          {totais.sem} entrevista(s) foram gravadas antes de o sistema passar a
          registrar quem conduziu. Elas aparecem agrupadas como “não identificado” —
          não é ausência de trabalho, é ausência de dado.
        </Aviso>
      )}

      {/* O painel: o que o escritório deve e quem deve o quê. Fica ACIMA da
        * grade de duas colunas porque é a pergunta com que o secretário abre a
        * tela; a lista e o checklist são o aprofundamento dela. */}
      {!carregando && pessoas.length > 0 && (
        <div className="mt-5">
          <PainelSupervisao
            pessoas={pessoas}
            pendencias={pendencias}
            total={totais.entrevistas}
            pessoaAberta={pessoaAberta}
            onEscolherPessoa={(nome) => carregarEntrevistas(nome, 1)}
          />
        </div>
      )}

      <div className="grid min-w-0 grid-cols-[minmax(min(100%,280px),360px)_minmax(0,1fr)] items-start gap-5 max-[960px]:grid-cols-1">
        {/* ------------------------------------------- funcionário e entrevistas */}
        <Cartao
          titulo={
            <span className="inline-flex min-w-0 items-center gap-2">
              <ClipboardCheck size={18} className="text-acao" aria-hidden />
              <span className="truncate">Atendimentos</span>
            </span>
          }
          subtitulo="Escolha uma entrevista para conferir o roteiro."
          className="min-w-0 overflow-hidden"
        >
          {carregando ? (
            <p className="m-0 text-tinta-3">Carregando…</p>
          ) : pessoas.length === 0 ? (
            <Vazio>Nenhuma entrevista registrada ainda.</Vazio>
          ) : listaVaziaInesperada ? (
            <Aviso tom="atencao" titulo="Não foi possível listar as entrevistas">
              O painel encontrou entrevistas para {pessoaAberta}, mas a página não retornou
              itens. Tente abrir essa pessoa novamente; se persistir, há divergência no nome
              gravado da entrevista.
              <div className="mt-3">
                <Botao
                  variante="secundario"
                  pequeno
                  onClick={() => pessoaAberta && carregarEntrevistas(pessoaAberta, 1)}
                >
                  Recarregar lista
                </Botao>
              </div>
            </Aviso>
          ) : entrevistas.itens.length === 0 ? (
            <Vazio>Nenhuma entrevista encontrada para esta pessoa.</Vazio>
          ) : (
            (() => {
              const pessoa = pessoaSelecionada;
              const semAvaliacao = entrevistas.itens.filter((e) => !e.avaliacao_google).length;
              const inicio = entrevistas.total === 0 ? 0 : (entrevistas.pagina - 1) * entrevistas.tamanho;
              const fim = Math.min(inicio + entrevistas.itens.length, entrevistas.total);

              return (
                <div
                  key={entrevistas.entrevistador}
                >
                  <h2 className="flex min-w-0 justify-between items-baseline gap-[10px] mb-1 mt-0 text-tinta font-titulo text-md font-semibold">
                    <span className="min-w-0 truncate" title={entrevistas.entrevistador}>
                      {entrevistas.entrevistador}
                    </span>
                    <span className="shrink-0 font-ui font-normal text-xs text-tinta-3 whitespace-nowrap">
                      {pessoa?.quantidade ?? entrevistas.total} entrevista{(pessoa?.quantidade ?? entrevistas.total) === 1 ? "" : "s"}
                    </span>
                  </h2>

                  {/* O que o secretário cobraria desta pessoa hoje, sem abrir nada.
                    * A avaliação do Google é o único item do roteiro que a lista
                    * consegue conferir sem ir ao modelo — e é o mais frágil deles. */}
                  <p className="mt-0 mb-2 text-xs leading-[1.5]">
                    {semAvaliacao === 0 ? (
                      <span className="text-ok">✓ avaliação do Google nos itens desta página</span>
                    ) : (
                      <span className="text-atencao">
                        ! {semAvaliacao} nesta página sem avaliação do Google registrada
                      </span>
                    )}
                  </p>

                  <ul className="list-none m-0 flex flex-col gap-[2px] p-0">
                    {entrevistas.itens.map((e: EntrevistaResumo) => (
                      <li key={e.id}>
                        <button
                          type="button"
                          className={`${ITEM_BASE} ${aberta === e.id ? ITEM_ABERTO : ITEM_RESTING}`}
                          onClick={() => void abrir(e.id)}
                        >
                          <span className="flex justify-between items-baseline gap-[10px] w-full">
                            <span
                              className={`min-w-0 text-tinta text-sm truncate ${aberta === e.id ? "font-semibold" : ""}`}
                              title={e.cliente || "cliente não informado"}
                            >
                              {e.cliente || "cliente não informado"}
                            </span>
                            <span className="shrink-0 text-tinta-3 text-xs whitespace-nowrap">
                              {e.realizada_em || e.criado_em?.slice(0, 10) || "sem data"}
                            </span>
                          </span>
                          <span className="flex items-center gap-[6px] flex-wrap">
                            <Selo
                              tom={e.avaliacao_google ? "ok" : "atencao"}
                              simbolo={e.avaliacao_google ? "✓" : "!"}
                            >
                              Google
                            </Selo>
                            {!e.enviada && (
                              <Selo tom="atencao" simbolo="!">
                                sem dossiê
                              </Selo>
                            )}
                            <span className="text-tinta-3 text-xs whitespace-nowrap">
                              {e.caracteres.toLocaleString("pt-BR")} car.
                            </span>
                          </span>
                        </button>
                      </li>
                    ))}
                  </ul>
                  <Paginacao
                    pagina={entrevistas.pagina}
                    totalPaginas={entrevistas.paginas}
                    total={entrevistas.total}
                    inicio={inicio}
                    fim={fim}
                    rotulo="entrevistas"
                    onPagina={(proxima) => carregarEntrevistas(entrevistas.entrevistador, proxima)}
                  />
                </div>
              );
            })()
          )}
        </Cartao>

        {/* --------------------------------------------------- checklist e texto */}
        <section className="min-w-0">
          {!aberta ? (
            <Vazio className="min-h-[240px] content-center">
              Escolha uma entrevista à esquerda para abrir o checklist do roteiro.
            </Vazio>
          ) : (
            <div className="flex min-w-0 flex-col gap-4">
              <BarraAbas className="self-start">
                <BotaoAba ativa={aba === "checklist"} onClick={() => setAba("checklist")}>
                  Checklist do roteiro
                </BotaoAba>
                <BotaoAba ativa={aba === "transcricao"} onClick={() => setAba("transcricao")}>
                  Transcrição
                </BotaoAba>
              </BarraAbas>

              {erroRegistro && (
                <Aviso tom="critico" titulo="Falhou ao carregar">
                  {erroRegistro}
                </Aviso>
              )}

              {aba === "checklist" ? (
                <ChecklistRoteiro
                  registro={registro}
                  auditoria={relatorio}
                  auditando={auditando}
                  erroAuditoria={erroAuditoria}
                  onAuditar={() => void auditar(aberta)}
                  onCorrigirAvaliacao={(c) => void corrigirAvaliacao(aberta, c)}
                  corrigindoAvaliacao={corrigindo}
                />
              ) : carregandoTexto ? (
                <p className="m-0 text-tinta-3">Carregando…</p>
              ) : texto ? (
                <>
                  {/* O áudio, quando a entrevista foi conduzida pelo roteiro.
                    * A transcrição vem de reconhecimento de voz e erra — quando
                    * o checklist aponta algo que o secretário quer conferir de
                    * verdade, é aqui que ele ouve o trecho em vez de decidir
                    * pelo texto. A anexada como arquivo não tem áudio. */}
                  {registro?.origem === "ao_vivo" && registro.gravacao_id && (
                    <AudioDaEntrevista entrevistaId={registro.gravacao_id} />
                  )}
                  <pre className="m-0 px-[14px] py-3 max-h-[620px] overflow-y-auto border border-borda-forte rounded-cartao bg-papel text-tinta-2 [font-family:inherit] text-sm leading-[1.6] whitespace-pre-wrap [overflow-wrap:anywhere]">
                    {texto}
                  </pre>
                </>
              ) : (
                <Vazio>Esta entrevista não tem texto.</Vazio>
              )}
            </div>
          )}
        </section>
      </div>
    </div>
  );
}
