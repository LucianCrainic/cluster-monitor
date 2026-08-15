import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { installApiMock, jsonResponse, renderApp } from "../test/renderApp";

describe("History page", () => {
  it("loads recent jobs and links each record to its details and logs", async () => {
    const fetchMock = installApiMock();
    renderApp("/history");

    expect(
      await screen.findByRole("heading", { name: "Job history" }),
    ).toBeInTheDocument();
    expect(await screen.findByText("dataset-cleanup")).toBeInTheDocument();
    expect(screen.getByText("failed-simulation")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "18390" })).toHaveAttribute(
      "href",
      "/jobs/18390",
    );
    expect(screen.getByRole("link", { name: "History" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/clusters/local-mock/history?limit=100",
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    );
  });

  it("filters accounting records and resets the filters", async () => {
    const user = userEvent.setup();
    installApiMock();
    renderApp("/history");

    await screen.findByText("dataset-cleanup");
    await user.selectOptions(
      screen.getByRole("combobox", { name: "State" }),
      "failed",
    );

    const table = screen.getByRole("table");
    expect(within(table).getByText("failed-simulation")).toBeInTheDocument();
    expect(within(table).queryByText("dataset-cleanup")).not.toBeInTheDocument();

    await user.type(
      screen.getByRole("searchbox", { name: "Search history" }),
      "no-such-job",
    );
    expect(
      screen.getByRole("heading", { name: "No jobs match" }),
    ).toBeInTheDocument();

    await user.click(
      screen.getByRole("button", { name: "Reset history filters" }),
    );
    expect(await screen.findByText("dataset-cleanup")).toBeInTheDocument();
  });

  it("renders an empty history state", async () => {
    installApiMock({ history: jsonResponse([]) });
    renderApp("/history");

    expect(
      await screen.findByRole("heading", { name: "No recent jobs" }),
    ).toBeInTheDocument();
  });
});
