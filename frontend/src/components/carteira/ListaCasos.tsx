"use client";

import { useState } from "react";

import type { Caso, CasoCriado, Categoria } from "@/lib/types";
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

  const totalPaginas = Math.max(1, Math.ceil(casos.length / POR_PAGINA));
  const paginaAtual = Math.min(Math.max(1, pagina), totalPaginas);
  const casosVisiveis = casos.slice((paginaAtual - 1) * POR_PAGINA, paginaAtual * POR_PAGINA);

  return (
    <div className="grid grid-cols-[minmax(320px,420px)_1fr] max-[900px]:grid-cols-1 gap-5 items-start">
      <Cartao
        titulo="Novo caso"
        subtitulo="Escolher o tipo de ação é o que monta o checklist de documentos do cliente."
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
          <ul className="list-none m-0 p-0">
            {casosVisiveis.map((caso) => (
              <li
                key={caso.id}
                className="flex items-center gap-[10px] py-2 border-b border-borda flex-wrap last:border-b-0"
              >
                <button
                  type="button"
                  className="flex-1 min-w-[180px] flex flex-col items-start gap-[2px] px-[10px] py-2 border-none rounded-campo bg-transparent text-inherit [font:inherit] text-left cursor-pointer transition-[background-color] duration-[120ms] ease-[ease] hover:bg-papel-3"
                  onClick={() => onAbrir(caso.id)}
                >
                  <span className="text-tinta text-base font-semibold">{caso.cliente}</span>
                  <span className="text-tinta-3 text-xs">
                    {nomeCategoria(caso.categoria)} · {caso.total_entregas ?? 0}{" "}
                    {(caso.total_entregas ?? 0) === 1 ? "arquivo recebido" : "arquivos recebidos"}
                  </span>
                </button>

                {confirmando === caso.id ? (
                  <span className="flex items-center gap-2 px-[10px] py-2 border border-critico-borda rounded-campo bg-critico-claro flex-wrap">
                    <span className="text-tinta-2 text-xs max-w-[30ch]">
                      Apagar o caso e todos os arquivos enviados? Não há como desfazer.
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
              </li>
            ))}
          </ul>

          {casos.length > POR_PAGINA && (
            <div className="flex items-center justify-between gap-3 mt-3 pt-3 border-t border-borda">
              <Botao
                variante="discreto"
                pequeno
                disabled={paginaAtual <= 1}
                onClick={() => setPagina(paginaAtual - 1)}
              >
                ← Anterior
              </Botao>
              <span className="text-tinta-3 text-xs tabular-nums">
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
