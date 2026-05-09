import type { HTMLAttributes } from "react";

import { cn } from "@/lib/utils";

interface ContentCardProps extends HTMLAttributes<HTMLDivElement> {
  className?: string;
  children: React.ReactNode;
}

export function ContentCard({ className, children, ...rest }: ContentCardProps) {
  return (
    <div className={cn("rounded-lg border border-shell-border bg-slate-900/35 p-3", className)} {...rest}>
      {children}
    </div>
  );
}
