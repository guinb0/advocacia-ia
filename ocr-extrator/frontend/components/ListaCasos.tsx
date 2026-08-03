"use client";

import { useState } from "react";

import type { Caso, Categoria } from "@/lib/types";
import estilos from "./ListaCasos.module.css";
import ui from "./ui.module.css";

interface Props {
  casos: Caso[];
  categorias: Categoria[];
  carregando: boolean;
  erro: string | null;
  onAbrir: (casoId: string) => void;
  onCriar: (cliente: string, categoria: string) => Promise<unknown>;
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

  const categoriaSelecionada = categoria || categorias[0]?.codigo || "";

  async function criar(evento: React.FormEvent) {
    evento.preventDefault();
    if (!cliente.trim() || !categoriaSelecionada) return;
    setCriando(true);
    try {
      await onCriar(cliente.trim(), categoriaSelecionada);
      setCliente("");
    } finally {
      setCriando(false);
    }
  }

  const nomeCategoria = (codigo: string) =>
    categorias.find((c) => c.codigo === codigo)?.nome ?? codigo;

  return (
    <div className={estilos.colunas}>
      <div className={ui.card}>
        <h2 className={ui.tituloCard}>Novo caso</h2>

        <form onSubmit={criar}>
          <label className={estilos.rotulo} htmlFor="cliente">
            Nome do cliente
          </label>
          <input
            id="cliente"
            className={estilos.campo}
            value={cliente}
            onChange={(e) => setCliente(e.target.value)}
            placeholder="Ex.: Maria Aparecida da Silva"
            autoComplete="off"
          />

          <label className={estilos.rotulo} htmlFor="categoria">
            Categoria
          </label>
          <select
            id="categoria"
            className={estilos.campo}
            value={categoriaSelecionada}
            onChange={(e) => setCategoria(e.target.value)}
          >
            {categorias.map((c) => (
              <option key={c.codigo} value={c.codigo}>
                {c.nome} — {c.total_obrigatorios} obrigatórios
              </option>
            ))}
          </select>

          <button
            type="submit"
            className={estilos.botaoPrimario}
            disabled={!cliente.trim() || !categoriaSelecionada || criando}
          >
            {criando ? "Criando…" : "Criar caso"}
          </button>
        </form>

        {categorias.length === 0 && (
          <p className={ui.observacao} style={{ marginTop: 12 }}>
            Nenhuma categoria disponível — verifique se o backend está no ar.
          </p>
        )}
      </div>

      <div className={ui.card}>
        <h2 className={ui.tituloCard}>Casos ({casos.length})</h2>

        {erro && <div className={ui.caixaErro}>{erro}</div>}

        {carregando && casos.length === 0 ? (
          <div className={ui.vazio}>Carregando…</div>
        ) : casos.length === 0 ? (
          <div className={ui.vazio}>
            Nenhum caso ainda.
            <br />
            <small>Crie o primeiro ao lado para começar a cobrar os documentos.</small>
          </div>
        ) : (
          <ul className={estilos.lista}>
            {casos.map((caso) => (
              <li key={caso.id} className={estilos.itemCaso}>
                <button type="button" className={estilos.abrir} onClick={() => onAbrir(caso.id)}>
                  <strong>{caso.cliente}</strong>
                  <span className={ui.observacao}>
                    {nomeCategoria(caso.categoria)} · {caso.total_entregas ?? 0} arquivo(s)
                  </span>
                </button>

                {confirmando === caso.id ? (
                  <span className={estilos.confirmar}>
                    <button
                      type="button"
                      className={estilos.perigo}
                      onClick={async () => {
                        await onExcluir(caso.id);
                        setConfirmando(null);
                      }}
                    >
                      Apagar tudo
                    </button>
                    <button
                      type="button"
                      className={estilos.botaoDiscreto}
                      onClick={() => setConfirmando(null)}
                    >
                      Cancelar
                    </button>
                  </span>
                ) : (
                  <button
                    type="button"
                    className={estilos.botaoDiscreto}
                    onClick={() => setConfirmando(caso.id)}
                    title="Excluir o caso e todos os arquivos enviados"
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
