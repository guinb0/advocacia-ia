"use client";

/**
 * O catálogo de roteiros — manutenção fora do atendimento.
 *
 * O botão "Editar roteiro" da entrevista serve ao advogado com o cliente na
 * linha: conserta a pergunta que não serve para AQUELE caso e segue a conversa.
 * Esta tela é o outro trabalho, o de escritório: importar o documento de uma
 * categoria nova, revisar com calma o que o modelo montou, corrigir o que ficou
 * torto, e desfazer edição que saiu errada.
 *
 * QUEM ENTRA AQUI, E POR QUE NÃO É SÓ O ADVOGADO
 *
 * O secretário tem o módulo `roteiros` sem ter `entrevista` (ver
 * `app/perfis.py`). Manter o roteiro e conduzir entrevista são trabalhos
 * diferentes, e amarrar um ao outro obrigaria a dar acesso ao atendimento
 * inteiro a quem só precisa consertar o texto de uma pergunta.
 *
 * DESFAZER É A FUNÇÃO MAIS IMPORTANTE DESTA TELA
 *
 * Um roteiro salvo passa a reger os atendimentos de todo o escritório. Se a
 * edição de ontem quebrou alguma coisa, "Voltar ao original" devolve o roteiro
 * escrito em `app/roteiros.py` na hora, sem deploy e sem ninguém mexer no banco.
 */

import { useCallback, useEffect, useState } from "react";
import { ArrowLeft, BookOpenText, FilePenLine, RotateCcw, Upload } from "lucide-react";

import EditorRoteiro from "@/components/entrevista/EditorRoteiro";
import ImportarRoteiro from "@/components/entrevista/ImportarRoteiro";
import { Aviso, Botao, Cartao, Paginacao, Selo, Vazio } from "@/components/ui/Basicos";
import {
  ApiError,
  excluirRoteiroSalvo,
  listarRoteirosPaginado,
  obterRoteiro,
} from "@/lib/api";
import type { RoteiroCompleto, RoteiroResumo } from "@/lib/types";

/** Data ISO do servidor em algo que se lê. Vazio quando nunca foi salvo. */
function quando(iso: string): string {
  if (!iso) return "";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "" : d.toLocaleString("pt-BR");
}

const ITENS_POR_PAGINA = 10;

export default function CatalogoRoteiros({ onVoltar }: { onVoltar: () => void }) {
  const [roteiros, setRoteiros] = useState<RoteiroResumo[]>([]);
  const [totalRoteiros, setTotalRoteiros] = useState(0);
  const [totalPaginas, setTotalPaginas] = useState(1);
  const [resumo, setResumo] = useState({ importados: 0, originais: 0 });
  const [carregando, setCarregando] = useState(true);
  const [erro, setErro] = useState<string | null>(null);
  const [recado, setRecado] = useState<string | null>(null);

  /** Qual roteiro está aberto no editor, já com blocos e perguntas. */
  const [emEdicao, setEmEdicao] = useState<RoteiroCompleto | null>(null);
  const [origemEmEdicao, setOrigemEmEdicao] = useState("");
  const [abrindo, setAbrindo] = useState<string | null>(null);
  const [importando, setImportando] = useState(false);
  const [revertendo, setRevertendo] = useState<string | null>(null);
  const [pagina, setPagina] = useState(1);

  const recarregar = useCallback(async () => {
    setCarregando(true);
    try {
      const paginaRecebida = await listarRoteirosPaginado(pagina, ITENS_POR_PAGINA);
      setRoteiros(paginaRecebida.roteiros);
      setTotalRoteiros(paginaRecebida.total);
      setTotalPaginas(paginaRecebida.paginas);
      setResumo({
        importados: paginaRecebida.importados,
        originais: paginaRecebida.originais,
      });
      if (pagina !== paginaRecebida.pagina) {
        setPagina(paginaRecebida.pagina);
      }
      setErro(null);
    } catch (e) {
      setErro(e instanceof ApiError ? e.message : String(e));
    } finally {
      setCarregando(false);
    }
  }, [pagina]);

  useEffect(() => {
    void recarregar();
  }, [recarregar]);

  /* A listagem não traz perguntas — são 89 num roteiro só, e a tela mostra dez
   * linhas. O roteiro inteiro é buscado no clique de editar. */
  async function abrirEditor(resumo: RoteiroResumo) {
    setAbrindo(resumo.codigo);
    setErro(null);
    try {
      setEmEdicao(await obterRoteiro(resumo.codigo));
      setOrigemEmEdicao(resumo.origem);
    } catch (e) {
      setErro(e instanceof ApiError ? e.message : String(e));
    } finally {
      setAbrindo(null);
    }
  }

  async function reverter(resumo: RoteiroResumo) {
    setRevertendo(resumo.codigo);
    setErro(null);
    try {
      const { revertido_para_o_modulo } = await excluirRoteiroSalvo(resumo.codigo);
      setRecado(
        revertido_para_o_modulo
          ? `“${resumo.nome}” voltou ao roteiro original do sistema.`
          : `“${resumo.nome}” foi removido do catálogo.`,
      );
      await recarregar();
    } catch (e) {
      setErro(e instanceof ApiError ? e.message : String(e));
    } finally {
      setRevertendo(null);
    }
  }

  const inicio = totalRoteiros ? (pagina - 1) * ITENS_POR_PAGINA : 0;
  const fim = Math.min(inicio + roteiros.length, totalRoteiros);

  return (
    <div className="flex min-w-0 max-w-full flex-col gap-5">
      <section className="overflow-hidden rounded-cartao border border-borda-forte bg-papel shadow-cartao">
        <div className="flex min-w-0 flex-wrap items-start justify-between gap-4 border-b border-borda bg-papel-2 px-5 py-4">
          <div className="min-w-0">
            <Botao variante="texto" onClick={onVoltar}>
              <ArrowLeft size={15} aria-hidden /> Voltar
            </Botao>
            <p className="mt-3 text-xs font-semibold uppercase tracking-[0.14em] text-tinta-3">
              Roteiros
            </p>
            <div className="mt-1 flex min-w-0 items-center gap-3">
              <span className="grid h-10 w-10 shrink-0 place-items-center rounded-campo border border-acao-borda bg-acao-clara text-acao">
                <BookOpenText size={20} aria-hidden />
              </span>
              <h1 className="m-0 min-w-0 truncate text-[26px] font-semibold leading-[1.15] font-titulo text-tinta">
                Roteiros de entrevista
              </h1>
            </div>
            <p className="mt-2 mb-0 max-w-[70ch] text-tinta-3 text-sm leading-[1.55]">
              Mantenha os roteiros fora do atendimento, revise perguntas com calma e preserve a entrevista progressiva.
            </p>
          </div>
          <div className="grid min-w-[240px] grid-cols-3 gap-2 rounded-campo border border-borda bg-papel p-2 text-center">
            <div className="min-w-0 px-2 py-1">
              <span className="block truncate text-[11px] text-tinta-3">Total</span>
              <strong className="block font-codigo text-lg text-tinta">{totalRoteiros}</strong>
            </div>
            <div className="min-w-0 border-x border-borda px-2 py-1">
              <span className="block truncate text-[11px] text-tinta-3">Importados</span>
              <strong className="block font-codigo text-lg text-tinta">{resumo.importados}</strong>
            </div>
            <div className="min-w-0 px-2 py-1">
              <span className="block truncate text-[11px] text-tinta-3">Originais</span>
              <strong className="block font-codigo text-lg text-tinta">{resumo.originais}</strong>
            </div>
          </div>
        </div>
      </section>

      {erro && <Aviso tom="critico">{erro}</Aviso>}
      {recado && <Aviso tom="ok">{recado}</Aviso>}

      <div className="grid min-w-0 grid-cols-[minmax(0,1fr)_minmax(280px,360px)] items-start gap-4 max-[920px]:grid-cols-1">
      <Cartao titulo="No catálogo" className="min-w-0 overflow-hidden">
        <div className="mt-2 flex min-w-0 flex-wrap items-center justify-between gap-3">
          <p className="m-0 text-sm leading-[1.5] text-tinta-3">
            Lista paginada dos roteiros disponíveis para manutenção do escritório.
          </p>
          <Selo tom="info">{totalRoteiros} roteiro(s)</Selo>
        </div>

        {carregando && (
          <div className="mt-3 rounded-campo border border-borda bg-papel-2 px-4 py-5 text-center text-sm text-tinta-3" aria-live="polite">
            Carregando roteiros…
          </div>
        )}

        {!carregando && totalRoteiros === 0 && (
          <Vazio className="mt-3">Nenhum roteiro cadastrado.</Vazio>
        )}

        <div className="mt-3 flex min-w-0 flex-col gap-2" aria-busy={carregando}>
          {roteiros.map((r) => (
            <div
              key={r.codigo}
              className="grid min-w-0 grid-cols-[minmax(0,1fr)_auto] items-start gap-4 rounded-campo border border-borda bg-papel px-3 py-3 max-[720px]:grid-cols-1"
            >
              <div className="min-w-0">
                <div className="flex min-w-0 flex-wrap items-center gap-2">
                  <strong className="min-w-0 truncate text-tinta text-sm" title={r.nome}>{r.nome}</strong>
                  {/* Dizer de onde veio é o que separa "o roteiro do escritório"
                      de "aquele que alguém importou na terça". */}
                  {r.importado ? (
                    <Selo tom="info">{r.origem ? `de ${r.origem}` : "editado"}</Selo>
                  ) : (
                    <Selo tom="neutro">original do sistema</Selo>
                  )}
                </div>
                {r.descricao && (
                  <p className="mt-1 mb-0 line-clamp-2 text-tinta-3 text-xs leading-[1.5]" title={r.descricao}>{r.descricao}</p>
                )}
                <p className="mt-1 mb-0 truncate font-codigo text-[11px] text-tinta-3" title={r.codigo}>
                  {r.codigo}
                </p>
                {r.importado && (
                  <p className="mt-1 mb-0 truncate text-tinta-3 text-xs leading-[1.5]">
                    {[quando(r.atualizado_em), r.criado_por].filter(Boolean).join(" · ")}
                  </p>
                )}
              </div>

              <div className="flex shrink-0 gap-2 items-center flex-wrap max-[720px]:justify-end">
                <Botao
                  pequeno
                  onClick={() => void abrirEditor(r)}
                  carregando={abrindo === r.codigo}
                  textoCarregando="Abrindo…"
                >
                  <FilePenLine size={14} aria-hidden />
                  Editar
                </Botao>
                {/* Só em quem TEM versão salva: num roteiro que nunca foi
                    editado não há nada para desfazer, e o botão convidaria a
                    apagar o que não dá para apagar. */}
                {r.importado && (
                  <Botao
                    pequeno
                    variante="texto"
                    onClick={() => void reverter(r)}
                    carregando={revertendo === r.codigo}
                    textoCarregando="Revertendo…"
                  >
                    <RotateCcw size={14} aria-hidden />
                    Voltar ao original
                  </Botao>
                )}
              </div>
            </div>
          ))}
        </div>
        <Paginacao
          pagina={pagina}
          totalPaginas={totalPaginas}
          total={totalRoteiros}
          inicio={inicio}
          fim={fim}
          rotulo="roteiros"
          onPagina={setPagina}
        />
      </Cartao>

      <aside className="flex min-w-0 flex-col gap-4">
        <Cartao
          titulo="Novo roteiro"
          subtitulo="Importe um documento do escritório. A proposta abre no editor para revisão antes de virar padrão."
          className="min-w-0 overflow-hidden"
        >
          <Botao variante="primario" onClick={() => setImportando(true)} bloco>
            <Upload size={16} aria-hidden /> Importar documento
          </Botao>
        </Cartao>

        <Cartao titulo="Uso no atendimento" className="min-w-0 overflow-hidden">
          <div className="flex flex-col gap-2 text-sm leading-[1.5] text-tinta-2">
            <div className="rounded-campo border border-borda bg-papel-2 px-3 py-2">
              <strong className="block text-tinta">Editar</strong>
              <span className="line-clamp-2">Abra perguntas e blocos somente quando precisar revisar.</span>
            </div>
            <div className="rounded-campo border border-borda bg-papel-2 px-3 py-2">
              <strong className="block text-tinta">Voltar ao original</strong>
              <span className="line-clamp-2">Recupere o padrão do sistema quando houver uma versão salva.</span>
            </div>
          </div>
        </Cartao>
      </aside>
      </div>

      {importando && (
        <ImportarRoteiro
          aoImportar={(importado) => {
            setImportando(false);
            setEmEdicao(importado.roteiro);
            setOrigemEmEdicao(importado.origem);
          }}
          aoFechar={() => setImportando(false)}
        />
      )}

      {emEdicao && (
        <EditorRoteiro
          roteiro={emEdicao}
          origem={origemEmEdicao}
          /* Fora de um atendimento não existe "usar só nesta sessão": nada
             consome o roteiro aqui. Fechar sem salvar é o que essa saída
             significa nesta tela. */
          aoUsar={() => setEmEdicao(null)}
          aoSalvar={(salvo) => {
            setRecado(`“${salvo.nome}” foi salvo no catálogo.`);
            void recarregar();
          }}
          aoFechar={() => setEmEdicao(null)}
        />
      )}
    </div>
  );
}
