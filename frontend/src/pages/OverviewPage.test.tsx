import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { installApiMock, jsonResponse, renderApp } from "../test/renderApp";

describe("Overview page", () => {
  it("persists the icon-only sidebar preference", async () => {
    window.localStorage.removeItem("cluster-monitor-sidebar-collapsed");
    installApiMock();
    const { container } = renderApp("/");
    const user = userEvent.setup();

    await screen.findByRole("heading", { name: "Overview" });
    await user.click(screen.getByRole("button", { name: "Collapse sidebar" }));

    expect(container.querySelector(".app-shell")).toHaveClass("app-shell--collapsed");
    expect(window.localStorage.getItem("cluster-monitor-sidebar-collapsed")).toBe("true");
    window.localStorage.removeItem("cluster-monitor-sidebar-collapsed");
  });

  it("renders mock overview data", async () => {
    installApiMock();
    renderApp("/");

    expect(
      await screen.findByRole("heading", { name: "Overview" }),
    ).toBeInTheDocument();
    expect(
      await screen.findByRole("heading", { name: "Cluster is reachable" }),
    ).toBeInTheDocument();
    expect(screen.getAllByText("Local Mock Cluster")).toHaveLength(2);

    const nodeSection = screen
      .getByRole("heading", { name: "Node capacity" })
      .closest("section");
    expect(nodeSection).not.toBeNull();
    const expectedMetrics = [
      ["Total nodes", "12"],
      ["Idle", "7"],
      ["Allocated", "4"],
      ["Unavailable", "1"],
    ] as const;
    for (const [label, value] of expectedMetrics) {
      const card = within(nodeSection!)
        .getByText(label, { selector: ".metric-card__label" })
        .closest("article");
      expect(card).not.toBeNull();
      expect(within(card!).getByText(value)).toBeInTheDocument();
    }
    expect(screen.getByText("24.05.4")).toBeInTheDocument();
  });

  it("shows a loading state while cluster discovery is pending", () => {
    installApiMock({
      clusters: new Promise<Response>(() => undefined),
    });
    renderApp("/");

    expect(screen.getByText("Loading configured clusters…")).toBeInTheDocument();
  });

  it("shows a connection error with a retry action", async () => {
    installApiMock({
      overview: jsonResponse(
        {
          error: {
            code: "cluster_connection_error",
            message: "SSH connection to the selected cluster failed.",
          },
        },
        503,
      ),
    });
    renderApp("/");

    const alert = await screen.findByRole("alert");
    expect(
      within(alert).getByRole("heading", { name: "Connection unavailable" }),
    ).toBeInTheDocument();
    expect(
      within(alert).getByText("SSH connection to the selected cluster failed."),
    ).toBeInTheDocument();
    expect(
      within(alert).getByRole("button", { name: "Try again" }),
    ).toBeInTheDocument();
  });
});
