from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
import yaml

from tools.ci_candidate_evidence import _PROTECTED_PRODUCER_FILES
from tools.ci_candidate_runner import _command_environment

ROOT = Path(__file__).resolve().parents[2]
PROTECTED_WORKFLOW = ROOT / ".github" / "workflows" / "protected-ci-evidence-gate.yml"
CHECKOUT_PIN = "actions/checkout@11d5960a326750d5838078e36cf38b85af677262"
UPLOAD_PIN = "actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02"
PULL_REQUEST_WORKFLOWS_DIR = ROOT / ".github" / "workflows"
PULL_REQUEST_READY_TO_DRAFT_EVENTS = ("ready_for_review", "converted_to_draft")
# THE COMPLETE ACTIVITY SET, not only the two draft transitions. Naming `types`
# explicitly REPLACES GitHub's default set, so a workflow that lists the draft
# transitions and drops `synchronize` stops rerunning on new commits -- a ready pull
# request would then keep a green check set that describes an older tree. Asserting only
# the two transitions left that mutation green.
PULL_REQUEST_REQUIRED_EVENTS = (
    "opened",
    "synchronize",
    "reopened",
    "ready_for_review",
    "converted_to_draft",
)
PULL_REQUEST_DRAFT_GATE = "github.event.pull_request.draft == false"
# Every expression reviewed as CANCELLING a pull-request run. Membership, never a
# substring search: `${{ github.event_name != 'pull_request' }}` contains the word and
# means the opposite.
_APPROVED_CANCEL_EXPRESSIONS = frozenset(
    {
        "${{ github.event_name == 'pull_request' }}",
        "${{ github.ref != 'refs/heads/master' }}",
    }
)
# Every concurrency group reviewed as giving each pull request its OWN group, KEYED BY
# THE WORKFLOW IT BELONGS TO. Two reasons it is not a plain set of strings:
#
#   * membership rather than a substring search, because
#     `${{ startsWith(github.ref, 'refs/pull/') }}` mentions `github.ref` and evaluates to
#     the SAME group for every pull request, so activity on one cancels the jobs of the
#     pull request that is about to merge;
#   * keyed by workflow, because a set alone lets one workflow adopt ANOTHER's reviewed
#     group. Give `main.yml` the docs-gate group and both then share a group on a pull
#     request while both enable cancellation -- whichever starts later cancels the other's
#     required run, and a required context that was cancelled waits forever.
#
# `${{ github.workflow }}` already differs per workflow, which is why three of them share
# that expression; `docs-gate.yml` spells its own name instead and therefore gets its own
# entry rather than the shared one.
_APPROVED_CONCURRENCY_GROUPS: dict[str, str] = {
    "main.yml": "${{ github.workflow }}-${{ github.ref }}",
    "protected-ci-evidence-gate.yml": "${{ github.workflow }}-${{ github.ref }}",
    "windows-onedir-smoke.yml": "${{ github.workflow }}-${{ github.ref }}",
    "docs-gate.yml": "docs-gate-${{ github.ref }}",
}
# `${{ github.workflow }}` is the workflow's top-level NAME, not its file name. Three
# workflows share that expression, so their groups are distinct only while their names
# are. Give two of them the same `name:` and they collide on a pull request while both
# cancel -- either can then cancel the other's required run, and the filename-to-
# expression table above would still accept it. So the group is EVALUATED for one
# pull-request ref and the results must be distinct.
_GROUP_PROBE_REF = "refs/pull/9999/merge"


def _evaluated_group(payload: dict, group: str) -> str:
    """Substitute the two context values these groups use, and nothing else.

    A general expression evaluator is not needed and would be worse: the reviewed groups
    use exactly these two, and a group that used anything else would fail the exact
    comparison before reaching here.
    """

    workflow_name = payload.get("name")
    assert isinstance(workflow_name, str) and workflow_name, "workflow has no top-level name"
    return group.replace("${{ github.workflow }}", workflow_name).replace("${{ github.ref }}", _GROUP_PROBE_REF)


# Every job condition reviewed as running the job on a ready pull request and NOT on a
# draft. Membership again: `... || true` contains the whole draft comparison and runs
# every expensive job on every draft.
# KEYED BY WORKFLOW AND BY JOB. A global list lets a job borrow an expression reviewed
# for a different dependency role: give `main.yml`'s `test` job the protected final
# gate's `!cancelled() && always() && ...` and `always()` overrides the normal skip when
# `candidate_identity` fails, so all eight matrix jobs launch with empty identity outputs
# and a default checkout before failing. Same string, different role, different outcome.
_ORDINARY_DRAFT_CONDITION = "${{ github.event_name != 'pull_request' || github.event.pull_request.draft == false }}"
_FINAL_GATE_DRAFT_CONDITION = (
    "${{ !cancelled() && always() && (github.event_name != 'pull_request'"
    " || github.event.pull_request.draft == false) }}"
)
_APPROVED_JOB_CONDITIONS: dict[tuple[str, str], str] = {
    ("main.yml", "candidate_identity"): _ORDINARY_DRAFT_CONDITION,
    ("main.yml", "test"): _ORDINARY_DRAFT_CONDITION,
    ("docs-gate.yml", "docs-freshness"): _ORDINARY_DRAFT_CONDITION,
    ("windows-onedir-smoke.yml", "windows-onedir"): _ORDINARY_DRAFT_CONDITION,
    ("protected-ci-evidence-gate.yml", "protected-execution"): _ORDINARY_DRAFT_CONDITION,
    ("protected-ci-evidence-gate.yml", "protected-ci-evidence-gate"): _FINAL_GATE_DRAFT_CONDITION,
}


def _workflow_trigger(payload: dict) -> dict:
    # PyYAML 1.1 parses the unquoted YAML key ``on`` as boolean true.
    return payload.get("on", payload.get(True))


def _immutable_paths(step: dict) -> tuple[str, ...]:
    lines = [line.strip() for line in step["run"].splitlines()]
    continuation = chr(92)
    start = lines.index(f"for path in {continuation}") + 1
    paths = []
    for line in lines[start:]:
        if line.endswith("; do"):
            paths.append(line.removesuffix("; do"))
            break
        assert line.endswith(continuation)
        paths.append(line.removesuffix(continuation).rstrip())
    return tuple(paths)


def _expected_immutable_paths() -> tuple[str, ...]:
    producer_files = _PROTECTED_PRODUCER_FILES
    anchor = producer_files.index("environment.yml") + 1
    return (*producer_files[:anchor], "requirements-lock.txt", *producer_files[anchor:])


def _pull_request_workflows() -> tuple[tuple[str, dict], ...]:
    """Every workflow under `.github/workflows` that reacts to pull_request events.

    BOTH EXTENSIONS. GitHub runs `.yaml` as readily as `.yml`, so a scan for one of
    them lets a real workflow run in production while this parametrization omits it --
    and an omitted workflow is an ungated draft job under a green suite. That is the
    exact shape this guard exists to refuse, arriving through the guard's own reader.
    """

    workflows = []
    for path in sorted(
        {candidate for pattern in ("*.yml", "*.yaml") for candidate in PULL_REQUEST_WORKFLOWS_DIR.glob(pattern)}
    ):
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
        if "pull_request" in _workflow_trigger(payload):
            workflows.append((path.name, payload))
    return tuple(workflows)


def test_every_protected_producer_file_is_pinned_to_lf(tmp_path: Path) -> None:
    attributes_root = tmp_path / "attributes"
    attributes_root.mkdir()
    attributes_raw = (ROOT / ".gitattributes").read_bytes()
    (attributes_root / ".gitattributes").write_bytes(attributes_raw)
    subprocess.run(
        ["git", "init", "--quiet"],
        cwd=attributes_root,
        check=True,
        capture_output=True,
    )
    completed = subprocess.run(
        ["git", "check-attr", "-z", "text", "eol", "--", *_PROTECTED_PRODUCER_FILES],
        cwd=attributes_root,
        check=True,
        capture_output=True,
    )
    fields = completed.stdout.split(b"\0")
    assert fields.pop() == b""
    attributes = {
        (path.decode("utf-8"), name.decode("utf-8")): value.decode("utf-8")
        for path, name, value in zip(fields[::3], fields[1::3], fields[2::3], strict=True)
    }
    assert attributes == {
        (path, attribute): value
        for path in _PROTECTED_PRODUCER_FILES
        for attribute, value in (("text", "set"), ("eol", "lf"))
    }
    assert b"\r" not in attributes_raw
    assert all(b"\r" not in (ROOT / path).read_bytes() for path in _PROTECTED_PRODUCER_FILES)


def _assert_workflow_source(step: dict) -> None:
    assert step["id"] == "workflow-source"
    assert step["shell"] == "bash"
    assert "GITHUB_WORKFLOW_REF" in step["run"]
    assert r"\.github/workflows/protected-ci-evidence-gate\.yml" in step["run"]
    assert "@(refs/.+)$" in step["run"]
    assert 'test "$source_repository" = "${GITHUB_REPOSITORY:?}"' in step["run"]
    assert '[[ "${JUDGE_SHA:?}" =~ ^[0-9a-f]{40}$ ]]' in step["run"]
    assert "repository=%s" in step["run"]


def test_protected_workflow_is_native_and_candidate_bound() -> None:
    text = PROTECTED_WORKFLOW.read_text(encoding="utf-8")
    payload = yaml.safe_load(text)

    assert _workflow_trigger(payload) == {
        "pull_request": {
            "types": [
                "opened",
                "synchronize",
                "reopened",
                "ready_for_review",
                "converted_to_draft",
            ]
        },
        "merge_group": None,
    }
    assert payload["concurrency"] == {
        "group": "${{ github.workflow }}-${{ github.ref }}",
        "cancel-in-progress": "${{ github.event_name == 'pull_request' }}",
    }

    assert "workflow_run" not in text
    assert "checks: write" not in text
    assert "check-runs" not in text
    assert "--method POST" not in text
    assert "--method PATCH" not in text
    assert "candidate-check" not in payload["jobs"]
    assert set(payload["jobs"]) == {"protected-execution", "protected-ci-evidence-gate"}

    execution = payload["jobs"]["protected-execution"]
    assert execution["if"] == ("${{ github.event_name != 'pull_request' || github.event.pull_request.draft == false }}")
    assert "needs" not in execution
    assert execution["permissions"] == {"actions": "read", "contents": "read", "id-token": "write"}
    assert execution["strategy"] == {
        "fail-fast": False,
        "matrix": {
            "os": ["ubuntu-latest", "windows-latest"],
            "suite": ["core", "gui", "agents", "remaining"],
        },
    }
    assert execution["env"]["TARGET_SHA"] == "${{ github.sha }}"
    assert execution["env"]["TARGET_RUN_ID"] == "${{ github.run_id }}"
    assert execution["env"]["TARGET_RUN_ATTEMPT"] == "${{ github.run_attempt }}"
    assert execution["env"]["ARTIFACT_NAME"].endswith("-${{ github.run_id }}-${{ github.run_attempt }}")
    assert "GITHUB_JOB_CHECK_RUN_ID" not in execution["env"]

    steps = execution["steps"]
    source = next(step for step in steps if step.get("id") == "workflow-source")
    _assert_workflow_source(source)
    candidate_checkout = next(step for step in steps if step.get("name") == "Check out candidate")
    judge_checkout = next(step for step in steps if step.get("name") == "Check out immutable producer")
    assert candidate_checkout["uses"] == CHECKOUT_PIN
    assert candidate_checkout["with"]["ref"] == "${{ env.TARGET_SHA }}"
    assert candidate_checkout["with"]["persist-credentials"] is False
    assert judge_checkout["uses"] == CHECKOUT_PIN
    assert judge_checkout["with"]["repository"] == "${{ steps.workflow-source.outputs.repository }}"
    assert judge_checkout["with"]["ref"] == "${{ env.JUDGE_SHA }}"
    assert judge_checkout["with"]["persist-credentials"] is False

    immutable = next(step for step in steps if step["name"] == "Verify immutable producer object")
    producer_paths = _immutable_paths(immutable)
    assert producer_paths == _expected_immutable_paths()
    assert "tools/ci_active_checkout_runner.py" in producer_paths
    assert "tools/ci_required_workflow_context.py" in producer_paths

    setup = next(step for step in steps if step.get("uses", "").startswith("conda-incubator/setup-miniconda@"))
    assert setup["with"]["environment-file"] == "judge/environment.yml"
    dependencies = next(step for step in steps if step.get("name") == "Install immutable producer dependencies")
    assert "pip install -r requirements-protected-ci-lock.txt" in dependencies["run"]
    assert "pip install -r requirements-lock.txt" not in dependencies["run"]
    assert "pip install -e" not in dependencies["run"]

    protected_run = next(step for step in steps if step.get("id") == "protected-run")
    assert protected_run["continue-on-error"] is True
    assert protected_run["env"]["GITHUB_JOB_CHECK_RUN_ID"] == "${{ job.check_run_id }}"
    assert '--revision "${TARGET_SHA:?}"' in protected_run["run"]
    assert '--producer-revision "${JUDGE_SHA:?}"' in protected_run["run"]
    assert "tools.ci_active_checkout_runner" not in protected_run["run"]
    identity = next(step for step in steps if step.get("id") == "job-attestation")
    assert identity["env"]["GITHUB_JOB_CHECK_RUN_ID"] == "${{ job.check_run_id }}"
    upload = next(step for step in steps if step.get("id") == "protected-upload")
    assert upload["uses"] == UPLOAD_PIN
    enforce = next(step for step in steps if step.get("name") == "Enforce protected execution and identity publication")
    assert "steps.protected-run.outcome" in enforce["run"]
    assert "steps.job-attestation.outcome" in enforce["run"]
    assert "steps.protected-upload.outcome" in enforce["run"]


def test_protected_workflow_binds_candidate_interpreter_alias_before_execution() -> None:
    """The git-index soak guards spawn the exact worktree .venv/bin/python.

    The ordinary workflow binds that alias in its own checkout; the protected
    candidate checkout is pristine, so without this step the two POSIX soak
    nodes fail closed with "exact worktree .venv interpreter is unavailable".
    """

    payload = yaml.safe_load(PROTECTED_WORKFLOW.read_text(encoding="utf-8"))
    steps = payload["jobs"]["protected-execution"]["steps"]
    alias = next(step for step in steps if step.get("name") == "Bind reviewed interpreter alias in candidate (Linux)")
    assert alias["if"] == "runner.os == 'Linux'"
    assert alias["working-directory"] == "candidate"
    assert "refusing to reuse an ambient .venv" in alias["run"]
    assert 'ln -s -- "$(command -v python)" .venv/bin/python' in alias["run"]
    assert "Path('/proc/self/exe')" in alias["run"] or 'Path("/proc/self/exe")' in alias["run"]
    protected_run = next(step for step in steps if step.get("id") == "protected-run")
    assert steps.index(alias) < steps.index(protected_run)


def test_native_final_job_is_fail_closed_and_uploads_only_accepted_context() -> None:
    payload = yaml.safe_load(PROTECTED_WORKFLOW.read_text(encoding="utf-8"))
    job = payload["jobs"]["protected-ci-evidence-gate"]
    assert job["name"] == "protected CI evidence gate"
    assert job["needs"] == "protected-execution"
    assert job["if"] == (
        "${{ !cancelled() && always() && "
        "(github.event_name != 'pull_request' || "
        "github.event.pull_request.draft == false) }}"
    )
    assert job["permissions"] == {"actions": "read", "contents": "read"}
    assert job["env"]["TARGET_SHA"] == "${{ github.sha }}"
    assert job["env"]["SOURCE_HEAD_SHA"] == "${{ github.event.pull_request.head.sha || github.sha }}"
    assert job["env"]["TARGET_RUN_ID"] == "${{ github.run_id }}"
    assert job["env"]["TARGET_RUN_ATTEMPT"] == "${{ github.run_attempt }}"

    steps = job["steps"]
    indexed = {step["id"]: step for step in steps if "id" in step}
    _assert_workflow_source(indexed["workflow-source"])
    candidate_checkout = next(step for step in steps if step.get("name") == "Check out candidate")
    assert candidate_checkout["with"]["ref"] == "${{ env.TARGET_SHA }}"
    assert candidate_checkout["with"]["persist-credentials"] is False
    immutable = next(step for step in steps if step["name"] == "Verify immutable judge object")
    assert _immutable_paths(immutable) == _expected_immutable_paths()
    judge_checkout = next(step for step in steps if step.get("name") == "Check out immutable judge")
    assert judge_checkout["with"]["repository"] == "${{ steps.workflow-source.outputs.repository }}"
    assert judge_checkout["with"]["ref"] == "${{ env.JUDGE_SHA }}"
    assert judge_checkout["with"]["persist-credentials"] is False

    context = indexed["context-proof"]
    assert context["working-directory"] == "judge"
    assert context["continue-on-error"] is True
    assert "tools/ci_required_workflow_context.py create" in context["run"]
    assert "tools/ci_required_workflow_context.py verify" in context["run"]
    assert '--event-path "${GITHUB_EVENT_PATH:?}"' in context["run"]
    assert '--repo-root "${GITHUB_WORKSPACE:?}/candidate"' in context["run"]
    assert "accepted-context.json" in context["run"]

    download = indexed["protected-download"]
    assert 'gh run download "${TARGET_RUN_ID:?}"' in download["run"]
    assert "actions/runs/${TARGET_RUN_ID:?}/jobs?per_page=100" in download["run"]
    assert "cryodaq-candidate-" not in download["run"]

    proof = indexed["protected-proof"]
    assert proof["working-directory"] == "judge"
    assert "tools.ci_candidate_evidence verify-protected" in proof["run"]
    assert "ubuntu-latest windows-latest" in proof["run"]
    assert "agents core gui remaining" in proof["run"]
    for required in (
        '--event-name "${GITHUB_EVENT_NAME:?}"',
        '--source-head-sha "${SOURCE_HEAD_SHA:?}"',
        '--target-run-id "${TARGET_RUN_ID:?}"',
        '--target-run-attempt "${TARGET_RUN_ATTEMPT:?}"',
        '--target-sha "${TARGET_SHA:?}"',
        '--workflow-sha "${JUDGE_SHA:?}"',
    ):
        assert required in proof["run"]

    accepted = indexed["context-upload"]
    assert accepted["uses"] == UPLOAD_PIN
    assert accepted["with"]["path"].endswith("/accepted-context.json")
    for condition in (
        "needs.protected-execution.result == 'success'",
        "steps.context-proof.outcome == 'success'",
        "steps.protected-download.outcome == 'success'",
        "steps.protected-proof.outcome == 'success'",
    ):
        assert condition in accepted["if"]

    enforce = next(step for step in steps if step.get("name") == "Enforce native protected evidence gate")
    assert enforce["if"] == "always()"
    assert enforce["env"] == {
        "CONTEXT_OUTCOME": "${{ steps.context-proof.outcome }}",
        "DOWNLOAD_OUTCOME": "${{ steps.protected-download.outcome }}",
        "EXECUTION_OUTCOME": "${{ needs.protected-execution.result }}",
        "PROTECTED_OUTCOME": "${{ steps.protected-proof.outcome }}",
        "UPLOAD_OUTCOME": "${{ steps.context-upload.outcome }}",
    }
    for outcome in ("EXECUTION", "CONTEXT", "DOWNLOAD", "PROTECTED", "UPLOAD"):
        assert f'test "${outcome}_OUTCOME" = success' in enforce["run"]


def test_workflow_has_no_ordinary_ci_or_manual_check_authority() -> None:
    text = PROTECTED_WORKFLOW.read_text(encoding="utf-8")
    forbidden = (
        "tools.ci_partition_execution_proof",
        "tools.montana_candidate_gate",
        "cryodaq-target-artifacts",
        "partition-execution-proof",
        "candidate-download",
        "montana-proof",
        "PARTITION_OUTCOME",
        "MONTANA_OUTCOME",
        "external_id",
        "status=in_progress",
        "conclusion=success",
    )
    for marker in forbidden:
        assert marker not in text


def test_immutable_path_consistency_rejects_drift() -> None:
    payload = yaml.safe_load(PROTECTED_WORKFLOW.read_text(encoding="utf-8"))
    producer_steps = payload["jobs"]["protected-execution"]["steps"]
    judge_steps = payload["jobs"]["protected-ci-evidence-gate"]["steps"]
    producer = _immutable_paths(
        next(step for step in producer_steps if step["name"] == "Verify immutable producer object")
    )
    judge = _immutable_paths(next(step for step in judge_steps if step["name"] == "Verify immutable judge object"))
    expected = _expected_immutable_paths()

    assert producer == expected
    assert judge == expected
    for drifted in (producer[:-1], judge[:-1], (*producer, "extra")):
        with pytest.raises(AssertionError):
            assert drifted == expected


@pytest.mark.parametrize(
    "channel",
    ("GITHUB_ENV", "GITHUB_OUTPUT", "GITHUB_PATH", "GITHUB_STATE", "GITHUB_STEP_SUMMARY"),
)
def test_candidate_environment_strips_workflow_command_channels(
    channel: str,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv(channel, str(tmp_path / channel))

    environment = _command_environment(basetemp=tmp_path / "pytest", suite="core", index=1)

    assert channel not in environment


def test_attestation_uses_absolute_conda_interpreter() -> None:
    payload = yaml.safe_load(PROTECTED_WORKFLOW.read_text(encoding="utf-8"))
    steps = payload["jobs"]["protected-execution"]["steps"]
    identity = next(step for step in steps if step.get("id") == "job-attestation")

    assert 'interpreter="${CONDA_PREFIX:?}' in identity["run"]
    assert '"$interpreter" -B -m tools.ci_candidate_evidence attest-job' in identity["run"]


def test_every_workflow_evaluates_to_its_own_concurrency_group() -> None:
    """`${{ github.workflow }}` is the workflow's NAME, so distinct files can still collide.

    Three workflows share that expression. Give two of them the same top-level `name:` and
    their groups become one group on a pull request while both cancel, so either can
    cancel the other's required run -- and a filename-to-expression table accepts it.
    """

    workflows = _pull_request_workflows()
    evaluated: dict[str, str] = {}
    for name, payload in workflows:
        group = payload["concurrency"]["group"]
        evaluated[name] = _evaluated_group(payload, group)

    collisions = {
        value: sorted(n for n, v in evaluated.items() if v == value)
        for value in set(evaluated.values())
        if list(evaluated.values()).count(value) > 1
    }
    assert not collisions, (
        "these workflows evaluate to the SAME concurrency group for one pull request, so "
        f"either can cancel the other's required run: {collisions}"
    )


def test_draft_gate_expressions_are_compared_not_searched() -> None:
    """The paired guard for DRAFT-GATE-EXPRESSION-EXACT-001.

    THE FALSE GREEN THIS EXISTS FOR IS A GUARD THAT READS AN EXPRESSION INSTEAD OF
    COMPARING IT. Three shapes of it were confirmed on this branch, each one a
    deterministic failure that a green suite had already survived:

    * a job condition widened with `|| true` still CONTAINS the whole draft comparison,
      and runs every expensive job on every draft;
    * a concurrency group that merely MENTIONS `github.ref` can be the same for every
      pull request, so activity on one cancels the jobs of the one about to merge;
    * one workflow adopting ANOTHER's reviewed group passes a global membership check,
      and then both share a group while both cancel.

    So this runs those mutations against the real workflow payloads and requires the
    gating assertion to reject each one. It calls the production assertion rather than
    restating it, which is what makes weakening that assertion visible here.
    """

    import copy

    workflows = dict(_pull_request_workflows())
    assert "main.yml" in workflows, "the ordinary workflow is missing from the inventory"

    def _refuses(name: str, payload: dict) -> bool:
        try:
            test_every_pull_request_workflow_keeps_ready_to_draft_gating(name, payload)
        except AssertionError:
            return True
        return False

    # The unmutated payload must PASS, or the mutations below prove nothing.
    assert not _refuses("main.yml", copy.deepcopy(workflows["main.yml"])), (
        "the reviewed workflow does not satisfy its own gating assertion"
    )

    widened = copy.deepcopy(workflows["main.yml"])
    for job in widened["jobs"].values():
        job["if"] = f"{job['if']} || true"
    assert _refuses("main.yml", widened), "a condition widened with `|| true` was accepted"

    constant_group = copy.deepcopy(workflows["main.yml"])
    constant_group["concurrency"]["group"] = "${{ startsWith(github.ref, 'refs/pull/') }}"
    assert _refuses("main.yml", constant_group), "a group that is constant per pull request was accepted"

    borrowed_group = copy.deepcopy(workflows["main.yml"])
    borrowed_group["concurrency"]["group"] = _APPROVED_CONCURRENCY_GROUPS["docs-gate.yml"]
    assert _refuses("main.yml", borrowed_group), (
        "one workflow adopted another's reviewed group and the guard accepted it"
    )

    inverted_cancel = copy.deepcopy(workflows["main.yml"])
    inverted_cancel["concurrency"]["cancel-in-progress"] = "${{ github.event_name != 'pull_request' }}"
    assert _refuses("main.yml", inverted_cancel), "an inverted cancellation expression was accepted"

    borrowed_condition = copy.deepcopy(workflows["main.yml"])
    borrowed_condition["jobs"]["test"]["if"] = _FINAL_GATE_DRAFT_CONDITION
    assert _refuses("main.yml", borrowed_condition), (
        "a job borrowed a condition reviewed for a different dependency role and was accepted"
    )

    # And the rename that makes two DIFFERENT files share one evaluated group.
    renamed = copy.deepcopy(workflows["main.yml"])
    renamed["name"] = dict(workflows)["protected-ci-evidence-gate.yml"]["name"]
    assert _evaluated_group(renamed, renamed["concurrency"]["group"]) == _evaluated_group(
        dict(workflows)["protected-ci-evidence-gate.yml"],
        dict(workflows)["protected-ci-evidence-gate.yml"]["concurrency"]["group"],
    ), "the rename does not actually collide, so this mutation proves nothing"


@pytest.mark.parametrize(
    ("workflow_name", "payload"),
    _pull_request_workflows(),
    ids=[name for name, _ in _pull_request_workflows()],
)
def test_every_pull_request_workflow_keeps_ready_to_draft_gating(workflow_name: str, payload: dict) -> None:
    """Every pull_request workflow must keep its ready-to-draft gating.

    A confirmed gap corrected by this PR was the ONEDIR workflow omitting the
    draft gate while the regression only parsed the protected workflow. This
    enumerates every pull_request workflow, so removing the gating from any of
    them -- the trigger events, the job condition, or the cancellation
    configuration -- fails the suite instead of passing green.
    """

    trigger = _workflow_trigger(payload)
    pr_trigger = trigger["pull_request"]
    assert pr_trigger is not None, f"{workflow_name}: pull_request trigger has no types"
    declared = set(pr_trigger["types"])
    missing = sorted(set(PULL_REQUEST_REQUIRED_EVENTS) - declared)
    assert not missing, (
        f"{workflow_name}: pull_request types omit {missing}. Declaring `types` replaces "
        "GitHub's default set, so a missing `synchronize` stops the workflow rerunning on "
        "new commits and leaves a green check set describing an older tree."
    )

    concurrency = payload["concurrency"]
    group = concurrency["group"]
    expected_group = _APPROVED_CONCURRENCY_GROUPS.get(workflow_name)
    assert expected_group is not None, (
        f"{workflow_name}: no reviewed concurrency group is recorded for this workflow. A new "
        "pull_request workflow must have its group reviewed here, not inherit one by accident."
    )
    assert group == expected_group, (
        f"{workflow_name}: concurrency group is {group!r}, and the group reviewed for THIS "
        f"workflow is {expected_group!r}. Two things this refuses: a group that merely mentions "
        "`github.ref` and is therefore the same for every pull request; and one workflow "
        "adopting another's reviewed group, after which both share a group on a pull request "
        "while both cancel, so whichever starts later cancels the other's required run."
    )
    # AN APPROVED EXPRESSION, not a mention of the word. Asking whether the string
    # CONTAINS "pull_request" accepts `${{ github.event_name != 'pull_request' }}`, which
    # disables cancellation for exactly the runs this is meant to cancel -- so the
    # ready-to-draft cancellation defect could be restored without reddening anything.
    cancel = concurrency["cancel-in-progress"]
    assert cancel is True or cancel in _APPROVED_CANCEL_EXPRESSIONS, (
        f"{workflow_name}: cancel-in-progress is {cancel!r}, which is neither `true` nor one "
        f"of the reviewed expressions {sorted(_APPROVED_CANCEL_EXPRESSIONS)}. A new expression "
        "must be added here deliberately, after someone works out what it does on a "
        "pull_request event."
    )

    for job_name, job in payload["jobs"].items():
        condition = job.get("if", "")
        expected_condition = _APPROVED_JOB_CONDITIONS.get((workflow_name, job_name))
        assert expected_condition is not None, (
            f"{workflow_name}: job {job_name!r} has no reviewed condition of its own. A new job "
            "must have its condition reviewed here rather than inheriting one by accident."
        )
        assert condition == expected_condition, (
            f"{workflow_name}: job {job_name!r} has condition {condition!r}, and the condition "
            f"reviewed for THIS job is {expected_condition!r}. Two things this refuses: a "
            "condition widened with `|| true`, which runs every expensive job on every draft; "
            "and a job borrowing an expression reviewed for a different dependency role, where "
            "`always()` overrides the normal skip on a failed `needs` and launches the matrix "
            "with empty identity outputs."
        )
