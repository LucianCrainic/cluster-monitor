import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { installApiMock, jsonResponse, renderApp } from "../test/renderApp";

describe("Jobs page", () => {
  it("renders jobs returned by the mock cluster", async () => {
    installApiMock();
    renderApp("/jobs");

    expect(await screen.findByText("protein-folding")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Jobs" })).toBeInTheDocument();
    expect(screen.getByText("language-model-train")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "18432" })).toHaveAttribute(
      "href",
      "/jobs/18432",
    );
    expect(screen.getByLabelText("Job state: Running")).toBeInTheDocument();
    expect(screen.getByText("Resources")).toBeInTheDocument();
  });

  it("renders an empty state when no active jobs exist", async () => {
    installApiMock({ jobs: jsonResponse([]) });
    renderApp("/jobs");

    expect(
      await screen.findByRole("heading", { name: "No active jobs" }),
    ).toBeInTheDocument();
    expect(
      screen.getByText(
        "There are no running or pending jobs for the configured user.",
      ),
    ).toBeInTheDocument();
  });

  it("filters jobs by state and search text", async () => {
    const user = userEvent.setup();
    installApiMock();
    renderApp("/jobs");

    await screen.findByText("protein-folding");
    await user.selectOptions(
      screen.getByRole("combobox", { name: "State" }),
      "pending",
    );

    const table = screen.getByRole("table");
    expect(within(table).getByText("language-model-train")).toBeInTheDocument();
    expect(within(table).queryByText("protein-folding")).not.toBeInTheDocument();

    await user.type(
      screen.getByRole("searchbox", { name: "Search jobs" }),
      "no-such-job",
    );
    expect(
      screen.getByRole("heading", { name: "No jobs match" }),
    ).toBeInTheDocument();

    await user.click(
      screen.getByRole("button", { name: "Reset job filters" }),
    );
    expect(await screen.findByText("protein-folding")).toBeInTheDocument();
    expect(
      screen.getByText(
        (_, element) => element?.textContent === "Showing 3 of 3 jobs",
      ),
    ).toBeInTheDocument();
  });
});
