import { screen, waitFor, within } from "@testing-library/react";
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

    const preview = screen.getByRole("complementary", { name: "File preview" });
    expect(await within(preview).findByText("Shell")).toBeInTheDocument();
    expect(within(preview).getByText("36 B")).toBeInTheDocument();
    expect(within(preview).getByText("-rw-r--r--")).toBeInTheDocument();
    expect(within(preview).getByText("2 lines")).toBeInTheDocument();
    expect(document.querySelector(".remote-preview__editor .cm-content")).toHaveAttribute("contenteditable", "false");
    expect(document.querySelector(".remote-preview__editor .cm-line span")).toBeInTheDocument();

    await user.type(screen.getByRole("searchbox", { name: "Filter directory" }), "missing");
    expect(screen.getByText("No matching files")).toBeInTheDocument();
    await user.clear(screen.getByRole("searchbox", { name: "Filter directory" }));
    expect(screen.getByRole("button", { name: /job script\.sh/ })).toBeInTheDocument();

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
