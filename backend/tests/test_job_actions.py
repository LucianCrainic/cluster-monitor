from __future__ import annotations

import pytest
from pydantic import ValidationError

from cluster_monitor.models import JobSubmissionRequest


def test_submission_request_normalizes_one_trailing_newline() -> None:
    request = JobSubmissionRequest(
        job_name="safe-job_1",
        script="#!/usr/bin/env bash\nhostname",
    )

    assert request.script == "#!/usr/bin/env bash\nhostname\n"
    assert request.nodes == 1
    assert request.gpus_per_node == 0


@pytest.mark.parametrize(
    "script",
    [
        "hostname\n",
        "#!/usr/bin/env bash\r\nhostname\r\n",
        "#!/usr/bin/env bash\nprintf '\\0'\x00\n",
        "#!/usr/bin/env bash\n#SBATCH --array=1-100\nhostname\n",
        "#!/usr/bin/env bash\n  #SBATCH --exclusive\nhostname\n",
    ],
)
def test_submission_request_rejects_ambiguous_or_bypassing_scripts(script: str) -> None:
    with pytest.raises(ValidationError):
        JobSubmissionRequest(job_name="safe-job", script=script)


@pytest.mark.parametrize("job_name", ["--exclusive", "has spaces", "bad\nname"])
def test_submission_request_rejects_unsafe_job_names(job_name: str) -> None:
    with pytest.raises(ValidationError):
        JobSubmissionRequest(
            job_name=job_name,
            script="#!/usr/bin/env bash\ntrue\n",
        )
