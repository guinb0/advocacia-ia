"use client";

import { FormEvent, useEffect, useRef, useState } from "react";
import { MessageSquare, Send } from "lucide-react";

import { useChamada } from "@/lib/ChamadaContexto";

export default function ChatChamada() {
  const chamada = useChamada();
  const [texto, setTexto] = useState("");
  const fim = useRef<HTMLDivElement>(null);

  useEffect(() => fim.current?.scrollIntoView({ behavior: "smooth" }), [chamada.mensagens]);

  function enviar(evento: FormEvent) {
    evento.preventDefault();
    const mensagem = texto.trim();
    if (!mensagem) return;
    chamada.enviarMensagem(mensagem);
    setTexto("");
  }

  if (chamada.estado === "fora") return null;

  return (
    <section className="mt-4 overflow-hidden rounded-xl border border-borda-forte bg-papel" aria-label="Chat da chamada">
      <header className="flex items-center gap-2 border-b border-borda px-3 py-2.5 font-ui text-xs font-semibold text-tinta">
        <MessageSquare className="h-4 w-4" aria-hidden="true" />
        Chat da chamada
      </header>
      <div className="max-h-52 min-h-24 space-y-2 overflow-y-auto bg-papel-2 px-3 py-3" aria-live="polite">
        {chamada.mensagens.length === 0 ? (
          <p className="m-0 text-xs leading-relaxed text-tinta-3">
            Envie links, nomes e informações que precisam ficar escritas durante a conversa.
          </p>
        ) : (
          chamada.mensagens.map((mensagem) => (
            <div key={mensagem.id} className={`flex ${mensagem.minha ? "justify-end" : "justify-start"}`}>
              <div className={`max-w-[85%] rounded-xl px-3 py-2 font-ui text-sm ${mensagem.minha ? "bg-tinta text-papel" : "border border-borda bg-papel text-tinta"}`}>
                <span className={`mb-0.5 block text-[10px] font-semibold ${mensagem.minha ? "text-papel/70" : "text-tinta-3"}`}>
                  {mensagem.minha ? "Você" : mensagem.autor}
                </span>
                <p className="m-0 whitespace-pre-wrap break-words">{mensagem.texto}</p>
              </div>
            </div>
          ))
        )}
        <div ref={fim} />
      </div>
      <form onSubmit={enviar} className="flex gap-2 border-t border-borda p-2">
        <input
          value={texto}
          onChange={(evento) => setTexto(evento.target.value)}
          className="min-w-0 flex-1 rounded-lg border border-borda-forte bg-papel px-3 py-2 text-sm text-tinta outline-none focus:border-tinta"
          placeholder="Escreva uma mensagem"
          maxLength={2000}
          aria-label="Mensagem para o chat da chamada"
        />
        <button type="submit" disabled={!texto.trim()} className="inline-flex h-10 w-10 items-center justify-center rounded-lg bg-tinta text-papel disabled:cursor-not-allowed disabled:opacity-40" aria-label="Enviar mensagem">
          <Send className="h-4 w-4" aria-hidden="true" />
        </button>
      </form>
    </section>
  );
}
