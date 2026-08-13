"use client";

import {
  useCallback,
  useEffect,
  useImperativeHandle,
  useMemo,
  useRef,
  useState,
} from "react";
import type { Ref } from "react";

import { entrevistaDeTeste } from "@/lib/amostraEntrevista";
import { analisarResposta, consultarCep, obterRoteiro } from "@/lib/api";
import { conferirCpf, formatarCep, formatarCpf } from "@/lib/documentos";
import type {
  AnaliseResposta,
  Bloco,
  EnderecoCep,
  Pergunta,
  RoteiroCompleto,
} from "@/lib/types";
import { CapturaEntrevista } from "@/lib/transcricao";
import type { EstadoCaptura } from "@/lib/transcricao";
import ConferenciaResposta from "./ConferenciaResposta";
import estilos from "./Roteiro.module.css";
import transcricaoEstilos from "./EntrevistaAoVivo.module.css";

/* Conduz a entrevista pergunta a pergunta.
 *
 * O microfone é UM só para a entrevista inteira, vivendo aqui no topo. Cada
 * pergunta gravável apenas liga e desliga o envio — se cada uma tivesse sua
 * própria captura, o navegador pediria permissão e piscaria o indicador a cada
 * pergunta, e o entrevistador perderia o fio da conversa.
 *
 * Só as perguntas narrativas trazem gravador. Nome, CPF e RG são digitados:
 * número ditado o Whisper erra, e ninguém confere dígito lido de ouvido. */

type Respostas = Record<string, string | string[]>;

/* O Next substitui esta comparação por `false` ao compilar para produção, e o
 * empacotador remove tudo que depende dela. O botão de teste não fica escondido
 * no pacote do escritório: ele não é compilado. */
const EM_DESENVOLVIMENTO = process.env.NODE_ENV === "development";

/** O que a chamada, na coluna ao lado, precisa poder fazer com o roteiro. */
export interface ManipuladorRoteiro {
  /** Passa a transcrever a voz que chega pela chamada, no lugar do microfone. */
  usarFaixaDaChamada: (trilha: MediaStreamTrack) => Promise<void>;
  /** A chamada caiu: solta a fonte, para o gravador não prometer o que não tem. */
  aoPerderChamada: () => void;
}

/** De onde vem o áudio que está sendo transcrito. */
type Fonte = "nenhuma" | "microfone" | "chamada";

/** A conferência de UMA resposta narrativa. */
interface EstadoConferencia {
  carregando: boolean;
  analise: AnaliseResposta | null;
  erro: string | null;
}

/* Abaixo disto a resposta ainda está sendo dada e não há o que conferir. É o
 * mesmo piso do backend (`analise_resposta.MINIMO_CARACTERES`); repetido aqui
 * para não gastar uma ida à API só para ouvir "curta demais". */
const MINIMO_PARA_CONFERIR = 40;

interface Props {
  codigo?: string;
  onConcluir?: (respostas: Respostas, relatoUnificado: string) => void;
  ref?: Ref<ManipuladorRoteiro>;
}

export default function Roteiro({ codigo = "empregado_publico", onConcluir, ref }: Props) {
  const [roteiro, setRoteiro] = useState<RoteiroCompleto | null>(null);
  const [respostas, setRespostas] = useState<Respostas>({});
  const [erro, setErro] = useState<string | null>(null);

  const [estadoMic, setEstadoMic] = useState<EstadoCaptura>("sem-audio");
  const [gravandoId, setGravandoId] = useState<string | null>(null);
  const [parcial, setParcial] = useState("");
  const [aviso, setAviso] = useState<string | null>(null);
  const [fonte, setFonte] = useState<Fonte>("nenhuma");
  // Lido dentro de callbacks fixados na construção, que não enxergam o estado.
  const fonteAtual = useRef<Fonte>("nenhuma");
  fonteAtual.current = fonte;

  const [conferencias, setConferencias] = useState<Record<string, EstadoConferencia>>({});

  const captura = useRef<CapturaEntrevista | null>(null);
  // A pergunta em gravação, lida dentro dos callbacks da captura — que são
  // fixados na construção e não enxergariam o estado do React.
  const emGravacao = useRef<string | null>(null);
  // Espelhos para os mesmos callbacks: eles precisam do texto já respondido e do
  // enunciado da pergunta, e nenhum dos dois chega até lá pelo estado.
  const respostasRef = useRef<Respostas>({});
  respostasRef.current = respostas;
  const roteiroRef = useRef<RoteiroCompleto | null>(null);
  roteiroRef.current = roteiro;
  /* Último texto já conferido, por pergunta. Sem isto, sair e voltar à caixa de
   * texto dispararia uma conferência a cada clique — e cada uma é uma chamada
   * ao modelo, numa tela em que o entrevistador clica o tempo todo. */
  const conferido = useRef<Record<string, string>>({});

  useEffect(() => {
    obterRoteiro(codigo).then(setRoteiro).catch((e) => setErro(String(e)));
  }, [codigo]);

  /* O que já se sabe do caso, resumido para a conferência.
   *
   * Só respostas curtas — rastreio, escolhas, dados. Os relatos ficam de fora de
   * propósito: eles são o volume da entrevista, e mandá-los inteiros a cada
   * pergunta encareceria a conferência sem dizer mais nada do que o formato do
   * caso, que é o que evita a análise pedir o que outra pergunta já respondeu. */
  const contextoDoCaso = useCallback((exceto: string): string => {
    const atual = roteiroRef.current;
    if (!atual) return "";
    const partes: string[] = [];
    for (const bloco of atual.blocos) {
      for (const p of bloco.perguntas) {
        if (p.id === exceto || p.transcrever) continue;
        const v = respostasRef.current[p.id];
        const texto = Array.isArray(v) ? v.join(", ") : (v ?? "");
        if (texto && texto.length <= 120) partes.push(`${p.texto}: ${texto}`);
      }
    }
    return partes.join("\n").slice(0, 1500);
  }, []);

  const conferir = useCallback(
    (perguntaId: string, texto: string, forcar = false) => {
      const atual = roteiroRef.current;
      if (!atual) return;
      const pergunta = atual.blocos
        .flatMap((b) => b.perguntas)
        .find((p) => p.id === perguntaId);
      // Só as narrativas graváveis: conferir um CPF contra precedentes não diz
      // nada, e gastaria uma chamada por campo digitado.
      if (!pergunta?.transcrever) return;

      const limpo = texto.trim();
      if (limpo.length < MINIMO_PARA_CONFERIR) return;
      if (!forcar && conferido.current[perguntaId] === limpo) return;
      conferido.current[perguntaId] = limpo;

      setConferencias((c) => ({
        ...c,
        [perguntaId]: { carregando: true, analise: c[perguntaId]?.analise ?? null, erro: null },
      }));

      void analisarResposta(perguntaId, pergunta.texto, limpo, contextoDoCaso(perguntaId))
        .then((analise) =>
          setConferencias((c) => ({
            ...c,
            [perguntaId]: { carregando: false, analise, erro: null },
          })),
        )
        .catch((e) => {
          // A conferência falhando não pode parar a entrevista: o erro fica
          // discreto embaixo da pergunta e o roteiro segue.
          conferido.current[perguntaId] = "";
          setConferencias((c) => ({
            ...c,
            [perguntaId]: {
              carregando: false,
              analise: null,
              erro: e instanceof Error ? e.message : "Não foi possível conferir a resposta.",
            },
          }));
        });
    },
    [contextoDoCaso],
  );

  // Lido dentro dos callbacks da captura, que são fixados na construção.
  const conferirRef = useRef(conferir);
  conferirRef.current = conferir;

  if (captura.current === null && typeof window !== "undefined") {
    captura.current = new CapturaEntrevista({
      onParcial: (texto) => {
        // A primeira palavra transcrita já responde o que o aviso explicava.
        setAviso(null);
        setParcial(texto);
      },
      onAviso: setAviso,
      onFinal: (texto) => {
        const id = emGravacao.current;
        if (id) {
          // Acrescenta em vez de substituir: é o que faz "adicionar complemento"
          // funcionar — o cliente completa a resposta depois de uma pausa, e o
          // trecho novo entra no fim do que já havia.
          const novo = [String(respostasRef.current[id] ?? ""), texto]
            .filter(Boolean)
            .join(" ");
          setRespostas((r) => ({ ...r, [id]: novo }));
          // A conferência roda sobre a resposta INTEIRA, não só o trecho novo:
          // o complemento costuma justamente preencher a lacuna apontada antes.
          conferirRef.current(id, novo);
        }
        emGravacao.current = null;
        setGravandoId(null);
        setParcial("");
      },
      onEstado: (e) => {
        setEstadoMic(e);
        // A trilha acabou (microfone desconectado, chamada caída): sem fonte, o
        // botão de gravar não pode continuar oferecendo o que não existe.
        if (e === "sem-audio") setFonte("nenhuma");
      },
      onErro: setErro,
    });
  }

  useEffect(() => () => captura.current?.encerrar(), []);

  useImperativeHandle(
    ref,
    () => ({
      usarFaixaDaChamada: async (trilha: MediaStreamTrack) => {
        await captura.current?.usarTrilha(trilha);
        setFonte("chamada");
        setErro(null);
      },
      aoPerderChamada: () => {
        // Só solta se a fonte era a chamada: quem estava no microfone continua
        // no microfone, mesmo que a chamada do lado tenha caído.
        if (fonteAtual.current === "chamada") {
          captura.current?.encerrar();
          setFonte("nenhuma");
        }
      },
    }),
    [],
  );

  const ligarMicrofone = useCallback(async () => {
    setErro(null);
    try {
      await captura.current?.selecionarAudio();
      setFonte("microfone");
    } catch (e) {
      const m = e instanceof Error ? e.message : "Não foi possível abrir o microfone.";
      setErro(/NotAllowedError|denied/i.test(m) ? "Permissão de microfone negada." : m);
    }
  }, []);

  /* Começa a gravar — ou volta a gravar por cima de uma resposta que já existe.
   *
   * São a mesma operação: o `onFinal` acrescenta ao que já havia. O que muda é
   * só o rótulo do botão, e é a diferença entre "gravar a resposta" e
   * "complementar o que ele já disse" — que é o que se faz depois de ler a
   * conferência e descobrir que faltou perguntar da CAT. */
  const gravar = useCallback(async (perguntaId: string) => {
    setErro(null);
    setParcial("");
    try {
      emGravacao.current = perguntaId;
      setGravandoId(perguntaId);
      await captura.current?.iniciarResposta(perguntaId);
    } catch (e) {
      emGravacao.current = null;
      setGravandoId(null);
      setErro(e instanceof Error ? e.message : "Não foi possível iniciar.");
    }
  }, []);

  const pausar = useCallback(() => captura.current?.pausar(), []);
  const retomar = useCallback(() => captura.current?.retomar(), []);
  const finalizar = useCallback(() => captura.current?.finalizarResposta(), []);

  const responder = useCallback((id: string, valor: string | string[]) => {
    setRespostas((r) => ({ ...r, [id]: valor }));
  }, []);

  /* Só entram os módulos cujo rastreio deu positivo: quem não sofreu assalto
   * não percorre o módulo de assalto. */
  const blocosVisiveis = useMemo(() => {
    if (!roteiro) return [];
    const positivos = new Set(
      Object.entries(roteiro.mapa_rastreio)
        .filter(([perguntaId]) => respostas[perguntaId] === "sim")
        .map(([, modulo]) => modulo),
    );
    return roteiro.blocos.filter((b) => !b.modulo || positivos.has(b.modulo));
  }, [roteiro, respostas]);

  const { total, feitas } = useMemo(() => {
    const perguntas = blocosVisiveis.flatMap((b) => b.perguntas);
    const resp = perguntas.filter((p) => {
      const v = respostas[p.id];
      return Array.isArray(v) ? v.length > 0 : Boolean(v);
    });
    return { total: perguntas.length, feitas: resp.length };
  }, [blocosVisiveis, respostas]);

  if (erro && !roteiro) return <p className={estilos.vazio}>{erro}</p>;
  if (!roteiro) return <p className={estilos.vazio}>Carregando o roteiro…</p>;

  const temMic = estadoMic !== "sem-audio";

  return (
    <div className={estilos.tela}>
      <div className={estilos.cabecalho}>
        <div>
          <h2 className={estilos.titulo}>{roteiro.nome}</h2>
        </div>
        <div className={transcricaoEstilos.acoes}>
          {/* Com a chamada no ar, o microfone daqui não entra na transcrição —
              ele serve para o entrevistado ouvir o advogado, e quem cuida disso
              é o painel da chamada. Oferecer "ligar microfone" aqui convidaria a
              trocar a voz do cliente pela do entrevistador sem perceber. */}
          {fonte !== "chamada" && (
            <button
              type="button"
              className={transcricaoEstilos.secundario}
              onClick={ligarMicrofone}
              disabled={gravandoId !== null}
            >
              {temMic ? "Trocar microfone" : "Ligar microfone"}
            </button>
          )}

          <span className={estilos.fonte}>
            {fonte === "chamada"
              ? "transcrevendo a voz do entrevistado"
              : fonte === "microfone"
                ? "transcrevendo este microfone"
                : "sem áudio"}
          </span>

          {EM_DESENVOLVIMENTO && (
            <button
              type="button"
              className={estilos.teste}
              onClick={() => setRespostas(entrevistaDeTeste(roteiro.blocos))}
              title="Só em desenvolvimento: preenche a entrevista com dados falsos"
            >
              Preencher para teste
            </button>
          )}

          <span className={estilos.progresso}>
            {feitas}/{total}
          </span>
        </div>
      </div>

      <div className={estilos.barra}>
        <i
          className={estilos.preenchimento}
          style={{ width: `${total ? (feitas / total) * 100 : 0}%` }}
        />
      </div>

      {erro && <div className={transcricaoEstilos.erro}>{erro}</div>}

      {aviso && (
        <p className={transcricaoEstilos.aviso} aria-live="polite">
          {aviso}
        </p>
      )}

      {!temMic && (
        <p className={transcricaoEstilos.aviso}>
          Abra a chamada ao lado para transcrever a voz do entrevistado, ou ligue este
          microfone se a entrevista for presencial. Os campos de dados podem ser
          preenchidos sem áudio nenhum.
        </p>
      )}

      {blocosVisiveis.map((bloco) => (
        <BlocoRoteiro
          key={bloco.id}
          bloco={bloco}
          respostas={respostas}
          onResponder={responder}
          gravandoId={gravandoId}
          pausado={estadoMic === "pausado"}
          parcial={parcial}
          temMic={temMic}
          onGravar={gravar}
          onPausar={pausar}
          onRetomar={retomar}
          onFinalizar={finalizar}
          conferencias={conferencias}
          onConferir={conferir}
        />
      ))}

      {onConcluir && (
        <button
          type="button"
          className={transcricaoEstilos.botao}
          style={{ marginTop: 24 }}
          onClick={() => onConcluir(respostas, montarRelato(blocosVisiveis, respostas))}
        >
          Concluir entrevista
        </button>
      )}
    </div>
  );
}

/** Junta as respostas num texto corrido — é o que alimenta a triagem. */
function montarRelato(blocos: Bloco[], respostas: Respostas): string {
  const partes: string[] = [];
  for (const bloco of blocos) {
    const doBloco = bloco.perguntas
      .map((p) => {
        const v = respostas[p.id];
        const texto = Array.isArray(v) ? v.join(", ") : v;
        return texto ? `${p.texto}\n${texto}` : "";
      })
      .filter(Boolean);
    if (doBloco.length) partes.push(`## ${bloco.titulo}\n\n${doBloco.join("\n\n")}`);
  }
  return partes.join("\n\n");
}

function BlocoRoteiro({
  bloco,
  respostas,
  onResponder,
  gravandoId,
  pausado,
  parcial,
  temMic,
  onGravar,
  onPausar,
  onRetomar,
  onFinalizar,
  conferencias,
  onConferir,
}: {
  bloco: Bloco;
  respostas: Respostas;
  onResponder: (id: string, valor: string | string[]) => void;
  gravandoId: string | null;
  pausado: boolean;
  parcial: string;
  temMic: boolean;
  onGravar: (id: string) => void;
  onPausar: () => void;
  onRetomar: () => void;
  onFinalizar: () => void;
  conferencias: Record<string, EstadoConferencia>;
  onConferir: (id: string, texto: string, forcar?: boolean) => void;
}) {
  return (
    <section className={estilos.bloco}>
      <span className={estilos.blocoTitulo}>{bloco.titulo.toUpperCase()}</span>
      {bloco.objetivo && <p className={estilos.objetivo}>{bloco.objetivo}</p>}

      <ul className={estilos.lista}>
        {bloco.perguntas.map((p, i) => (
          <li
            key={p.id}
            className={`${estilos.pergunta} ${respostas[p.id] ? estilos.respondida : ""}`}
          >
            <div className={estilos.enunciado}>
              <span className={estilos.numero}>{String(i + 1).padStart(2, "0")}</span>
              <span className={estilos.texto}>
                {p.texto}
                {p.obrigatoria && <span className={estilos.obrigatoria}>*</span>}
              </span>
              {p.transcrever && <span className={estilos.marcaGravavel}>VOZ</span>}
            </div>

            {p.dica && <span className={estilos.dica}>{p.dica}</span>}

            <div className={estilos.resposta}>
              <CampoResposta
                pergunta={p}
                valor={respostas[p.id]}
                valorAlvo={p.preenche ? respostas[p.preenche] : undefined}
                onResponder={onResponder}
                gravando={gravandoId === p.id}
                pausado={gravandoId === p.id && pausado}
                parcial={gravandoId === p.id ? parcial : ""}
                temMic={temMic}
                ocupado={gravandoId !== null && gravandoId !== p.id}
                onGravar={onGravar}
                onPausar={onPausar}
                onRetomar={onRetomar}
                onFinalizar={onFinalizar}
                onConferir={onConferir}
              />
            </div>

            {/* A conferência mora embaixo da pergunta que a gerou: lida em
              * qualquer outro lugar, ela obrigaria a procurar de qual resposta
              * está falando — e o cliente está esperando. */}
            {p.transcrever && conferencias[p.id] && (
              <ConferenciaResposta
                analise={conferencias[p.id].analise}
                carregando={conferencias[p.id].carregando}
                erro={conferencias[p.id].erro}
                onRefazer={() =>
                  onConferir(p.id, String(respostas[p.id] ?? ""), true)
                }
              />
            )}
          </li>
        ))}
      </ul>
    </section>
  );
}

/* CEP digitado, endereço preenchido.
 *
 * A entrevista é o gargalo do escritório: cada campo datilografado é tempo com
 * o cliente na frente. O CEP é o único dado do roteiro que uma base pública
 * resolve de graça e sem pedir procuração — e resolve quatro campos de uma vez.
 * O que ele NÃO traz é o número da casa, e por isso o texto preenchido deixa
 * "nº ___" à vista: endereço sem número não serve para citação.
 *
 * CPF continua digitado e conferido pelo dígito verificador. Não existe base
 * pública que troque um CPF por um nome — quem promete isso vende dado vazado.
 * A discussão está em `app/consultas.py`. */
function CampoCep({
  pergunta,
  valor,
  valorAlvo,
  onResponder,
}: {
  pergunta: Pergunta;
  valor: string;
  valorAlvo: string;
  onResponder: (id: string, valor: string | string[]) => void;
}) {
  const [buscando, setBuscando] = useState(false);
  const [achado, setAchado] = useState<EnderecoCep | null>(null);
  const [erro, setErro] = useState<string | null>(null);

  // Uma consulta por CEP: sem isto, cada tecla depois do oitavo dígito
  // (ou qualquer re-render) bateria de novo na base pública.
  const consultado = useRef("");
  // Lidos dentro do efeito sem entrar nas dependências: mudam a cada tecla do
  // campo de endereço, e não é isso que deve disparar uma consulta.
  const alvo = useRef(valorAlvo);
  alvo.current = valorAlvo;
  const responder = useRef(onResponder);
  responder.current = onResponder;

  const digitos = valor.replace(/\D/g, "");

  useEffect(() => {
    if (digitos.length !== 8) {
      consultado.current = "";
      setAchado(null);
      setErro(null);
      return;
    }
    if (consultado.current === digitos) return;
    consultado.current = digitos;

    let cancelado = false;
    setBuscando(true);
    setErro(null);
    consultarCep(digitos)
      .then((endereco) => {
        if (cancelado) return;
        setAchado(endereco);
        // Não sobrescreve o que já foi digitado: o endereço na tela pode ter
        // número e complemento que a base não tem. A troca fica no botão.
        if (!alvo.current.trim()) {
          responder.current(pergunta.preenche, endereco.endereco_formatado);
        }
      })
      .catch((e) => {
        if (!cancelado) setErro(e instanceof Error ? e.message : "Não foi possível consultar o CEP.");
      })
      .finally(() => {
        if (!cancelado) setBuscando(false);
      });

    return () => {
      cancelado = true;
    };
  }, [digitos, pergunta.preenche]);

  return (
    <>
      <input
        className={estilos.campo}
        type="text"
        inputMode="numeric"
        value={valor}
        maxLength={9}
        placeholder="00000-000"
        onChange={(e) => onResponder(pergunta.id, formatarCep(e.target.value))}
      />

      {buscando && <span className={estilos.campoDica}>consultando o endereço…</span>}
      {erro && <span className={estilos.campoErro}>{erro}</span>}

      {achado && !erro && !buscando && (
        <span className={estilos.campoOk}>
          {achado.endereco_formatado}
          <em className={estilos.fonte}>via {achado.fonte}</em>
          {alvo.current.trim() && alvo.current !== achado.endereco_formatado && (
            <button
              type="button"
              className={estilos.usar}
              onClick={() => onResponder(pergunta.preenche, achado.endereco_formatado)}
            >
              Substituir o endereço digitado
            </button>
          )}
        </span>
      )}
    </>
  );
}

function CampoResposta({
  pergunta,
  valor,
  valorAlvo,
  onResponder,
  gravando,
  pausado,
  parcial,
  temMic,
  ocupado,
  onGravar,
  onPausar,
  onRetomar,
  onFinalizar,
  onConferir,
}: {
  pergunta: Pergunta;
  valor?: string | string[];
  /** Resposta atual do campo que a busca preenche — para não sobrescrevê-la. */
  valorAlvo?: string | string[];
  onResponder: (id: string, valor: string | string[]) => void;
  gravando: boolean;
  pausado: boolean;
  parcial: string;
  temMic: boolean;
  /** Outra pergunta está gravando — o microfone é um só para a entrevista. */
  ocupado: boolean;
  onGravar: (id: string) => void;
  onPausar: () => void;
  onRetomar: () => void;
  onFinalizar: () => void;
  onConferir: (id: string, texto: string, forcar?: boolean) => void;
}) {
  const texto = typeof valor === "string" ? valor : "";

  if (pergunta.tipo === "sim_nao") {
    return (
      <div className={estilos.opcoes}>
        {["sim", "não"].map((o) => (
          <button
            key={o}
            type="button"
            className={`${estilos.opcao} ${o === "sim" ? estilos.opcaoSim : ""} ${
              texto === o ? estilos.opcaoAtiva : ""
            }`}
            onClick={() => onResponder(pergunta.id, texto === o ? "" : o)}
          >
            {o}
          </button>
        ))}
      </div>
    );
  }

  if (pergunta.tipo === "escolha") {
    return (
      <div className={estilos.opcoes}>
        {pergunta.opcoes.map((o) => (
          <button
            key={o}
            type="button"
            className={`${estilos.opcao} ${texto === o ? estilos.opcaoAtiva : ""}`}
            onClick={() => onResponder(pergunta.id, texto === o ? "" : o)}
          >
            {o}
          </button>
        ))}
      </div>
    );
  }

  if (pergunta.tipo === "lista") {
    return (
      <select
        className={estilos.seletor}
        value={texto}
        onChange={(e) => onResponder(pergunta.id, e.target.value)}
        aria-label={pergunta.texto}
      >
        <option value="">—</option>
        {pergunta.opcoes.map((o) => (
          <option key={o} value={o}>
            {o}
          </option>
        ))}
      </select>
    );
  }

  if (pergunta.tipo === "documentos") {
    const marcados = Array.isArray(valor) ? valor : [];
    return (
      <div className={estilos.checks}>
        {pergunta.opcoes.map((o) => (
          <label key={o} className={estilos.check}>
            <input
              type="checkbox"
              checked={marcados.includes(o)}
              onChange={(e) =>
                onResponder(
                  pergunta.id,
                  e.target.checked ? [...marcados, o] : marcados.filter((x) => x !== o),
                )
              }
            />
            {o}
          </label>
        ))}
      </div>
    );
  }

  if (pergunta.busca === "cep") {
    return (
      <CampoCep
        pergunta={pergunta}
        valor={texto}
        valorAlvo={typeof valorAlvo === "string" ? valorAlvo : ""}
        onResponder={onResponder}
      />
    );
  }

  if (pergunta.validacao === "cpf") {
    /* O CPF é conferido aqui, não depois: o dígito verificador só serve para
     * pegar erro de digitação, e erro de digitação se corrige perguntando de
     * novo — o que só dá para fazer com o cliente ainda na frente. Descoberto
     * na conferência da papelada, meses depois, o mesmo aviso não vale nada. */
    const veredito = conferirCpf(texto);
    return (
      <>
        <input
          className={`${estilos.campo} ${veredito.valido === false ? estilos.campoInvalido : ""}`}
          type="text"
          inputMode="numeric"
          value={texto}
          maxLength={14}
          onChange={(e) => onResponder(pergunta.id, formatarCpf(e.target.value))}
          aria-invalid={veredito.valido === false}
          aria-describedby={veredito.mensagem ? `dv-${pergunta.id}` : undefined}
        />
        {veredito.mensagem && (
          <span
            id={`dv-${pergunta.id}`}
            className={
              veredito.valido === false
                ? estilos.campoErro
                : veredito.valido
                  ? estilos.campoOk
                  : estilos.campoDica
            }
            // O aviso muda a cada tecla; sem `polite` o leitor de tela leria
            // "faltam 7 dígitos, faltam 6 dígitos" por cima da digitação.
            aria-live="polite"
          >
            {veredito.mensagem}
          </span>
        )}
      </>
    );
  }

  if (pergunta.tipo === "dado" || pergunta.tipo === "data") {
    return (
      <input
        className={estilos.campo}
        type={pergunta.tipo === "data" ? "date" : "text"}
        value={texto}
        onChange={(e) => onResponder(pergunta.id, e.target.value)}
      />
    );
  }

  // relato — com gravador quando marcado, sempre editável por teclado.
  const emCurso = gravando || pausado;

  return (
    <>
      {pergunta.transcrever && (
        <div className={estilos.opcoes} style={{ marginBottom: 8 }}>
          {!emCurso && (
            <button
              type="button"
              className={transcricaoEstilos.botao}
              onClick={() => onGravar(pergunta.id)}
              disabled={!temMic || ocupado}
              title={
                !temMic
                  ? "Ligue o microfone no topo da tela"
                  : ocupado
                    ? "Outra pergunta está gravando — finalize aquela antes"
                    : ""
              }
            >
              {/* O rótulo muda porque a operação é a mesma mas a intenção não:
                * complementar é o que se faz depois de ler a conferência e
                * descobrir o que faltou perguntar. O trecho novo entra no fim
                * do que já estava escrito, sem apagar nada. */}
              {texto.trim() ? "Adicionar complemento" : "Gravar resposta"}
            </button>
          )}

          {emCurso && (
            <>
              <button
                type="button"
                className={transcricaoEstilos.secundario}
                onClick={pausado ? onRetomar : onPausar}
              >
                {pausado ? "Retomar" : "Pausar"}
              </button>
              <button
                type="button"
                className={`${transcricaoEstilos.botao} ${
                  gravando ? transcricaoEstilos.gravando : ""
                }`}
                onClick={onFinalizar}
              >
                Finalizar resposta
              </button>
            </>
          )}

          {pausado && (
            <span className={estilos.pausa}>
              pausado — o que for dito agora não entra na resposta
            </span>
          )}
        </div>
      )}

      <textarea
        className={estilos.area}
        value={gravando && parcial ? `${texto}${texto ? " " : ""}${parcial}` : texto}
        onChange={(e) => onResponder(pergunta.id, e.target.value)}
        /* Conferir ao sair do campo é o equivalente digitado de "finalizar
         * resposta". Fazê-lo a cada tecla custaria uma chamada ao modelo por
         * letra; num botão à parte, ninguém clicaria no meio da entrevista. */
        onBlur={(e) => {
          if (pergunta.transcrever && !emCurso) onConferir(pergunta.id, e.target.value);
        }}
        placeholder={
          pergunta.transcrever ? "Grave pelo microfone ou digite aqui." : "Digite a resposta."
        }
        readOnly={gravando}
      />
    </>
  );
}
