import { fireEvent, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { parseJobLogEventFrame, streamJobLogs } from "../api/client";
import { installApiMock, renderApp, sseResponse } from "../test/renderApp";

describe("job log streaming", () => {
  beforeEach(() => {
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: { writeText: vi.fn().mockResolvedValue(undefined) },
    });
    Object.defineProperty(URL, "createObjectURL", {
      configurable: true,
      value: vi.fn(() => "blob:test"),
    });
    Object.defineProperty(URL, "revokeObjectURL", {
      configurable: true,
      value: vi.fn(),
    });
  });

  it("parses typed SSE data and ignores heartbeats", () => {
    expect(parseJobLogEventFrame(": heartbeat")).toBeNull();
    expect(
      parseJobLogEventFrame(
        'event: chunk\ndata: {"type":"chunk","source":"stdout","sequence":7,"text":"hello\\n"}',
      ),
    ).toEqual({ type: "chunk", source: "stdout", sequence: 7, text: "hello\n" });
  });

  it("decodes SSE frames split across chunks and UTF-8 boundaries", async () => {
    const encoded = new TextEncoder().encode(
      'event: chunk\ndata: {"type":"chunk","source":"stdout","sequence":1,"text":"café"}\n\n',
    );
    const split = encoded.indexOf(0xc3) + 1;
    const body = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(encoded.slice(0, split));
        controller.enqueue(encoded.slice(split));
        controller.close();
      },
    });
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(body, { headers: { "Content-Type": "text/event-stream" } }),
      ),
    );

    const events = [];
    for await (const event of streamJobLogs("cluster", "123", new AbortController().signal)) {
      events.push(event);
    }

    expect(events).toEqual([
      { type: "chunk", source: "stdout", sequence: 1, text: "café" },
    ]);
  });

  it("mounts only on the Logs tab and provides viewer controls", async () => {
    const fetchMock = installApiMock();
    renderApp("/jobs/18432");
    const user = userEvent.setup();

    expect(await screen.findByRole("heading", { name: "Job summary" })).toBeVisible();
    expect(fetchMock).not.toHaveBeenCalledWith(
      expect.stringContaining("/logs/stream"),
      expect.anything(),
    );

    await user.click(screen.getByRole("tab", { name: "Logs" }));

    expect(await screen.findByText("training epoch 1")).toBeVisible();
    expect(screen.getByText("warning: sample")).toBeVisible();
    expect(screen.getByText("Completed")).toBeVisible();

    await user.click(screen.getByRole("button", { name: "stderr" }));
    expect(screen.queryByText("training epoch 1")).not.toBeInTheDocument();
    expect(screen.getByText("warning: sample")).toBeVisible();

    await user.type(screen.getByRole("searchbox", { name: "Search logs" }), "sample");
    expect(screen.getByText("1 of 1")).toBeVisible();
    expect(screen.getByText("sample", { selector: "mark" })).toBeVisible();

    await user.click(screen.getByRole("button", { name: "Wrap lines" }));
    expect(screen.getByRole("log")).toHaveClass("log-terminal--wrap");
    await user.click(screen.getByRole("button", { name: "Copy" }));
    expect(await screen.findByText("Copied the buffered log output.")).toBeVisible();

    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
    await user.click(screen.getByRole("button", { name: "Download" }));
    expect(click).toHaveBeenCalledOnce();
    expect(URL.createObjectURL).toHaveBeenCalledOnce();
    expect(screen.getByText("Downloaded the buffered log snapshot.")).toBeVisible();
  });

  it("aborts the stream when leaving the Logs tab and reconnects with a clean request", async () => {
    const fetchMock = installApiMock();
    renderApp("/jobs/18432");
    const user = userEvent.setup();

    await user.click(await screen.findByRole("tab", { name: "Logs" }));
    await screen.findByText("training epoch 1");
    const firstLogCall = fetchMock.mock.calls.find(([input]) =>
      String(input).endsWith("/logs/stream"),
    );
    expect(firstLogCall?.[1]?.signal).toBeInstanceOf(AbortSignal);

    await user.click(screen.getByRole("button", { name: "Reconnect" }));
    await waitFor(() => {
      expect(
        fetchMock.mock.calls.filter(([input]) => String(input).endsWith("/logs/stream")),
      ).toHaveLength(2);
    });

    await user.click(screen.getByRole("tab", { name: "Overview" }));
    expect(firstLogCall?.[1]?.signal?.aborted).toBe(true);
  });

  it("turns off autoscroll when the reader moves away from the bottom", async () => {
    installApiMock();
    renderApp("/jobs/18432");
    const user = userEvent.setup();
    await user.click(await screen.findByRole("tab", { name: "Logs" }));
    const log = await screen.findByRole("log");
    Object.defineProperties(log, {
      scrollHeight: { configurable: true, value: 1000 },
      clientHeight: { configurable: true, value: 200 },
      scrollTop: { configurable: true, value: 100 },
    });

    fireEvent.scroll(log);

    expect(screen.getByRole("button", { name: "Jump to latest" })).toBeVisible();
  });

  it("trims the oldest lines when the bounded viewer reaches 5,000 lines", async () => {
    const text = Array.from({ length: 5_002 }, (_, index) => `line ${index}`).join("\n");
    const frames = [
      'event: metadata\ndata: {"type":"metadata","job_id":"18432","state":"running","sources":["stdout"],"initial_lines":200}\n\n',
      `event: chunk\ndata: ${JSON.stringify({
        type: "chunk",
        source: "stdout",
        sequence: 1,
        text: `${text}\n`,
      })}\n\n`,
      'event: complete\ndata: {"type":"complete","reason":"job_finished"}\n\n',
    ].join("");
    installApiMock({ jobLogs: sseResponse(frames) });
    renderApp("/jobs/18432");
    const user = userEvent.setup();

    await user.click(await screen.findByRole("tab", { name: "Logs" }));

    expect(
      await screen.findByText("Earlier output was trimmed to keep the viewer responsive."),
    ).toBeVisible();
    expect(screen.getByText("5,000 buffered lines")).toBeVisible();
    expect(screen.queryByText("line 0")).not.toBeInTheDocument();
    expect(screen.getByText("line 5001")).toBeVisible();
  });
});
