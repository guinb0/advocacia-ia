/* A marca em um lugar só.
 *
 * Os três pontos que a desenhavam — barra lateral, coluna do formulário de
 * login e painel ilustrado — tinham cada um o seu selo, o seu ícone e a sua
 * legenda. Um deles usava uma balança, que contraria a regra de não usar
 * símbolo jurídico decorativo; os outros dois usavam o ícone genérico de
 * documento do lucide, que nunca foi marca, só um provisório que ficou.
 *
 * Trocar a identidade agora é mexer AQUI, e só aqui.
 *
 * `logo-forense-icone.png` é a cabeça da coruja recortada da arte original
 * (`logo-forense.png`), SEM a faixa "FORENSE" — a arte inteira apertada em
 * 44px vira ruído e ainda duplicaria o nome, que já é escrito ao lado em
 * texto. A versão completa fica reservada para onde houver espaço de verdade
 * (splash, e-mail, material impresso), fora do escopo desta troca.
 */

type Superficie = "navy" | "papel";

const SELO: Record<Superficie, string> = {
  navy: "bg-white/[0.10] text-marca-ouro ring-1 ring-white/[0.14]",
  papel: "border border-nav-borda bg-nav-fundo text-marca-ouro",
};

const NOME: Record<Superficie, string> = {
  navy: "text-nav-texto",
  papel: "text-tinta",
};

const LEGENDA: Record<Superficie, string> = {
  /* Tracking mais apertado aqui: a sidebar tem 248px de largura fixa, contra
   * o respiro do painel de login. Com o mesmo 0.15em do papel, "Escritório
   * jurídico" em versalete cortava em "ESCRITÓRIO JURÍDI…". */
  navy: "tracking-[0.04em] text-nav-texto-3",
  papel: "tracking-[0.15em] text-tinta-3",
};

export default function MarcaForense({
  superficie = "navy",
  legenda = "Escritório jurídico",
  className = "",
}: {
  superficie?: Superficie;
  /** A palavra sob o nome. O painel do login diz "Inteligência jurídica". */
  legenda?: string;
  className?: string;
}) {
  return (
    <div className={`flex min-w-0 items-center gap-3 ${className}`}>
      <span
        className={`inline-flex h-11 w-11 shrink-0 items-center justify-center overflow-hidden rounded-[14px] p-1 shadow-[0_8px_24px_rgba(0,0,0,0.14)] ${SELO[superficie]}`}
      >
        {/* eslint-disable-next-line @next/next/no-img-element -- ícone de 44px, sem benefício do otimizador */}
        <img
          src="/logo-forense-icone.png"
          alt=""
          className="h-full w-full object-contain"
        />
      </span>
      <div className="min-w-0">
        <span className={`block truncate font-titulo text-xl font-bold leading-none ${NOME[superficie]}`}>
          Forense
        </span>
        <span className={`mt-1 block truncate text-[11px] font-semibold uppercase ${LEGENDA[superficie]}`}>
          {legenda}
        </span>
      </div>
    </div>
  );
}
