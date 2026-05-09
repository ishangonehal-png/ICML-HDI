"use client";

import { useEffect, useId, useRef, useState } from "react";

import { cn } from "@/lib/utils";

interface InfoEyeTooltipProps {
  ariaLabel: string;
  description?: string;
  content?: string;
  className?: string;
  align?: "center" | "start" | "end";
}

export function InfoEyeTooltip({
  ariaLabel,
  description,
  content,
  className,
  align = "center",
}: InfoEyeTooltipProps) {
  const tooltipId = useId();
  const rootRef = useRef<HTMLSpanElement>(null);
  const pointerTypeRef = useRef<string>("mouse");

  const [isHoverOpen, setIsHoverOpen] = useState(false);
  const [isFocusOpen, setIsFocusOpen] = useState(false);
  const [isTapOpen, setIsTapOpen] = useState(false);

  const tooltipText = (description ?? content ?? "").trim();
  const hasTooltipText = tooltipText.length > 0;
  const isOpen = hasTooltipText && (isHoverOpen || isFocusOpen || isTapOpen);

  useEffect(() => {
    if (!isTapOpen) {
      return;
    }

    const handlePointerDown = (event: PointerEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) {
        setIsTapOpen(false);
      }
    };

    document.addEventListener("pointerdown", handlePointerDown);
    return () => {
      document.removeEventListener("pointerdown", handlePointerDown);
    };
  }, [isTapOpen]);

  const tooltipAlignmentClass =
    align === "end" ? "right-0" : align === "start" ? "left-0" : "left-1/2 -translate-x-1/2";

  return (
    <span
      ref={rootRef}
      className={cn("relative inline-flex", className)}
      onMouseEnter={() => {
        if (hasTooltipText) {
          setIsHoverOpen(true);
        }
      }}
      onMouseLeave={() => {
        setIsHoverOpen(false);
      }}
    >
      <button
        type="button"
        aria-label={ariaLabel}
        aria-controls={hasTooltipText ? tooltipId : undefined}
        aria-expanded={hasTooltipText ? isOpen : undefined}
        aria-describedby={isOpen ? tooltipId : undefined}
        onPointerDown={(event) => {
          pointerTypeRef.current = event.pointerType;
        }}
        onFocus={() => {
          if (hasTooltipText) {
            setIsFocusOpen(true);
          }
        }}
        onBlur={() => {
          setIsFocusOpen(false);
          setIsTapOpen(false);
        }}
        onClick={() => {
          if (!hasTooltipText || pointerTypeRef.current === "mouse") {
            return;
          }
          setIsTapOpen((previous) => !previous);
        }}
        onKeyDown={(event) => {
          if (event.key === "Escape") {
            setIsHoverOpen(false);
            setIsFocusOpen(false);
            setIsTapOpen(false);
            event.currentTarget.blur();
          }
        }}
        className="inline-flex h-5 w-5 items-center justify-center rounded-full border border-slate-500/70 bg-slate-900/80 text-slate-200 transition-colors hover:border-cyan-300/70 hover:text-cyan-100 focus-visible:border-cyan-300/80 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-300/40"
      >
        <svg
          viewBox="0 0 16 10"
          className="h-2.5 w-2.5"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.35"
          aria-hidden="true"
        >
          <path d="M1 5c1.45-2.35 3.46-3.5 7-3.5S13.55 2.65 15 5c-1.45 2.35-3.46 3.5-7 3.5S2.45 7.35 1 5Z" />
          <circle cx="8" cy="5" r="1.7" fill="currentColor" stroke="none" />
        </svg>
      </button>

      {hasTooltipText ? (
        <div
          id={tooltipId}
          role="tooltip"
          aria-hidden={!isOpen}
          data-open={isOpen ? "true" : "false"}
          className={cn(
            "absolute top-[calc(100%+0.5rem)] z-30 w-64 max-w-[calc(100vw-1.5rem)] rounded-md border border-shell-border bg-slate-950/95 px-3 py-2 text-[11px] leading-4 text-slate-200 shadow-lg transition-opacity",
            tooltipAlignmentClass,
            isOpen ? "pointer-events-auto opacity-100" : "pointer-events-none invisible opacity-0",
          )}
        >
          {tooltipText}
        </div>
      ) : null}
    </span>
  );
}
