"use client";

import { useState } from "react";

import type { Caso, CasoCriado, Categoria } from "@/lib/types";
import { Aviso, Selo } from "./Basicos";
import CredenciaisPortal from "./CredenciaisPortal";
import estilos from "./ListaCasos.module.css";
import TriagemEntrevista from "./TriagemEntrevista";
import ui from "./ui.module.css";

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

  return (
    <div className={estilos.colunas}>
      <div className="cartao">
        <h2 className="tituloCartao">Novo caso</h2>
        <p className="subtituloCartao">
          Escolher o tipo de ação é o que monta o checklist de documentos do cliente.
        </p>

        <TriagemEntrevista
          onEscolher={(cat, nome) => {
            if (cat) setCategoria(cat);
            // A entrevista costuma trazer o nome no cabeçalho; não sobrescreve
            // o que o usuário já tiver digitado.
            if (nome && !cliente.trim()) setCliente(nome);
          }}
        />

        <form onSubmit={criar}>
          <div className={estilos.grupoCampo}>
            <label className="rotuloCampo" htmlFor="cliente">
              Nome do cliente
            </label>
            <input
              id="cliente"
              className="campo"
              value={cliente}
              onChange={(e) => setCliente(e.target.value)}
              placeholder="Ex.: Maria Aparecida da Silva"
              autoComplete="off"
            />
          </div>

          <div className={estilos.grupoCampo}>
            <label className="rotuloCampo" htmlFor="categoria">
              Tipo de ação
            </label>
            <select
              id="categoria"
              className="campo campo--seletor"
              value={categoriaSelecionada}
              onChange={(e) => setCategoria(e.target.value)}
              aria-describedby={categoriaEscolhida ? "resumo-categoria" : undefined}
            >
              {categorias.map((c) => (
                <option key={c.codigo} value={c.codigo}>
                  {c.nome}
                </option>
              ))}
            </select>

            {categoriaEscolhida && (
              <div id="resumo-categoria" className={estilos.resumoCategoria}>
                <strong>{categoriaEscolhida.nome}</strong>
                <p>{categoriaEscolhida.descricao}</p>
                <div className={estilos.numerosCategoria}>
                  <Selo tom="info">{categoriaEscolhida.total_obrigatorios} obrigatórios</Selo>
                  <Selo tom="neutro">{categoriaEscolhida.total_documentos} no total</Selo>
                </div>
              </div>
            )}
          </div>

          <button
            type="submit"
            className="botao botao--primario botao--bloco"
            disabled={!cliente.trim() || !categoriaSelecionada || criando}
          >
            {criando ? "Criando…" : "Criar o caso"}
          </button>
        </form>

        {categorias.length === 0 && (
          <div style={{ marginTop: 14 }}>
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
      </div>

      <div className="cartao">
        <h2 className="tituloCartao">Casos cadastrados</h2>
        <p className="subtituloCartao">
          {casos.length === 0
            ? "Nenhum caso ainda."
            : `${casos.length} ${casos.length === 1 ? "caso" : "casos"} — clique em um para abrir o checklist.`}
        </p>

        {erro && (
          <div style={{ marginBottom: 14 }}>
            <Aviso tom="critico" titulo="Não foi possível carregar os casos">
              {erro}
            </Aviso>
          </div>
        )}

        {carregando && casos.length === 0 ? (
          <div className={ui.vazio}>Carregando…</div>
        ) : casos.length === 0 ? (
          <div className={ui.vazio}>
            Crie o primeiro caso ao lado para começar a cobrar os documentos do cliente.
          </div>
        ) : (
          <ul className={estilos.lista}>
            {casos.map((caso) => (
              <li key={caso.id} className={estilos.itemCaso}>
                <button type="button" className={estilos.abrir} onClick={() => onAbrir(caso.id)}>
                  <span className={estilos.abrirCliente}>{caso.cliente}</span>
                  <span className={estilos.abrirMeta}>
                    {nomeCategoria(caso.categoria)} · {caso.total_entregas ?? 0}{" "}
                    {(caso.total_entregas ?? 0) === 1 ? "arquivo recebido" : "arquivos recebidos"}
                  </span>
                </button>

                {confirmando === caso.id ? (
                  <span className={estilos.confirmar}>
                    <span className={estilos.confirmarTexto}>
                      Apagar o caso e todos os arquivos enviados? Não há como desfazer.
                    </span>
                    <button
                      type="button"
                      className="botao botao--perigo botao--pequeno"
                      onClick={async () => {
                        await onExcluir(caso.id);
                        setConfirmando(null);
                      }}
                    >
                      Apagar
                    </button>
                    <button
                      type="button"
                      className="botao botao--discreto botao--pequeno"
                      onClick={() => setConfirmando(null)}
                    >
                      Cancelar
                    </button>
                  </span>
                ) : (
                  <button
                    type="button"
                    className="botao botao--discreto botao--pequeno"
                    onClick={() => setConfirmando(caso.id)}
                  >
                    Excluir
                  </button>
                )}
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
