import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { mockCluster, mockJobDetails } from "../test/fixtures";
import { installApiMock, jsonResponse, renderApp } from "../test/renderApp";

describe("Job actions", () => {
  it("blocks the submission route when cluster actions are disabled", async () => {
    installApiMock({
      clusters: jsonResponse([
        {
          ...mockCluster,
          job_actions_enabled: false,
        },
      ]),
    });
    renderApp("/jobs/submit");

    expect(
      await screen.findByRole("heading", {
        name: "Job actions are disabled",
      }),
    ).toBeInTheDocument();
    expect(
      screen.getByText(
        (_, element) =>
          element?.textContent ===
          "Submission and cancellation are not enabled for Local Mock Cluster.",
      ),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Review job request" }),
    ).not.toBeInTheDocument();
  });

  it("reviews an exact request before submitting it with confirmation", async () => {
    const user = userEvent.setup();
    const fetchMock = installApiMock();
    renderApp("/jobs/submit");

    expect(
      await screen.findByRole("heading", { name: "Submit a job" }),
    ).toBeInTheDocument();
    expect(
      (screen.getByLabelText("Batch script") as HTMLTextAreaElement).value,
    ).toContain("set -euo pipefail");

    const name = screen.getByLabelText("Job name");
    await user.clear(name);
    await user.type(name, "gpu-check");
    await user.type(screen.getByLabelText("Partition"), "gpu");

    const nodes = screen.getByLabelText("Nodes");
    await user.clear(nodes);
    await user.type(nodes, "2");

    const cpus = screen.getByLabelText("CPUs per task");
    await user.clear(cpus);
    await user.type(cpus, "4");

    const gpus = screen.getByLabelText("GPUs per node");
    await user.clear(gpus);
    await user.type(gpus, "1");

    await user.click(
      screen.getByRole("button", { name: "Review job request" }),
    );

    expect(
      screen.getByRole("heading", { name: "Review before submitting" }),
    ).toBeInTheDocument();
    expect(screen.getByText("Not submitted")).toBeInTheDocument();
    expect(screen.getByText("gpu-check")).toBeInTheDocument();
    expect(
      fetchMock.mock.calls.some(([, init]) => init?.method === "POST"),
    ).toBe(false);

    await user.click(
      screen.getByRole("button", { name: "Confirm and submit job" }),
    );

    expect(
      await screen.findByRole("heading", { name: "Job 20001 is in Slurm" }),
    ).toBeInTheDocument();
    const postCall = fetchMock.mock.calls.find(
      ([, init]) => init?.method === "POST",
    );
    expect(postCall).toBeDefined();
    const options = postCall?.[1];
    expect(options?.headers).toMatchObject({
      "Content-Type": "application/json",
      "X-Cluster-Monitor-Action": "confirmed",
    });
    expect(JSON.parse(String(options?.body))).toEqual({
      job_name: "gpu-check",
      script:
        '#!/bin/bash\nset -euo pipefail\n\necho "Starting Slurm job"\nsrun hostname',
      partition: "gpu",
      nodes: 2,
      cpus_per_task: 4,
      memory_mb: 1024,
      time_limit_minutes: 10,
      gpus_per_node: 1,
    });
  });

  it("disables confirmation while submission is pending", async () => {
    const user = userEvent.setup();
    installApiMock({
      submitJob: new Promise<Response>(() => undefined),
    });
    renderApp("/jobs/submit");

    await screen.findByRole("heading", { name: "Submit a job" });
    await user.click(
      screen.getByRole("button", { name: "Review job request" }),
    );
    await user.click(
      screen.getByRole("button", { name: "Confirm and submit job" }),
    );

    expect(
      screen.getByRole("button", { name: "Submitting job…" }),
    ).toBeDisabled();
    expect(screen.getByRole("button", { name: "Edit request" })).toBeDisabled();
  });

  it("surfaces a rejected submission without retrying automatically", async () => {
    const user = userEvent.setup();
    const fetchMock = installApiMock({
      submitJob: jsonResponse(
        {
          error: {
            code: "job_action_rejected",
            message: "The selected partition rejected this resource request.",
          },
        },
        409,
      ),
    });
    renderApp("/jobs/submit");

    await screen.findByRole("heading", { name: "Submit a job" });
    await user.click(
      screen.getByRole("button", { name: "Review job request" }),
    );
    await user.click(
      screen.getByRole("button", { name: "Confirm and submit job" }),
    );

    const alert = await screen.findByRole("alert");
    expect(
      within(alert).getByText(
        "The selected partition rejected this resource request.",
      ),
    ).toBeInTheDocument();
    expect(
      fetchMock.mock.calls.filter(([, init]) => init?.method === "POST"),
    ).toHaveLength(1);
    expect(
      screen.getByRole("button", { name: "Confirm and submit job" }),
    ).toBeEnabled();
  });

  it("names the active job in confirmation before cancelling", async () => {
    const user = userEvent.setup();
    const fetchMock = installApiMock();
    renderApp("/jobs/18432");

    await screen.findByRole("heading", { name: "protein-folding" });
    await user.click(screen.getByRole("button", { name: "Cancel job" }));

    const confirmation = screen.getByRole("alertdialog");
    expect(
      within(confirmation).getByRole("heading", {
        name: "Cancel job 18432?",
      }),
    ).toBeInTheDocument();
    expect(
      fetchMock.mock.calls.some(([, init]) => init?.method === "DELETE"),
    ).toBe(false);

    await user.click(
      within(confirmation).getByRole("button", {
        name: "Yes, cancel job 18432",
      }),
    );

    expect(
      await screen.findByText("Cancellation requested for job 18432."),
    ).toBeInTheDocument();
    const deleteCall = fetchMock.mock.calls.find(
      ([, init]) => init?.method === "DELETE",
    );
    expect(deleteCall?.[1]?.headers).toMatchObject({
      "X-Cluster-Monitor-Action": "confirmed",
    });
  });

  it("surfaces an uncertain cancellation outcome and does not auto-retry", async () => {
    const user = userEvent.setup();
    const fetchMock = installApiMock({
      cancelJob: jsonResponse(
        {
          error: {
            code: "job_action_outcome_uncertain",
            message:
              "The SSH connection closed before cancellation could be confirmed.",
          },
        },
        504,
      ),
    });
    renderApp("/jobs/18432");

    await screen.findByRole("heading", { name: "protein-folding" });
    await user.click(screen.getByRole("button", { name: "Cancel job" }));
    await user.click(
      screen.getByRole("button", { name: "Yes, cancel job 18432" }),
    );

    const alert = await screen.findByRole("alert");
    expect(
      within(alert).getByText(
        "The SSH connection closed before cancellation could be confirmed.",
      ),
    ).toBeInTheDocument();
    expect(
      fetchMock.mock.calls.filter(([, init]) => init?.method === "DELETE"),
    ).toHaveLength(1);
  });

  it("does not offer cancellation for an inactive job", async () => {
    installApiMock({
      job: jsonResponse({
        ...mockJobDetails,
        state: "completed",
        state_raw: "COMPLETED",
        end_time: "2026-07-26T09:00:00Z",
      }),
    });
    renderApp("/jobs/18432");

    await screen.findByRole("heading", { name: "protein-folding" });
    expect(
      screen.queryByRole("button", { name: "Cancel job" }),
    ).not.toBeInTheDocument();
  });

  it("does not offer cancellation for an array task ID", async () => {
    installApiMock({
      job: jsonResponse({
        ...mockJobDetails,
        job_id: "18432_7",
      }),
    });
    renderApp("/jobs/18432_7");

    await screen.findByRole("heading", { name: "protein-folding" });
    expect(
      screen.queryByRole("button", { name: "Cancel job" }),
    ).not.toBeInTheDocument();
    expect(
      screen.getByText(
        "Array and heterogeneous job cancellation is not supported yet.",
      ),
    ).toBeInTheDocument();
  });

  it("does not offer cancellation for a numeric array leader", async () => {
    installApiMock({
      job: jsonResponse({
        ...mockJobDetails,
        job_id: "18432",
        array_job_id: "18432",
        array_task_id: "1-128%8",
      }),
    });
    renderApp("/jobs/18432");

    await screen.findByRole("heading", { name: "protein-folding" });
    expect(
      screen.queryByRole("button", { name: "Cancel job" }),
    ).not.toBeInTheDocument();
    expect(
      screen.getByText(
        "Array and heterogeneous job cancellation is not supported yet.",
      ),
    ).toBeInTheDocument();
  });

  it("does not offer cancellation when cluster actions are disabled", async () => {
    installApiMock({
      clusters: jsonResponse([
        {
          ...mockCluster,
          job_actions_enabled: false,
        },
      ]),
    });
    renderApp("/jobs/18432");

    await screen.findByRole("heading", { name: "protein-folding" });
    expect(
      screen.queryByRole("button", { name: "Cancel job" }),
    ).not.toBeInTheDocument();
    expect(
      screen.getByText("Job actions are disabled for this cluster."),
    ).toBeInTheDocument();
  });
});
