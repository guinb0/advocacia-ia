"use client";

import { FileCheck2, FileText, Scale, ShieldCheck } from "lucide-react";

const CARD =
  "rounded-[18px] border border-[#d8e6f6] bg-white/86 shadow-[0_18px_50px_rgba(20,70,130,0.10)] backdrop-blur";

function Connector({
  className,
  vertical,
}: {
  className: string;
  vertical?: boolean;
}) {
  return (
    <span
      className={
        "absolute border-[#8fb8ea] opacity-50 motion-safe:animate-[loginPulseLine_3.8s_ease-in-out_infinite] " +
        (vertical ? "border-l border-dashed" : "border-t border-dashed") +
        " " +
        className
      }
      aria-hidden
    />
  );
}

export default function LoginVisualPanel() {
  return (
    <section className="relative hidden h-full min-h-[600px] overflow-hidden rounded-[28px] border border-[#d9e8f6] bg-[#f6fbff] px-8 py-8 shadow-[0_24px_70px_rgba(16,32,51,0.10)] lg:block xl:min-h-[680px] xl:px-10 xl:py-9">
      <div
        className="pointer-events-none absolute inset-0 opacity-70"
        style={{
          backgroundImage:
            "radial-gradient(circle at 1px 1px, rgba(18,91,196,0.14) 1px, transparent 0)",
          backgroundSize: "26px 26px",
        }}
        aria-hidden
      />
      <div className="relative z-10 flex h-full flex-col">
        <div className="flex items-center gap-3">
          <span className="inline-flex h-11 w-11 items-center justify-center rounded-[14px] bg-[#125bc4] text-white shadow-[0_10px_26px_rgba(18,91,196,0.28)]">
            <Scale size={22} aria-hidden />
          </span>
          <div>
            <span className="block text-base font-bold leading-none text-[#101828]">Acervo</span>
            <span className="mt-1 block text-xs font-semibold uppercase tracking-[0.16em] text-[#607089]">
              Inteligencia juridica
            </span>
          </div>
        </div>

        <div className="mt-8 max-w-[520px] xl:mt-12">
          <p className="text-xs font-bold uppercase tracking-[0.18em] text-[#125bc4]">
            Sistema do escritorio
          </p>
          <div className="mt-4 font-ui text-[2.55rem] font-extrabold leading-[1.05] text-[#111827] xl:text-[3rem]">
            Atenda. Organize. Peticione.
          </div>
          <p className="mt-5 max-w-[480px] text-sm leading-6 text-[#475467] xl:text-base xl:leading-7">
            Uma mesa de trabalho para conduzir entrevistas, conferir documentos,
            medir riscos e preparar a producao juridica com rastreabilidade.
          </p>
        </div>

        <div className="relative mt-8 h-[260px] xl:mt-10 xl:h-[300px]">
          <Connector className="left-[92px] top-[94px] w-[128px]" />
          <Connector className="right-[98px] top-[94px] w-[124px]" />
          <Connector className="left-[258px] top-[64px] h-[84px]" vertical />
          <Connector className="bottom-[68px] left-[158px] w-[260px]" />

          <div className="absolute left-1/2 top-10 h-[190px] w-[190px] -translate-x-1/2 rounded-[34px] bg-[#dcecff] shadow-[inset_0_1px_0_rgba(255,255,255,0.8),0_22px_60px_rgba(18,91,196,0.22)] motion-safe:animate-[loginFloat_8s_ease-in-out_infinite]">
            <div className="absolute inset-5 rounded-[26px] bg-white shadow-[0_16px_32px_rgba(16,32,51,0.08)]">
              <div className="mx-auto mt-8 h-12 w-12 rounded-[14px] bg-[#ebf4ff] text-[#125bc4]">
                <FileText className="m-3" size={24} aria-hidden />
              </div>
              <span className="mx-auto mt-5 block h-2 w-24 rounded-full bg-[#dbe8f6]" />
              <span className="mx-auto mt-3 block h-2 w-32 rounded-full bg-[#edf3fa]" />
              <span className="mx-auto mt-3 block h-2 w-20 rounded-full bg-[#edf3fa]" />
            </div>
            <div className="absolute -right-7 top-[72px] h-16 w-16 rounded-full border-[10px] border-[#125bc4] bg-white/50 shadow-[0_16px_30px_rgba(18,91,196,0.22)]" />
            <div className="absolute -right-11 top-[128px] h-12 w-4 -rotate-45 rounded-full bg-[#125bc4] shadow-[0_12px_24px_rgba(18,91,196,0.24)]" />
          </div>

          <div className={`${CARD} absolute left-0 top-12 flex h-[76px] w-[86px] items-center justify-center text-[#125bc4]`}>
            <Scale size={31} aria-hidden />
          </div>
          <div className={`${CARD} absolute right-3 top-12 flex h-[76px] w-[86px] items-center justify-center text-[#125bc4]`}>
            <FileCheck2 size={31} aria-hidden />
          </div>
          <div className={`${CARD} absolute bottom-4 left-12 flex h-[72px] w-[86px] items-center justify-center text-[#125bc4]`}>
            <ShieldCheck size={30} aria-hidden />
          </div>
          <div className={`${CARD} absolute bottom-4 right-16 flex h-[72px] w-[86px] items-center justify-center text-[#b88634]`}>
            <FileText size={30} aria-hidden />
          </div>
        </div>

        <div className="mt-auto grid grid-cols-3 gap-3">
          {[
            ["Atendimento", "roteiro claro"],
            ["Documentos", "rastreaveis"],
            ["Peticao", "com revisao"],
          ].map(([titulo, texto]) => (
            <div key={titulo} className="rounded-[14px] border border-[#dfeaf6] bg-white/78 p-3">
              <strong className="block text-xs text-[#101828]">{titulo}</strong>
              <span className="mt-1 block text-xs leading-4 text-[#667085]">{texto}</span>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
