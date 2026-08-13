/* Conferência de documento digitado, na hora em que é digitado.
 *
 * Isto é uma cópia do módulo 11 que já existe em `app/validators.py`, e a cópia
 * é proposital: o campo do roteiro precisa avisar o erro ENQUANTO a entrevista
 * acontece, com o cliente ainda na linha para corrigir. Uma ida ao servidor a
 * cada tecla resolveria o mesmo problema com latência e mais peças.
 *
 * O backend continua sendo a autoridade — o CPF que sai do OCR de um documento
 * é conferido lá, por `validators.validar_cpf`. Se um dia as regras divergirem,
 * a do Python é a certa.
 *
 * O que o DV prova e o que não prova: um CPF que fecha no módulo 11 apenas foi
 * escrito sem erro de digitação. Ele pode nunca ter sido emitido, ou ser de
 * outra pessoa. Quem confere existência e titularidade é a Receita.
 */

export function apenasDigitos(valor: string): string {
  return (valor || "").replace(/\D/g, "");
}

/** Os dois dígitos verificadores do CPF (módulo 11). */
export function validarCpf(cpf: string): boolean {
  const d = apenasDigitos(cpf);
  // 111.111.111-11 e os outros repetidos passam no módulo 11 por acidente
  // aritmético — são rejeitados à mão, como no validador do backend.
  if (d.length !== 11 || new Set(d).size === 1) return false;

  for (const pos of [9, 10]) {
    let soma = 0;
    for (let i = 0; i < pos; i += 1) soma += Number(d[i]) * (pos + 1 - i);
    const dv = ((soma * 10) % 11) % 10;
    if (dv !== Number(d[pos])) return false;
  }
  return true;
}

/** Máscara progressiva: aplica o que já dá, sem esperar os 11 dígitos. */
export function formatarCpf(cpf: string): string {
  const d = apenasDigitos(cpf).slice(0, 11);
  if (d.length <= 3) return d;
  if (d.length <= 6) return `${d.slice(0, 3)}.${d.slice(3)}`;
  if (d.length <= 9) return `${d.slice(0, 3)}.${d.slice(3, 6)}.${d.slice(6)}`;
  return `${d.slice(0, 3)}.${d.slice(3, 6)}.${d.slice(6, 9)}-${d.slice(9)}`;
}

/** Máscara progressiva do CEP: 00000-000. */
export function formatarCep(cep: string): string {
  const d = apenasDigitos(cep).slice(0, 8);
  return d.length <= 5 ? d : `${d.slice(0, 5)}-${d.slice(5)}`;
}

export interface Conferencia {
  /** `null` enquanto o campo está vazio ou incompleto: ainda não há veredito. */
  valido: boolean | null;
  mensagem: string;
}

/** O veredito exibido sob o campo, já em português de tela. */
export function conferirCpf(valor: string): Conferencia {
  const d = apenasDigitos(valor);
  if (d.length === 0) return { valido: null, mensagem: "" };
  if (d.length < 11) {
    // Durante a digitação, "faltam 4 dígitos" é informação; "CPF inválido"
    // seria só um alarme falso que o entrevistador aprenderia a ignorar.
    const faltam = 11 - d.length;
    return { valido: null, mensagem: `faltam ${faltam} dígito${faltam > 1 ? "s" : ""}` };
  }
  return validarCpf(d)
    ? { valido: true, mensagem: "CPF confere" }
    : { valido: false, mensagem: "CPF não confere — verifique os números com o cliente" };
}
