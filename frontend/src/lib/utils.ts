import { clsx } from "clsx";
import type { ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

/** Junta classes condicionais e resolve conflitos do Tailwind — o `cn` que os
 *  componentes shadcn esperam encontrar. Sem o `twMerge`, `"p-2"` e `"p-4"`
 *  vindos de lugares diferentes ficariam os dois na string e venceria quem
 *  aparecesse por último no CSS, não quem foi passado por último. */
export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}
