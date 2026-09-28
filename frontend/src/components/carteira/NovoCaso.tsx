"use client";

import { useEffect, useMemo, useRef, useState, type FormEvent, type ReactNode } from "react";
import { CalendarDays, Check, Loader2, Sparkles, Upload, X } from "lucide-react";

import type { CasoCriado, Categoria } from "@/lib/types";
import { Aviso, Botao, Campo, CampoSeletor, Cartao, RotuloCampo, Selo } from "@/components/ui/Basicos";
import { BotaoProcesso } from "@/components/ui/BotaoProcesso";
import CredenciaisPortal from "@/components/portal/CredenciaisPortal";
import {
  enviarTranscricaoEntrevista,
  listarReunioesTactiq,
  obterTranscricaoTactiq,
  triarEntrevista,
  type ReuniaoTactiq,
} from "@/lib/api";
import SeletorSkillPeticao from "@/components/skills/SeletorSkillPeticao";
import { digitosTelefone, formatarTelefone } from "@/lib/formato";

interface Props {
  categorias: Categoria[];
  onCriar: (
    cliente: string, categoria: string, observacao?: string, telefone?: string, tipoAcao?: string, skillJuridicaId?: string,
  ) => Promise<CasoCriado>;
  onImportarZip: (
    cliente: string, categoria: string, arquivo: File, skillJuridicaId?: string, telefone?: string,
  ) => Promise<CasoCriado>;
  onAbrir: (casoId: string) => void;
  onAbrirDossie: (casoId: string) => void;
  onCancelar: () => void;
}

type Passo = 1 | 2 | 3;

const PASSOS: { numero: Passo; rotulo: string }[] = [
  { numero: 1, rotulo: "Cliente" },
  { numero: 2, rotulo: "Tipo de ação" },
  { numero: 3, rotulo: "Conferir e criar" },
];

/** Acima disto a lista de tipos ganha um campo de busca. */
const TIPOS_SEM_BUSCA = 8;

interface Criado {
  caso: CasoCriado;
  viaZip: boolean;
  /** O caso existe, mas a conversa não subiu — criar de novo duplicaria o caso. */
  falhaEntrevista: string | null;
}

function mensagem(erro: unknown, padrao: string): string {
  return erro instanceof Error && erro.message ? erro.message : padrao;
}

function normalizar(valor: string): string {
  return valor.normalize("NFD").replace(/[\u0300-\u036f]/g, "").trim().toLowerCase();
}

function IndicadorPassos({ atual, onIr }: { atual: Passo; onIr: (passo: Passo) => void }) {
  return (
    <ol className="m-0 mb-5 flex list-none flex-wrap items-center gap-2 p-0" aria-label="Etapas para criar o caso">
      {PASSOS.map(({ numero, rotulo }, i) => {
        const feito = numero < atual;
        const ativo = numero === atual;
        return (
          <li key={numero} className="flex items-center gap-2">
            <button
              type="button"
              disabled={!feito}
              onClick={() => onIr(numero)}
              aria-current={ativo ? "step" : undefined}
              className={
                "flex items-center gap-2 rounded-pill border px-3 py-1 text-sm font-semibold [font:inherit] " +
                (ativo
                  ? "border-acao bg-acao text-white"
                  : feito
                    ? "cursor-pointer border-acao-borda bg-acao-clara text-acao hover:border-acao"
                    : "border-borda bg-papel-2 text-tinta-3")
              }
              title={feito ? `Voltar para: ${rotulo}` : undefined}
            >
              <span aria-hidden>{feito ? <Check className="h-4 w-4" /> : numero}</span>
              {rotulo}
            </button>
            {i < PASSOS.length - 1 && <span className="text-tinta-3" aria-hidden>›</span>}
          </li>
        );
      })}
    </ol>
  );
}

function LinhaResumo({ rotulo, children, onAlterar }: { rotulo: string; children: ReactNode; onAlterar: () => void }) {
  return (
    <div className="flex flex-wrap items-start justify-between gap-2 border-b border-borda py-3 last:border-b-0">
      <div className="min-w-0">
        <dt className="text-xs font-semibold text-tinta-3">{rotulo}</dt>
        <dd className="m-0 mt-0.5 text-base text-tinta [overflow-wrap:anywhere]">{children}</dd>
      </div>
      <Botao type="button" variante="texto" pequeno onClick={onAlterar}>
        Alterar
      </Botao>
    </div>
  );
}

/** Assistente de três passos para abrir um caso: quem é o cliente, qual é a ação, conferir.
 *
 * Só o nome e o tipo de ação são obrigatórios — é tudo o que o servidor exige.
 * A conversa com o cliente e o ZIP de documentos ajudam, mas podem entrar depois,
 * pelo dossiê do caso. */
export default function NovoCaso({ categorias, onCriar, onImportarZip, onAbrir, onAbrirDossie, onCancelar }: Props) {
  const [passo, setPasso] = useState<Passo>(1);
  const [cliente, setCliente] = useState("");
  const [telefone, setTelefone] = useState("");
  const [categoria, setCategoria] = useState("");
  const [busca, setBusca] = useState("");

  const [entrevista, setEntrevista] = useState<File | null>(null);
  const [analisando, setAnalisando] = useState(false);
  const [sugerida, setSugerida] = useState<string | null>(null);
  const [avisoTriagem, setAvisoTriagem] = useState<string | null>(null);

  const [reunioesTactiq, setReunioesTactiq] = useState<ReuniaoTactiq[] | null>(null);
  const [carregandoTactiq, setCarregandoTactiq] = useState(false);
  const [importandoTactiq, setImportandoTactiq] = useState<string | null>(null);
  const [erroTactiq, setErroTactiq] = useState<string | null>(null);

  const [zip, setZip] = useState<File | null>(null);
  const [erroZip, setErroZip] = useState<string | null>(null);
  const [arrastando, setArrastando] = useState(false);
  const [skillId, setSkillId] = useState("");

  const [criando, setCriando] = useState(false);
  const [erro, setErro] = useState<string | null>(null);
  const [criado, setCriado] = useState<Criado | null>(null);

  const topoRef = useRef<HTMLDivElement>(null);
  const entrevistaRef = useRef<HTMLInputElement>(null);
  const zipRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    topoRef.current?.scrollIntoView({ block: "start", behavior: "smooth" });
  }, [passo, criado]);

  const escolhida = categorias.find((c) => c.codigo === categoria) ?? null;
  const nomeSugerido = categorias.find((c) => c.codigo === sugerida)?.nome ?? null;
  const tiposVisiveis = useMemo(() => {
    const termo = normalizar(busca);
    const filtrados = termo
      ? categorias.filter((c) => normalizar(`${c.nome} ${c.descricao}`).includes(termo))
      : categorias;
    return sugerida
      ? [...filtrados].sort((a, b) => Number(b.codigo === sugerida) - Number(a.codigo === sugerida))
      : filtrados;
  }, [busca, categorias, sugerida]);

  async function usarEntrevista(arquivo: File | null) {
    setEntrevista(arquivo);
    setAvisoTriagem(null);
    setSugerida(null);
    if (!arquivo) return;
    setAnalisando(true);
    try {
      const triagem = await triarEntrevista("", arquivo);
      const sugestao = triagem.sugestoes[0];
      if (sugestao) {
        setSugerida(sugestao.codigo);
        setCategoria(sugestao.codigo);
      }
      if (!cliente.trim() && triagem.dados.cliente) setCliente(triagem.dados.cliente);
      setAvisoTriagem(
        sugestao
          ? null
          : "A IA leu a conversa, mas não conseguiu indicar um tipo de ação com segurança. Escolha abaixo.",
      );
    } catch (falha) {
      setAvisoTriagem(
        `${mensagem(falha, "Não foi possível ler a conversa.")} Você pode escolher o tipo de ação abaixo mesmo assim.`,
      );
    } finally {
      setAnalisando(false);
    }
  }

  async function carregarTactiq() {
    setCarregandoTactiq(true);
    setErroTactiq(null);
    try {
      setReunioesTactiq(await listarReunioesTactiq());
    } catch (falha) {
      setErroTactiq(mensagem(falha, "Não foi possível carregar as transcrições do Tactiq."));
    } finally {
      setCarregandoTactiq(false);
    }
  }

  async function usarTactiq(reuniao: ReuniaoTactiq) {
    setImportandoTactiq(reuniao.id);
    setErroTactiq(null);
    try {
      const transcricao = await obterTranscricaoTactiq(reuniao.id);
      const nome = `${transcricao.titulo || reuniao.titulo || "entrevista-tactiq"}.txt`.replace(/[\\/:*?"<>|]/g, "-");
      setReunioesTactiq(null);
      await usarEntrevista(new File([transcricao.texto], nome, { type: "text/plain;charset=utf-8" }));
    } catch (falha) {
      setErroTactiq(mensagem(falha, "Não foi possível importar esta transcrição."));
    } finally {
      setImportandoTactiq(null);
    }
  }

  function escolherZip(arquivo: File | null) {
    if (!arquivo) return;
    if (!arquivo.name.toLowerCase().endsWith(".zip")) {
      setErroZip(`"${arquivo.name}" não é um arquivo .zip. Compacte a pasta do cliente e tente de novo.`);
      return;
    }
    setErroZip(null);
    setZip(arquivo);
  }

  function avancarDoCliente(evento: FormEvent) {
    evento.preventDefault();
    if (cliente.trim()) setPasso(2);
  }

  function avancarDoTipo(evento: FormEvent) {
    evento.preventDefault();
    if (escolhida) setPasso(3);
  }

  async function criar(evento: FormEvent) {
    evento.preventDefault();
    if (criado || criando || !escolhida || !cliente.trim()) return;
    setErro(null);
    setCriando(true);
    const nome = cliente.trim();
    const numero = digitosTelefone(telefone);
    let caso: CasoCriado;
    try {
      caso = zip
        ? await onImportarZip(nome, escolhida.codigo, zip, skillId, numero)
        : await onCriar(nome, escolhida.codigo, "", numero, escolhida.nome, skillId);
    } catch (falha) {
      setErro(mensagem(falha, "Não foi possível criar o caso. Confira a conexão e tente de novo."));
      setCriando(false);
      return;
    }
    let falhaEntrevista: string | null = null;
    if (entrevista) {
      try {
        await enviarTranscricaoEntrevista(caso.id, entrevista);
      } catch (falha) {
        falhaEntrevista = mensagem(falha, "O envio da conversa falhou.");
      }
    }
    setCriado({ caso, viaZip: Boolean(zip), falhaEntrevista });
    setCriando(false);
  }

  function recomecar() {
    setPasso(1);
    setCliente("");
    setTelefone("");
    setCategoria("");
    setBusca("");
    setEntrevista(null);
    setSugerida(null);
    setAvisoTriagem(null);
    setReunioesTactiq(null);
    setZip(null);
    setErroZip(null);
    setErro(null);
    setCriado(null);
  }

  if (criado) {
    const { caso, viaZip, falhaEntrevista } = criado;
    const abrir = () => (viaZip ? onAbrirDossie(caso.id) : onAbrir(caso.id));
    return (
      <div ref={topoRef} className="grid min-w-0 gap-4">
        <Cartao
          titulo={`Pronto! O caso de ${caso.cliente} foi criado.`}
          subtitulo={escolhida ? `Tipo de ação: ${escolhida.nome}.` : undefined}
        >
          {(falhaEntrevista || viaZip) && (
            <div className="grid gap-3">
              {falhaEntrevista && (
                <Aviso tom="atencao" titulo="O caso foi criado, mas a conversa com o cliente não foi enviada">
                  {falhaEntrevista} Não crie o caso de novo: abra o caso e envie a conversa pelo dossiê.
                </Aviso>
              )}
              {viaZip && (
                <Aviso tom="info" titulo="Os documentos do ZIP estão sendo lidos">
                  Isso continua sozinho, mesmo se você sair desta tela. Pode abrir o caso agora.
                </Aviso>
              )}
            </div>
          )}

          <CredenciaisPortal
            titulo="Próximo passo: mande o link e a senha para o cliente"
            explicacao="É por esse link que o cliente envia os documentos pelo celular."
            cliente={caso.cliente}
            portal={caso.portal}
            casoId={caso.id}
            telefone={caso.telefone || telefone}
          />

          <div className="mt-5 flex flex-wrap gap-3">
            <Botao variante="primario" onClick={abrir}>
              Abrir o caso
            </Botao>
            <Botao variante="secundario" onClick={recomecar}>
              Criar outro caso
            </Botao>
          </div>
        </Cartao>
      </div>
    );
  }

  return (
    <div ref={topoRef} className="min-w-0">
      <Cartao titulo="Novo caso" subtitulo="Três passos rápidos. Só o nome e o tipo de ação são obrigatórios.">
        <IndicadorPassos atual={passo} onIr={setPasso} />

        {passo === 1 && (
          <form onSubmit={avancarDoCliente} className="grid gap-4">
            <h3 className="m-0 text-base font-semibold text-tinta">Quem é o cliente?</h3>
            <div>
              <RotuloCampo htmlFor="novo-caso-cliente">Nome completo do cliente</RotuloCampo>
              <Campo
                id="novo-caso-cliente"
                value={cliente}
                onChange={(e) => setCliente(e.target.value)}
                placeholder="Ex.: Maria Aparecida da Silva"
                autoComplete="off"
                autoFocus
              />
            </div>
            <div>
              <RotuloCampo htmlFor="novo-caso-telefone">
                WhatsApp do cliente <span className="font-normal text-tinta-3">(opcional)</span>
              </RotuloCampo>
              <Campo
                id="novo-caso-telefone"
                type="tel"
                inputMode="tel"
                value={telefone}
                onChange={(e) => setTelefone(formatarTelefone(e.target.value))}
                placeholder="(61) 98180-8863"
                autoComplete="off"
              />
              <p className="mt-1 text-xs leading-[1.5] text-tinta-3">
                Com o número, o sistema já manda o link para o cliente enviar os documentos.
              </p>
            </div>
            <div className="flex flex-wrap items-start justify-between gap-3">
              <Botao type="button" variante="discreto" onClick={onCancelar}>
                Cancelar
              </Botao>
              <BotaoProcesso
                type="submit"
                variante="primario"
                pendencia={cliente.trim() ? null : "Digite o nome do cliente."}
                pendenciaAoClicar
                onPendencia={() => document.getElementById("novo-caso-cliente")?.focus()}
              >
                Continuar
              </BotaoProcesso>
            </div>
          </form>
        )}

        {passo === 2 && (
          <form onSubmit={avancarDoTipo} className="grid gap-4">
            <h3 className="m-0 text-base font-semibold text-tinta">Qual é o tipo de ação de {cliente.trim()}?</h3>

            <div className="rounded-campo border border-acao-borda bg-acao-clara p-4">
              <strong className="flex items-center gap-2 text-sm text-tinta">
                <Sparkles className="h-4 w-4 text-acao" aria-hidden />
                Não sabe qual escolher? A IA ajuda. <span className="font-normal text-tinta-3">(opcional)</span>
              </strong>
              <p className="mt-1 text-xs leading-[1.5] text-tinta-2">
                Envie a conversa com o cliente — transcrição ou anotações — e a IA indica o tipo de ação.
                A conversa também fica guardada no caso.
              </p>
              <div className="mt-3 flex flex-wrap items-center gap-3">
                <Botao type="button" variante="secundario" onClick={() => entrevistaRef.current?.click()} disabled={analisando}>
                  {analisando ? <Loader2 className="h-4 w-4 animate-spin" /> : <Upload className="h-4 w-4" />}
                  {analisando ? "Lendo a conversa…" : entrevista ? "Trocar a conversa" : "Enviar a conversa"}
                </Botao>
                {entrevista && !analisando && (
                  <span className="flex items-center gap-2 text-sm text-tinta-2">
                    {entrevista.name}
                    <button
                      type="button"
                      className="inline-flex h-6 w-6 items-center justify-center rounded-pill border-none bg-transparent text-tinta-3 hover:bg-papel-3 hover:text-critico"
                      onClick={() => void usarEntrevista(null)}
                      aria-label="Remover a conversa"
                      title="Remover a conversa"
                    >
                      <X className="h-4 w-4" />
                    </button>
                  </span>
                )}
                <Botao type="button" variante="texto" pequeno onClick={() => void carregarTactiq()} disabled={carregandoTactiq}>
                  {carregandoTactiq ? <Loader2 className="h-3 w-3 animate-spin" /> : <CalendarDays className="h-3 w-3" />}
                  Buscar no Tactiq
                </Botao>
              </div>
              <input
                ref={entrevistaRef}
                type="file"
                className="hidden"
                onChange={(e) => { void usarEntrevista(e.target.files?.[0] ?? null); e.target.value = ""; }}
              />
              {nomeSugerido && !analisando && (
                <p className="mt-2 mb-0 text-sm text-tinta">
                  <strong>A IA sugere: {nomeSugerido}.</strong> Já deixamos marcado abaixo — troque se não for isso.
                </p>
              )}
              {avisoTriagem && <p className="mt-2 mb-0 text-xs text-atencao">{avisoTriagem}</p>}
              {erroTactiq && <p className="mt-2 mb-0 text-xs text-critico">{erroTactiq}</p>}
              {reunioesTactiq && (
                <div className="mt-3 max-h-64 space-y-2 overflow-y-auto pr-1">
                  {reunioesTactiq.length === 0 ? (
                    <p className="text-xs text-tinta-2">Nenhuma reunião disponível nesta conta do Tactiq.</p>
                  ) : (
                    reunioesTactiq.map((reuniao) => (
                      <div key={reuniao.id} className="flex items-center justify-between gap-3 rounded-campo border border-acao-borda bg-papel px-3 py-2">
                        <div className="min-w-0">
                          <strong className="block truncate text-sm text-tinta">{reuniao.titulo}</strong>
                          {reuniao.data && <span className="text-xs text-tinta-3">{reuniao.data}</span>}
                        </div>
                        <Botao type="button" variante="secundario" pequeno onClick={() => void usarTactiq(reuniao)} disabled={importandoTactiq !== null}>
                          {importandoTactiq === reuniao.id && <Loader2 className="h-3 w-3 animate-spin" />}
                          Usar esta
                        </Botao>
                      </div>
                    ))
                  )}
                </div>
              )}
            </div>

            {categorias.length === 0 ? (
              <Aviso tom="critico" titulo="Nenhum tipo de ação disponível">
                Verifique se o servidor do sistema está no ar — sem os tipos de ação não é possível criar um caso.
              </Aviso>
            ) : (
              <fieldset className="m-0 min-w-0 border-none p-0">
                <legend className="mb-2 text-sm font-semibold text-tinta">Escolha o tipo de ação</legend>
                {categorias.length > TIPOS_SEM_BUSCA && (
                  <Campo
                    className="mb-3"
                    value={busca}
                    onChange={(e) => setBusca(e.target.value)}
                    placeholder="Procurar pelo nome (ex.: aposentadoria, acidente)"
                    aria-label="Procurar tipo de ação"
                    autoComplete="off"
                  />
                )}
                {tiposVisiveis.length === 0 ? (
                  <p className="text-sm text-tinta-3">Nenhum tipo de ação com esse nome.</p>
                ) : (
                  <div className="grid gap-2 sm:grid-cols-2">
                    {tiposVisiveis.map((tipo) => {
                      const marcado = tipo.codigo === categoria;
                      return (
                        <label
                          key={tipo.codigo}
                          className={
                            "flex cursor-pointer items-start gap-3 rounded-campo border p-3 transition-colors duration-[120ms] " +
                            (marcado ? "border-acao bg-acao-clara" : "border-borda-campo bg-papel hover:border-acao")
                          }
                        >
                          <input
                            type="radio"
                            name="novo-caso-tipo"
                            value={tipo.codigo}
                            checked={marcado}
                            onChange={() => setCategoria(tipo.codigo)}
                            className="mt-1 h-4 w-4 flex-none accent-acao"
                          />
                          <span className="min-w-0">
                            <span className="flex flex-wrap items-center gap-2">
                              <strong className="text-sm text-tinta">{tipo.nome}</strong>
                              {tipo.codigo === sugerida && <Selo tom="ok" simbolo="✓">Sugerido pela IA</Selo>}
                            </span>
                            {tipo.descricao && (
                              <span className="mt-1 block text-xs leading-[1.5] text-tinta-2 line-clamp-2">{tipo.descricao}</span>
                            )}
                            <span className="mt-1 block text-xs text-tinta-3">
                              {tipo.total_documentos} {tipo.total_documentos === 1 ? "documento pedido" : "documentos pedidos"} ao cliente
                            </span>
                          </span>
                        </label>
                      );
                    })}
                  </div>
                )}
              </fieldset>
            )}

            <div className="flex flex-wrap items-start justify-between gap-3">
              <Botao type="button" variante="secundario" onClick={() => setPasso(1)}>
                Voltar
              </Botao>
              <BotaoProcesso
                type="submit"
                variante="primario"
                pendencia={analisando ? "Aguarde a IA terminar de ler a conversa." : escolhida ? null : "Escolha o tipo de ação."}
                pendenciaAoClicar
              >
                Continuar
              </BotaoProcesso>
            </div>
          </form>
        )}

        {passo === 3 && escolhida && (
          <form onSubmit={criar} className="grid gap-4">
            <h3 className="m-0 text-base font-semibold text-tinta">Confira antes de criar</h3>

            <dl className="m-0 rounded-campo border border-borda bg-papel-2 px-4">
              <LinhaResumo rotulo="Cliente" onAlterar={() => setPasso(1)}>{cliente.trim()}</LinhaResumo>
              <LinhaResumo rotulo="WhatsApp" onAlterar={() => setPasso(1)}>
                {digitosTelefone(telefone) ? telefone : <span className="text-tinta-3">não informado</span>}
              </LinhaResumo>
              <LinhaResumo rotulo="Tipo de ação" onAlterar={() => setPasso(2)}>{escolhida.nome}</LinhaResumo>
              <LinhaResumo rotulo="Conversa com o cliente" onAlterar={() => setPasso(2)}>
                {entrevista ? entrevista.name : <span className="text-tinta-3">não enviada — dá para enviar depois, dentro do caso</span>}
              </LinhaResumo>
            </dl>

            <SeletorSkillPeticao
              id="novo-caso-skill"
              valor={skillId}
              onMudar={setSkillId}
              desabilitado={criando}
              ajuda="Muda o texto, a ordem dos blocos, as conferências e o layout da petição deste caso. Na dúvida, deixe o padrão; dá para trocar depois, dentro do caso."
            />

            <div className="text-sm text-tinta-2">
              <strong className="text-tinta">Ao criar, o sistema:</strong>
              <ul className="mt-1 mb-0 list-disc pl-5 leading-[1.7]">
                <li>monta a lista dos {escolhida.total_documentos} documentos que {cliente.trim()} precisa enviar</li>
                <li>gera um link com senha para o cliente mandar os documentos pelo celular</li>
                {entrevista && <li>guarda a conversa no caso e faz o resumo do atendimento</li>}
                {zip && <li>lê os documentos do ZIP e encaixa cada um na lista</li>}
              </ul>
            </div>

            <details className="rounded-campo border border-borda bg-papel px-4 py-3" open={Boolean(zip)}>
              <summary className="cursor-pointer text-sm font-semibold text-acao">
                Já tem os documentos do cliente num arquivo ZIP? <span className="font-normal text-tinta-3">(opcional)</span>
              </summary>
              <div
                className={`mt-3 rounded-xl border-2 border-dashed p-5 text-center transition-colors ${arrastando ? "border-acao bg-acao-clara" : "border-borda bg-papel-2"}`}
                onDragEnter={(e) => { e.preventDefault(); setArrastando(true); }}
                onDragOver={(e) => { e.preventDefault(); e.dataTransfer.dropEffect = "copy"; }}
                onDragLeave={(e) => { e.preventDefault(); setArrastando(false); }}
                onDrop={(e) => { e.preventDefault(); setArrastando(false); escolherZip(e.dataTransfer.files?.[0] ?? null); }}
              >
                <Upload className="mx-auto h-6 w-6 text-acao" aria-hidden />
                <p className="mt-2 mb-0 text-sm font-medium text-tinta">Arraste o arquivo ZIP aqui</p>
                <p className="mt-1 mb-0 text-xs text-tinta-3">até 500 MB · os documentos são lidos e encaixados na lista sozinhos</p>
                <div className="mt-3 flex flex-wrap items-center justify-center gap-3">
                  <Botao type="button" variante="secundario" onClick={() => zipRef.current?.click()}>
                    {zip ? "Trocar o ZIP" : "Escolher o ZIP"}
                  </Botao>
                  {zip && (
                    <span className="flex items-center gap-2 text-sm text-tinta-2">
                      {zip.name}
                      <button
                        type="button"
                        className="inline-flex h-6 w-6 items-center justify-center rounded-pill border-none bg-transparent text-tinta-3 hover:bg-papel-3 hover:text-critico"
                        onClick={() => setZip(null)}
                        aria-label="Remover o ZIP"
                        title="Remover o ZIP"
                      >
                        <X className="h-4 w-4" />
                      </button>
                    </span>
                  )}
                </div>
                <input
                  ref={zipRef}
                  type="file"
                  accept=".zip,application/zip,application/x-zip-compressed"
                  className="hidden"
                  onChange={(e) => { escolherZip(e.target.files?.[0] ?? null); e.target.value = ""; }}
                />
              </div>
              {erroZip && <p className="mt-2 mb-0 text-xs text-critico">{erroZip}</p>}
            </details>

            {erro && (
              <Aviso tom="critico" titulo="O caso não foi criado">
                {erro}
              </Aviso>
            )}

            <div className="flex flex-wrap items-start justify-between gap-3">
              <Botao type="button" variante="secundario" onClick={() => setPasso(2)} disabled={criando}>
                Voltar
              </Botao>
              <BotaoProcesso
                type="submit"
                variante="primario"
                processando={criando}
                textoProcessando={zip ? "Enviando o ZIP e criando o caso…" : "Criando o caso…"}
                dica={zip ? "Pastas grandes podem levar alguns minutos. Não feche esta tela." : undefined}
              >
                Criar o caso
              </BotaoProcesso>
            </div>
          </form>
        )}
      </Cartao>
    </div>
  );
}
