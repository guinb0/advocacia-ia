"use client";

/**
 * Perfis de acesso: o que cada um alcança, módulo a módulo.
 *
 * POR QUE ESTA TELA EXISTE
 *
 * Os perfis eram três, cravados no código do servidor, e o motivo estava escrito
 * lá: papel novo sem código que o entenda vira acesso que ninguém sabe explicar.
 * A objeção era certa. Esta tela a resolve pelo outro lado — perfil novo nasce
 * declarando os módulos que alcança, e é essa declaração que as rotas conferem.
 *
 * A MATRIZ É O DOCUMENTO
 *
 * Uma linha por perfil, uma coluna por módulo, uma caixa em cada cruzamento. Não
 * é a forma mais bonita de mostrar isso, é a que permite responder de relance a
 * pergunta que se faz de verdade: "quem enxerga as entrevistas de todo mundo?".
 * Uma lista de perfis com um detalhe por vez esconderia justamente a comparação.
 *
 * NADA É SALVO SOZINHO
 *
 * Marcar caixa não grava. Cada linha guarda o que mudou e só vai ao servidor no
 * "Salvar" — porque desmarcar um módulo tira acesso de gente que está usando o
 * sistema neste momento, e isso não pode acontecer por um clique errado de quem
 * estava só olhando.
 */

import { useCallback, useEffect, useState } from "react";

/* Classes que eram seletor descendente ou se repetiam por linha da matriz.
 *
 * Os apelidos antigos do tema (--surface, --ink, --muted, --border) viraram os
 * nomes de verdade (papel, tinta, tinta-3, borda): são os mesmos valores, e o
 * apelido só existia para não quebrar CSS legado. */
const CELULA_MATRIZ = "border-b border-borda px-2 py-[10px] text-center";
/* A coluna do perfil é fixa na rolagem horizontal: ela é a única que diz de
 * quem é a linha, e perdê-la ao rolar deixa a matriz ilegível. */
const COLUNA_FIXA = "sticky left-0 z-[1] min-w-[220px] bg-papel text-left";
const BOTAO_ACAO =
  "border-[1.5px] border-tinta bg-tinta text-papel text-xs font-semibold uppercase " +
  "tracking-[0.06em] leading-none px-3 py-2 cursor-pointer disabled:opacity-45 disabled:cursor-default";
const CAMPO_NOVO =
  "flex flex-col gap-[5px] " +
  "[&>span]:text-tinta-3 [&>span]:text-xs [&>span]:font-semibold [&>span]:uppercase " +
  "[&>span]:tracking-[0.06em] [&>span]:leading-[1.3] " +
  "[&>input]:min-w-[260px] [&>input]:border [&>input]:border-borda-forte [&>input]:px-[11px] " +
  "[&>input]:py-[9px] [&>input]:bg-papel [&>input]:text-tinta [&>input]:text-sm [&>input]:leading-[1.4]";


import {
  ApiError,
  listarMatrizPerfis,
  removerPerfil,
  salvarPerfil,
} from "@/lib/api";
import type { ModuloDeAcesso, PerfilComAcesso } from "@/lib/api";


/** Código a partir do rótulo: minúsculas, sem acento, sem espaço.
 *
 * O código vai no claim `perfil` do token e é comparado como texto exato;
 * acento e espaço só criam jeito de errar. Gerar aqui evita pedir à pessoa um
 * dado técnico que ela não tem como saber que importa. */
function codigoDe(rotulo: string): string {
  return rotulo
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "")
    .slice(0, 60);
}

export default function PerfisDeAcesso() {
  const [perfis, setPerfis] = useState<PerfilComAcesso[]>([]);
  const [modulos, setModulos] = useState<ModuloDeAcesso[]>([]);
  const [carregando, setCarregando] = useState(true);
  const [erro, setErro] = useState<string | null>(null);
  const [salvando, setSalvando] = useState<string | null>(null);

  /* O que mudou desde a última leitura, por perfil. Só o que está aqui é
   * enviado — e é o que acende o botão "Salvar" de cada linha. */
  const [rascunho, setRascunho] = useState<Record<string, string[]>>({});
  const [novoRotulo, setNovoRotulo] = useState("");

  const carregar = useCallback(async () => {
    setCarregando(true);
    try {
      const r = await listarMatrizPerfis();
      setPerfis(r.perfis);
      setModulos(r.modulos);
      setRascunho({});
      setErro(null);
    } catch (e) {
      setErro(e instanceof ApiError ? e.message : "Não foi possível ler os perfis.");
    } finally {
      setCarregando(false);
    }
  }, []);

  useEffect(() => {
    void carregar();
  }, [carregar]);

  const marcados = (perfil: PerfilComAcesso) => rascunho[perfil.codigo] ?? perfil.modulos;
  const mudou = (perfil: PerfilComAcesso) => rascunho[perfil.codigo] !== undefined;

  function alternar(perfil: PerfilComAcesso, modulo: string) {
    const atual = marcados(perfil);
    const novo = atual.includes(modulo)
      ? atual.filter((m) => m !== modulo)
      : [...atual, modulo];
    setRascunho((r) => ({ ...r, [perfil.codigo]: novo }));
  }

  async function salvar(perfil: PerfilComAcesso) {
    setSalvando(perfil.codigo);
    try {
      await salvarPerfil(perfil.codigo, perfil.rotulo, perfil.descricao, marcados(perfil));
      await carregar();
    } catch (e) {
      setErro(e instanceof ApiError ? e.message : "Não foi possível salvar.");
    } finally {
      setSalvando(null);
    }
  }

  async function criar() {
    const rotulo = novoRotulo.trim();
    const codigo = codigoDe(rotulo);
    if (!codigo) return;
    setSalvando(codigo);
    try {
      // Nasce sem módulo nenhum, de propósito: quem cria escolhe o que abrir, em
      // vez de sair fechando o que não devia ter vindo aberto.
      await salvarPerfil(codigo, rotulo, "", []);
      setNovoRotulo("");
      await carregar();
    } catch (e) {
      setErro(e instanceof ApiError ? e.message : "Não foi possível criar o perfil.");
    } finally {
      setSalvando(null);
    }
  }

  async function remover(perfil: PerfilComAcesso) {
    if (!confirm(`Apagar o perfil "${perfil.rotulo}"? Quem já o tem continua com ele no login.`))
      return;
    setSalvando(perfil.codigo);
    try {
      await removerPerfil(perfil.codigo);
      await carregar();
    } catch (e) {
      setErro(e instanceof ApiError ? e.message : "Não foi possível apagar.");
    } finally {
      setSalvando(null);
    }
  }

  return (
    <section className="mt-8 border-t border-borda pt-6">
      <header className="[&>h2]:m-0 [&>h2]:mb-1 [&>h2]:font-titulo [&>h2]:text-lg [&>h2]:font-semibold [&>h2]:leading-[1.2] [&>p]:mt-0 [&>p]:mb-[18px] [&>p]:max-w-[62ch] [&>p]:text-tinta-3 [&>p]:text-sm [&>p]:leading-[1.55]">
        <h2>Perfis de acesso</h2>
        <p>
          O que cada perfil alcança no sistema. Módulo desmarcado fica fora — quem
          tiver só esse perfil recebe recusa ao tentar entrar nele.
        </p>
      </header>

      {erro && <p className="mt-0 mb-[14px] border-l-[3px] border-critico px-3 py-2 bg-critico-claro text-sm leading-[1.5]">{erro}</p>}

      {carregando ? (
        <p className="text-tinta-3 text-sm leading-[1.5]">Carregando…</p>
      ) : (
        <div className="overflow-x-auto border border-borda-forte">
          <table className="border-collapse w-full text-sm leading-[1.4]">
            <thead>
              <tr>
                <th className={`${CELULA_MATRIZ} ${COLUNA_FIXA} text-tinta-3 text-xs font-semibold uppercase tracking-[0.06em] leading-[1.3]`}>Perfil</th>
                {modulos.map((m) => (
                  // O `title` carrega a descrição do módulo: a coluna é estreita
                  // e o rótulo sozinho não diz o que "Entrevistas no geral" cobre.
                  <th key={m.codigo} title={m.descricao} className={`${CELULA_MATRIZ} min-w-[46px] align-bottom pb-3 [&>span]:inline-block [&>span]:[writing-mode:vertical-rl] [&>span]:rotate-180 [&>span]:max-h-[148px] [&>span]:text-tinta [&>span]:text-xs [&>span]:font-semibold [&>span]:leading-[1.2] [&>span]:cursor-help`}>
                    <span>{m.rotulo}</span>
                  </th>
                ))}
                <th className={`${CELULA_MATRIZ} min-w-[92px] whitespace-nowrap`} />
              </tr>
            </thead>
            <tbody>
              {perfis.map((perfil) => (
                <tr key={perfil.codigo} className={mudou(perfil) ? "bg-atencao-claro" : ""}>
                  <th scope="row" className={`${CELULA_MATRIZ} ${COLUNA_FIXA} [&>strong]:block [&>strong]:text-sm [&>strong]:font-semibold [&>strong]:leading-[1.3] [&>small]:block [&>small]:mt-[3px] [&>small]:text-tinta-3 [&>small]:text-xs [&>small]:leading-[1.4]`}>
                    <strong>{perfil.rotulo}</strong>
                    {perfil.sistema && <span className="inline-block ml-[6px] border border-borda-forte px-[6px] py-px text-tinta-3 text-xs font-semibold leading-[1.4] align-middle">sistema</span>}
                    {perfil.descricao && <small>{perfil.descricao}</small>}
                  </th>

                  {modulos.map((m) => (
                    <td key={m.codigo} className={CELULA_MATRIZ}>
                      <label className={`${CELULA_MATRIZ} [&>input]:w-[17px] [&>input]:h-[17px] [&>input]:cursor-pointer [&>input]:accent-acao`}>
                        <input
                          type="checkbox"
                          checked={marcados(perfil).includes(m.codigo)}
                          onChange={() => alternar(perfil, m.codigo)}
                          aria-label={`${perfil.rotulo} acessa ${m.rotulo}`}
                        />
                      </label>
                    </td>
                  ))}

                  <td className={`${CELULA_MATRIZ} min-w-[92px] whitespace-nowrap`}>
                    {mudou(perfil) && (
                      <button
                        type="button"
                        className={BOTAO_ACAO}
                        onClick={() => void salvar(perfil)}
                        disabled={salvando === perfil.codigo}
                      >
                        {salvando === perfil.codigo ? "Salvando…" : "Salvar"}
                      </button>
                    )}
                    {/* Perfil de sistema não some: um Acervo sem ninguém capaz de
                      * administrar usuários só se conserta no banco, à mão. */}
                    {!perfil.sistema && !mudou(perfil) && (
                      <button
                        type="button"
                        className="border border-borda-forte bg-transparent text-tinta-3 text-xs font-semibold uppercase tracking-[0.06em] leading-none px-[10px] py-2 cursor-pointer enabled:hover:border-critico enabled:hover:text-critico"
                        onClick={() => void remover(perfil)}
                        disabled={salvando === perfil.codigo}
                      >
                        Apagar
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <div className="flex items-end gap-3 flex-wrap mt-[18px]">
        <label className={CAMPO_NOVO}>
          <span>Novo perfil</span>
          <input
            value={novoRotulo}
            onChange={(e) => setNovoRotulo(e.target.value)}
            placeholder="Analista, Estagiário, Financeiro…"
            maxLength={120}
          />
        </label>
        <button
          type="button"
          className={BOTAO_ACAO}
          onClick={() => void criar()}
          disabled={!novoRotulo.trim() || salvando !== null}
        >
          Criar
        </button>
        {novoRotulo.trim() && (
          <span className="text-tinta-3 text-xs leading-[1.4] [&>code]:font-codigo [&>code]:text-tinta">
            código: <code>{codigoDe(novoRotulo)}</code>
          </span>
        )}
      </div>
    </section>
  );
}
