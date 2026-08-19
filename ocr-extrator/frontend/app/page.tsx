"use client";

import { useState } from "react";

import { Aviso, Selo } from "@/components/Basicos";
import Carteira from "@/components/Carteira";
import Checklist from "@/components/Checklist";
import Dossie from "@/components/Dossie";
import Investigacao from "@/components/Investigacao";
import ListaCasos from "@/components/ListaCasos";
import PainelEnvio from "@/components/PainelEnvio";
import ProgressoOcr from "@/components/ProgressoOcr";
import Usuarios from "@/components/Usuarios";
import Resultado from "@/components/Resultado";
import ui from "@/components/ui.module.css";
import { useCasos, useCategorias, useSituacao } from "@/lib/useCasos";
import { useExtracao, useModelo, useTipos } from "@/lib/useExtracao";
import estilos from "./page.module.css";

/** A carteira é a porta de entrada; as outras telas são destinos dela. */
type Tela =
  | "carteira"
  | "caso"
  | "dossie"
  | "casos"
  | "avulso"
  | "investigacao"
  | "usuarios";

/* Título e explicação de cada tela secundária. Ter isso escrito na tela é o
 * que responde "onde eu estou" sem depender de memória. */
const CABECALHO: Record<"casos" | "avulso", { titulo: string; subtitulo: string }> = {
  casos: {
    titulo: "Casos",
    subtitulo:
      "Cadastre um caso para montar o checklist de documentos do cliente, ou abra um caso existente.",
  },
  avulso: {
    titulo: "Ler um documento",
    subtitulo:
      "Leitura solta, para conferir os dados de um documento na hora. Nada aqui é guardado em nenhum caso.",
  },
};

export default function Home() {
  const [tela, setTela] = useState<Tela>("carteira");
  const [casoAberto, setCasoAberto] = useState<string | null>(null);

  const categorias = useCategorias();
  const listaCasos = useCasos();
  const situacaoCaso = useSituacao(casoAberto);

  function abrirCaso(casoId: string) {
    setCasoAberto(casoId);
    setTela("caso");
  }

  function voltarParaCarteira() {
    setCasoAberto(null);
    setTela("carteira");
    void listaCasos.recarregar();
  }

  if (tela === "carteira") {
    return (
      <Carteira
        onAbrir={abrirCaso}
        onNovoCaso={() => setTela("casos")}
        onAnalisarAvulso={() => setTela("avulso")}
        onInvestigar={() => setTela("investigacao")}
        onUsuarios={() => setTela("usuarios")}
      />
    );
  }

  if (tela === "dossie") {
    // Sem caso aberto não há dossiê: voltar é mais honesto que renderizar vazio.
    if (!casoAberto) {
      voltarParaCarteira();
      return null;
    }
    return <Dossie casoId={casoAberto} onVoltar={voltarParaCarteira} />;
  }

  if (tela === "investigacao") {
    return <Investigacao onVoltar={voltarParaCarteira} />;
  }

  if (tela === "usuarios") {
    return <Usuarios onVoltar={voltarParaCarteira} />;
  }

  if (tela === "caso") {
    return (
      <div className={estilos.container}>
        {/* O checklist responde "o que falta chegar"; o dossiê, "o que o caso já
          * é". São perguntas diferentes e telas diferentes — juntá-las numa só
          * faria a mais longa esconder a mais usada. */}
        <div className={estilos.abasCaso}>
          <button type="button" className="botao botao--secundario botao--pequeno" disabled>
            Checklist de documentos
          </button>
          <button
            type="button"
            className="botao botao--texto botao--pequeno"
            onClick={() => setTela("dossie")}
          >
            Dossiê do caso →
          </button>
        </div>
        {situacaoCaso.situacao ? (
          <Checklist
            situacao={situacaoCaso.situacao}
            enviando={situacaoCaso.enviando}
            erro={situacaoCaso.erro}
            onVoltar={voltarParaCarteira}
            onEnviar={situacaoCaso.enviar}
            onRemover={situacaoCaso.removerEntrega}
            onVincularIdentidade={situacaoCaso.vincularIdentidade}
          />
        ) : situacaoCaso.erro ? (
          <>
            <button
              type="button"
              className="botao botao--secundario"
              onClick={voltarParaCarteira}
              style={{ marginBottom: 16 }}
            >
              ← Voltar para a carteira
            </button>
            <Aviso tom="critico" titulo="Não foi possível abrir o caso">
              {situacaoCaso.erro}
            </Aviso>
          </>
        ) : (
          <div className={ui.vazio}>Carregando o caso…</div>
        )}
      </div>
    );
  }

  const cabecalho = CABECALHO[tela];

  return (
    <div className={estilos.container}>
      <div className={estilos.cabecalho}>
        <div>
          <button
            type="button"
            className="botao botao--secundario botao--pequeno"
            onClick={voltarParaCarteira}
          >
            ← Voltar para a carteira
          </button>
          <h1 className={estilos.titulo}>{cabecalho.titulo}</h1>
          <p className={estilos.subtitulo}>{cabecalho.subtitulo}</p>
        </div>
      </div>

      {tela === "casos" ? (
        <ListaCasos
          casos={listaCasos.casos}
          categorias={categorias}
          carregando={listaCasos.carregando}
          erro={listaCasos.erro}
          onAbrir={abrirCaso}
          onCriar={listaCasos.criar}
          onExcluir={listaCasos.excluir}
        />
      ) : (
        <AnaliseAvulsa />
      )}
    </div>
  );
}

/** A ferramenta original: lê um documento solto, sem vincular a nenhum caso. */
function AnaliseAvulsa() {
  const tipos = useTipos();
  const estadoModelo = useModelo();
  const { arquivo, previewUrl, resultado, processando, erro, escolher, limpar, processar } =
    useExtracao();

  return (
    <div className={estilos.grade}>
      <PainelEnvio
        arquivo={arquivo}
        previewUrl={previewUrl}
        processando={processando}
        erro={erro}
        tipos={tipos}
        onEscolher={escolher}
        onExtrair={processar}
        onLimpar={limpar}
      />

      <div className="cartao">
        <h2 className="tituloCartao">Dados lidos</h2>

        {processando ? (
          <ProgressoOcr modeloPronto={estadoModelo === "pronto"} />
        ) : resultado ? (
          <Resultado doc={resultado} />
        ) : (
          <div className={ui.vazio}>
            Escolha um documento ao lado para começar.
            <div className={estilos.tiposAceitos}>
              {["CPF", "RG", "CIN", "CNH", "CTPS", "Título de eleitor", "Cartão SUS", "Comprovante de residência"].map(
                (tipo) => (
                  <Selo key={tipo} tom="neutro">
                    {tipo}
                  </Selo>
                ),
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
