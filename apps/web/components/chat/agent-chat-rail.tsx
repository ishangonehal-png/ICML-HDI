"use client";

import { useMemo, useRef, useState } from "react";

import { apiClient } from "@/lib/api-client";

interface AgentChatRailProps {
  caseId: string;
  suggestedPrompts?: string[];
}

interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  text: string;
  citations?: Array<{ panel: string; field: string; source: string }>;
}

const defaultPrompts = [
  "Why did RNA change score?",
  "Show source for this claim",
  "Compare to similar cases",
];
const MAX_QUERY_CHARS = 600;

export function AgentChatRail({ caseId, suggestedPrompts = defaultPrompts }: AgentChatRailProps) {
  const [messages, setMessages] = useState<ChatMessage[]>([
    {
      id: "welcome",
      role: "assistant",
      text: "Grounded research agent ready. Ask about score deltas, multimodal evidence, literature context, or source provenance.",
    },
  ]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const inFlightRef = useRef(false);

  const trimmedInput = input.trim();
  const isTooLong = trimmedInput.length > MAX_QUERY_CHARS;
  const canSend = useMemo(
    () => trimmedInput.length > 0 && !loading && !isTooLong,
    [isTooLong, loading, trimmedInput.length],
  );

  const send = async (text: string) => {
    if (inFlightRef.current) {
      return;
    }

    const trimmed = text.trim();
    if (!trimmed || trimmed.length > MAX_QUERY_CHARS) {
      return;
    }

    inFlightRef.current = true;
    setLoading(true);
    const userMessage: ChatMessage = {
      id: `user-${Date.now()}`,
      role: "user",
      text: trimmed,
    };
    setMessages((current) => [...current, userMessage]);
    setInput("");

    try {
      const response = await apiClient.queryAgent({ case_id: caseId, query: trimmed });

      setMessages((current) => [
        ...current,
        {
          id: `assistant-${Date.now()}`,
          role: "assistant",
          text: response.answer,
          citations: response.citations,
        },
      ]);
    } catch {
      setMessages((current) => [
        ...current,
        {
          id: `assistant-${Date.now()}`,
          role: "assistant",
          text: "Agent request failed. Please retry in a moment.",
        },
      ]);
    } finally {
      inFlightRef.current = false;
      setLoading(false);
    }
  };

  return (
    <aside className="flex h-full min-h-0 flex-col rounded-xl border border-shell-border bg-shell-panel/70 p-4 xl:sticky xl:top-6 xl:h-[calc(100dvh-3rem)]">
      <h2 className="text-sm font-semibold text-slate-100">Agent chat rail</h2>
      <p className="mt-1 text-xs text-slate-300">Grounded multimodal research assistant with internal evidence and optional PubMed citations.</p>

      <div className="mt-3 flex flex-wrap gap-2">
        {suggestedPrompts.map((prompt) => (
          <button
            key={prompt}
            type="button"
            className="rounded-full border border-cyan-400/40 bg-cyan-500/10 px-3 py-1 text-[11px] text-cyan-100"
            onClick={() => setInput(prompt)}
            disabled={loading}
          >
            {prompt}
          </button>
        ))}
      </div>

      <div className="mt-4 min-h-[12rem] min-w-0 flex-1 space-y-3 overflow-y-auto pr-1">
        {messages.map((message) => (
          <div
            key={message.id}
            className={`rounded-lg border px-3 py-2 text-sm ${
              message.role === "assistant"
                ? "border-shell-border bg-slate-900/35 text-slate-100"
                : "border-cyan-400/40 bg-cyan-500/15 text-cyan-100"
            }`}
          >
            <p className="text-xs uppercase tracking-wide opacity-70">{message.role}</p>
            <p className="mt-1 text-sm">{message.text}</p>
            {message.citations?.length ? (
              <ul className="mt-2 list-disc space-y-1 pl-4 text-[11px] text-slate-300">
                {message.citations.map((citation, index) => (
                  <li key={`${citation.panel}-${citation.field}-${citation.source}-${index}`}>
                    {citation.panel}.{citation.field} · {citation.source}
                  </li>
                ))}
              </ul>
            ) : null}
          </div>
        ))}

        {loading ? (
          <div className="rounded-lg border border-shell-border bg-slate-900/30 px-3 py-2 text-xs text-slate-300">
            Agent is drafting a grounded response...
          </div>
        ) : null}
      </div>

      <form
        className="mt-4 space-y-2"
        onSubmit={(event) => {
          event.preventDefault();
          if (!canSend) {
            return;
          }
          void send(input);
        }}
      >
        <textarea
          value={input}
          onChange={(event) => setInput(event.target.value)}
          rows={3}
          placeholder="Ask: Why did RNA change score?"
          className="w-full rounded-lg border border-shell-border bg-slate-900 px-3 py-2 text-sm text-slate-100"
        />
        <p className={`text-[11px] ${isTooLong ? "text-rose-200" : "text-slate-400"}`}>
          {trimmedInput.length}/{MAX_QUERY_CHARS}
        </p>
        {isTooLong ? (
          <p role="alert" className="text-xs text-rose-200">
            Prompt is too long. Keep it under {MAX_QUERY_CHARS} characters.
          </p>
        ) : null}
        <button
          type="submit"
          disabled={!canSend}
          className="w-full rounded-md bg-cyan-500 px-3 py-2 text-sm font-semibold text-slate-900 hover:bg-cyan-400 disabled:cursor-not-allowed disabled:opacity-60"
        >
          {loading ? "Asking..." : "Ask agent"}
        </button>
      </form>

      <p className="mt-3 text-[11px] text-amber-200/90">
        Research-only guardrail active: responses are explanatory summaries, not clinical recommendations.
      </p>
    </aside>
  );
}
