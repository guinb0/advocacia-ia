"use client";

import { use, useCallback, useEffect, useRef, useState } from "react";

import { Aviso } from "@/components/Basicos";
import * as portal from "@/lib/apiPortal";
import type { ItemPortal, SituacaoPortal } from "@/lib/apiPortal";
import { SELO_TOM } from "@/lib/formato";
import { ChamadaJitsi } from "@/lib/chamadaJitsi";
import type { EstadoChamada } from "@/lib/chamadaJitsi";
import estilos from "./portal.module.css";

/* Cada estado com símbolo, palavra e tom. O cliente lê "Recebido" e "Precisa
 * reenviar" — não "ENTREGUE" e "CONFERIR", que eram o vocabulário interno do
 * escritório. */
const SELO = {
  entregue: { classe: estilos.entregue, texto: "Recebido", simbolo: "✓", tom: "ok" },
  processando: {
    classe: estilos.processando,
    texto: "Conferindo",
    simbolo: "◌",
    tom: "info",
  },
  conferir: {
    classe: estilos.conferir,
    texto: "Precisa reenviar",
    simbolo: "!",
    tom: "atencao",
  },
  pendente: { classe: estilos.pendente, texto: "Falta enviar", simbolo: "✕", tom: "critico" },
} as const;

export default function PaginaPortal({ params }: { params: Promise<{ token: string }> }) {
  const { token } = use(params);
  const [sessao, setSessao] = useState<string | null>(null);
  const [situacao, setSituacao] = useState<SituacaoPortal | null>(null);

  // Uma sessão da mesma aba evita pedir a senha a cada recarga da página.
  useEffect(() => {
    setSessao(portal.recuperarSessao(token));
  }, [token]);

  const carregar = useCallback(
    async (s: string) => {
      try {
        setSituacao(await portal.situacao(token, s));
      } catch {
        // Sessão vencida no servidor: volta para a senha.
        portal.esquecerSessao();
        setSessao(null);
      }
    },
    [token],
  );

  useEffect(() => {
    if (sessao) void carregar(sessao);
  }, [sessao, carregar]);

  /* O envio responde antes de a leitura terminar, então a tela se atualiza
   * sozinha enquanto houver documento sendo lido — e só enquanto houver. */
  const lendo = situacao?.itens.some((i) => i.status === "processando") ?? false;

  useEffect(() => {
    if (!sessao || !lendo) return;
    const id = setInterval(() => void carregar(sessao), 3000);
    return () => clearInterval(id);
  }, [sessao, lendo, carregar]);

  if (!sessao) {
    return <TelaSenha token={token} onEntrar={setSessao} />;
  }

  return (
    <Checklist
      token={token}
      sessao={sessao}
      situacao={situacao}
      onAtualizar={setSituacao}
      onSair={() => {
        portal.esquecerSessao();
        setSessao(null);
        setSituacao(null);
      }}
    />
  );
}

function TelaSenha({
  token,
  onEntrar,
}: {
  token: string;
  onEntrar: (sessao: string) => void;
}) {
  const [senha, setSenha] = useState("");
  const [erro, setErro] = useState<string | null>(null);
  const [entrando, setEntrando] = useState(false);

  async function enviar(evento: React.FormEvent) {
    evento.preventDefault();
    if (!senha.trim()) return;
    setEntrando(true);
    setErro(null);
    try {
      const s = await portal.entrar(token, senha);
      portal.guardarSessao(token, s.sessao, s.expira_em);
      onEntrar(s.sessao);
    } catch (e) {
      setErro(e instanceof Error ? e.message : "Não foi possível entrar.");
    } finally {
      setEntrando(false);
    }
  }

  return (
    <div className={estilos.tela}>
      <div className={estilos.centro}>
        <span className={estilos.marca}>Acervo</span>
        <span className={estilos.marcaAjuda}>Envio de documentos</span>
        <hr className={estilos.divisor} />

        <form className={estilos.cartao} onSubmit={enviar}>
          <h1 className={estilos.titulo}>Seus documentos</h1>
          <p className={estilos.texto}>
            Digite a senha que o escritório enviou junto com este link. Ela serve para proteger os
            seus documentos — ninguém além de você entra aqui sem ela.
          </p>

          <label className="rotuloCampo somenteLeitor" htmlFor="senha-portal">
            Senha de acesso
          </label>
          <input
            id="senha-portal"
            className={estilos.campoSenha}
            value={senha}
            onChange={(e) => setSenha(e.target.value)}
            placeholder="XXXXX-XXXXX"
            autoComplete="one-time-code"
            autoFocus
          />

          {erro && (
            <div style={{ marginTop: 16 }}>
              <Aviso tom="critico" titulo="Não foi possível entrar">
                {erro}
              </Aviso>
            </div>
          )}

          <button
            type="submit"
            className={`botao botao--primario botao--bloco ${estilos.acaoPrincipal}`}
            disabled={entrando || !senha.trim()}
          >
            {entrando ? "Verificando…" : "Ver meus documentos"}
          </button>
        </form>
      </div>
    </div>
  );
}

function Checklist({
  token,
  sessao,
  situacao,
  onAtualizar,
  onSair,
}: {
  token: string;
  sessao: string;
  situacao: SituacaoPortal | null;
  onAtualizar: (s: SituacaoPortal) => void;
  onSair: () => void;
}) {
  const [enviando, setEnviando] = useState<string | null>(null);
  const [erro, setErro] = useState<string | null>(null);

  if (!situacao) {
    return (
      <div className={estilos.tela}>
        <div className={estilos.centro}>
          <p className={estilos.texto}>Carregando seus documentos…</p>
        </div>
      </div>
    );
  }

  const { progresso } = situacao;
  const faltam = situacao.itens.filter(
    (i) => i.obrigatorio && i.status !== "entregue" && i.status !== "processando",
  );
  const prontos = situacao.itens.filter(
    (i) => i.status === "entregue" || i.status === "processando",
  );

  async function enviar(item: string, arquivo: File) {
    setEnviando(item);
    setErro(null);
    try {
      onAtualizar(await portal.enviarDocumento(token, sessao, item, arquivo));
    } catch (e) {
      setErro(e instanceof Error ? e.message : "Não foi possível enviar o arquivo.");
    } finally {
      setEnviando(null);
    }
  }

  const pct = Math.max(0, Math.min(100, progresso.percentual));

  return (
    <div className={estilos.tela}>
      <div className={estilos.centro}>
        <span className={estilos.marca}>Acervo</span>
        <span className={estilos.marcaAjuda}>Envio de documentos</span>
        <hr className={estilos.divisor} />

        <div className={estilos.cabecalho}>
          <div>
            <h1 className={estilos.cliente}>{situacao.cliente}</h1>
            <p className={estilos.categoria}>{situacao.categoria}</p>
          </div>
          <div>
            <span className={estilos.contagem}>
              {progresso.obrigatorios_entregues}
              <span className={estilos.contagemTotal}>/{progresso.obrigatorios_total}</span>
            </span>
            <div className={estilos.contagemRotulo}>documentos recebidos</div>
          </div>
        </div>

        <div
          className={estilos.barra}
          role="progressbar"
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={pct}
          aria-label="Documentos já recebidos"
        >
          <i className={estilos.preenchimento} style={{ width: `${pct}%` }} />
        </div>

        {progresso.pronto && (
          <div style={{ marginTop: 20 }}>
            <Aviso tom="ok" titulo="Recebemos tudo o que era necessário">
              Não falta nenhum documento. O escritório entra em contato com você.
            </Aviso>
          </div>
        )}

        <Chamada token={token} />

        {erro && (
          <div style={{ marginTop: 20 }}>
            <Aviso tom="critico" titulo="O arquivo não foi enviado">
              {erro}
            </Aviso>
          </div>
        )}

        {faltam.length > 0 && (
          <>
            <div className={estilos.instrucoes}>
              <h2 className={estilos.instrucoesTitulo}>Como fotografar para dar certo</h2>
              <ul>
                <li>Use um lugar bem iluminado, sem sombra sobre o documento.</li>
                <li>Enquadre o documento inteiro, sem cortar as bordas.</li>
                <li>Uma foto por documento. Também aceitamos PDF.</li>
                <li>Se a leitura não der certo, pedimos o reenvio aqui mesmo.</li>
              </ul>
            </div>

            <h2 className={estilos.secao}>
              Ainda falta enviar
              <span className="selo selo--critico">{faltam.length}</span>
            </h2>
            <ul className={estilos.lista}>
              {faltam.map((item) => (
                <Linha
                  key={item.codigo}
                  item={item}
                  enviando={enviando === item.codigo}
                  onEnviar={enviar}
                />
              ))}
            </ul>
          </>
        )}

        {prontos.length > 0 && (
          <>
            <h2 className={estilos.secao}>
              Já recebemos
              <span className="selo selo--ok">{prontos.length}</span>
            </h2>
            <ul className={estilos.lista}>
              {prontos.map((item) => (
                <Linha
                  key={item.codigo}
                  item={item}
                  enviando={enviando === item.codigo}
                  onEnviar={enviar}
                />
              ))}
            </ul>
          </>
        )}

        <div className={estilos.rodape}>
          Esta página é sua e do escritório. Pode fechá-la e voltar pelo mesmo link quando quiser.
          <br />
          <button type="button" className="botao botao--texto" onClick={onSair}>
            Sair desta página
          </button>
        </div>
      </div>
    </div>
  );
}

/* A entrevista por voz, do lado de quem é leigo.
 *
 * O cliente já provou quem é ao digitar a senha, então não há segunda barreira:
 * o token deste link é o nome da sala, e o escritório espera do outro lado.
 *
 * Duas coisas ficam ditas na tela, e não por gentileza: que a conversa é
 * transcrita, e que sem microfone liberado não há chamada. Um aviso genérico de
 * erro do navegador não diria nem uma nem outra. */
function Chamada({ token }: { token: string }) {
  const [estado, setEstado] = useState<EstadoChamada>("fora");
  const [entrando, setEntrando] = useState(false);
  const [mudo, setMudo] = useState(false);
  const [erro, setErro] = useState<string | null>(null);

  const chamada = useRef<ChamadaJitsi | null>(null);
  if (chamada.current === null && typeof window !== "undefined") {
    chamada.current = new ChamadaJitsi("cliente", { onEstado: setEstado, onErro: setErro });
  }

  // Fechar a aba sem soltar deixaria o microfone aceso e a sala ocupada.
  useEffect(() => () => chamada.current?.desligar(), []);

  async function entrar() {
    setErro(null);
    setEntrando(true);
    try {
      await chamada.current?.entrar(token);
    } catch (e) {
      const m = e instanceof Error ? e.message : "Não foi possível entrar na chamada.";
      setErro(
        /NotAllowedError|denied/i.test(m)
          ? "Você precisa permitir o uso do microfone para conversar por aqui."
          : m,
      );
    } finally {
      setEntrando(false);
    }
  }

  const naChamada = estado !== "fora";
  const situacao: Record<EstadoChamada, string> = {
    fora: "",
    aguardando: "Esperando o escritório entrar. Deixe esta tela aberta.",
    conectando: "Conectando…",
    falando: "Você está na chamada. Pode falar.",
    encerrada: "A chamada foi encerrada.",
  };

  return (
    <div className={estilos.chamada}>
      <h2 className={estilos.secao}>Conversar com o escritório</h2>

      {!naChamada ? (
        <>
          <p className={estilos.texto}>
            Se o escritório combinou uma conversa por voz, toque abaixo. Você fala pelo
            próprio celular, sem instalar nada.
          </p>
          <button
            type="button"
            className="botao botao--primario"
            onClick={entrar}
            disabled={entrando}
            style={{ marginTop: 14 }}
          >
            {entrando ? "Abrindo…" : "Entrar na chamada"}
          </button>
        </>
      ) : (
        <>
          <p className={estilos.chamadaEstado} aria-live="polite">
            {situacao[estado]}
          </p>

          <div className={estilos.chamadaAcoes}>
            <button
              type="button"
              className="botao botao--secundario"
              onClick={() => setMudo(chamada.current?.alternarMudo() ?? false)}
            >
              {mudo ? "Voltar a falar" : "Desligar meu microfone"}
            </button>
            <button
              type="button"
              className="botao botao--secundario"
              onClick={() => {
                chamada.current?.desligar();
                setMudo(false);
              }}
            >
              Sair da chamada
            </button>
          </div>
        </>
      )}

      <p className={estilos.chamadaNota}>
        A conversa é transcrita pelo escritório para virar o registro do seu atendimento.
      </p>

      {erro && (
        <div style={{ marginTop: 14 }}>
          <Aviso tom="critico" titulo="A chamada não abriu">
            {erro}
          </Aviso>
        </div>
      )}
    </div>
  );
}

function Linha({
  item,
  enviando,
  onEnviar,
}: {
  item: ItemPortal;
  enviando: boolean;
  onEnviar: (item: string, arquivo: File) => void;
}) {
  const inputRef = useRef<HTMLInputElement>(null);
  const selo = SELO[item.status];

  return (
    <li className={`${estilos.item} ${selo.classe}`}>
      <span className={estilos.marcador} aria-hidden>
        {selo.simbolo}
      </span>

      <span className={estilos.nome}>
        {item.nome}
        {item.observacao && <span className={estilos.observacao}>{item.observacao}</span>}
      </span>

      <span className={`selo ${SELO_TOM[selo.tom]}`}>
        <span aria-hidden>{selo.simbolo}</span>
        {selo.texto}
      </span>

      <button
        type="button"
        className={`botao ${item.enviados > 0 ? "botao--secundario" : "botao--primario"} ${estilos.enviar}`}
        onClick={() => inputRef.current?.click()}
        disabled={enviando}
      >
        {enviando ? "Enviando…" : item.enviados > 0 ? "Enviar outra foto" : "Enviar foto ou PDF"}
      </button>

      <input
        ref={inputRef}
        type="file"
        accept="image/*,application/pdf,.pdf"
        hidden
        onChange={(e) => {
          const arquivo = e.target.files?.[0];
          if (arquivo) onEnviar(item.codigo, arquivo);
          e.target.value = "";
        }}
      />

      {item.motivo && (
        <span className={estilos.motivo}>
          <strong>Por que pedimos de novo:</strong> {item.motivo}.
        </span>
      )}

      {item.status === "processando" && (
        <span className={estilos.lendo}>
          Recebemos o arquivo e estamos conferindo. Pode fechar a página — não vai perder nada.
        </span>
      )}
    </li>
  );
}
