"use client";

import { useState } from "react";

import { useChamada } from "@/lib/ChamadaContexto";
import type { CasoCriado, Categoria } from "@/lib/types";
import { useSituacao } from "@/lib/useCasos";
import { Aviso, Selo } from "./Basicos";
import estilos from "./CasoEDocumentos.module.css";
import Checklist from "./Checklist";
import CredenciaisPortal from "./CredenciaisPortal";

/* A última etapa do atendimento, e ela acontece COM O CLIENTE NA LINHA.
 *
 * Antes, criar o caso era outra tela: a entrevista terminava, o atendente saía,
 * criava o caso, copiava o link do portal e mandava — com o cliente já
 * desligado, ou esperando sem saber o quê. O checklist só era aberto depois, e
 * quem descobria que faltava documento era o escritório, dias depois, por
 * telefone.
 *
 * Agora o caso nasce aqui, o portal abre aqui, e o checklist fica na tela
 * enquanto a chamada corre. O ganho é um só e é grande: **o cliente envia o que
 * já tem agora**, com alguém do outro lado para dizer se a foto saiu legível.
 * O que ele não tiver, ele manda depois pelo mesmo link — e para isso existe o
 * botão de encerrar a chamada sem encerrar o caso. */

interface Props {
  /** Nome que a entrevista trouxe. É o nome do caso, e o atendente pode ajustar. */
  cliente: string;
  categorias: Categoria[];
  onCriar: (cliente: string, categoria: string) => Promise<CasoCriado>;
  /** A categoria que a triagem sugeriu, quando houve. */
  sugerida?: string;
  /** Desliga a chamada e deixa o cliente enviar o resto depois. */
  onEncerrarChamada: () => void;
  /** Há chamada de pé — sem ela, o botão de desligar não faz sentido. */
  emChamada: boolean;
}

export default function CasoEDocumentos({
  cliente,
  categorias,
  onCriar,
  sugerida,
  onEncerrarChamada,
  emChamada,
}: Props) {
  const [nome, setNome] = useState(cliente);
  const [categoria, setCategoria] = useState(sugerida ?? "");
  const [criando, setCriando] = useState(false);
  const [erro, setErro] = useState<string | null>(null);
  const [criado, setCriado] = useState<CasoCriado | null>(null);
  const [mostrarCredenciais, setMostrarCredenciais] = useState(true);
  /* Em que sala a conversa estava ANTES de o caso nascer.
   *
   * Se havia uma, o cliente ficou nela quando o advogado passou para a sala do
   * caso — e precisa ser chamado para a nova. Sem este aviso o atendente fica
   * falando sozinho, achando que a chamada caiu. */
  const [salaAnterior, setSalaAnterior] = useState<string | null>(null);

  const chamada = useChamada();
  const situacao = useSituacao(criado?.id ?? null);

  const escolhida = categoria || sugerida || categorias[0]?.codigo || "";
  const categoriaEscolhida = categorias.find((c) => c.codigo === escolhida);

  /* Criar o caso já coloca o ADVOGADO na sala dele.
   *
   * A sala do caso é nomeada pelo token do portal — é a mesma em que o cliente
   * cai ao abrir o link (ver `PainelPortal`). Até aqui, a entrevista corria numa
   * sala sorteada ANTES de o caso existir, com outro id: o cliente que entrasse
   * pelo portal ia parar numa sala vazia enquanto o escritório continuava na da
   * entrevista. Estava anotado como pendência no CONTEXTO, e é isto que a
   * fecha do lado de cá.
   *
   * O advogado entra sozinho, sem senha: ele já está autenticado no sistema, e
   * pedir a senha do portal a quem acabou de gerá-la seria teatro. Ao cliente
   * vão o link e a senha, que é o que a caixa de credenciais mostra em seguida. */
  async function criar() {
    if (!nome.trim() || !escolhida) return;
    setCriando(true);
    setErro(null);
    try {
      const novo = await onCriar(nome.trim(), escolhida);
      setCriado(novo);
      setSalaAnterior(chamada.sala);
      /* A câmera precisa atravessar a troca de sala.
       *
       * Entrar noutra sala fecha a chamada anterior e cria outra do zero (ver
       * `entrar`, no `ChamadaContexto`): a instância nova nasce sem câmera a
       * menos que alguém peça. Sem isto, criar o caso apagava a imagem do
       * advogado no meio da conversa, e ele descobria pelo cliente. Lido ANTES,
       * porque fechar a chamada zera o estado. */
      const camera = chamada.temCamera;
      try {
        await chamada.entrar(novo.portal.token, "advogado", {
          nome: "Escritório",
          camera,
        });
      } catch {
        // A sala não é o caso: ele foi criado e os documentos podem chegar do
        // mesmo jeito. Falhar aqui não pode desfazer o que deu certo.
        setErro(
          "O caso foi criado, mas não consegui entrar na sala dele. " +
            "Abra a chamada pelo painel e mande o link ao cliente.",
        );
      }
    } catch (e) {
      setErro(e instanceof Error ? e.message : "Não foi possível criar o caso.");
    } finally {
      setCriando(false);
    }
  }

  /* ------------------------------------------------- antes de criar o caso */

  if (!criado) {
    return (
      <section className={estilos.bloco}>
        <span className={estilos.rotulo}>CASO E DOCUMENTOS DO CLIENTE</span>
        <p className={estilos.texto}>
          Criar o caso abre o <strong>portal do cliente</strong> — um link com senha por
          onde ele envia os documentos. Feito agora, com ele na linha, dá para receber o
          que ele já tem em mãos e conferir se a foto saiu legível.
        </p>

        <div className={estilos.campos}>
          <label className={estilos.campo}>
            <span className={estilos.rotuloCampo}>Nome do cliente</span>
            <input
              className={estilos.entrada}
              value={nome}
              onChange={(e) => setNome(e.target.value)}
              placeholder="Ex.: Maria Aparecida da Silva"
              autoComplete="off"
            />
          </label>

          <label className={estilos.campo}>
            <span className={estilos.rotuloCampo}>Tipo de ação</span>
            <select
              className={estilos.entrada}
              value={escolhida}
              onChange={(e) => setCategoria(e.target.value)}
            >
              {categorias.map((c) => (
                <option key={c.codigo} value={c.codigo}>
                  {c.nome}
                </option>
              ))}
            </select>
          </label>
        </div>

        {/* O tipo de ação é o que monta o checklist: escolhido errado, o
          * escritório passa a cobrar do cliente documento que a ação não usa. */}
        {categoriaEscolhida && (
          <p className={estilos.resumo}>
            {categoriaEscolhida.descricao}{" "}
            <Selo tom="info">{categoriaEscolhida.total_obrigatorios} obrigatórios</Selo>{" "}
            <Selo tom="neutro">{categoriaEscolhida.total_documentos} no total</Selo>
          </p>
        )}

        {erro && (
          <div className={estilos.aviso}>
            <Aviso tom="critico" titulo="Não foi possível criar o caso">
              {erro}
            </Aviso>
          </div>
        )}

        <button
          type="button"
          className={estilos.botao}
          onClick={() => void criar()}
          disabled={criando || !nome.trim() || !escolhida}
        >
          {criando ? "Criando…" : "Criar o caso e abrir o portal"}
        </button>
      </section>
    );
  }

  /* -------------------------------------------------- caso criado: receber */

  const progresso = situacao.situacao?.progresso;
  const pronto = progresso?.pronto ?? false;

  return (
    <section className={estilos.bloco}>
      <span className={estilos.rotulo}>DOCUMENTOS DO CLIENTE</span>

      {/* Onde o advogado está agora, e o que o cliente precisa fazer.
        *
        * O advogado entrou sozinho na sala do caso ao criá-lo. Se a conversa
        * vinha de outra sala (a da entrevista, sorteada antes de o caso
        * existir), o cliente ficou lá — e é preciso chamá-lo, não esperar. */}
      <div className={estilos.sala}>
        {salaAnterior && salaAnterior !== criado.portal.token ? (
          <Aviso tom="atencao" titulo="Você mudou de sala — chame o cliente">
            A conversa vinha da sala da entrevista; agora você está na sala deste caso.
            O cliente <strong>continuou na sala anterior</strong>: mande o link e a senha
            abaixo para ele entrar aqui.
          </Aviso>
        ) : (
          <Aviso tom="ok" titulo="Você já está na sala do caso">
            Entrou automaticamente ao criar — sem senha, porque você já está autenticado
            no sistema. Mande o link e a senha abaixo para o cliente entrar.
          </Aviso>
        )}
      </div>

      {/* A senha existe em texto claro só nesta resposta. Enquanto a caixa está
        * na tela, é a hora de mandá-la ao cliente — que está na linha. */}
      {mostrarCredenciais && (
        <CredenciaisPortal
          cliente={criado.cliente}
          portal={criado.portal}
          /* "Abrir o caso" aqui não navega para lugar nenhum: o caso já está
           * aberto logo abaixo, nesta mesma tela. Fechar a caixa é tudo o que
           * resta a fazer — e ela some só depois de a senha ter sido copiada,
           * porque em texto claro ela existe uma vez só. */
          onAbrirCaso={() => setMostrarCredenciais(false)}
          onFechar={() => setMostrarCredenciais(false)}
        />
      )}

      <p className={estilos.texto}>
        Mande o link acima e <strong>peça o que ele já tiver em mãos agora</strong> — foto
        do RG, CPF, carteira de trabalho. Cada arquivo que chega aparece aqui embaixo, com
        a leitura conferida: dá para dizer na hora se saiu ilegível, em vez de descobrir
        dias depois.
      </p>

      {situacao.situacao ? (
        <Checklist
          mostrarPrazos
          situacao={situacao.situacao}
          enviando={situacao.enviando}
          erro={situacao.erro}
          onVoltar={() => undefined}
          onEnviar={situacao.enviar}
          onRemover={situacao.removerEntrega}
          onVincularIdentidade={situacao.vincularIdentidade}
          dentroDoAtendimento
        />
      ) : (
        <p className={estilos.carregando}>Abrindo o checklist do caso…</p>
      )}

      {/* O que ele não tiver agora, manda depois pelo mesmo link.
        *
        * Segurar o cliente na chamada até ter tudo é o que faz o atendimento
        * durar uma hora e o documento não chegar mesmo assim. Encerrar a
        * chamada NÃO encerra o caso: o portal continua de pé. */}
      <div className={estilos.fecho}>
        {pronto ? (
          <Aviso tom="ok" titulo="Tudo o que é obrigatório já chegou">
            O caso está instruído. Pode encerrar a chamada e seguir para o encerramento do
            atendimento.
          </Aviso>
        ) : (
          <Aviso tom="info" titulo="Falta documento? Não segure o cliente na linha">
            O portal continua valendo depois que a chamada acabar — mesmo link, mesma
            senha. Combine com ele o que falta e encerre.
          </Aviso>
        )}

        {emChamada && (
          <button type="button" className={estilos.botaoSecundario} onClick={onEncerrarChamada}>
            Encerrar a chamada e deixar o cliente enviar depois
          </button>
        )}
      </div>
    </section>
  );
}
