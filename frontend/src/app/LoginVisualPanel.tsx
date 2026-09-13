"use client";

import { FileCheck2, FileText, Fingerprint, ShieldCheck } from "lucide-react";

type EntityProps = {
  children: React.ReactNode;
  className: string;
};

function Entity({ children, className }: EntityProps) {
  return (
    <div
      className={`absolute grid place-items-center rounded-2xl border border-[#4c697a]/70 bg-[#2a4150]/74 text-[#9fc4d4] shadow-[0_12px_28px_rgba(6,17,25,0.20)] backdrop-blur-sm ${className}`}
      aria-hidden
    >
      {children}
    </div>
  );
}

function Connector({ className }: { className: string }) {
  return (
    <span
      className={`absolute border-t border-dashed border-[#7096a9]/55 motion-safe:animate-[loginPulseLine_4.8s_ease-in-out_infinite] ${className}`}
      aria-hidden
    />
  );
}

export default function LoginVisualPanel() {
  return (
    <section className="relative hidden min-h-[620px] overflow-hidden bg-[#203340] px-9 py-9 lg:block lg:rounded-l-[28px] xl:min-h-[680px] xl:px-11 xl:py-10">
      <div
        className="pointer-events-none absolute inset-0 opacity-45"
        style={{
          backgroundImage:
            "radial-gradient(circle at 1px 1px, rgba(151,190,207,0.20) 1px, transparent 0)",
          backgroundSize: "29px 29px",
        }}
        aria-hidden
      />
      <div className="pointer-events-none absolute -left-20 bottom-[-110px] h-72 w-72 rounded-full bg-[#365467]/45 blur-3xl" aria-hidden />

      <div className="relative z-10 flex h-full flex-col">
        <div className="flex items-center gap-3">
          <span className="inline-flex h-10 w-10 items-center justify-center overflow-hidden rounded-xl border border-[#567589] bg-[#2e4b5e] p-1 shadow-[0_10px_22px_rgba(7,20,29,0.24)]">
            {/* eslint-disable-next-line @next/next/no-img-element -- ícone de 40px, sem benefício do otimizador */}
            <img src="/logo-forense-icone.png" alt="" className="h-full w-full object-contain" />
          </span>
          <div>
            <span className="block text-base font-bold leading-none text-[#f2f7f9]">Forense</span>
            <span className="mt-1 block text-[11px] font-semibold uppercase tracking-[0.16em] text-[#a9c0cb]">
              Inteligência jurídica
            </span>
          </div>
        </div>

        <div className="mt-12 max-w-[485px]">
          <p className="text-[11px] font-bold uppercase tracking-[0.19em] text-[#91b8c9]">
            Sistema do escritório
          </p>
          <h2 className="mt-4 font-ui text-[2.6rem] font-semibold tracking-[-0.045em] text-[#f1f6f8] xl:text-[3rem]">
            Trabalho jurídico, <span className="text-[#9dc1d0]">sem ruído.</span>
          </h2>
          <p className="mt-5 max-w-[440px] text-sm leading-6 text-[#b3c6cf] xl:text-base">
            Entrevistas, documentos e decisões conectados numa mesa de trabalho mais clara e contínua.
          </p>
        </div>

        <div className="relative mt-9 h-[255px] xl:mt-10 xl:h-[285px]">
          <Connector className="left-[82px] top-[96px] w-[144px]" />
          <Connector className="right-[74px] top-[96px] w-[128px]" />
          <Connector className="bottom-[56px] left-[146px] w-[250px]" />

          <div className="absolute left-1/2 top-7 h-[188px] w-[188px] -translate-x-1/2 rounded-[30px] border border-[#55768a] bg-[#294352] p-4 shadow-[0_24px_48px_rgba(5,16,24,0.28)] motion-safe:animate-[loginFloat_9s_ease-in-out_infinite]">
            <div className="flex h-full flex-col items-center rounded-[22px] border border-[#4c6b7e] bg-[#203744] pt-7 shadow-[inset_0_1px_0_rgba(221,240,247,0.06)]">
              <span className="grid h-11 w-11 place-items-center rounded-xl bg-[#315367] text-[#a6c9d8]">
                <FileText size={22} aria-hidden />
              </span>
              <span className="mt-5 h-2 w-24 rounded-full bg-[#5f8497]" />
              <span className="mt-3 h-2 w-32 rounded-full bg-[#365565]" />
              <span className="mt-3 h-2 w-20 rounded-full bg-[#365565]" />
            </div>
            <div className="absolute -right-7 top-[74px] h-[62px] w-[62px] rounded-full border-[9px] border-[#88b4c7] bg-[#243e4d] shadow-[0_12px_24px_rgba(5,16,24,0.28)]" />
            <div className="absolute -right-10 top-[128px] h-11 w-3.5 -rotate-45 rounded-full bg-[#88b4c7]" />
          </div>

          <Entity className="left-0 top-12 h-[70px] w-[80px]"><Fingerprint size={28} /></Entity>
          <Entity className="right-2 top-12 h-[70px] w-[80px]"><FileCheck2 size={28} /></Entity>
          <Entity className="bottom-2 left-12 h-[67px] w-[80px]"><ShieldCheck size={27} /></Entity>
          <Entity className="bottom-2 right-14 h-[67px] w-[80px]"><FileText size={27} /></Entity>
        </div>

        <div className="mt-auto grid grid-cols-3 gap-2.5">
          {[
            ["Atendimento", "roteiro claro"],
            ["Documentos", "leitura rastreável"],
            ["Petições", "revisão segura"],
          ].map(([titulo, texto]) => (
            <div key={titulo} className="rounded-xl border border-[#4a6879]/75 bg-[#29414f]/65 px-3 py-3 shadow-[0_5px_14px_rgba(6,17,25,0.10)]">
              <strong className="block text-xs text-[#e4eef2]">{titulo}</strong>
              <span className="mt-1 block text-xs leading-4 text-[#abc0ca]">{texto}</span>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
