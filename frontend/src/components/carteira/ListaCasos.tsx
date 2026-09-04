"use client";

import { useRef, useState } from "react";

import type { Caso, CasoCriado, Categoria } from "@/lib/types";
import {
  sugerirCategoriaPorDocumentos,
  sugerirCategoriaPorZip,
  type SugestaoCategoriaPorDocumentos,
} from "@/lib/api";
import { Aviso, Botao, Campo, CampoSeletor, Cartao, RotuloCampo, Selo, Vazio } from "@/components/ui/Basicos";
import CredenciaisPortal from "@/components/portal/CredenciaisPortal";

interface Props {
  casos: Caso[];
  categorias: Categoria[];
  carregando: boolean;
  erro: string | null;
  onAbrir: (casoId: string) => void;
  onCriar: (cliente: string, categoria: string) => Promise<CasoCriado>;
  onExcluir: (casoId: string) => Promise<void>;
}

export default function ListaCasos({
  casos,
  categorias,
  carregando,
  erro,
  onAbrir,
  onCriar,
  onExcluir,
}: Props) {
  const [cliente, setCliente] = useState("");
  const [categoria, setCategoria] = useState("");
  const [criando, setCriando] = useState(false);
  const [confirmando, setConfirmando] = useState<string | null>(null);
  const [sugerindo, setSugerindo] = useState(false);
  const [sugestao, setSugestao] = useState<SugestaoCategoriaPorDocumentos | null>(null);
  const [erroSugestao, setErroSugestao] = useState<string | null>(null);
  const inputSugestaoRef = useRef<HTMLInputElement>(null);
  /* A lista chega inteira do servidor (podem ser centenas). Aqui ela é paginada
   * de 5 em 5 só para exibição — nada é buscado por página. `pagina` pode ficar
   * maior que o total depois de uma exclusão; `paginaAtual` reancora. */
  const POR_PAGINA = 5;
  const [pagina, setPagina] = useState(1);
  /* Credenciais do caso recém-criado. Ficam só em memória: a senha existe em
   * texto claro apenas nesta resposta, e some ao sair da tela. */
  const [novoPortal, setNovoPortal] = useState<CasoCriado | null>(null);
  const categoriaSelecionada = categoria || categorias[0]?.codigo || "";
  const categoriaEscolhida = categorias.find((item) => item.codigo === categoriaSelecionada);

  async function criar(evento: React.FormEvent) {
    evento.preventDefault();
    if (!cliente.trim() || !categoriaSelecionada) return;
    setCriando(true);
    try {
      setNovoPortal(await onCriar(cliente.trim(), categoriaSelecionada));
      setCliente("");
    } finally {
      setCriando(false);
    }
  }

  const nomeCategoria = (codigo: string) =>
    categorias.find((c) => c.codigo === codigo)?.nome ?? codigo;

  async function sugerirPelosDocumentos(arquivos: File[]) {
    if (!arquivos.length) return;
    setSugerindo(true);
    setErroSugestao(null);
    setSugestao(null);
    try {
      const resultado =
        arquivos.length === 1 && arquivos[0].name.toLowerCase().endsWith(".zip")
          ? await sugerirCategoriaPorZip(arquivos[0])
          : await sugerirCategoriaPorDocumentos(arquivos);
      setSugestao(resultado);
      const melhor = resultado.sugestoes[0];
      if (melhor && categorias.some((c) => c.codigo === melhor.codigo)) {
        setCategoria(melhor.codigo);
      }
    } catch (e) {
      setErroSugestao(e instanceof Error ? e.message : "Falha ao ler os documentos.");
    } finally {
      setSugerindo(false);
    }
  }

  const totalPaginas = Math.max(1, Math.ceil(casos.length / POR_PAGINA));
  const paginaAtual = Math.min(Math.max(1, pagina), totalPaginas);
  const casosVisiveis = casos.slice((paginaAtual - 1) * POR_PAGINA, paginaAtual * POR_PAGINA);

  return (
    <div className="grid min-w-0 grid-cols-[minmax(280px,380px)_minmax(0,1fr)] items-start gap-5 max-[980px]:grid-cols-1">
      <Cartao
        titulo="Novo caso"
        subtitulo="Escolher o tipo de ação é o que monta o checklist de documentos do cliente."
        className="min-w-0"
      >
        <form onSubmit={criar}>
          <div className="mb-4">
            <RotuloCampo htmlFor="cliente">Nome do cliente</RotuloCampo>
            <Campo
              id="cliente"
              value={cliente}
              onChange={(e) => setCliente(e.target.value)}
              placeholder="Ex.: Maria Aparecida da Silva"
              autoComplete="off"
            />
          </div>

          <div className="mb-4 px-[14px] py-[13px] border border-borda rounded-campo bg-papel-2">
            <div className="flex justify-between items-center gap-3 flex-wrap">
              <div>
                <strong className="block text-tinta text-sm">Não sabe o tipo de ação?</strong>
                <p className="mt-1 mb-0 text-tinta-2 text-xs leading-[1.5]">
                  Envie os documentos do cliente (ou um .zip da pasta) e o sistema lê e sugere.
                  A escolha final continua sendo sua.
                </p>
              </div>
              <Botao
                type="button"
                variante="secundario"
                pequeno
                disabled={sugerindo}
                onClick={() => inputSugestaoRef.current?.click()}
              >
                {sugerindo ? "Lendo…" : "Escolher documentos"}
              </Botao>
              <input
                ref={inputSugestaoRef}
                type="file"
                multiple
                hidden
                onChange={(e) => {
                  void sugerirPelosDocumentos(Array.from(e.target.files ?? []));
                  e.target.value = "";
                }}
              />
            </div>

            {sugerindo && (
              <p className="mt-[10px] mb-0 text-tinta-3 text-xs">
                Lendo os documentos por OCR — um lote com várias dezenas de arquivos pode levar
                alguns minutos.
              </p>
            )}

            {erroSugestao && (
              <div className="mt-[10px]">
                <Aviso tom="critico" titulo="Não foi possível sugerir">
                  {erroSugestao}
                </Aviso>
              </div>
            )}

            {sugestao && (
              <div className="mt-[10px]">
                {sugestao.sugestoes.length === 0 ? (
                  <p className="m-0 text-tinta-2 text-xs leading-[1.5]">{sugestao.motivo}</p>
                ) : (
                  <>
                    <p className="m-0 text-tinta-2 text-xs leading-[1.5]">
                      {sugestao.confiante ? "Sugestão: " : "Sugestão (confira antes de aceitar): "}
                      <strong>{sugestao.sugestoes[0].nome}</strong> — {sugestao.motivo}
                    </p>
                    {sugestao.sugestoes[0].evidencias.length > 0 && (
                      <ul className="mt-[6px] mb-0 pl-4 text-tinta-3 text-xs leading-[1.5]">
                        {sugestao.sugestoes[0].evidencias.slice(0, 3).map((ev, i) => (
                          <li key={i}>{ev}</li>
                        ))}
                      </ul>
                    )}
                  </>
                )}
                <p className="mt-[6px] mb-0 text-tinta-3 text-xs">
                  {sugestao.documentos.length} documento(s) lido(s).
                </p>
              </div>
            )}
          </div>

          <div className="mb-4">
            <RotuloCampo htmlFor="categoria">Tipo de ação</RotuloCampo>
            <CampoSeletor
              id="categoria"
              value={categoriaSelecionada}
              onChange={(e) => setCategoria(e.target.value)}
              aria-describedby={categoriaEscolhida ? "resumo-categoria" : undefined}
            >
              {categorias.map((c) => (
                <option key={c.codigo} value={c.codigo}>
                  {c.nome}
                </option>
              ))}
            </CampoSeletor>

            {categoriaEscolhida && (
              <div
                id="resumo-categoria"
                className="mt-[10px] px-[14px] py-[13px] border border-acao-borda rounded-campo bg-acao-clara"
              >
                <strong className="block text-tinta text-sm">{categoriaEscolhida.nome}</strong>
                <p className="mt-1 text-tinta-2 text-xs leading-[1.5]">
                  {categoriaEscolhida.descricao}
                </p>
                <div className="flex gap-2 mt-[10px] flex-wrap">
                  <Selo tom="info">{categoriaEscolhida.total_obrigatorios} obrigatórios</Selo>
                  <Selo tom="neutro">{categoriaEscolhida.total_documentos} no total</Selo>
                </div>
              </div>
            )}
          </div>

          <Botao
            type="submit"
            variante="primario"
            bloco
            disabled={!cliente.trim() || !categoriaSelecionada || criando}
          >
            {criando ? "Criando…" : "Criar o caso"}
          </Botao>
        </form>

        {categorias.length === 0 && (
          <div className="mt-[14px]">
            <Aviso tom="critico" titulo="Nenhum tipo de ação disponível">
              Verifique se o servidor do sistema está no ar — sem os tipos de ação não é possível
              criar um caso.
            </Aviso>
          </div>
        )}

        {novoPortal && (
          <CredenciaisPortal
            cliente={novoPortal.cliente}
            portal={novoPortal.portal}
            onAbrirCaso={() => onAbrir(novoPortal.id)}
            onFechar={() => setNovoPortal(null)}
          />
        )}
      </Cartao>

      <Cartao
        titulo="Casos cadastrados"
        className="min-w-0 overflow-hidden"
        subtitulo={
          casos.length === 0
            ? "Nenhum caso ainda."
            : `${casos.length} ${casos.length === 1 ? "caso" : "casos"} — clique em um para abrir o checklist.`
        }
      >
        {erro && (
          <div className="mb-[14px]">
            <Aviso tom="critico" titulo="Não foi possível carregar os casos">
              {erro}
            </Aviso>
          </div>
        )}

        {carregando && casos.length === 0 ? (
          <Vazio>Carregando…</Vazio>
        ) : casos.length === 0 ? (
          <Vazio>Crie o primeiro caso ao lado para começar a cobrar os documentos do cliente.</Vazio>
        ) : (
          <>
          <div className="min-w-0 overflow-hidden rounded-campo border border-borda">
            <div className="hidden grid-cols-[minmax(0,1.3fr)_minmax(0,1fr)_112px_164px] gap-3 border-b border-borda bg-papel-2 px-4 py-3 text-[11px] font-bold uppercase tracking-[0.08em] text-tinta-3 min-[780px]:grid">
              <span>Cliente</span>
              <span>Tipo de ação</span>
              <span>Arquivos</span>
              <span className="text-right">Ações</span>
            </div>

            <ul className="m-0 list-none divide-y divide-borda p-0">
              {casosVisiveis.map((caso) => {
                const totalEntregas = caso.total_entregas ?? 0;
                const categoriaNome = nomeCategoria(caso.categoria);

                return (
                  <li key={caso.id} className="min-w-0 bg-papel">
                    <div className="grid min-w-0 gap-3 px-3 py-3 min-[780px]:grid-cols-[minmax(0,1.3fr)_minmax(0,1fr)_112px_164px] min-[780px]:items-center min-[780px]:px-4">
                      <button
                        type="button"
                        className="min-w-0 rounded-campo border-none bg-transparent p-1 text-left text-inherit [font:inherit] transition-colors hover:bg-papel-3"
                        onClick={() => onAbrir(caso.id)}
                        title={caso.cliente}
                      >
                        <span className="block truncate text-base font-semibold text-tinta">
                          {caso.cliente}
                        </span>
                        <span className="mt-1 block truncate font-codigo text-xs text-tinta-3">
                          {caso.id}
                        </span>
                      </button>

                      <div className="min-w-0">
                        <span className="mb-1 block text-[11px] font-bold uppercase tracking-[0.08em] text-tinta-3 min-[780px]:hidden">
                          Tipo de ação
                        </span>
                        <span className="block truncate text-sm text-tinta-2" title={categoriaNome}>
                          {categoriaNome}
                        </span>
                      </div>

                      <div className="min-w-0">
                        <span className="mb-1 block text-[11px] font-bold uppercase tracking-[0.08em] text-tinta-3 min-[780px]:hidden">
                          Arquivos
                        </span>
                        <Selo tom={totalEntregas > 0 ? "info" : "neutro"}>
                          {totalEntregas} {totalEntregas === 1 ? "arquivo" : "arquivos"}
                        </Selo>
                      </div>

                      <div className="flex min-w-0 flex-wrap items-center justify-start gap-2 min-[780px]:justify-end">
                        <Botao variante="secundario" pequeno onClick={() => onAbrir(caso.id)}>
                          Abrir
                        </Botao>
                        {confirmando === caso.id ? (
                          <span className="flex min-w-0 max-w-full items-center gap-2 rounded-campo border border-critico-borda bg-critico-claro px-2 py-2">
                            <span className="min-w-0 max-w-[22ch] truncate text-xs text-tinta-2">
                              Apagar caso e arquivos?
                            </span>
                            <Botao
                              variante="perigo"
                              pequeno
                              onClick={async () => {
                                await onExcluir(caso.id);
                                setConfirmando(null);
                              }}
                            >
                              Apagar
                            </Botao>
                            <Botao variante="discreto" pequeno onClick={() => setConfirmando(null)}>
                              Cancelar
                            </Botao>
                          </span>
                        ) : (
                          <Botao variante="discreto" pequeno onClick={() => setConfirmando(caso.id)}>
                            Excluir
                          </Botao>
                        )}
                      </div>
                    </div>
                  </li>
                );
              })}
            </ul>
          </div>

          {casos.length > POR_PAGINA && (
            <div className="mt-3 flex min-w-0 items-center justify-between gap-3 border-t border-borda pt-3">
              <Botao
                variante="discreto"
                pequeno
                disabled={paginaAtual <= 1}
                onClick={() => setPagina(paginaAtual - 1)}
              >
                ← Anterior
              </Botao>
              <span className="min-w-0 truncate text-center text-xs tabular-nums text-tinta-3">
                Página {paginaAtual} de {totalPaginas}
              </span>
              <Botao
                variante="discreto"
                pequeno
                disabled={paginaAtual >= totalPaginas}
                onClick={() => setPagina(paginaAtual + 1)}
              >
                Próximo →
              </Botao>
            </div>
          )}
          </>
        )}
      </Cartao>
    </div>
  );
}
