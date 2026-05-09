import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { apiClient } from "@/lib/api-client";

import { AgentChatRail } from "./agent-chat-rail";

const meta = {
  method: "agent-v1",
  version: "2026.03",
  timestamp: "2026-03-08T00:00:00Z",
  proxy_estimate: true as const,
};

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("AgentChatRail", () => {
  it("uses a viewport-height rail layout so the chat body can grow and scroll", () => {
    render(<AgentChatRail caseId="TCGA-05-4244" />);

    const rail = screen.getByText("Agent chat rail").closest("aside");
    expect(rail).not.toBeNull();
    expect(rail).toHaveClass("flex", "min-h-0", "flex-col", "xl:sticky", "xl:top-6", "xl:h-[calc(100dvh-3rem)]");
  });

  it("prevents rapid duplicate submits while a request is in-flight", async () => {
    type AgentQueryResult = Awaited<ReturnType<typeof apiClient.queryAgent>>;
    let resolveQuery!: (value: AgentQueryResult) => void;
    const pendingQuery = new Promise<AgentQueryResult>((resolve) => {
      resolveQuery = resolve;
    });
    const queryAgentSpy = vi
      .spyOn(apiClient, "queryAgent")
      .mockReturnValue(pendingQuery as ReturnType<typeof apiClient.queryAgent>);

    render(<AgentChatRail caseId="TCGA-05-4244" />);

    const input = screen.getByPlaceholderText("Ask: Why did RNA change score?");
    fireEvent.change(input, { target: { value: "Why did RNA change score?" } });

    const form = input.closest("form");
    expect(form).not.toBeNull();

    fireEvent.submit(form!);
    fireEvent.submit(form!);

    expect(queryAgentSpy).toHaveBeenCalledTimes(1);

    resolveQuery({
      case_id: "TCGA-05-4244",
      answer: "RNA signal increased refined score in this case.",
      citations: [],
      acknowledged_missing_modalities: [],
      meta,
    });

    await waitFor(() => {
      expect(screen.getByText("RNA signal increased refined score in this case.")).toBeInTheDocument();
    });
  });

  it("blocks over-limit prompts and keeps submit disabled", () => {
    const queryAgentSpy = vi.spyOn(apiClient, "queryAgent").mockResolvedValue({
      case_id: "TCGA-05-4244",
      answer: "ok",
      citations: [],
      acknowledged_missing_modalities: [],
      meta,
    } as Awaited<ReturnType<typeof apiClient.queryAgent>>);

    render(<AgentChatRail caseId="TCGA-05-4244" />);

    const input = screen.getByPlaceholderText("Ask: Why did RNA change score?");
    fireEvent.change(input, { target: { value: "a".repeat(700) } });

    const submit = screen.getByRole("button", { name: "Ask agent" });
    expect(submit).toBeDisabled();
    expect(screen.getByRole("alert")).toHaveTextContent("Prompt is too long");

    const form = input.closest("form");
    expect(form).not.toBeNull();
    fireEvent.submit(form!);

    expect(queryAgentSpy).not.toHaveBeenCalled();
  });
});
