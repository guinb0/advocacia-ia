"use client";

import { use, useEffect, useRef, useState } from "react";

import { ChamadaJitsi } from "@/lib/chamadaJitsi";
import type { EstadoChamada, Participante } from "@/lib/chamadaJitsi";
import Retratos from "@/components/Retratos";
import estilos from "./chamada.module.css";

/* A chamada do lado de quem é entrevistado.
 *
 * Página deliberadamente pobre: um botão. Quem abre isto é o cliente, no
 * celular, no meio de um dia ruim — não há login, não há senha, não há
 * instalação. O que protege a sala é o link, sorteado com 128 bits.
 *
 * A voz sobe pelo Jitsi e chega ao navegador do advogado numa faixa própria —
 * é ela que alimenta a transcrição do outro lado. Está escrito na tela: gravar a conversa de alguém
 * sem dizer não é coisa que se faça, ainda mais num escritório que promete
 * sigilo no acolhimento. */

export default function PaginaChamada({ params }: { params: Promise<{ sala: string }> }) {
  const { sala } = use(params);

  const [estado, setEstado] = useState<EstadoChamada>("fora");
  const [entrando, setEntrando] = useState(false);
  const [mudo, setMudo] = useState(false);
  const [camera, setCamera] = useState(false);
  /* Sem login: o nome é o que a pessoa digitar. Serve para o advogado saber
   * quem entrou — numa sala com link solto, "Convidado" não diz nada. */
  const [nome, setNome] = useState("");
  const [participantes, setParticipantes] = useState<Participante[]>([]);
  const [erro, setErro] = useState<string | null>(null);

  const chamada = useRef<ChamadaJitsi | null>(null);
  if (chamada.current === null && typeof window !== "undefined") {
    chamada.current = new ChamadaJitsi("cliente", {
      onEstado: setEstado,
      onParticipantes: setParticipantes,
      onErro: setErro,
    });
  }

  // Fechar a aba sem soltar deixaria o microfone aceso e a sala ocupada.
  useEffect(() => () => chamada.current?.desligar(), []);

  async function entrar() {
    setErro(null);
    setEntrando(true);
    try {
      await chamada.current?.entrar(sala, { nome: nome.trim(), camera });
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
    <div className={estilos.tela}>
      <div className={estilos.centro}>
        <span className={estilos.marca}>ACERVO</span>
        <div className={estilos.filete} />

        <div className={estilos.cartao}>
          <h1 className={estilos.titulo}>Conversa com o escritório</h1>

          {!naChamada ? (
            <>
              <p className={estilos.texto}>
                Diga como quer ser chamado e toque no botão. É pelo próprio navegador — não
                precisa instalar nada, criar conta nem informar o seu número.
              </p>

              <label className={estilos.rotuloCampo} htmlFor="nome-na-chamada">
                Seu nome
              </label>
              <input
                id="nome-na-chamada"
                className={estilos.campoNome}
                value={nome}
                onChange={(e) => setNome(e.target.value)}
                placeholder="Como o escritório deve te chamar"
                autoComplete="name"
                maxLength={40}
              />

              <label className={estilos.opcaoCamera}>
                <input
                  type="checkbox"
                  checked={camera}
                  onChange={(e) => setCamera(e.target.checked)}
                />
                Entrar com a câmera ligada
              </label>

              <button
                type="button"
                className={estilos.botao}
                onClick={entrar}
                disabled={entrando || !nome.trim()}
              >
                {entrando ? "Abrindo…" : "Entrar na chamada"}
              </button>
              <p className={estilos.nota}>
                Ao entrar, a conversa é transcrita pelo escritório para virar o registro do
                seu atendimento.
              </p>
            </>
          ) : (
            <>
              <p
                className={estado === "falando" ? estilos.ativo : estilos.esperando}
                aria-live="polite"
              >
                {situacao[estado]}
              </p>

              <Retratos participantes={participantes} tamanho="grande" />

              <div className={estilos.acoes}>
                <button
                  type="button"
                  className={estilos.secundario}
                  onClick={async () => setCamera(await (chamada.current?.alternarCamera() ?? false))}
                >
                  {camera ? "Desligar câmera" : "Ligar câmera"}
                </button>
                <button
                  type="button"
                  className={estilos.secundario}
                  onClick={() => setMudo(chamada.current?.alternarMudo() ?? false)}
                >
                  {mudo ? "Voltar a falar" : "Desligar meu microfone"}
                </button>
                <button
                  type="button"
                  className={estilos.secundario}
                  onClick={() => {
                    chamada.current?.desligar();
                    setMudo(false);
                  }}
                >
                  Sair da chamada
                </button>
              </div>

              <p className={estilos.nota}>
                A conversa está sendo transcrita. Se precisar de um instante reservado,
                desligue o microfone.
              </p>
            </>
          )}

          {erro && <div className={estilos.erro}>{erro}</div>}
        </div>

        <p className={estilos.rodape}>
          Se a chamada não conectar, avise o escritório: em algumas redes de celular a
          ligação direta entre navegadores não passa.
        </p>
      </div>
    </div>
  );
}
