"use client";

import { use, useCallback, useEffect, useRef, useState } from "react";

import { Aviso, Botao, Selo } from "@/components/ui/Basicos";
import { criarSalaChamada } from "@/lib/api";
import * as portal from "@/lib/apiPortal";
import type { ItemPortal, SituacaoPortal } from "@/lib/apiPortal";
import type { TomSelo } from "@/lib/formato";
import { useChamada } from "@/lib/ChamadaContexto";
import type { EstadoChamada } from "@/lib/chamadaJitsi";
import EnvioEmLote from "@/components/caso/EnvioEmLote";

/* Cada estado com símbolo, palavra e tom. O cliente lê "Recebido" e "Precisa
 * reenviar" — não "ENTREGUE" e "CONFERIR", que eram o vocabulário interno do
 * escritório. */
const SELO_TEXTO: Record<ItemPortal["status"], { texto: string; simbolo: string; tom: TomSelo }> = {
  entregue: { texto: "Recebido", simbolo: "✓", tom: "ok" },
  processando: { texto: "Conferindo", simbolo: "◌", tom: "info" },
  conferir: { texto: "Precisa reenviar", simbolo: "!", tom: "atencao" },
  pendente: { texto: "Falta enviar", simbolo: "✕", tom: "critico" },
};
/* A faixa lateral do item — a mesma gravidade do checklist interno, no
 * vocabulário do cliente. */
const ITEM_BORDA: Record<ItemPortal["status"], string> = {
  entregue: "var(--ok)",
  processando: "var(--acao)",
  conferir: "var(--atencao-marca)",
  pendente: "var(--critico)",
};
const ITEM_FUNDO: Record<ItemPortal["status"], string> = {
  entregue: "",
  processando: "",
  conferir: "bg-atencao-claro",
  pendente: "",
};
const MARCADOR: Record<ItemPortal["status"], string> = {
  entregue: "border-ok-borda bg-ok-claro text-ok",
  processando: "border-acao-borda bg-acao-clara text-acao",
  conferir: "border-atencao-borda bg-papel text-atencao",
  pendente: "border-critico-borda bg-critico-claro text-critico",
};

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
  const lendo =
    situacao?.itens.some((i) => i.status === "processando") ||
    Boolean(situacao?.processando);

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
    <div className="min-h-screen px-4 pt-5 pb-12 bg-fundo text-md">
      <div className="w-[min(680px,100%)] mx-auto">
        <span className="block text-tinta font-titulo text-[1.25rem] font-bold">Acervo</span>
        <span className="block mt-[1px] text-tinta-3 text-xs">Envio de documentos</span>
        <hr className="mt-4 mb-5 border-none border-t border-borda" />

        <form
          className="p-6 border border-borda-forte rounded-cartao bg-papel shadow-cartao"
          onSubmit={enviar}
        >
          <h1 className="m-0 text-[1.625rem]">Seus documentos</h1>
          <p className="mt-[10px] mb-0 text-tinta-2 text-base leading-[1.6]">
            Digite a senha que o escritório enviou junto com este link. Ela serve para proteger os
            seus documentos — ninguém além de você entra aqui sem ela.
          </p>

          <label className="sr-only" htmlFor="senha-portal">
            Senha de acesso
          </label>
          <input
            id="senha-portal"
            className="w-full min-h-[52px] mt-5 px-[14px] py-3 border border-borda-campo rounded-campo bg-papel text-tinta font-codigo text-[1.25rem] tracking-[0.12em] text-center uppercase focus:border-acao focus:shadow-[0_0_0_3px_var(--acao-clara)] focus:outline-none"
            value={senha}
            onChange={(e) => setSenha(e.target.value)}
            placeholder="XXXXX-XXXXX"
            autoComplete="one-time-code"
            autoFocus
          />

          {erro && (
            <div className="mt-4">
              <Aviso tom="critico" titulo="Não foi possível entrar">
                {erro}
              </Aviso>
            </div>
          )}

          <Botao
            type="submit"
            variante="primario"
            bloco
            className="mt-[14px] text-base"
            style={{ minHeight: 48 }}
            disabled={entrando || !senha.trim()}
          >
            {entrando ? "Verificando…" : "Ver meus documentos"}
          </Botao>
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
  const [enviandoLote, setEnviandoLote] = useState(false);
  const [erro, setErro] = useState<string | null>(null);
  const [avisoLote, setAvisoLote] = useState<string | null>(null);

  if (!situacao) {
    return (
      <div className="min-h-screen px-4 pt-5 pb-12 bg-fundo text-md">
        <div className="w-[min(680px,100%)] mx-auto">
          <p className="mt-[10px] mb-0 text-tinta-2 text-base leading-[1.6]">Carregando seus documentos…</p>
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

  async function enviarLote(arquivos: File[]) {
    setEnviandoLote(true);
    setErro(null);
    setAvisoLote(null);
    try {
      const resultado = await portal.enviarDocumentosEmLote(token, sessao, arquivos);
      onAtualizar(resultado.situacao);
      const recusados = resultado.recusados.length;
      setAvisoLote(
        recusados
          ? `${resultado.recebidos.length} arquivo(s) recebido(s). ${recusados} não entraram e precisam ser selecionados novamente.`
          : `${resultado.recebidos.length} arquivo(s) recebido(s). Agora estamos identificando cada documento.`,
      );
      if (recusados) {
        setErro(resultado.recusados.map((item) => `${item.arquivo}: ${item.motivo}`).join("; "));
      }
    } catch (e) {
      setErro(e instanceof Error ? e.message : "Não foi possível enviar os arquivos.");
    } finally {
      setEnviandoLote(false);
    }
  }

  const pct = Math.max(0, Math.min(100, progresso.percentual));

  return (
    <div className="min-h-screen px-4 pt-5 pb-12 bg-fundo text-md">
      <div className="w-[min(680px,100%)] mx-auto">
        <span className="block text-tinta font-titulo text-[1.25rem] font-bold">Acervo</span>
        <span className="block mt-[1px] text-tinta-3 text-xs">Envio de documentos</span>
        <hr className="mt-4 mb-5 border-none border-t border-borda" />

        <div className="flex justify-between items-end gap-4 flex-wrap">
          <div>
            <h1 className="m-0 text-[1.625rem]">{situacao.cliente}</h1>
            <p className="mt-1 mb-0 text-tinta-3 text-sm">{situacao.categoria}</p>
          </div>
          <div>
            <span className="text-tinta font-titulo text-[1.875rem] font-semibold tabular-nums leading-none whitespace-nowrap">
              {progresso.obrigatorios_entregues}
              <span className="text-tinta-3 text-[1.25rem]">/{progresso.obrigatorios_total}</span>
            </span>
            <div className="mt-[2px] text-tinta-3 text-xs text-right">documentos recebidos</div>
          </div>
        </div>

        <div
          className="h-[10px] mt-4 rounded-pill bg-papel-3 overflow-hidden"
          role="progressbar"
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={pct}
          aria-label="Documentos já recebidos"
        >
          <i
            className="block h-full rounded-pill bg-ok transition-[width] duration-[240ms] ease-[ease]"
            style={{ width: `${pct}%` }}
          />
        </div>

        {progresso.pronto && (
          <div className="mt-5">
            <Aviso tom="ok" titulo="Recebemos tudo o que era necessário">
              Não falta nenhum documento. O escritório entra em contato com você.
            </Aviso>
          </div>
        )}

        <Chamada token={token} />

        <div className="mt-5">
          <EnvioEmLote onEnviar={enviarLote} enviando={enviandoLote} compacto />
        </div>

        {avisoLote && (
          <div className="mt-4">
            <Aviso tom="ok" titulo="Arquivos recebidos">{avisoLote}</Aviso>
          </div>
        )}

        {situacao.em_analise > 0 && (
          <div className="mt-4">
            <Aviso tom="info" titulo="Estamos separando seus documentos">
              {situacao.em_analise} {situacao.em_analise === 1 ? "arquivo está" : "arquivos estão"} em análise.
              Você não precisa escolher onde colocar: o escritório verá qualquer documento que não
              pudermos identificar automaticamente.
            </Aviso>
          </div>
        )}

        {erro && (
          <div className="mt-5">
            <Aviso tom="critico" titulo="O arquivo não foi enviado">
              {erro}
            </Aviso>
          </div>
        )}

        {faltam.length > 0 && (
          <>
            <div className="mt-5 mb-0 px-[18px] py-4 border border-acao-borda rounded-campo bg-acao-clara">
              <h2 className="mb-2 mt-0 text-tinta font-ui text-sm font-bold">Como fotografar para dar certo</h2>
              <ul className="m-0 pl-5">
                <li className="mb-1 text-tinta-2 text-sm leading-[1.55]">
                  Use um lugar bem iluminado, sem sombra sobre o documento.
                </li>
                <li className="mb-1 text-tinta-2 text-sm leading-[1.55]">
                  Enquadre o documento inteiro, sem cortar as bordas.
                </li>
                <li className="mb-1 text-tinta-2 text-sm leading-[1.55]">
                  Uma foto por documento. Também aceitamos PDF.
                </li>
                <li className="mb-1 text-tinta-2 text-sm leading-[1.55]">
                  Se a leitura não der certo, pedimos o reenvio aqui mesmo.
                </li>
              </ul>
            </div>

            <h2 className="flex items-center gap-[10px] mt-7 mb-[10px] text-tinta font-titulo text-lg font-semibold">
              Ainda falta enviar
              <Selo tom="critico">{faltam.length}</Selo>
            </h2>
            <ul className="list-none m-0 p-0 border border-borda-forte rounded-cartao bg-papel shadow-cartao overflow-hidden">
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
            <h2 className="flex items-center gap-[10px] mt-7 mb-[10px] text-tinta font-titulo text-lg font-semibold">
              Já recebemos
              <Selo tom="ok">{prontos.length}</Selo>
            </h2>
            <ul className="list-none m-0 p-0 border border-borda-forte rounded-cartao bg-papel shadow-cartao overflow-hidden">
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

        <div className="mt-7 pt-4 border-t border-borda text-tinta-3 text-sm leading-[1.6]">
          Esta página é sua e do escritório. Pode fechá-la e voltar pelo mesmo link quando quiser.
          <br />
          <Botao variante="texto" onClick={onSair}>
            Sair desta página
          </Botao>
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
 * A chamada vive no `ProvedorChamada`, na raiz: se o cliente veio da página da
 * chamada (mesma sala, que é este token), a ligação JÁ está de pé aqui — e
 * continua enquanto ele envia os documentos, que é o ponto. Fechar a página não
 * derruba de propósito; quem encerra é o botão de sair, ou fechar a aba.
 *
 * Duas coisas ficam ditas na tela, e não por gentileza: que a conversa é
 * transcrita, e que sem microfone liberado não há chamada. */
function Chamada({ token }: { token: string }) {
  const chamada = useChamada();
  const [entrando, setEntrando] = useState(false);
  const [erro, setErro] = useState<string | null>(null);

  // Esta seção mostra a chamada por inteiro: enquanto está na tela, o painel
  // flutuante se recolhe. `registrarPainel` é estável, então roda uma vez.
  useEffect(() => chamada.registrarPainel(), [chamada.registrarPainel]);

  async function entrar() {
    setErro(null);
    setEntrando(true);
    try {
      const { token: jitsiToken } = await criarSalaChamada(token);
      await chamada.entrar(token, "cliente", undefined, jitsiToken);
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

  const naChamada = chamada.ativa;
  const situacao: Record<EstadoChamada, string> = {
    fora: "",
    aguardando: "Esperando o escritório entrar. Deixe esta tela aberta.",
    conectando: "Conectando…",
    falando: "Você está na chamada. Pode falar.",
    encerrada: "A chamada foi encerrada.",
  };

  return (
    <div className="mt-6 px-5 pb-5 pt-[18px] border border-borda-forte rounded-cartao bg-papel shadow-cartao">
      <h2 className="flex items-center gap-[10px] mt-0 mb-1 text-tinta font-titulo text-lg font-semibold">
        Conversar com o escritório
      </h2>

      {!naChamada ? (
        <>
          <p className="mt-[10px] mb-0 text-tinta-2 text-base leading-[1.6]">
            Se o escritório combinou uma conversa por voz, toque abaixo. Você fala pelo
            próprio celular, sem instalar nada.
          </p>
          <Botao variante="primario" className="mt-[14px]" onClick={entrar} disabled={entrando}>
            {entrando ? "Abrindo…" : "Entrar na chamada"}
          </Botao>
        </>
      ) : (
        <>
          <p className="m-0 text-ok text-md font-medium leading-[1.5]" aria-live="polite">
            {situacao[chamada.estado]}
          </p>

          <div className="flex gap-[10px] mt-4 flex-wrap">
            <Botao variante="secundario" onClick={chamada.alternarMudo}>
              {chamada.mudo ? "Voltar a falar" : "Desligar meu microfone"}
            </Botao>
            <Botao variante="secundario" onClick={chamada.desligar}>
              Sair da chamada
            </Botao>
          </div>
        </>
      )}

      <p className="mt-[14px] mb-0 text-tinta-3 text-sm leading-[1.55]">
        A conversa é transcrita pelo escritório para virar o registro do seu atendimento.
        Ela continua enquanto você envia os documentos.
      </p>

      {(erro || chamada.erro) && (
        <div className="mt-[14px]">
          <Aviso tom="critico" titulo="A chamada não abriu">
            {erro ?? chamada.erro}
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
  const selo = SELO_TEXTO[item.status];

  return (
    <li
      className={`flex items-center gap-3 px-[18px] py-4 border-b border-borda border-l-4 flex-wrap last:border-b-0 ${ITEM_FUNDO[item.status]}`}
      style={{ borderLeftColor: ITEM_BORDA[item.status] }}
    >
      <span
        className={`flex-none grid place-items-center w-7 h-7 border-[1.5px] rounded-full text-[0.875rem] font-bold leading-none ${MARCADOR[item.status]}`}
        aria-hidden
      >
        {selo.simbolo}
      </span>

      <span className="flex-1 min-w-[170px] text-tinta text-md font-medium leading-[1.4]">
        {item.nome}
        {item.observacao && (
          <span className="block mt-[3px] text-tinta-3 text-sm font-normal leading-[1.5]">{item.observacao}</span>
        )}
      </span>

      <Selo tom={selo.tom} simbolo={selo.simbolo}>
        {selo.texto}
      </Selo>

      <Botao
        variante={item.enviados > 0 ? "secundario" : "primario"}
        className="flex-none"
        style={{ minHeight: 44 }}
        onClick={() => inputRef.current?.click()}
        disabled={enviando}
      >
        {enviando ? "Enviando…" : item.enviados > 0 ? "Enviar outra foto" : "Enviar foto ou PDF"}
      </Botao>

      <input
        ref={inputRef}
        type="file"
        hidden
        onChange={(e) => {
          const arquivo = e.target.files?.[0];
          if (arquivo) onEnviar(item.codigo, arquivo);
          e.target.value = "";
        }}
      />

      {item.motivo && (
        <span
          className="[flex-basis:100%] ml-10 px-3 py-[10px] rounded-campo text-sm leading-[1.55] border border-atencao-borda border-l-4 bg-papel text-tinta-2"
          style={{ borderLeftColor: "var(--atencao-marca)" }}
        >
          <strong>Por que pedimos de novo:</strong> {item.motivo}.
        </span>
      )}

      {item.status === "processando" && (
        <span
          className="[flex-basis:100%] ml-10 px-3 py-[10px] rounded-campo text-sm leading-[1.55] border border-acao-borda border-l-4 bg-acao-clara text-tinta-2"
          style={{ borderLeftColor: "var(--acao)" }}
        >
          Recebemos o arquivo e estamos conferindo. Pode fechar a página — não vai perder nada.
        </span>
      )}
    </li>
  );
}
