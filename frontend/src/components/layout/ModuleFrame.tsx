import type { ReactNode } from "react";

type ModuleFrameVariant = "workspace" | "compact" | "wide";

const WIDTH: Record<ModuleFrameVariant, string> = {
  workspace: "max-w-full",
  compact: "max-w-[1180px]",
  wide: "max-w-[1320px]",
};

interface ModuleFrameProps {
  children: ReactNode;
  variant?: ModuleFrameVariant;
}

export default function ModuleFrame({
  children,
  variant = "workspace",
}: ModuleFrameProps) {
  return (
    <section className={`mx-auto flex w-full min-w-0 flex-col ${WIDTH[variant]}`}>
      <div className="min-w-0 max-w-full [&_*]:min-w-0">{children}</div>
    </section>
  );
}
