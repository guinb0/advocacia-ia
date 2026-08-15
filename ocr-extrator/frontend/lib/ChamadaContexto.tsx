"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
} from "react";

import { ChamadaJitsi } from "./chamadaJitsi";
import type {
  EstadoChamada,
  OpcoesEntrada,
  PapelChamada,
  Participante,
} from "./chamadaJitsi";

/* A chamada que sobrevive à navegação.
 *
 * Antes, cada tela criava a sua `ChamadaJitsi` e a desligava ao sair — então a
 * ligação caía no instante em que o atendente saía da entrevista para o
 * checklist, ou o cliente trocava de aba. O escritório pediu o contrário: a
 * chamada PERMANECE, para conduzir o cliente pelo envio dos documentos sem
 * largar a conversa.
 *
 * A instância passa a viver AQUI, no provedor montado na raiz do app (ver
 * `app/layout.tsx`). As telas deixam de possuí-la: elas entram, controlam e
 * mostram a chamada, mas quem a segura é o provedor, que não desmonta entre uma
 * tela e a seguinte. Quem encerra é só o botão de desligar — ou fechar a aba.
 *
 * Vale para os dois lados: o mesmo provedor está na raiz do escritório e na do
 * cliente (portal e página da chamada são rotas do mesmo app). Cada navegador
 * tem o seu; o do escritório carrega o papel `advogado`, o do cliente, `cliente`.
 */

interface ValorChamada {
  estado: EstadoChamada;
  participantes: Participante[];
  /** A sala em que estamos (ou a última). É o mesmo token do portal do caso. */
  sala: string | null;
  papel: PapelChamada | null;
  mudo: boolean;
  temCamera: boolean;
  erro: string | null;
  /** Há chamada de pé. */
  ativa: boolean;
  /** Mostrar o painel flutuante: só quando a chamada existe E nenhuma tela já a
   *  está exibindo por inteiro (a entrevista, o checklist, o portal). É o que
   *  faz o painel "seguir" o atendente só para onde não há a chamada na tela. */
  mostrarDock: boolean;
  /** Uma tela declara que mostra a chamada por inteiro; devolve o cancelamento.
   *  Enquanto houver ao menos uma, o painel flutuante se recolhe. */
  registrarPainel: () => () => void;

  entrar: (sala: string, papel: PapelChamada, opcoes?: OpcoesEntrada) => Promise<void>;
  desligar: () => void;
  alternarMudo: () => void;
  alternarCamera: () => Promise<void>;
  limparErro: () => void;
  /** Assina a voz do outro lado — é o que alimenta a transcrição do escritório.
   *  Devolve o cancelamento. Se a faixa já chegou, chama o retorno na hora. */
  aoReceberFaixa: (retorno: (trilha: MediaStreamTrack) => void) => () => void;
}

const Contexto = createContext<ValorChamada | null>(null);

export function ProvedorChamada({ children }: { children: React.ReactNode }) {
  const [estado, setEstado] = useState<EstadoChamada>("fora");
  const [participantes, setParticipantes] = useState<Participante[]>([]);
  const [sala, setSala] = useState<string | null>(null);
  const [papel, setPapel] = useState<PapelChamada | null>(null);
  const [mudo, setMudo] = useState(false);
  const [temCamera, setTemCamera] = useState(false);
  const [erro, setErro] = useState<string | null>(null);
  // Quantas telas mostram a chamada por inteiro agora. Enquanto > 0, o painel
  // flutuante fica recolhido — não há por que repetir a chamada num canto.
  const [paineis, setPaineis] = useState(0);

  const chamada = useRef<ChamadaJitsi | null>(null);
  const salaRef = useRef<string | null>(null);
  // A última faixa remota e quem quer ser avisado dela. A faixa costuma chegar
  // antes de a tela que transcreve montar; guardá-la deixa o assinante recebê-la
  // mesmo quando assina depois.
  const faixaAtual = useRef<MediaStreamTrack | null>(null);
  const assinantes = useRef(new Set<(t: MediaStreamTrack) => void>());

  const soltar = useCallback(() => {
    chamada.current?.desligar();
    chamada.current = null;
    faixaAtual.current = null;
    salaRef.current = null;
    setSala(null);
    setPapel(null);
    setMudo(false);
    setTemCamera(false);
    setParticipantes([]);
    setEstado("fora");
  }, []);

  const entrar = useCallback(
    async (novaSala: string, novoPapel: PapelChamada, opcoes?: OpcoesEntrada) => {
      // Já na sala pedida: nada a fazer — é o caso de outra tela "reabrindo" a
      // chamada que já está de pé, e reabrir de verdade a derrubaria.
      if (chamada.current && salaRef.current === novaSala) return;
      // Sala diferente (ou papel diferente): fecha a anterior antes.
      if (chamada.current) soltar();

      const instancia = new ChamadaJitsi(novoPapel, {
        onEstado: setEstado,
        onParticipantes: setParticipantes,
        onFaixaRemota: (trilha) => {
          faixaAtual.current = trilha;
          assinantes.current.forEach((cb) => cb(trilha));
        },
        onErro: setErro,
      });
      chamada.current = instancia;
      salaRef.current = novaSala;
      setSala(novaSala);
      setPapel(novoPapel);
      setErro(null);
      await instancia.entrar(novaSala, opcoes);
    },
    [soltar],
  );

  const alternarMudo = useCallback(() => {
    setMudo(chamada.current?.alternarMudo() ?? false);
  }, []);

  const alternarCamera = useCallback(async () => {
    setTemCamera(await (chamada.current?.alternarCamera() ?? Promise.resolve(false)));
  }, []);

  const registrarPainel = useCallback(() => {
    setPaineis((n) => n + 1);
    return () => setPaineis((n) => Math.max(0, n - 1));
  }, []);

  const limparErro = useCallback(() => setErro(null), []);

  const aoReceberFaixa = useCallback((retorno: (t: MediaStreamTrack) => void) => {
    assinantes.current.add(retorno);
    if (faixaAtual.current) retorno(faixaAtual.current);
    return () => {
      assinantes.current.delete(retorno);
    };
  }, []);

  // Fechar a aba solta o microfone e libera a sala. O provedor não desmonta em
  // navegação normal (ele está na raiz), então este é o único lugar que precisa
  // encerrar sozinho — o resto é o botão de desligar.
  useEffect(() => {
    const aoSair = () => chamada.current?.desligar();
    window.addEventListener("pagehide", aoSair);
    return () => window.removeEventListener("pagehide", aoSair);
  }, []);

  const valor: ValorChamada = {
    estado,
    participantes,
    sala,
    papel,
    mudo,
    temCamera,
    erro,
    ativa: estado !== "fora",
    mostrarDock: estado !== "fora" && paineis === 0,
    registrarPainel,
    entrar,
    desligar: soltar,
    alternarMudo,
    alternarCamera,
    limparErro,
    aoReceberFaixa,
  };

  return <Contexto.Provider value={valor}>{children}</Contexto.Provider>;
}

export function useChamada(): ValorChamada {
  const valor = useContext(Contexto);
  if (!valor) throw new Error("useChamada precisa estar dentro de <ProvedorChamada>.");
  return valor;
}
