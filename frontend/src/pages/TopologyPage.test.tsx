import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { mockTopology } from "../test/fixtures";
import { installApiMock, jsonResponse, renderApp } from "../test/renderApp";

describe("Topology page", () => {
  it("renders the flat resource fallback, filters nodes, and highlights a job allocation", async () => {
    const user = userEvent.setup();
    installApiMock();
    renderApp("/topology?job=18432");

    expect(await screen.findByRole("heading", { name: "Cluster topology" })).toBeInTheDocument();
    expect(screen.getByText(/No rack layout is inferred/)).toBeInTheDocument();
    expect((await screen.findAllByText("Selected job")).length).toBeGreaterThan(0);

    await user.click(screen.getByLabelText("GPU nodes only"));
    expect(screen.getByRole("button", { name: /gpu-01/i })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /cpu-02/i })).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /gpu-01/i }));
    expect(screen.getByRole("heading", { name: "gpu-01" })).toBeInTheDocument();
    expect(screen.getByText("gpu:a100:4")).toBeInTheDocument();
  });

  it("shows Slurm-reported physical groups when available", async () => {
    const user = userEvent.setup();
    installApiMock({
      topology: jsonResponse({
        ...mockTopology,
        kind: "tree",
        groups: [
          {
            id: "switch:leaf-a",
            name: "leaf-a",
            kind: "switch",
            child_group_ids: [],
            node_names: ["cpu-01", "cpu-02"],
            link_speed: "100G",
          },
        ],
      }),
    });
    renderApp("/topology");

    await screen.findByRole("heading", { name: "Cluster topology" });
    await user.click(screen.getByRole("tab", { name: "Physical topology" }));

    expect(screen.getByRole("heading", { name: "Tree topology" })).toBeInTheDocument();
    expect(screen.getByText("Switch · 100G")).toBeInTheDocument();
    expect(screen.queryByText(/No rack layout is inferred/)).not.toBeInTheDocument();
  });
});
