"use client";

import { FileCheck2, FileText, Scale, ShieldCheck } from "lucide-react";

const CARD =
  "flex items-center justify-center rounded-2xl border border-[#d7e0e7] bg-white/75 shadow-[0_14px_30px_rgba(41,62,78,0.10)] backdrop-blur-sm";

function Connector({ className }: { className: string }) {
  return (
    <span
      className={`absolute border-t border-dashed border-[#94aabc]/65 motion-safe:animate-[loginPulseLine_4.8s_ease-in-out_infinite] ${className}`}
      aria-hidden
    />
  );
}

export default function LoginVisualPanel() {
  return (
    <section className="relative hidden min-h-[620px] overflow-hidden bg-[#eef2f5] px-9 py-9 lg:block lg:rounded-l-[28px] xl:min-h-[680px] xl:px-11 xl:py-10">
      <div
        className="pointer-events-none absolute inset-0 opacity-60"
        style={{
          backgroundImage:
            "radial-gradient(circle at 1px 1px, rgba(70,105,130,0.16) 1px, transparent 0)",
          backgroundSize: "28px 28px",
        }}
        aria-hidden
      />
      <div className="pointer-events-none absolute -left-28 bottom-[-150px] h-80 w-80 rounded-full bg-[#d6e5ee]/70 blur-3xl" aria-hidden />

      <div className="relative z-10 flex h-full flex-col">
        <div className="flex items-center gap-3">
          <span className="inline-flex h-10 w-10 items-center justify-center rounded-xl bg-[#31536b] text-white shadow-[0_10px_22px_rgba(45,78,102,0.22)]">
            <Scale size={20} aria-hidden />
          </span>
          <div>
            <span className="block text-base font-bold leading-none text-[#1c2a35]">Forense</span>
            <span className="mt-1 block text-[11px] font-semibold uppercase tracking-[0.16em] text-[#697c8b]">
              Inteligência jurídica
            </span>
          </div>
        </div>

        <div className="mt-12 max-w-[490px]">
          <p className="text-[11px] font-bold uppercase tracking-[0.19em] text-[#517b95]">
            Sistema do escritório
          </p>
          <h2 className="mt-4 font-ui text-[2.6rem] font-semibold tracking-[-0.045em] text-[#1a2732] xl:text-[3rem]">
            Atenda. Organize. <span className="text-[#527a92]">Peticione.</span>
          </h2>
          <p className="mt-5 max-w-[430px] text-sm leading-6 text-[#5e6e7b] xl:text-base">
            Uma mesa de trabalho serena para conduzir entrevistas, conferir documentos e preparar cada próxima etapa.
          </p>
        </div>

        <div className="relative mt-9 h-[255px] xl:mt-10 xl:h-[285px]">
          <Connector className="left-[84px] top-[97px] w-[140px]" />
          <Connector className="right-[76px] top-[97px] w-[126px]" />
          <Connector className="bottom-[55px] left-[145px] w-[250px]" />

          <div className="absolute left-1/2 top-8 h-[186px] w-[186px] -translate-x-1/2 rounded-[30px] border border-white/80 bg-[#dce8ef] p-4 shadow-[0_24px_48px_rgba(48,79,101,0.18)] motion-safe:animate-[loginFloat_9s_ease-in-out_infinite]">
            <div className="flex h-full flex-col items-center rounded-[22px] bg-[#f9fbfc] pt-7 shadow-[inset_0_1px_0_rgba(255,255,255,0.8)]">
              <span className="grid h-11 w-11 place-items-center rounded-xl bg-[#e6eff4] text-[#527a92]">
                <FileText size={22} aria-hidden />
              </span>
              <span className="mt-5 h-2 w-24 rounded-full bg-[#cbdce6]" />
              <span className="mt-3 h-2 w-32 rounded-full bg-[#e2eaef]" />
              <span className="mt-3 h-2 w-20 rounded-full bg-[#e2eaef]" />
            </div>
            <div className="absolute -right-7 top-[74px] h-[62px] w-[62px] rounded-full border-[9px] border-[#638da6] bg-[#eef2f5]/80 shadow-[0_12px_24px_rgba(48,79,101,0.16)]" />
            <div className="absolute -right-10 top-[128px] h-11 w-3.5 -rotate-45 rounded-full bg-[#638da6]" />
          </div>

          <div className={`${CARD} absolute left-0 top-12 h-[70px] w-[80px] text-[#527a92]`}>
            <Scale size={28} aria-hidden />
          </div>
          <div className={`${CARD} absolute right-2 top-12 h-[70px] w-[80px] text-[#527a92]`}>
            <FileCheck2 size={28} aria-hidden />
          </div>
          <div className={`${CARD} absolute bottom-2 left-12 h-[67px] w-[80px] text-[#527a92]`}>
            <ShieldCheck size={27} aria-hidden />
          </div>
          <div className={`${CARD} absolute bottom-2 right-14 h-[67px] w-[80px] text-[#8d704d]`}>
            <FileText size={27} aria-hidden />
          </div>
        </div>

        <div className="mt-auto grid grid-cols-3 gap-2.5">
          {[
            ["Atendimento", "roteiro claro"],
            ["Documentos", "leitura rastreável"],
            ["Petições", "revisão segura"],
          ].map(([titulo, texto]) => (
            <div key={titulo} className="rounded-xl border border-[#d8e2e8] bg-white/58 px-3 py-3 shadow-[0_5px_14px_rgba(48,79,101,0.05)]">
              <strong className="block text-xs text-[#263641]">{titulo}</strong>
              <span className="mt-1 block text-xs leading-4 text-[#71818d]">{texto}</span>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
