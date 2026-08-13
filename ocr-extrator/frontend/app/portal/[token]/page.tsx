"use client";

import { use, useCallback, useEffect, useRef, useState } from "react";

import * as portal from "@/lib/apiPortal";
import type { ItemPortal, SituacaoPortal } from "@/lib/apiPortal";
import { ChamadaJitsi } from "@/lib/chamadaJitsi";
import type { EstadoChamada } from "@/lib/chamadaJitsi";
import estilos from "./portal.module.css";

const SELO = {
  entregue: { classe: estilos.entregue, texto: "RECEBIDO" },
  processando: { classe: estilos.processando, texto: "CONFERINDO" },
  conferir: { classe: estilos.conferir, texto: "REENVIAR" },
  pendente: { classe: estilos.pendente, texto: "FALTA" },
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
        <span className={estilos.marca}>ACERVO</span>
        <div className={estilos.filete} />

        <form className={estilos.cartao} onSubmit={enviar}>
          <h1 className={estilos.titulo}>Seus documentos</h1>
          <p className={estilos.texto}>
            Digite a senha que o escritório enviou junto com este link. Ela serve para
            proteger os seus documentos.
          </p>

          <input
            className={estilos.campo}
            value={senha}
            onChange={(e) => setSenha(e.target.value)}
            placeholder="XXXXX-XXXXX"
            autoComplete="one-time-code"
            autoFocus
            aria-label="Senha de acesso"
          />

          {erro && <div className={estilos.erro}>{erro}</div>}

          <button type="submit" className={estilos.botao} disabled={entrando || !senha.trim()}>
            {entrando ? "Verificando…" : "Acessar meus documentos"}
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

  return (
    <div className={estilos.tela}>
      <div className={estilos.centro}>
        <span className={estilos.marca}>ACERVO</span>
        <div className={estilos.filete} />

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
          </div>
        </div>

        <div className={estilos.barra}>
          <i
            className={estilos.preenchimento}
            style={{ width: `${Math.max(0, Math.min(100, progresso.percentual))}%` }}
          />
        </div>

        {progresso.pronto && (
          <div className={estilos.completo}>
            ✓ Recebemos tudo o que era necessário. O escritório entra em contato.
          </div>
        )}

        <Chamada token={token} />

        {erro && <div className={estilos.erro}>{erro}</div>}

        {faltam.length > 0 && (
          <>
            <p className={estilos.secao}>AINDA FALTA ENVIAR ({faltam.length})</p>
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
            <p className={estilos.secao}>JÁ RECEBEMOS ({prontos.length})</p>
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

        <p className={estilos.rodape}>
          Envie foto ou PDF. Prefira boa luz e o documento inteiro no quadro — se a leitura
          não for possível, pedimos o reenvio aqui mesmo.
          <br />
          <button
            type="button"
            onClick={onSair}
            style={{ background: "none", border: "none", padding: 0, cursor: "pointer", color: "inherit", textDecoration: "underline" }}
          >
            Sair
          </button>
        </p>
      </div>
    </div>
  );
}

/* A entrevista por voz, do lado de quem é leigo.
 *
 * O cliente já provou quem é ao digitar a senha, então não há segunda barreira:
 * o token deste link é o nome da sala, e o escritório espera do outro lado. A
 * voz sobe pelo Jitsi e chega separada no navegador do advogado.
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

  return (
    <div className={estilos.chamada}>
      <span className={estilos.secao}>CONVERSAR COM O ESCRITÓRIO</span>

      {!naChamada ? (
        <>
          <p className={estilos.texto}>
            Se o escritório combinou uma conversa por voz, toque abaixo. Você vai falar
            pelo próprio celular, sem instalar nada.
          </p>
          <button
            type="button"
            className={estilos.botao}
            onClick={entrar}
            disabled={entrando}
          >
            {entrando ? "Abrindo…" : "Entrar na chamada"}
          </button>
        </>
      ) : (
        <>
          <p className={estilos.chamadaEstado}>
            {estado === "falando"
              ? "Você está na chamada. Pode falar."
              : estado === "encerrada"
                ? "A chamada foi encerrada."
                : estado === "conectando"
                  ? "Conectando…"
                  : "Esperando o escritório entrar. Deixe esta tela aberta."}
          </p>

          <div className={estilos.chamadaAcoes}>
            <button
              type="button"
              className={estilos.enviar}
              onClick={() => setMudo(chamada.current?.alternarMudo() ?? false)}
            >
              {mudo ? "Voltar a falar" : "Desligar meu microfone"}
            </button>
            <button
              type="button"
              className={estilos.enviar}
              onClick={() => {
                chamada.current?.desligar();
                setMudo(false);
              }}
            >
              Sair da chamada
            </button>
          </div>

          <p className={estilos.chamadaNota}>
            A conversa é transcrita pelo escritório para virar o registro do seu caso.
          </p>
        </>
      )}

      {erro && <div className={estilos.erro}>{erro}</div>}
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
      <span className={estilos.marcador} aria-hidden />

      <span className={estilos.nome}>
        {item.nome}
        {item.observacao && <span className={estilos.observacao}>{item.observacao}</span>}
      </span>

      <span className={estilos.selo}>{selo.texto}</span>

      <button
        type="button"
        className={estilos.enviar}
        onClick={() => inputRef.current?.click()}
        disabled={enviando}
      >
        {item.enviados > 0 ? "Enviar outro" : "Enviar"}
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

      {item.motivo && <span className={estilos.motivo}>Precisa reenviar: {item.motivo}.</span>}

      {item.status === "processando" && (
        <span className={estilos.lendo}>
          Recebemos o arquivo. Estamos conferindo — pode fechar a página, não vai perder.
        </span>
      )}
    </li>
  );
}
