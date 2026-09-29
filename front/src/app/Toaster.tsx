"use client";

import { Toaster as Sonner } from "sonner";

/* As mensagens de erro e confirmação da aplicação. Ficam no topo à direita e não
 * no rodapé porque a tela da entrevista já tem o painel da chamada flutuando na
 * base — um toast ali nasceria por baixo do vídeo. */
export default function Toaster() {
  return <Sonner position="top-right" richColors closeButton />;
}
