import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { installApiMock, renderApp } from "../test/renderApp";

describe("Submit preparation workspace", () => {
  it("fills a partition from advisory cards without exposing node placement", async () => {
    const user = userEvent.setup();
    installApiMock();
    renderApp("/jobs/submit");

    await screen.findByRole("heading", { name: "Submit a job" });
    const gpuCard = await screen.findByRole("button", { name: /gpu.*Compatible with this request/i });
    await user.click(gpuCard);

    expect(screen.getByLabelText("Partition")).toHaveValue("gpu");
    expect(screen.queryByLabelText(/node list/i)).not.toBeInTheDocument();
  });

  it("inserts a quoted path and confirms before replacing a dirty local draft", async () => {
    const user = userEvent.setup();
    installApiMock();
    renderApp("/jobs/submit");

    await screen.findByRole("heading", { name: "Submit a job" });
    await user.click(screen.getByRole("tab", { name: "Files" }));
    await user.click(await screen.findByRole("button", { name: /job script\.sh/ }));
    await screen.findByRole("button", { name: "Use as job script" });

    const editor = screen.getByLabelText("Batch script") as HTMLTextAreaElement;
    editor.setSelectionRange(editor.value.length, editor.value.length);
    await user.click(screen.getByRole("button", { name: "Insert path" }));
    expect(editor.value).toContain("'/home/researcher/job script.sh'");

    await user.click(screen.getByRole("button", { name: "Use as job script" }));
    const confirmation = screen.getByRole("alertdialog");
    expect(within(confirmation).getByText(/remote file will remain unchanged/i)).toBeInTheDocument();
    await user.click(within(confirmation).getByRole("button", { name: "Replace local draft" }));
    expect(editor.value).toBe("#!/bin/bash\necho remote job\n");
  });
});
