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

import EditorRoteiro from "@/components/entrevista/EditorRoteiro";
import ImportarRoteiro from "@/components/entrevista/ImportarRoteiro";
import { Aviso, Botao, Cartao, Selo, Vazio } from "@/components/ui/Basicos";
import {
  ApiError,
  excluirRoteiroSalvo,
  listarRoteiros,
  obterRoteiro,
} from "@/lib/api";
import type { RoteiroCompleto, RoteiroResumo } from "@/lib/types";

/** Data ISO do servidor em algo que se lê. Vazio quando nunca foi salvo. */
function quando(iso: string): string {
  if (!iso) return "";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "" : d.toLocaleString("pt-BR");
}

export default function CatalogoRoteiros({ onVoltar }: { onVoltar: () => void }) {
  const [roteiros, setRoteiros] = useState<RoteiroResumo[]>([]);
  const [carregando, setCarregando] = useState(true);
  const [erro, setErro] = useState<string | null>(null);
  const [recado, setRecado] = useState<string | null>(null);

  /** Qual roteiro está aberto no editor, já com blocos e perguntas. */
  const [emEdicao, setEmEdicao] = useState<RoteiroCompleto | null>(null);
  const [origemEmEdicao, setOrigemEmEdicao] = useState("");
  const [abrindo, setAbrindo] = useState<string | null>(null);
  const [importando, setImportando] = useState(false);
  const [revertendo, setRevertendo] = useState<string | null>(null);

  const recarregar = useCallback(async () => {
    setCarregando(true);
    try {
      setRoteiros(await listarRoteiros());
      setErro(null);
    } catch (e) {
      setErro(e instanceof ApiError ? e.message : String(e));
    } finally {
      setCarregando(false);
    }
  }, []);

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

  return (
    <div className="flex flex-col gap-5">
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div>
          <h1 className="m-0 text-[26px] font-semibold leading-[1.15] font-titulo">
            Roteiros de entrevista
          </h1>
          <p className="mt-2 mb-0 max-w-[70ch] text-tinta-3 text-sm leading-[1.55]">
            O roteiro é o que a entrevista inteira segue. Aqui ele é mantido fora do
            atendimento: importe o documento de uma categoria nova, corrija perguntas e
            blocos, e desfaça edição que não deu certo.
          </p>
        </div>
        <Botao variante="texto" onClick={onVoltar}>
          ← Voltar
        </Botao>
      </div>

      {erro && <Aviso tom="critico">{erro}</Aviso>}
      {recado && <Aviso tom="ok">{recado}</Aviso>}

      <Cartao
        titulo="Novo roteiro a partir de um documento"
        subtitulo="Anexe o roteiro do escritório em .docx, PDF ou foto. O texto é lido — por OCR, se preciso — e vira uma proposta que abre no editor."
      >
        <div className="mt-3">
          <Botao variante="primario" onClick={() => setImportando(true)}>
            Importar documento
          </Botao>
        </div>
      </Cartao>

      <Cartao titulo="No catálogo">
        {carregando && <p className="mt-3 text-tinta-3 text-sm">Carregando…</p>}

        {!carregando && roteiros.length === 0 && (
          <Vazio>Nenhum roteiro cadastrado.</Vazio>
        )}

        <div className="mt-3 flex flex-col gap-2">
          {roteiros.map((r) => (
            <div
              key={r.codigo}
              className="flex items-start justify-between gap-4 flex-wrap p-3 border border-borda rounded-campo bg-papel"
            >
              <div className="min-w-[240px] flex-1">
                <div className="flex items-center gap-2 flex-wrap">
                  <strong className="text-tinta text-sm">{r.nome}</strong>
                  {/* Dizer de onde veio é o que separa "o roteiro do escritório"
                      de "aquele que alguém importou na terça". */}
                  {r.importado ? (
                    <Selo tom="info">{r.origem ? `de ${r.origem}` : "editado"}</Selo>
                  ) : (
                    <Selo tom="neutro">original do sistema</Selo>
                  )}
                </div>
                {r.descricao && (
                  <p className="mt-1 mb-0 text-tinta-3 text-xs leading-[1.5]">{r.descricao}</p>
                )}
                {r.importado && (
                  <p className="mt-1 mb-0 text-tinta-3 text-xs leading-[1.5]">
                    {[quando(r.atualizado_em), r.criado_por].filter(Boolean).join(" · ")}
                  </p>
                )}
              </div>

              <div className="flex gap-2 items-center flex-wrap">
                <Botao
                  pequeno
                  onClick={() => void abrirEditor(r)}
                  disabled={abrindo === r.codigo}
                >
                  {abrindo === r.codigo ? "Abrindo…" : "Editar"}
                </Botao>
                {/* Só em quem TEM versão salva: num roteiro que nunca foi
                    editado não há nada para desfazer, e o botão convidaria a
                    apagar o que não dá para apagar. */}
                {r.importado && (
                  <Botao
                    pequeno
                    variante="texto"
                    onClick={() => void reverter(r)}
                    disabled={revertendo === r.codigo}
                  >
                    {revertendo === r.codigo ? "…" : "Voltar ao original"}
                  </Botao>
                )}
              </div>
            </div>
          ))}
        </div>
      </Cartao>

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
