"use client";

import { useCallback, useEffect, useState } from "react";
import type { ReactNode } from "react";

import { Aviso, Botao, Campo, Cartao, LinkBotao, RotuloCampo, Selo } from "@/components/ui/Basicos";
import {
  ApiError,
  desconectarDrive,
  salvarCredenciaisDrive,
  statusDrive,
  testarDrive,
  urlConectarDrive,
  type StatusDrive,
} from "@/lib/api";

const LINK_API = "https://console.cloud.google.com/apis/library/drive.googleapis.com";
const LINK_CONSENTIMENTO = "https://console.cloud.google.com/auth/overview";
const LINK_USUARIOS_TESTE = "https://console.cloud.google.com/auth/audience";
const LINK_CREDENCIAL = "https://console.cloud.google.com/auth/clients/create";

function Copiavel({ rotulo, valor }: { rotulo: string; valor: string }) {
  const [copiado, setCopiado] = useState(false);
  return (
    <div className="mt-2">
      <span className="block text-[11px] font-semibold uppercase tracking-[0.08em] text-tinta-3">{rotulo}</span>
      <div className="mt-1 flex flex-wrap items-center gap-2 rounded-campo border border-borda-forte bg-papel px-3 py-2">
        <code className="min-w-0 flex-1 font-codigo text-[13px] text-tinta [overflow-wrap:anywhere]">{valor}</code>
        <Botao
          variante="secundario"
          pequeno
          onClick={() => {
            void navigator.clipboard.writeText(valor).then(() => {
              setCopiado(true);
              window.setTimeout(() => setCopiado(false), 2000);
            });
          }}
        >
          {copiado ? "✓ Copiado" : "Copiar"}
        </Botao>
      </div>
    </div>
  );
}

function Passo({
  numero,
  titulo,
  feito,
  aberto,
  children,
}: {
  numero: number;
  titulo: string;
  feito: boolean;
  aberto: boolean;
  children: ReactNode;
}) {
  return (
    <details open={aberto} className="rounded-campo border border-borda bg-papel-2 [&[open]]:bg-papel">
      <summary className="flex cursor-pointer items-center gap-3 px-4 py-3">
        <span
          className={`grid size-7 shrink-0 place-items-center rounded-full text-sm font-bold ${
            feito ? "bg-ok text-papel" : "border border-borda-forte bg-papel text-tinta"
          }`}
          aria-hidden
        >
          {feito ? "✓" : numero}
        </span>
        <span className="text-sm font-semibold text-tinta">{titulo}</span>
        {feito && <span className="ml-auto text-xs text-ok">feito</span>}
      </summary>
      <div className="px-4 pb-4 pl-14 text-sm leading-[1.6] text-tinta-2">{children}</div>
    </details>
  );
}

export default function CartaoGoogleDrive() {
  const [status, setStatus] = useState<StatusDrive | null>(null);
  const [clientId, setClientId] = useState("");
  const [clientSecret, setClientSecret] = useState("");
  const [ocupado, setOcupado] = useState<"salvar" | "conectar" | "desconectar" | "testar" | null>(null);
  const [aguardando, setAguardando] = useState(false);
  const [erro, setErro] = useState<string | null>(null);
  const [sucesso, setSucesso] = useState<string | null>(null);
  const [trocarCredenciais, setTrocarCredenciais] = useState(false);

  const ler = useCallback(async () => {
    try {
      const s = await statusDrive();
      setStatus(s);
      if (s.conectado && aguardando) {
        setAguardando(false);
        setSucesso("Google Drive conectado! Clique em “Testar conexão” para conferir.");
      }
    } catch (e) {
      setErro(e instanceof ApiError ? e.message : "Não foi possível consultar o Google Drive.");
    }
  }, [aguardando]);

  useEffect(() => {
    void ler();
  }, [ler]);

  useEffect(() => {
    if (!aguardando) return;
    const id = window.setInterval(() => void ler(), 3000);
    return () => window.clearInterval(id);
  }, [aguardando, ler]);

  async function executar(acao: "salvar" | "conectar" | "desconectar" | "testar", tarefa: () => Promise<void>) {
    setOcupado(acao);
    setErro(null);
    setSucesso(null);
    try {
      await tarefa();
    } catch (e) {
      setErro(e instanceof ApiError ? e.message : "A operação com o Google Drive falhou.");
    } finally {
      setOcupado(null);
    }
  }

  const idValido = clientId.trim().endsWith(".apps.googleusercontent.com");
  const configurado = Boolean(status?.configurado);
  const conectado = Boolean(status?.conectado);
  const mostrarPassos = status && !status.credenciais_do_ambiente && (!configurado || trocarCredenciais);

  const selo = !status
    ? { tom: "info" as const, texto: "Verificando…" }
    : conectado
      ? { tom: "ok" as const, texto: "Conectado" }
      : configurado
        ? { tom: "atencao" as const, texto: "Falta conectar a conta" }
        : { tom: "atencao" as const, texto: "Não configurado" };

  return (
    <Cartao
      titulo="Google Drive das gravações"
      subtitulo="Cada vídeo de entrevista, além de baixar no computador, é salvo automaticamente numa pasta do Google Drive do escritório."
      className="min-w-0 overflow-hidden"
    >
      <div className="flex flex-wrap items-center gap-2">
        <Selo tom={selo.tom} simbolo={conectado ? "✓" : "!"}>{selo.texto}</Selo>
        {conectado && status?.conta && <span className="text-sm font-semibold text-tinta">{status.conta}</span>}
        {status?.pasta_url && (
          <a className="text-sm text-acao underline" href={status.pasta_url} target="_blank" rel="noreferrer">
            abrir a pasta das gravações
          </a>
        )}
      </div>

      {conectado && (
        <div className="mt-4 flex flex-wrap gap-2">
          <Botao
            variante="primario"
            pequeno
            carregando={ocupado === "testar"}
            textoCarregando="Testando…"
            onClick={() => void executar("testar", async () => setSucesso((await testarDrive()).mensagem))}
          >
            Testar conexão
          </Botao>
          <Botao
            variante="secundario"
            pequeno
            carregando={ocupado === "desconectar"}
            textoCarregando="Desconectando…"
            onClick={() => {
              if (!window.confirm("Desconectar o Google Drive? As próximas gravações ficarão só no computador.")) return;
              void executar("desconectar", async () => setStatus(await desconectarDrive()));
            }}
          >
            Desconectar
          </Botao>
        </div>
      )}

      {sucesso && (
        <div className="mt-3">
          <Aviso tom="ok" titulo="Google Drive">{sucesso}</Aviso>
        </div>
      )}
      {erro && (
        <div className="mt-3">
          <Aviso tom="critico" titulo="Não deu certo">{erro}</Aviso>
        </div>
      )}

      {status && !conectado && (
        <div className="mt-4 grid gap-2">
          <p className="m-0 text-sm text-tinta-2">
            Siga os passos em ordem. Leva uns 10 minutos e só precisa ser feito uma vez. Use a conta Google onde os
            vídeos devem ficar guardados.
          </p>

          {mostrarPassos && (
            <>
              <Passo numero={1} titulo="Ativar a Google Drive API" feito={false} aberto>
                <ol className="m-0 pl-5">
                  <li>Clique no botão abaixo e entre com a conta Google do escritório.</li>
                  <li>
                    No topo da página, em “Selecione um projeto”, clique em <strong>Novo projeto</strong>, dê o nome{" "}
                    <strong>Acervo</strong> e clique em <strong>Criar</strong>. Se já tiver um projeto, só selecione.
                  </li>
                  <li>Com o projeto selecionado, clique no botão azul <strong>Ativar</strong>.</li>
                </ol>
                <LinkBotao variante="secundario" pequeno className="mt-3" href={LINK_API} target="_blank" rel="noreferrer">
                  Abrir a Google Drive API ↗
                </LinkBotao>
              </Passo>

              <Passo numero={2} titulo="Configurar a tela de consentimento" feito={false} aberto>
                <ol className="m-0 pl-5">
                  <li>
                    Abra a página abaixo e clique em <strong>Começar</strong> (ou “Configurar tela de consentimento”).
                  </li>
                  <li>
                    Nome do app: <strong>Acervo</strong>. E-mail de suporte: o seu e-mail. Clique em{" "}
                    <strong>Próxima</strong>.
                  </li>
                  <li>
                    Em “Público-alvo”, escolha <strong>Externo</strong>. Em “Informações de contato”, coloque o seu
                    e-mail. Aceite a política e clique em <strong>Criar</strong>.
                  </li>
                  <li>
                    <strong>Importante:</strong> abra “Público-alvo” e, em <strong>Usuários de teste</strong>, clique em{" "}
                    <strong>Adicionar usuários</strong> e coloque o e-mail da conta Google onde os vídeos vão ficar.
                    Sem isso o Google bloqueia a conexão.
                  </li>
                </ol>
                <div className="mt-3 flex flex-wrap gap-2">
                  <LinkBotao variante="secundario" pequeno href={LINK_CONSENTIMENTO} target="_blank" rel="noreferrer">
                    Abrir a tela de consentimento ↗
                  </LinkBotao>
                  <LinkBotao variante="texto" pequeno href={LINK_USUARIOS_TESTE} target="_blank" rel="noreferrer">
                    Abrir usuários de teste ↗
                  </LinkBotao>
                </div>
              </Passo>

              <Passo numero={3} titulo="Criar o ID do cliente OAuth" feito={false} aberto>
                <ol className="m-0 pl-5">
                  <li>
                    Abra a página abaixo. Em “Tipo de aplicativo”, escolha <strong>Aplicativo da Web</strong>. Nome:{" "}
                    <strong>Acervo</strong>.
                  </li>
                  <li>
                    Em <strong>Origens JavaScript autorizadas</strong>, clique em “Adicionar URI” e cole:
                    <Copiavel rotulo="Origem" valor={status.origem} />
                  </li>
                  <li className="mt-2">
                    Em <strong>URIs de redirecionamento autorizados</strong>, clique em “Adicionar URI” e cole
                    exatamente, sem espaço nem barra no fim:
                    <Copiavel rotulo="URI de redirecionamento" valor={status.redirect_uri} />
                  </li>
                  <li className="mt-2">
                    Clique em <strong>Criar</strong>. Vai abrir uma janela com o <strong>ID do cliente</strong> e a{" "}
                    <strong>Chave secreta do cliente</strong>. Deixe essa janela aberta para o próximo passo.
                  </li>
                </ol>
                <LinkBotao variante="secundario" pequeno className="mt-3" href={LINK_CREDENCIAL} target="_blank" rel="noreferrer">
                  Criar o ID do cliente ↗
                </LinkBotao>
              </Passo>

              <Passo numero={4} titulo="Colar o ID e a chave aqui" feito={false} aberto>
                <div className="grid gap-3">
                  <div>
                    <RotuloCampo htmlFor="drive-client-id">ID do cliente (Client ID)</RotuloCampo>
                    <Campo
                      id="drive-client-id"
                      value={clientId}
                      onChange={(e) => setClientId(e.target.value)}
                      placeholder="123456789-abc.apps.googleusercontent.com"
                      autoComplete="off"
                    />
                    {clientId.trim() && !idValido && (
                      <p className="mt-1 mb-0 text-xs text-atencao">
                        O ID do cliente termina com “.apps.googleusercontent.com”. Confira se copiou o campo certo.
                      </p>
                    )}
                  </div>
                  <div>
                    <RotuloCampo htmlFor="drive-client-secret">Chave secreta do cliente (Client Secret)</RotuloCampo>
                    <Campo
                      id="drive-client-secret"
                      type="password"
                      value={clientSecret}
                      onChange={(e) => setClientSecret(e.target.value)}
                      placeholder="GOCSPX-…"
                      autoComplete="off"
                    />
                  </div>
                  <div className="flex flex-wrap gap-2">
                    <Botao
                      variante="primario"
                      carregando={ocupado === "salvar"}
                      textoCarregando="Salvando…"
                      disabled={!idValido || !clientSecret.trim()}
                      onClick={() =>
                        void executar("salvar", async () => {
                          setStatus(await salvarCredenciaisDrive(clientId, clientSecret));
                          setClientSecret("");
                          setTrocarCredenciais(false);
                          setSucesso("Credenciais salvas. Agora clique em “Conectar Google Drive”.");
                        })
                      }
                    >
                      Salvar e continuar
                    </Botao>
                    {configurado && (
                      <Botao variante="texto" onClick={() => setTrocarCredenciais(false)}>
                        Cancelar
                      </Botao>
                    )}
                  </div>
                </div>
              </Passo>
            </>
          )}

          {configurado && !mostrarPassos && (
            <>
              <Passo numero={1} titulo="Credenciais do Google salvas" feito aberto={false}>
                <p className="m-0">
                  ID do cliente em uso: <code className="font-codigo [overflow-wrap:anywhere]">{status.client_id}</code>
                </p>
                {!status.credenciais_do_ambiente && (
                  <Botao variante="texto" pequeno className="mt-2" onClick={() => setTrocarCredenciais(true)}>
                    Trocar credenciais
                  </Botao>
                )}
              </Passo>
              <Passo numero={2} titulo="Conectar a conta Google" feito={false} aberto>
                <ol className="m-0 pl-5">
                  <li>Clique no botão abaixo. Vai abrir uma aba do Google.</li>
                  <li>Escolha a conta onde os vídeos vão ficar (a mesma colocada em “Usuários de teste”).</li>
                  <li>
                    Se aparecer “<strong>O Google não verificou este app</strong>”, clique em <strong>Avançado</strong> e
                    depois em <strong>Acessar Acervo</strong>. É normal: o app é do próprio escritório.
                  </li>
                  <li>
                    Marque a permissão do Google Drive e clique em <strong>Continuar</strong>. A aba fecha sozinha e esta
                    tela atualiza.
                  </li>
                </ol>
                <Botao
                  variante="primario"
                  className="mt-3"
                  carregando={ocupado === "conectar"}
                  textoCarregando="Abrindo o Google…"
                  onClick={() =>
                    void executar("conectar", async () => {
                      const { url } = await urlConectarDrive();
                      window.open(url, "_blank");
                      setAguardando(true);
                    })
                  }
                >
                  Conectar Google Drive
                </Botao>
                {aguardando && (
                  <p className="mt-2 mb-0 text-sm text-atencao">
                    Aguardando você terminar na aba do Google… esta tela confere sozinha a cada 3 segundos.
                  </p>
                )}
              </Passo>
            </>
          )}

          <details className="mt-2 text-sm">
            <summary className="cursor-pointer font-semibold text-tinta">Deu erro? Veja as soluções mais comuns</summary>
            <ul className="mt-2 mb-0 pl-5 leading-[1.6] text-tinta-2">
              <li>
                <strong>“Erro 400: redirect_uri_mismatch”</strong>: a URI de redirecionamento do passo 3 está diferente.
                Copie de novo pelo botão e cole exatamente, sem espaço nem barra no fim. Pode levar alguns minutos para
                o Google aplicar.
              </li>
              <li>
                <strong>“Acesso bloqueado” ou “Erro 403: access_denied”</strong>: falta colocar o seu e-mail em
                “Usuários de teste” (passo 2).
              </li>
              <li>
                <strong>“O Google não verificou este app”</strong>: clique em “Avançado” e depois em “Acessar Acervo”.
              </li>
              <li>
                <strong>“invalid_client”</strong>: o ID ou a chave foram copiados errado. Use “Trocar credenciais” e cole
                de novo.
              </li>
              <li>
                <strong>Conectou mas não aparece a conta</strong>: clique em “Testar conexão” ou recarregue a página.
              </li>
            </ul>
          </details>
        </div>
      )}
    </Cartao>
  );
}
