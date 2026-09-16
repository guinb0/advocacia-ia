"use client";

import { use, useEffect, useState } from "react";

import { criarSalaChamada } from "@/lib/api";
import { useChamada } from "@/lib/ChamadaContexto";
import type { EstadoChamada } from "@/lib/chamadaJitsi";
import AtivarMicrofone from "@/components/chamada/AtivarMicrofone";
import IndicadorVoz from "@/components/chamada/IndicadorVoz";
import Retratos from "@/components/ui/Retratos";
import { BotaoProcesso } from "@/components/ui/BotaoProcesso";

/* A chamada do lado de quem é entrevistado.
 *
 * Página deliberadamente pobre: um botão. Quem abre isto é o cliente, no
 * celular, no meio de um dia ruim — não há login, não há senha, não há
 * instalação. O que protege a sala é o link, sorteado com 128 bits.
 *
 * A voz sobe pelo Jitsi e chega ao navegador do advogado numa faixa própria — é
 * ela que alimenta a transcrição do outro lado. Está escrito na tela: gravar a
 * conversa de alguém sem dizer não é coisa que se faça, ainda mais num
 * escritório que promete sigilo no acolhimento.
 *
 * A chamada vive no `ProvedorChamada`, na raiz — então se o cliente abrir o
 * portal para enviar documentos (mesma sala, que é o token do caso), a ligação
 * NÃO cai: ela segue no painel flutuante. */

/* Dois por linha no celular, e nao quatro empilhados.
 *
 * Empilhados, os botoes ocupavam ~300px — metade da tela do telefone — e
 * empurravam a chamada para uma faixa no topo. `basis` de metade com o vao
 * descontado da exatamente duas colunas; o texto quebra em duas linhas quando
 * precisa, que custa muito menos altura que uma linha inteira por botao. De
 * `sm` para cima volta ao comportamento antigo, que ali sobra largura. */
const SECUNDARIO =
  "basis-[calc(50%-5px)] grow min-w-0 sm:basis-auto sm:min-w-[150px] border border-borda-forte " +
  "bg-transparent text-tinta text-[11px] font-semibold leading-[1.3] text-center " +
  "font-ui tracking-[0.08em] uppercase px-2 py-[13px] cursor-pointer hover:bg-papel-2";

export default function PaginaChamada({ params }: { params: Promise<{ sala: string }> }) {
  const { sala } = use(params);
  const chamada = useChamada();

  const [entrando, setEntrando] = useState(false);
  const [camera, setCamera] = useState(false);
  /* Sem login: o nome é o que a pessoa digitar. Serve para o advogado saber
   * quem entrou — numa sala com link solto, "Convidado" não diz nada. */
  const [nome, setNome] = useState("");
  const [erro, setErro] = useState<string | null>(null);
  /* O microfone que passou no teste acima. A chamada abre COM ELE: abrir no
   * padrão do sistema devolveria justamente o dispositivo que o teste reprovou. */
  const [microfone, setMicrofone] = useState<string | undefined>(undefined);

  // Esta página é a própria chamada: enquanto está aberta, o painel flutuante
  // se recolhe. `registrarPainel` é estável, então roda uma vez.
  useEffect(() => chamada.registrarPainel(), [chamada.registrarPainel]);

  async function entrar() {
    setErro(null);
    setEntrando(true);
    try {
      const { token: jitsiToken, p2p } = await criarSalaChamada(sala);
      await chamada.entrar(
        sala,
        "cliente",
        { nome: nome.trim(), camera, microfoneId: microfone, p2p },
        jitsiToken,
      );
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

  /* Margem menor no telefone: 16+26 de cada lado tiravam 84px dos 390 da
   * tela, e essa largura e a que define o tamanho do rosto na chamada. */
  return (
    <div className="min-h-screen bg-papel px-2 pt-4 pb-8 sm:px-4 sm:pt-6 sm:pb-12 flex items-center">
      <div className="w-[min(820px,100%)] mx-auto">
        <span className="font-bold text-[14px] leading-none font-titulo tracking-[0.02em]">ACERVO</span>
        <div className="mt-3 mb-[22px] border-t-[3px] border-double border-borda-forte" />

        <div className="border border-borda-forte p-4 sm:p-[26px]">
          <h1 className="mb-[10px] mt-0 font-semibold text-[24px] leading-[1.15] font-titulo">
            Conversa com o escritório
          </h1>

          {!naChamada ? (
            <>
            <p className="m-0 text-[14px] leading-[1.65] font-ui text-tinta-3">
                Diga como quer ser chamado e toque em entrar. É pelo próprio navegador — não
                precisa instalar nada, criar conta nem informar o seu número. Deixe esta tela
                aberta durante a conversa.
              </p>

              <AtivarMicrofone onMicrofone={setMicrofone} />

              <label
                className="block mt-5 mb-[6px] font-medium text-[13px] leading-[1.3] font-ui text-tinta-3"
                htmlFor="nome-na-chamada"
              >
                Seu nome
              </label>
              <input
                id="nome-na-chamada"
                className="w-full min-h-[52px] px-[14px] py-3 border border-borda-forte bg-papel-2 text-tinta text-[17px] leading-[1.3] font-ui focus:[outline:2px_solid_var(--ok)] focus:outline-offset-[1px]"
                value={nome}
                onChange={(e) => setNome(e.target.value)}
                placeholder="Como o escritório deve te chamar"
                autoComplete="name"
                maxLength={40}
              />

              <label className="flex items-center gap-[10px] min-h-[44px] mt-3 text-[14.5px] leading-[1.4] font-ui cursor-pointer">
                <input
                  className="w-5 h-5"
                  type="checkbox"
                  checked={camera}
                  onChange={(e) => setCamera(e.target.checked)}
                />
                Entrar com a câmera ligada
              </label>

              {/* Botão grande e sempre com a cor da ação: quem abre isto é o cliente,
                * no celular. Sem nome, o toque diz o que falta e leva ao campo. */}
              <BotaoProcesso
                variante="primario"
                bloco
                className="mt-5"
                classeBotao="text-base"
                style={{ minHeight: 52 }}
                onClick={entrar}
                processando={entrando}
                textoProcessando="Abrindo…"
                pendencia={nome.trim() ? null : "Digite seu nome acima para entrar."}
                pendenciaAoClicar
                onPendencia={() => document.getElementById("nome-na-chamada")?.focus()}
              >
                Entrar na chamada
              </BotaoProcesso>
              <p className="mt-4 mb-0 text-[11.5px] leading-[1.6] font-ui text-tinta-3">
                Ao entrar, a conversa é transcrita pelo escritório para virar o registro do
                seu atendimento.
              </p>
              <div className="mt-4 rounded-campo border border-acao-borda bg-acao-clara px-3 py-3 text-[12px] leading-[1.55] text-tinta-2">
                <strong className="block text-tinta">No celular</strong>
                Se usar fone Bluetooth, conecte-o antes de entrar. Quando o navegador perguntar,
                permita o microfone. A tela fica acesa durante a chamada; se ela apagar, chegar
                uma ligação ou você trocar de aplicativo, volte a esta tela que o microfone
                é retomado sozinho.
              </div>
            </>
          ) : (
            <>
              <p
                className={
                  chamada.estado === "falando"
                    ? "m-0 text-[16px] font-medium leading-[1.5] font-ui text-ok"
                    : "m-0 text-[15px] font-medium leading-[1.5] font-ui text-atencao"
                }
                aria-live="polite"
              >
                {situacao[chamada.estado]}
              </p>

              {/* A prova de que a voz está saindo — e o conserto ao alcance da
                  mão quando não está. Sem isto o cliente idoso só descobre que
                  está mudo quando o escritório consegue avisá-lo por outro meio. */}
              <IndicadorVoz
                trilha={chamada.faixaLocal}
                titulo="Sua voz"
                mudo={chamada.mudo}
                acaoSilencio={
                  <button type="button" className={SECUNDARIO} onClick={() => void chamada.reativarAudio()}>
                    Religar meu microfone
                  </button>
                }
              />

              <Retratos participantes={chamada.participantes} tamanho="grande" />

              <div className="flex gap-[10px] mt-5 flex-wrap">
                <button type="button" className={SECUNDARIO} onClick={() => void chamada.alternarCamera()}>
                  {chamada.temCamera ? "Desligar câmera" : "Ligar câmera"}
                </button>
                {chamada.telaDisponivel && (
                  <button type="button" className={SECUNDARIO} onClick={() => void chamada.alternarTela()}>
                    {chamada.compartilhandoTela ? "Parar de mostrar a tela" : "Mostrar minha tela"}
                  </button>
                )}
                <button type="button" className={SECUNDARIO} onClick={chamada.alternarMudo}>
                  {chamada.mudo ? "Voltar a falar" : "Desligar meu microfone"}
                </button>
                {/* As mensagens de falha do microfone mandavam usar "Reativar
                    áudio", botão que só existia no painel do escritório. Quem
                    precisa dele é justamente quem está deste lado. */}
                <button type="button" className={SECUNDARIO} onClick={() => void chamada.reativarAudio()}>
                  Reativar áudio
                </button>
                <button type="button" className={SECUNDARIO} onClick={chamada.desligar}>
                  Sair da chamada
                </button>
              </div>

              <p className="mt-4 mb-0 text-[11.5px] leading-[1.6] font-ui text-tinta-3">
                A conversa está sendo transcrita. Mantenha esta página aberta; se precisar de
                um instante reservado, desligue o microfone.
              </p>
            </>
          )}

          {(erro || chamada.erro) && (
            <div className="mt-4 border-[1.5px] border-critico text-critico p-3 text-[12.5px] leading-[1.5] font-ui">
              {erro ?? chamada.erro}
            </div>
          )}
        </div>

        <p className="mt-5 text-[11.5px] leading-[1.6] font-ui text-tinta-3">
          Se não ouvir ou não for ouvido, toque uma vez na tela, confira o ícone de volume e
          avise o escritório. Algumas redes de celular precisam do relay seguro da chamada.
        </p>
      </div>
    </div>
  );
}
