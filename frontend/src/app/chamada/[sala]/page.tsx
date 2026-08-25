"use client";

import { use, useEffect, useState } from "react";

import { criarSalaChamada } from "@/lib/api";
import { useChamada } from "@/lib/ChamadaContexto";
import type { EstadoChamada } from "@/lib/chamadaJitsi";
import Retratos from "@/components/ui/Retratos";

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

const BOTAO =
  "mt-5 w-full p-4 border-[1.5px] border-tinta bg-transparent text-tinta text-[13px] font-semibold leading-none " +
  "font-ui tracking-[0.14em] uppercase cursor-pointer disabled:opacity-[0.45] disabled:cursor-default " +
  "enabled:hover:bg-tinta enabled:hover:text-papel";
const SECUNDARIO =
  "flex-1 min-w-[150px] border border-borda-forte bg-transparent text-tinta text-[11px] font-semibold leading-none " +
  "font-ui tracking-[0.08em] uppercase px-3 py-[13px] cursor-pointer hover:bg-papel-2";

export default function PaginaChamada({ params }: { params: Promise<{ sala: string }> }) {
  const { sala } = use(params);
  const chamada = useChamada();

  const [entrando, setEntrando] = useState(false);
  const [camera, setCamera] = useState(false);
  /* Sem login: o nome é o que a pessoa digitar. Serve para o advogado saber
   * quem entrou — numa sala com link solto, "Convidado" não diz nada. */
  const [nome, setNome] = useState("");
  const [erro, setErro] = useState<string | null>(null);

  // Esta página é a própria chamada: enquanto está aberta, o painel flutuante
  // se recolhe. `registrarPainel` é estável, então roda uma vez.
  useEffect(() => chamada.registrarPainel(), [chamada.registrarPainel]);

  async function entrar() {
    setErro(null);
    setEntrando(true);
    try {
      const { token: jitsiToken } = await criarSalaChamada(sala);
      await chamada.entrar(sala, "cliente", { nome: nome.trim(), camera }, jitsiToken);
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
    <div className="min-h-screen bg-papel px-4 pt-6 pb-12 flex items-center">
      <div className="w-[min(820px,100%)] mx-auto">
        <span className="font-bold text-[14px] leading-none font-titulo tracking-[0.02em]">ACERVO</span>
        <div className="mt-3 mb-[22px] border-t-[3px] border-double border-borda-forte" />

        <div className="border border-borda-forte p-[26px]">
          <h1 className="mb-[10px] mt-0 font-semibold text-[24px] leading-[1.15] font-titulo">
            Conversa com o escritório
          </h1>

          {!naChamada ? (
            <>
              <p className="m-0 text-[13.5px] leading-[1.6] font-ui text-tinta-3">
                Diga como quer ser chamado e toque no botão. É pelo próprio navegador — não
                precisa instalar nada, criar conta nem informar o seu número.
              </p>

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

              <button type="button" className={BOTAO} onClick={entrar} disabled={entrando || !nome.trim()}>
                {entrando ? "Abrindo…" : "Entrar na chamada"}
              </button>
              <p className="mt-4 mb-0 text-[11.5px] leading-[1.6] font-ui text-tinta-3">
                Ao entrar, a conversa é transcrita pelo escritório para virar o registro do
                seu atendimento.
              </p>
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

              <Retratos participantes={chamada.participantes} tamanho="grande" />

              <div className="flex gap-[10px] mt-5 flex-wrap">
                <button type="button" className={SECUNDARIO} onClick={() => void chamada.alternarCamera()}>
                  {chamada.temCamera ? "Desligar câmera" : "Ligar câmera"}
                </button>
                <button type="button" className={SECUNDARIO} onClick={chamada.alternarMudo}>
                  {chamada.mudo ? "Voltar a falar" : "Desligar meu microfone"}
                </button>
                <button type="button" className={SECUNDARIO} onClick={chamada.desligar}>
                  Sair da chamada
                </button>
              </div>

              <p className="mt-4 mb-0 text-[11.5px] leading-[1.6] font-ui text-tinta-3">
                A conversa está sendo transcrita. Se precisar de um instante reservado,
                desligue o microfone.
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
          Se a chamada não conectar, avise o escritório: em algumas redes de celular a
          ligação direta entre navegadores não passa.
        </p>
      </div>
    </div>
  );
}
