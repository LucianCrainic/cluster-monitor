from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from cluster_monitor.connection import build_remote_command
from cluster_monitor.models import JobSubmissionRequest
from cluster_monitor.slurm.commands import (
    build_file_test_command,
    build_nodes_json_command,
    build_nodes_text_command,
    build_partitions_json_command,
    build_partitions_text_command,
    build_remote_user_command,
    build_sacct_job_logs_text_command,
    build_sacct_json_command,
    build_sacct_text_command,
    build_sbatch_command,
    build_scancel_command,
    build_scontrol_job_json_command,
    build_scontrol_job_text_command,
    build_squeue_json_command,
    build_squeue_text_command,
    build_tail_command,
)
from cluster_monitor.slurm.text_parser import (
    NODE_SINFO_FORMAT,
    PARTITION_SINFO_FORMAT,
    SACCT_JOB_FIELDS,
    SQUEUE_JOB_FORMAT,
)


def test_read_only_inventory_commands_use_fixed_formats() -> None:
    assert build_remote_user_command().arguments == ("-un",)
    assert build_partitions_json_command().arguments == ("--json",)
    assert build_nodes_json_command().arguments == ("--json", "--Node")
    assert build_partitions_text_command().arguments == (
        "--noheader",
        "--summarize",
        f"--format={PARTITION_SINFO_FORMAT}",
    )
    assert build_nodes_text_command().arguments == (
        "--noheader",
        "--Node",
        "--exact",
        f"--format={NODE_SINFO_FORMAT}",
    )


def test_user_scoped_job_commands_keep_filters_inside_options() -> None:
    assert build_squeue_json_command("researcher").arguments == (
        "--json",
        "--user=researcher",
    )
    assert build_squeue_text_command("researcher").arguments == (
        "--noheader",
        "--user=researcher",
        f"--Format={SQUEUE_JOB_FORMAT}",
    )
    assert build_sacct_json_command("researcher").arguments == (
        "--json",
        "--allocations",
        "--user=researcher",
        "--starttime=now-7days",
    )
    assert build_sacct_text_command("researcher").arguments == (
        "--allocations",
        "--parsable2",
        "--noheader",
        "--user=researcher",
        "--starttime=now-7days",
        f"--format={','.join(SACCT_JOB_FIELDS)}",
    )


def test_targeted_accounting_commands_validate_job_ids() -> None:
    command = build_sacct_json_command("researcher", job_id="12345_7")
    assert command.arguments[-1] == "--jobs=12345_7"
    assert command.command_type == "sacct_job_json"

    with pytest.raises(ValueError):
        build_sacct_json_command("researcher", job_id="123; squeue")


def test_job_log_commands_are_fixed_and_keep_paths_in_one_argument() -> None:
    path = "/home/researcher/logs/a b;$(touch nope).out"

    assert build_scontrol_job_json_command("12345_7").arguments == (
        "--json",
        "show",
        "job",
        "12345_7",
    )
    assert build_scontrol_job_text_command("12345_7").arguments[-1] == "12345_7"
    assert (
        "--expand-patterns" in build_sacct_job_logs_text_command("researcher", "12345_7").arguments
    )
    assert build_file_test_command(path, "readable").arguments == ("-r", path)
    tail = build_tail_command(path, initial_lines=200, follow=True)
    assert tail.executable == "tail"
    assert tail.arguments == (
        "--lines=200",
        "--follow=name",
        "--retry",
        "--",
        path,
    )
    assert build_remote_command(tail.executable, tail.arguments).endswith(
        "'/home/researcher/logs/a b;$(touch nope).out'"
    )

    with pytest.raises(ValueError):
        build_scontrol_job_json_command("123.batch")


def test_submission_command_uses_validated_options_and_stdin_script_boundary() -> None:
    request = JobSubmissionRequest(
        job_name="gpu-train",
        script="#!/usr/bin/env bash\npython train.py\n",
        partition="students",
        nodes=2,
        cpus_per_task=8,
        memory_mb=16_384,
        time_limit_minutes=90,
        gpus_per_node=2,
    )

    command = build_sbatch_command(request)

    assert command.executable == "/usr/bin/env"
    assert command.command_type == "sbatch_submit"
    assert command.arguments == (
        "-u",
        "BASH_ENV",
        "-u",
        "ENV",
        "/bin/bash",
        "--noprofile",
        "--norc",
        "-p",
        "-c",
        'for name in "${!SBATCH_@}"; do unset "$name"; done; '
        'unset SLURM_CLUSTERS; exec sbatch "$@"',
        "cluster-monitor-sbatch",
        "--parsable",
        "--job-name=gpu-train",
        "--nodes=2",
        "--cpus-per-task=8",
        "--time=90",
        "--partition=students",
        "--mem=16384M",
        "--gres=gpu:2",
    )
    assert build_remote_command(command.executable, command.arguments) == (
        "/usr/bin/env -u BASH_ENV -u ENV /bin/bash --noprofile --norc -p -c "
        """'for name in "${!SBATCH_@}"; do unset "$name"; done; """
        """unset SLURM_CLUSTERS; exec sbatch "$@"' cluster-monitor-sbatch """
        "--parsable --job-name=gpu-train --nodes=2 --cpus-per-task=8 --time=90 "
        "--partition=students --mem=16384M --gres=gpu:2"
    )
    assert all("python train.py" not in argument for argument in command.arguments)
    assert all(not argument.startswith("SBATCH_") for argument in command.arguments)
    assert all(not argument.startswith("SLURM_CLUSTERS=") for argument in command.arguments)


def test_submission_wrapper_scrubs_scheduler_environment_only(
    tmp_path: Path,
) -> None:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    capture_path = tmp_path / "capture.json"
    startup_marker = tmp_path / "startup-ran"
    startup_script = tmp_path / "startup.sh"
    startup_script.write_text(
        'export SBATCH_FROM_STARTUP="injected"\n: > "$BASH_ENV_MARKER"\n',
        encoding="utf-8",
    )
    fake_sbatch = fake_bin / "sbatch"
    fake_sbatch.write_text(
        "#!/usr/bin/env python3\n"
        "import json\n"
        "import os\n"
        "import sys\n"
        "from pathlib import Path\n"
        "scheduler_environment = {\n"
        "    name: value\n"
        "    for name, value in os.environ.items()\n"
        '    if name.startswith("SBATCH_") or name == "SLURM_CLUSTERS"\n'
        "}\n"
        "payload = {\n"
        '    "arguments": sys.argv[1:],\n'
        '    "stdin": sys.stdin.read(),\n'
        '    "safe_environment": os.environ.get("SAFE_UNRELATED"),\n'
        '    "scheduler_environment": scheduler_environment,\n'
        '    "startup_environment": {\n'
        "        name: os.environ[name]\n"
        '        for name in ("BASH_ENV", "ENV")\n'
        "        if name in os.environ\n"
        "    },\n"
        "}\n"
        'Path(os.environ["CAPTURE_PATH"]).write_text(\n'
        '    json.dumps(payload), encoding="utf-8"\n'
        ")\n",
        encoding="utf-8",
    )
    fake_sbatch.chmod(0o755)

    request = JobSubmissionRequest(
        job_name="wrapper-test",
        script="#!/usr/bin/env bash\nprintf 'stdin remains exact\\n'\n",
        nodes=3,
        cpus_per_task=4,
        time_limit_minutes=12,
    )
    command = build_sbatch_command(request)
    environment = os.environ.copy()
    environment.update(
        {
            "PATH": f"{fake_bin}{os.pathsep}{environment['PATH']}",
            "CAPTURE_PATH": str(capture_path),
            "SAFE_UNRELATED": "survives",
            "SBATCH_ARRAY_INX": "1-99",
            "SBATCH_PARTITION": "wrong-partition",
            "SLURM_CLUSTERS": "wrong-cluster",
            "BASH_ENV": str(startup_script),
            "ENV": str(startup_script),
            "BASH_ENV_MARKER": str(startup_marker),
        }
    )

    subprocess.run(
        [command.executable, *command.arguments],
        input=request.script,
        text=True,
        env=environment,
        check=True,
    )

    captured = json.loads(capture_path.read_text(encoding="utf-8"))
    assert captured == {
        "arguments": [
            "--parsable",
            "--job-name=wrapper-test",
            "--nodes=3",
            "--cpus-per-task=4",
            "--time=12",
        ],
        "stdin": request.script,
        "safe_environment": "survives",
        "scheduler_environment": {},
        "startup_environment": {},
    }
    assert not startup_marker.exists()


def test_cancel_command_accepts_only_one_validated_job_id() -> None:
    assert build_scancel_command("12345").arguments == ("--quiet", "12345")

    with pytest.raises(ValueError):
        build_scancel_command("--user=all")
    with pytest.raises(ValueError):
        build_scancel_command("12345_7")


@pytest.mark.parametrize("user", ["--all", "name with spaces", "bad\nname", ""])
def test_job_commands_reject_invalid_users(user: str) -> None:
    with pytest.raises(ValueError):
        build_squeue_json_command(user)
