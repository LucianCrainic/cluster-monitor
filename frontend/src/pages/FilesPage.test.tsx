import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { installApiMock, renderApp } from "../test/renderApp";

describe("Files page", () => {
  it("lists the login directory, toggles hidden files, and previews text read-only", async () => {
    const user = userEvent.setup();
    const fetchMock = installApiMock();
    renderApp("/files");

    expect(await screen.findByRole("heading", { name: "Files" })).toBeInTheDocument();
    expect(await screen.findByRole("button", { name: /job script\.sh/ })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /job script\.sh/ }));

    expect(await screen.findByText("36 B · -rw-r--r--")).toBeInTheDocument();
    expect(document.querySelector(".remote-preview__editor .cm-content")).toHaveAttribute("contenteditable", "false");

    await user.click(screen.getByLabelText("Hidden files"));
    await waitFor(() => {
      const listCalls = fetchMock.mock.calls.filter(([input]) => String(input).endsWith("/files/list"));
      expect(listCalls).toHaveLength(2);
      expect(JSON.parse(String(listCalls[1]?.[1]?.body))).toEqual({
        path: null,
        show_hidden: true,
      });
    });
    expect(fetchMock.mock.calls.every(([input]) => !String(input).includes("/home/researcher"))).toBe(true);
  });
});
