"use client";

import { useEffect, useState } from "react";

import { useChamada } from "@/lib/ChamadaContexto";
import type { CasoCriado, Categoria } from "@/lib/types";
import { useSituacao } from "@/lib/useCasos";
import { Aviso, Selo } from "@/components/ui/Basicos";
import Checklist from "@/components/caso/Checklist";
import CredenciaisPortal from "@/components/portal/CredenciaisPortal";
import { obterAtendimentoDocumentacao, criarSalaChamada, solicitarDocumentacao } from "@/lib/api";
import type { AtendimentoDocumentacao } from "@/lib/api";

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
  entrevistaId: string;
  categorias: Categoria[];
  onCriar: (cliente: string, categoria: string) => Promise<CasoCriado>;
  /** A categoria que a triagem sugeriu, quando houve. */
  sugerida?: string;
  /** O caso nasceu — quem chama guarda no caso a entrevista já conduzida.
   *
   * É aqui e não no fim do atendimento porque o caso é o primeiro momento em que
   * existe onde prender a entrevista: `entrevistas.caso_id` é obrigatório. */
  onCasoCriado?: (casoId: string) => Promise<void> | void;
  /** Desliga a chamada e deixa o cliente enviar o resto depois. */
  onEncerrarChamada: () => void;
  /** Há chamada de pé — sem ela, o botão de desligar não faz sentido. */
  emChamada: boolean;
}

export default function CasoEDocumentos({
  cliente,
  entrevistaId,
  categorias,
  onCriar,
  sugerida,
  onCasoCriado,
  onEncerrarChamada,
  emChamada,
}: Props) {
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
  const [transferencia, setTransferencia] = useState<AtendimentoDocumentacao | null>(null);

  const chamada = useChamada();
  const situacao = useSituacao(criado?.id ?? null);

  const escolhida = sugerida || categorias[0]?.codigo || "";
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
    if (!cliente.trim() || !escolhida) return;
    setCriando(true);
    setErro(null);
    try {
      const salaEmCurso = chamada.sala;
      const novo = await onCriar(cliente.trim(), escolhida);
      setCriado(novo);
      // Antes da sala e da documentação: é a primeira coisa que pode ser feita
      // com o caso na mão, e a que se perde para sempre se a aba fechar.
      await onCasoCriado?.(novo.id);
      if (entrevistaId) {
        await solicitarDocumentacao(entrevistaId, novo.id, salaEmCurso || novo.portal.token, cliente.trim());
      }
      setSalaAnterior(salaEmCurso);
      /* A câmera precisa atravessar a troca de sala.
       *
       * Entrar noutra sala fecha a chamada anterior e cria outra do zero (ver
       * `entrar`, no `ChamadaContexto`): a instância nova nasce sem câmera a
       * menos que alguém peça. Sem isto, criar o caso apagava a imagem do
       * advogado no meio da conversa, e ele descobria pelo cliente. Lido ANTES,
       * porque fechar a chamada zera o estado. */
      const camera = chamada.temCamera;
      if (!salaEmCurso) try {
        const { token } = await criarSalaChamada(novo.portal.token);
        await chamada.entrar(novo.portal.token, "advogado", {
          nome: "Escritório",
          camera,
        }, token);
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

  useEffect(() => {
    if (!criado || !entrevistaId) return;
    let cancelado = false;
    const consultar = () => void obterAtendimentoDocumentacao(entrevistaId)
      .then((item) => {
        if (cancelado) return;
        setTransferencia(item);
      })
      .catch(() => undefined);
    consultar();
    const id = window.setInterval(consultar, 4_000);
    return () => { cancelado = true; window.clearInterval(id); };
  }, [criado, entrevistaId, chamada]);

  /* ------------------------------------------------- antes de criar o caso */

  if (!criado) {
    return (
      <section className="mt-6 border-t border-borda pt-[14px]">
        <span className="block text-[11px] font-semibold leading-none font-ui tracking-[0.14em] text-tinta-3 mb-2">
          CASO E DOCUMENTOS DO CLIENTE
        </span>
        <p className="mb-[14px] mt-0 max-w-[74ch] font-normal text-[12px] leading-[1.6] font-ui text-tinta-3">
          Criar o caso abre o <strong>portal do cliente</strong> — um link com senha por
          onde ele envia os documentos. Feito agora, com ele na linha, dá para receber o
          que ele já tem em mãos e conferir se a foto saiu legível.
        </p>

        <p className="mb-3 mt-0 text-[12px] font-ui text-tinta">
          O caso será criado para <strong>{cliente}</strong> com os dados já coletados na entrevista.
        </p>

        {/* O tipo de ação é o que monta o checklist: escolhido errado, o
          * escritório passa a cobrar do cliente documento que a ação não usa. */}
        {categoriaEscolhida && (
          <p className="mb-[14px] mt-0 max-w-[74ch] italic font-normal text-[12px] leading-[1.55] font-titulo text-tinta-3">
            {categoriaEscolhida.descricao}{" "}
            <Selo tom="info">{categoriaEscolhida.total_obrigatorios} obrigatórios</Selo>{" "}
            <Selo tom="neutro">{categoriaEscolhida.total_documentos} no total</Selo>
          </p>
        )}

        {erro && (
          <div className="my-3">
            <Aviso tom="critico" titulo="Não foi possível criar o caso">
              {erro}
            </Aviso>
          </div>
        )}

        <button
          type="button"
          className="border-[1.5px] border-acao bg-acao text-papel text-[11px] font-semibold leading-none font-ui tracking-[0.1em] uppercase px-[15px] py-[11px] cursor-pointer enabled:hover:bg-acao-forte enabled:hover:border-acao-forte disabled:opacity-100 disabled:bg-papel-3 disabled:text-tinta-3 disabled:border-borda-forte disabled:cursor-default"
          onClick={() => void criar()}
          disabled={criando || !cliente.trim() || !escolhida}
        >
          {criando ? "Criando…" : "Criar caso"}
        </button>
      </section>
    );
  }

  /* -------------------------------------------------- caso criado: receber */

  const progresso = situacao.situacao?.progresso;
  const pronto = progresso?.pronto ?? false;

  return (
    <section className="mt-6 border-t border-borda pt-[14px]">
      <span className="block text-[11px] font-semibold leading-none font-ui tracking-[0.14em] text-tinta-3 mb-2">
        DOCUMENTOS DO CLIENTE
      </span>
      <div className="mb-3">
        {transferencia?.status === "assumido" ? (
          <Aviso tom="ok" titulo="Chamada transferida">
            {transferencia.documentador_nome} entrou na chamada. Faça a passagem do caso e saia quando estiver pronto.
            <button type="button" onClick={chamada.desligar}
              className="block mt-3 border border-ok bg-ok text-papel px-3 py-2 text-xs font-bold uppercase tracking-wider cursor-pointer">
              Sair da chamada
            </button>
          </Aviso>
        ) : (
          <Aviso tom="info" titulo="Departamento de Documentação solicitado">
            O caso entrou na fila. Assim que um documentador assumir, ele entrará nesta mesma chamada e sua participação será encerrada automaticamente.
          </Aviso>
        )}
      </div>

      {/* Onde o advogado está agora, e o que o cliente precisa fazer.
        *
        * O advogado entrou sozinho na sala do caso ao criá-lo. Se a conversa
        * vinha de outra sala (a da entrevista, sorteada antes de o caso
        * existir), o cliente ficou lá — e é preciso chamá-lo, não esperar. */}
      <div className="mb-3">
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

      <p className="mb-[14px] mt-0 max-w-[74ch] font-normal text-[12px] leading-[1.6] font-ui text-tinta-3">
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
          onEnviarLote={situacao.enviarLote}
          onRemover={situacao.removerEntrega}
          onVincularIdentidade={situacao.vincularIdentidade}
          onReatribuir={situacao.reatribuir}
          dentroDoAtendimento
        />
      ) : (
        <p className="italic font-normal text-[12px] leading-[1.5] font-titulo text-tinta-3">
          Abrindo o checklist do caso…
        </p>
      )}

      {/* O que ele não tiver agora, manda depois pelo mesmo link.
        *
        * Segurar o cliente na chamada até ter tudo é o que faz o atendimento
        * durar uma hora e o documento não chegar mesmo assim. Encerrar a
        * chamada NÃO encerra o caso: o portal continua de pé. */}
      <div className="flex items-start flex-col gap-3 mt-[18px] border-t border-borda pt-[14px]">
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
          <button
            type="button"
            /* Original usava `var(--border-campo)`, variável nunca definida
             * (mesmo bug encontrado em ChamadaDoAtendimento.tsx) — este botão
             * nunca teve borda visível. Mantido igual (paridade visual). */
            className="bg-transparent text-tinta text-[10.5px] font-semibold leading-none font-ui tracking-[0.06em] uppercase px-[13px] py-[10px] cursor-pointer"
            onClick={onEncerrarChamada}
          >
            Encerrar a chamada e deixar o cliente enviar depois
          </button>
        )}
      </div>
    </section>
  );
}
