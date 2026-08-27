import type { ReactNode } from "react";

import { corDoScore, leituraDoScore, SELO_TOM, type TomSelo } from "@/lib/formato";

/* Primitivos do sistema visual (ver docs/GUIA-VISUAL.md), em Tailwind.
 *
 * Migrados de classes globais (`app/globals.css` + `components/ui.module.css`)
 * para componentes React: a cor/fonte/raio continuam vindo de UM lugar só
 * (os tokens em `globals.css`, apontados pelo bloco `@theme inline`) — o que
 * muda aqui é só o mecanismo de aplicar a regra, não onde a regra é definida.
 * Cada variante é uma constante de classes definida uma vez nesta função;
 * mudar a REGRA (ex.: "botão primário ganha sombra no hover") edita aqui,
 * mudar a COR edita em globals.css — a mesma divisão de responsabilidade que
 * já existia entre globals.css e Basicos.tsx antes desta migração.
 *
 * `.botao`/`.campo`/`.cartao`/`.selo`/`.aviso` globais em globals.css
 * continuam existindo por enquanto: outros arquivos ainda não convertidos os
 * referenciam por className literal. Só saem de globals.css quando o último
 * arquivo que os usa diretamente também for convertido (ver o plano de
 * migração). Esta é a implementação NOVA, consumida por quem já migrou. */

/** Junta classes condicionais, descartando falsy — sem dependência nova. */
function cn(...classes: (string | false | null | undefined)[]): string {
  return classes.filter(Boolean).join(" ");
}

/* ------------------------------------------------------------- botão -- */

type BotaoVariante = "primario" | "secundario" | "discreto" | "perigo" | "texto";

const BASE_BOTAO =
  "inline-flex items-center justify-center gap-2 border border-transparent " +
  "rounded-campo bg-transparent font-ui text-sm font-semibold leading-tight " +
  "text-center no-underline cursor-pointer transition-[background-color,border-color,color] " +
  "duration-[120ms] ease-out disabled:cursor-not-allowed";

/* Ação principal: preenchimento sólido — é o que faz o olho achá-la sem
 * procurar. Só uma por bloco (ver GUIA-VISUAL.md). */
const VARIANTE_BOTAO: Record<BotaoVariante, string> = {
  primario:
    "bg-acao border-acao text-white " +
    "enabled:hover:bg-acao-forte enabled:hover:border-acao-forte " +
    "enabled:focus-visible:bg-acao-forte enabled:focus-visible:border-acao-forte " +
    "disabled:border-borda-forte disabled:bg-papel-3 disabled:text-tinta-desabilitada",
  secundario:
    "border-borda-campo bg-papel text-acao " +
    "enabled:hover:bg-acao-clara enabled:hover:border-acao " +
    "disabled:border-borda disabled:bg-papel-2 disabled:text-tinta-desabilitada",
  discreto: "text-tinta-2 enabled:hover:bg-papel-3 enabled:hover:text-tinta disabled:text-tinta-desabilitada",
  /* Destrutiva: única variante em que cor de estado também é cor de ação —
   * de propósito, para pedir hesitação antes de excluir. */
  perigo:
    "border-critico-borda text-critico bg-papel " +
    "enabled:hover:bg-critico-claro enabled:hover:border-critico " +
    "disabled:border-borda disabled:bg-papel-2 disabled:text-tinta-desabilitada",
  /* Link-como-botão (voltar, "ver mais"): sem altura mínima nem padding de
   * botão de verdade. Nunca ganha as classes de tamanho da base (ver
   * `variante !== "texto"` abaixo), então não há conflito a resolver com
   * `!important`. */
  texto:
    "min-h-0 px-0 py-[2px] text-acao underline underline-offset-[3px] " +
    "enabled:hover:text-acao-forte disabled:text-tinta-desabilitada",
};

interface BotaoProps extends React.ComponentPropsWithoutRef<"button"> {
  variante?: BotaoVariante;
  /** Botão dentro de linha de lista. */
  pequeno?: boolean;
  /** 100% da largura do contêiner. */
  bloco?: boolean;
}

export function Botao({
  variante = "secundario",
  pequeno,
  bloco,
  className,
  ...props
}: BotaoProps) {
  return (
    <button
      className={cn(
        BASE_BOTAO,
        variante !== "texto" && (pequeno ? "min-h-8 px-[11px] py-[6px] text-xs gap-[6px]" : "min-h-10 px-4 py-[9px]"),
        VARIANTE_BOTAO[variante],
        bloco && "w-full",
        className,
      )}
      {...props}
    />
  );
}

/** Mesma aparência do botão, mas para link/download — `<a>` não aceita `disabled`. */
interface LinkBotaoProps extends React.ComponentPropsWithoutRef<"a"> {
  variante?: BotaoVariante;
  pequeno?: boolean;
  bloco?: boolean;
  /** Estilo "desabilitado"; o próprio consumidor decide se ainda navega. */
  desabilitado?: boolean;
}

export function LinkBotao({
  variante = "secundario",
  pequeno,
  bloco,
  desabilitado,
  className,
  ...props
}: LinkBotaoProps) {
  return (
    <a
      className={cn(
        BASE_BOTAO,
        variante !== "texto" && (pequeno ? "min-h-8 px-[11px] py-[6px] text-xs gap-[6px]" : "min-h-10 px-4 py-[9px]"),
        VARIANTE_BOTAO[variante],
        bloco && "w-full",
        desabilitado && "cursor-not-allowed border-borda bg-papel-2 text-tinta-desabilitada",
        className,
      )}
      aria-disabled={desabilitado || undefined}
      {...props}
    />
  );
}

/* -------------------------------------------------------------- abas -- */

const BASE_ABA =
  "flex-none min-h-[34px] px-[13px] py-[6px] border border-transparent rounded-[6px] bg-transparent " +
  "text-sm font-semibold whitespace-nowrap cursor-pointer transition-[background-color,color] duration-[120ms] ease-out";
const ABA_INATIVA = "text-tinta-2 hover:bg-papel-3 hover:text-tinta";
const ABA_ATIVA = "bg-papel border-acao-borda text-acao shadow-cartao";

/** Contêiner de abas (filtro ou de resultado) — só o wrapper, `role="tablist"`. */
export function BarraAbas({ className, ...props }: React.ComponentPropsWithoutRef<"div">) {
  return (
    <div
      className={cn(
        "flex gap-[6px] p-1 border border-borda rounded-campo bg-papel-2 overflow-x-auto",
        className,
      )}
      role="tablist"
      {...props}
    />
  );
}

/** Botão de uma aba — `ativa` decide o estilo, sem depender de `:hover` disputar com o ativo. */
export function BotaoAba({
  ativa,
  className,
  ...props
}: React.ComponentPropsWithoutRef<"button"> & { ativa: boolean }) {
  return (
    <button
      type="button"
      role="tab"
      aria-selected={ativa}
      className={cn(BASE_ABA, ativa ? ABA_ATIVA : ABA_INATIVA, className)}
      {...props}
    />
  );
}

/* ------------------------------------------------------------- campo -- */

interface CampoProps extends React.ComponentPropsWithoutRef<"input"> {
  area?: false;
}
interface CampoAreaProps extends React.ComponentPropsWithoutRef<"textarea"> {
  area: true;
}

const BASE_CAMPO =
  "w-full min-h-[42px] px-3 py-[10px] border border-borda-campo rounded-campo " +
  "bg-papel text-tinta text-base transition-[border-color,box-shadow] duration-[120ms] ease-out " +
  "enabled:hover:border-acao focus:border-acao focus:shadow-[0_0_0_3px_var(--acao-clara)] focus:outline-none";

/** Campo de texto — use `area` para textarea. Rótulo visível vai em `<RotuloCampo>`. */
export function Campo({ area, className, ...props }: CampoProps | CampoAreaProps) {
  if (area) {
    const { area: _a, ...resto } = props as CampoAreaProps;
    return (
      <textarea
        className={cn(BASE_CAMPO, "min-h-[120px] leading-[1.6] resize-y", className)}
        {...resto}
      />
    );
  }
  const { area: _a, ...resto } = props as CampoProps;
  return <input className={cn(BASE_CAMPO, className)} {...resto} />;
}

/** Select nativo com seta desenhada em SVG — `appearance:none` remove a nativa. */
export function CampoSeletor({
  className,
  ...props
}: React.ComponentPropsWithoutRef<"select">) {
  return (
    <select
      /* As `option` precisam de cor e fundo PRÓPRIOS, e não herdados. No Windows,
       * a lista aberta de um select sem eles pega as cores do sistema e vira uma
       * faixa preta sem texto legível — o `BASE_CAMPO` acima veste a caixa
       * fechada, não a lista que o sistema operacional desenha por cima. */
      className={cn(
        BASE_CAMPO,
        "appearance-none pr-[38px] cursor-pointer bg-no-repeat",
        "[&>option]:bg-papel [&>option]:text-tinta",
        className,
      )}
      style={{
        backgroundImage:
          "url(\"data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='16' height='16' viewBox='0 0 16 16' fill='none' stroke='%2333465c' stroke-width='1.8' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpath d='m4 6 4 4 4-4'/%3E%3C/svg%3E\")",
        backgroundPosition: "right 12px center",
      }}
      {...props}
    />
  );
}

export function RotuloCampo({
  className,
  ...props
}: React.ComponentPropsWithoutRef<"label">) {
  return (
    <label
      className={cn("block mb-[6px] text-tinta text-sm font-semibold", className)}
      {...props}
    />
  );
}

export function AjudaCampo({ className, ...props }: React.ComponentPropsWithoutRef<"p">) {
  return <p className={cn("mt-[6px] text-tinta-3 text-xs leading-[1.5]", className)} {...props} />;
}

/* Caixa de marcação com área de clique de linha inteira. */
export function Marcacao({ className, ...props }: React.ComponentPropsWithoutRef<"label">) {
  return (
    <label
      className={cn(
        "flex items-start gap-[9px] py-[7px] text-tinta-2 text-sm leading-[1.5] cursor-pointer " +
          "[&_input[type=checkbox]]:flex-none [&_input[type=checkbox]]:w-[18px] [&_input[type=checkbox]]:h-[18px] " +
          "[&_input[type=checkbox]]:mt-[1px] [&_input[type=checkbox]]:accent-acao [&_input[type=checkbox]]:cursor-pointer",
        className,
      )}
      {...props}
    />
  );
}

/* ------------------------------------------------------------- tabela -- */

/** Tabela de campos/dados — usada pelas abas de resultado do documento. */
export function Tabela({ className, ...props }: React.ComponentPropsWithoutRef<"table">) {
  return <table className={cn("w-full border-collapse text-sm", className)} {...props} />;
}

export function Th({ className, ...props }: React.ComponentPropsWithoutRef<"th">) {
  return (
    <th
      className={cn(
        "px-3 py-[10px] border-b border-borda-forte bg-papel-2 text-tinta-2 text-xs font-bold text-left " +
          "first:rounded-tl-campo last:rounded-tr-campo",
        className,
      )}
      {...props}
    />
  );
}

const BASE_TD = "px-3 py-[11px] border-b border-borda align-top";

export function Td({ className, ...props }: React.ComponentPropsWithoutRef<"td">) {
  return <td className={cn(BASE_TD, "text-tinta-2 [&_strong]:text-tinta", className)} {...props} />;
}

/** Linha de corpo de tabela: zebra nas pares, sem filete na última linha. */
export function TrZebra({ className, ...props }: React.ComponentPropsWithoutRef<"tr">) {
  return <tr className={cn("even:bg-papel-2 last:[&>td]:border-b-0", className)} {...props} />;
}

/** Valor em fonte monoespaçada — número, data, código. Não usa <Td>: a cor
 * própria (`text-tinta`) conflitaria com a cor-base de <Td> (`text-tinta-2`)
 * como duas classes concorrendo pela mesma propriedade — o Tailwind não
 * garante que a última no JSX vença no CSS gerado. */
export function ValorTabela({ className, ...props }: React.ComponentPropsWithoutRef<"td">) {
  return (
    <td
      className={cn(BASE_TD, "font-codigo tabular-nums text-sm text-tinta [word-break:break-word]", className)}
      {...props}
    />
  );
}

export function ObservacaoTabela({ className, ...props }: React.ComponentPropsWithoutRef<"div">) {
  return <div className={cn("mt-1 text-tinta-3 text-xs leading-[1.5]", className)} {...props} />;
}

/* ------------------------------------------------------------- cartão -- */

interface CartaoProps extends React.ComponentPropsWithoutRef<"div"> {
  titulo?: ReactNode;
  subtitulo?: ReactNode;
}

/** Cartão branco com sombra discreta — o contêiner mais usado do sistema. */
export function Cartao({ titulo, subtitulo, className, children, ...props }: CartaoProps) {
  return (
    <div
      className={cn("border border-borda-forte rounded-cartao bg-papel shadow-cartao p-5", className)}
      {...props}
    >
      {titulo && <h2 className="mb-1 text-tinta font-titulo text-lg font-semibold leading-[1.25]">{titulo}</h2>}
      {subtitulo && <p className="mb-4 text-tinta-3 text-sm leading-[1.5]">{subtitulo}</p>}
      {children}
    </div>
  );
}

export function TituloSecao({ className, ...props }: React.ComponentPropsWithoutRef<"div">) {
  return (
    <div className={cn("text-tinta text-sm font-bold tracking-[0.01em]", className)} {...props} />
  );
}

/* ------------------------------------------------------------- estado -- */

/** Barra fina de progresso/score — a cor entra por `estilo`, não por classe. */
export function Barra({ score }: { score: number }) {
  const leitura = leituraDoScore(score);

  return (
    <div
      className="h-[6px] mt-2 rounded-pill bg-papel-3 overflow-hidden"
      title={`${score}% — ${leitura.texto}`}
    >
      <i
        className="block h-full rounded-pill"
        style={{ width: `${Math.max(0, Math.min(100, score))}%`, background: corDoScore(score) }}
      />
    </div>
  );
}

export function Stat({
  chave,
  valor,
  score,
  titulo,
}: {
  chave: string;
  valor: string;
  /** Quando informado, desenha a barrinha colorida abaixo do número. */
  score?: number | null;
  titulo?: string;
}) {
  const temScore = score !== null && score !== undefined;

  return (
    <div className="p-3 px-[14px] border border-borda rounded-campo bg-papel-2" title={titulo}>
      <div className="text-tinta-3 text-xs font-semibold">{chave}</div>
      <div className="mt-[3px] text-tinta font-titulo text-lg font-semibold tabular-nums leading-[1.15]">
        {valor}
      </div>
      {temScore && (
        <>
          <Barra score={score} />
          {/* A barra é decoração; a leitura em palavra é o que sobra para quem
              usa leitor de tela ou não distingue as cores. */}
          <div className="mt-[4px] text-tinta-3 text-xs leading-[1.5]">{leituraDoScore(score).texto}</div>
        </>
      )}
    </div>
  );
}

const CLASSE_SELO: Record<TomSelo, string> = {
  critico: "border-critico-borda bg-critico-claro text-critico",
  atencao: "border-atencao-borda bg-atencao-claro text-atencao",
  ok: "border-ok-borda bg-ok-claro text-ok",
  info: "border-acao-borda bg-acao-clara text-acao",
  neutro: "border-borda-forte bg-papel-2 text-tinta-2",
};

/** Selo de estado: pílula com símbolo + palavra — nunca cor sozinha. */
export function Selo({
  tom,
  simbolo,
  children,
}: {
  tom: TomSelo;
  /** Símbolo antes da palavra. Omitir só quando o texto já for um número. */
  simbolo?: string;
  children: ReactNode;
}) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-[5px] px-[10px] py-[3px] border rounded-pill text-xs font-semibold leading-[1.45] whitespace-nowrap",
        "max-w-full overflow-hidden text-ellipsis",
        CLASSE_SELO[tom],
      )}
    >
      {simbolo && <span className="shrink-0" aria-hidden>{simbolo}</span>}
      <span className="min-w-0 truncate">{children}</span>
    </span>
  );
}

const CLASSE_AVISO: Record<Exclude<TomSelo, "neutro">, { caixa: string; simbolo: string }> = {
  critico: { caixa: "border-critico-borda bg-critico-claro", simbolo: "text-critico" },
  atencao: { caixa: "border-atencao-borda bg-atencao-claro", simbolo: "text-atencao" },
  ok: { caixa: "border-ok-borda bg-ok-claro", simbolo: "text-ok" },
  info: { caixa: "border-acao-borda bg-acao-clara", simbolo: "text-acao" },
};

/** Faixa de mensagem com símbolo. Usada para erro, ressalva e confirmação. */
export function Aviso({
  tom,
  titulo,
  children,
}: {
  tom: TomSelo;
  titulo?: string;
  children?: ReactNode;
}) {
  const simbolo = { ok: "✓", atencao: "!", critico: "✕", info: "i", neutro: "•" }[tom];
  const visual = CLASSE_AVISO[tom === "neutro" ? "info" : tom];

  return (
    <div
      className={cn(
        "flex items-start gap-[10px] px-[14px] py-3 border border-l-4 rounded-campo text-tinta-2 text-sm leading-[1.55] [&_strong]:text-tinta",
        visual.caixa,
      )}
      role={tom === "critico" ? "alert" : undefined}
    >
      <span className={cn("flex-none text-base font-bold leading-[1.4]", visual.simbolo)} aria-hidden>
        {simbolo}
      </span>
      <div>
        {titulo && <strong>{titulo}</strong>}
        {titulo && children ? <br /> : null}
        {children}
      </div>
    </div>
  );
}

/** Caixa de estado vazio — "nenhum X ainda". Usada em toda lista/tabela sem itens. */
export function Vazio({ className, ...props }: React.ComponentPropsWithoutRef<"div">) {
  return (
    <div
      className={cn(
        "px-5 py-8 border border-dashed border-borda-forte rounded-campo bg-papel-2 text-tinta-3 text-sm leading-[1.6] text-center",
        className,
      )}
      {...props}
    />
  );
}

const SIMBOLO_MENSAGEM: Record<"erro" | "aviso" | "sugestao", { caixa: string; simbolo: string; conteudo: string }> = {
  erro: { caixa: "border-critico-borda bg-critico-claro", simbolo: "text-critico", conteudo: "✕" },
  aviso: { caixa: "border-atencao-borda bg-atencao-claro", simbolo: "text-atencao", conteudo: "!" },
  sugestao: { caixa: "border-acao-borda bg-acao-clara", simbolo: "text-acao", conteudo: "→" },
};

export function ListaMensagens({
  titulo,
  itens,
  tom,
}: {
  titulo: string;
  itens: string[];
  tom: "erro" | "aviso" | "sugestao";
}) {
  if (itens.length === 0) return null;

  const visual = SIMBOLO_MENSAGEM[tom];

  return (
    <>
      <div className="mt-[22px] mb-[10px] text-tinta text-sm font-bold first:mt-0">
        {titulo} ({itens.length})
      </div>
      <ul className="list-none mb-4">
        {itens.map((item, i) => (
          <li
            key={i}
            className={cn(
              "flex gap-[9px] px-[13px] py-[10px] mb-[7px] border border-borda border-l-4 rounded-campo text-tinta-2 text-sm leading-[1.55]",
              visual.caixa,
            )}
          >
            <span className={cn("flex-none font-bold", visual.simbolo)} aria-hidden>
              {visual.conteudo}
            </span>
            {item}
          </li>
        ))}
      </ul>
    </>
  );
}
