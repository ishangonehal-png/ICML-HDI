import { cn } from "@/lib/utils";

interface PageSectionProps {
  className?: string;
  children: React.ReactNode;
}

export function PageSection({ className, children }: PageSectionProps) {
  return <section className={cn("rounded-xl border border-shell-border bg-shell-panel/60 p-4", className)}>{children}</section>;
}
