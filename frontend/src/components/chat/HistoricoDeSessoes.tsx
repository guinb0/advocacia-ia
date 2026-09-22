"use client";

/* A barra lateral do chat: as conversas de quem entrou, e só as dele.
 *
 * SÃO OITO, E A TELA DIZ ISSO
 *
 * O teto é regra do produto (`armazenamento.TETO_DE_SESSOES`) e está escrito no rodapé
 * antes de doer: "7 de 8 — a próxima empurra a mais antiga". Descobrir o limite pelo
 * sumiço de uma conversa é a pior forma de aprendê-lo, porque o que saiu não volta.
 *
 * Agrupadas por dia porque é assim que se procura uma conversa: "aquela de ontem". Uma
 * lista corrida de oito títulos parecidos obriga a ler todos. */

import { Trash2 } from "lucide-react";

import { Botao } from "@/components/ui/Basicos";
import estilos from "@/components/chat/Chat.module.css";
import type { ResumoDeSessao } from "@/lib/chat";

interface Props {
  sessoes: ResumoDeSessao[];
  teto: number;
  abertaId: string | null;
  aConfirmar: string | null;
  onAbrir: (id: string) => void;
  onNova: () => void;
  onPedirExclusao: (id: string | null) => void;
  onApagar: (id: string) => void;
}

/** Hoje, ontem, últimos 7 dias, antes. Vazios não aparecem. */
function agrupar(sessoes: ResumoDeSessao[]) {
  const dia = 24 * 60 * 60 * 1000;
  const inicioDeHoje = new Date().setHours(0, 0, 0, 0);
  const grupos: { titulo: string; sessoes: ResumoDeSessao[] }[] = [
    { titulo: "Hoje", sessoes: [] },
    { titulo: "Ontem", sessoes: [] },
    { titulo: "Últimos 7 dias", sessoes: [] },
    { titulo: "Antes", sessoes: [] },
  ];

  for (const sessao of sessoes) {
    const quando = new Date(sessao.atualizadoEm).getTime();
    if (Number.isNaN(quando)) grupos[3].sessoes.push(sessao);
    else if (quando >= inicioDeHoje) grupos[0].sessoes.push(sessao);
    else if (quando >= inicioDeHoje - dia) grupos[1].sessoes.push(sessao);
    else if (quando >= inicioDeHoje - 7 * dia) grupos[2].sessoes.push(sessao);
    else grupos[3].sessoes.push(sessao);
  }
  return grupos.filter((grupo) => grupo.sessoes.length > 0);
}

/** Hora para o que é de hoje, data para o resto. O servidor manda UTC justamente para a
 *  conversão acontecer aqui, onde se sabe o fuso de quem lê. */
function horaOuData(iso: string): string {
  const quando = new Date(iso);
  if (Number.isNaN(quando.getTime())) return "";
  const hoje = new Date().setHours(0, 0, 0, 0);
  return quando.getTime() >= hoje
    ? quando.toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" })
    : quando.toLocaleDateString("pt-BR", { day: "2-digit", month: "2-digit" });
}

export default function HistoricoDeSessoes({
  sessoes,
  teto,
  abertaId,
  aConfirmar,
  onAbrir,
  onNova,
  onPedirExclusao,
  onApagar,
}: Props) {
  const grupos = agrupar(sessoes);
  const cheio = sessoes.length >= teto;

  return (
    <>
      <div className={estilos.blocoDoTopo}>
        <span className={estilos.tituloDoHistorico}>Conversas</span>
        <Botao variante="primario" bloco onClick={onNova}>
          Nova conversa
        </Botao>
      </div>

      <div className={estilos.lista}>
        {sessoes.length === 0 && (
          <p className={estilos.vazioDoHistorico}>
            Nenhuma conversa ainda. Pergunte qualquer coisa: sobre um caso, sobre o
            escritório, sobre a lei.
          </p>
        )}

        {grupos.map((grupo) => (
          <div key={grupo.titulo}>
            <div className={estilos.tituloDoHistorico} style={{ padding: "10px 6px 5px" }}>
              {grupo.titulo}
            </div>
            {grupo.sessoes.map((sessao) => {
              const aberta = sessao.id === abertaId;
              if (aConfirmar === sessao.id) {
                return (
                  <div
                    key={sessao.id}
                    className={`${estilos.item} ${estilos.itemAConfirmar}`}
                  >
                    <span className={estilos.perguntaDeExclusao}>
                      Apagar esta conversa? Ela não volta.
                    </span>
                    <div className={estilos.acoesDaExclusao}>
                      <Botao variante="perigo" pequeno onClick={() => onApagar(sessao.id)}>
                        Apagar
                      </Botao>
                      <Botao variante="texto" pequeno onClick={() => onPedirExclusao(null)}>
                        Cancelar
                      </Botao>
                    </div>
                  </div>
                );
              }
              return (
                <div
                  key={sessao.id}
                  className={`${estilos.item} ${aberta ? estilos.itemAberto : ""}`}
                >
                  <button
                    type="button"
                    className={estilos.abrirItem}
                    onClick={() => onAbrir(sessao.id)}
                    aria-current={aberta || undefined}
                  >
                    <span className={estilos.tituloDoItem}>{sessao.titulo}</span>
                    <span className={estilos.contextoDoItem}>
                      <span>{horaOuData(sessao.atualizadoEm)}</span>
                      {sessao.resumo && <span>· {sessao.resumo}</span>}
                    </span>
                  </button>
                  <button
                    type="button"
                    className={estilos.apagarItem}
                    aria-label={`Apagar a conversa ${sessao.titulo}`}
                    onClick={() => onPedirExclusao(sessao.id)}
                  >
                    <Trash2 size={15} aria-hidden />
                  </button>
                </div>
              );
            })}
          </div>
        ))}
      </div>

      <div className={estilos.rodapeDoHistorico}>
        {sessoes.length} de {teto} conversas guardadas.
        {cheio
          ? " A próxima apaga a mais antiga — é o limite por pessoa."
          : " Cada pessoa mantém as últimas oito."}
      </div>
    </>
  );
}
