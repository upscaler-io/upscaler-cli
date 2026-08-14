"""Compliance framework management CLI commands.

Inspects and manages installed compliance frameworks (tenant-side).
Wraps POST /api/v1/frameworks on the up-ai REST API.
"""

import sys

import click

from upscaler_cli.cli.context import pass_context
from upscaler_cli.cli.helpers import execute_rest_action


@click.group("framework")
def framework_group():
    """Manage installed compliance frameworks (ISO 27001 etc.).

    The installed-framework id is the catalog id (a colon, e.g. ``iso27001:2022``),
    NOT an ``if_*`` value and NOT the hyphen form. A hyphen form (``iso27001-2022``)
    is normalized to the colon form for convenience.

    Examples:
        upscaler framework list-installed
        upscaler framework get-installed iso27001:2022
        upscaler framework list-contributions --asset-id d_xyz
        upscaler framework list-test-bindings --asset-id d_xyz
        upscaler framework list-requirement-contributions \\
            --framework-id iso27001:2022 --requirement-id A.5.1
        upscaler framework bind --framework-id iso27001:2022 --data @binding.json
        upscaler framework set-test-binding --framework-id iso27001:2022 \\
            --requirement-id A.5.1 --test-id t-exists --asset-id d_xyz
        upscaler framework evaluate --framework-id iso27001:2022 --requirement-id A.5.1
    """
    pass


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------


@framework_group.command("list-installed")
@pass_context
def list_installed(ctx):
    """List installed frameworks with bindings and resolution status."""
    _execute(ctx, {"action": "list_installed"})


@framework_group.command("get-installed")
@click.argument("framework_id")
@pass_context
def get_installed(ctx, framework_id):
    """Get a single installed framework with full requirements and tests."""
    _execute(ctx, {"action": "get_installed", "framework_id": framework_id})


@framework_group.command("list-contributions")
@click.option("--asset-id", required=True)
@pass_context
def list_contributions(ctx, asset_id):
    """List per-requirement contribution verdicts for an asset."""
    _execute(ctx, {"action": "list_asset_contributions", "asset_id": asset_id})


@framework_group.command("list-requirement-contributions")
@click.option("--framework-id", required=True)
@click.option("--requirement-id", required=True)
@pass_context
def list_requirement_contributions(ctx, framework_id, requirement_id):
    """List documents and records contributing to a requirement."""
    _execute(
        ctx,
        {
            "action": "list_requirement_contributions",
            "framework_id": framework_id,
            "requirement_id": requirement_id,
        },
    )


@framework_group.command("list-test-bindings")
@click.option("--asset-id", default=None, help="Per-asset: Tests bound to this asset.")
@click.option(
    "--framework-id",
    default=None,
    help="Framework-wide: every Test/binding row for this installed framework.",
)
@click.option(
    "--source",
    default=None,
    type=click.Choice(["autoBind", "override", "ambiguous"]),
    help="Framework-wide filter: only bindings with this source.",
)
@click.option(
    "--unbound-only",
    is_flag=True,
    help="Framework-wide filter: only Tests with no bound asset.",
)
@click.option(
    "--coverage-state",
    default=None,
    help="Framework-wide filter: only requirements in this coverage state.",
)
@pass_context
def list_test_bindings(ctx, asset_id, framework_id, source, unbound_only, coverage_state):
    """List framework Tests bound to an asset, or framework-wide.

    Pass --asset-id for the per-asset inverse (Tests bound to one asset), or
    --framework-id to get every Test/binding row across the framework in one
    call (optionally filtered by --source / --unbound-only / --coverage-state)
    to answer "which bindings are ambiguous / how many untested?".
    """
    if framework_id:
        data = {}
        if source:
            data["source"] = source
        if unbound_only:
            data["unbound_only"] = True
        if coverage_state:
            data["coverage_state"] = coverage_state
        payload = {
            "action": "list_framework_test_bindings",
            "framework_id": framework_id,
        }
        if data:
            payload["data"] = data
        _execute(ctx, payload)
    elif asset_id:
        _execute(ctx, {"action": "list_asset_test_bindings", "asset_id": asset_id})
    else:
        click.echo(
            "Provide either --asset-id (per-asset) or --framework-id (framework-wide).",
            err=True,
        )
        sys.exit(1)


# ---------------------------------------------------------------------------
# Bindings (SoA / record-library)
# ---------------------------------------------------------------------------


@framework_group.command("bind")
@click.option("--framework-id", required=True)
@click.option(
    "--data",
    "data_input",
    required=True,
    help=(
        "BindingInput JSON: {role, target: {kind, registerId|recordDefinitionId}, "
        "fields, rowFilter?}"
    ),
)
@click.option("--dry-run", is_flag=True)
@pass_context
def create_binding(ctx, framework_id, data_input, dry_run):
    """Create a framework binding (e.g. SoA register or record-library)."""
    data = _parse_data_or_exit(data_input)
    _execute(
        ctx,
        {"action": "create_binding", "framework_id": framework_id, "data": data},
        dry_run=dry_run,
    )


@framework_group.command("update-binding")
@click.option("--framework-id", required=True)
@click.option("--role", required=True)
@click.option(
    "--data",
    "data_input",
    required=True,
    help="BindingUpdateInput JSON: {target?, fields, rowFilter?}",
)
@click.option("--dry-run", is_flag=True)
@pass_context
def update_binding(ctx, framework_id, role, data_input, dry_run):
    """Update an existing binding."""
    data = _parse_data_or_exit(data_input)
    _execute(
        ctx,
        {
            "action": "update_binding",
            "framework_id": framework_id,
            "role": role,
            "data": data,
        },
        dry_run=dry_run,
    )


@framework_group.command("remove-binding")
@click.option("--framework-id", required=True)
@click.option("--role", required=True)
@click.option(
    "--target",
    "target_input",
    default=None,
    help=(
        "Optional BindingTargetInput JSON for disambiguating multi-target roles "
        "(e.g. record-library)."
    ),
)
@click.option("--dry-run", is_flag=True)
@pass_context
def remove_binding(ctx, framework_id, role, target_input, dry_run):
    """Remove a binding."""
    data = {}
    if target_input:
        data["target"] = _parse_data_or_exit(target_input)
    _execute(
        ctx,
        {
            "action": "remove_binding",
            "framework_id": framework_id,
            "role": role,
            "data": data,
        },
        dry_run=dry_run,
    )


# ---------------------------------------------------------------------------
# A066 Tests
# ---------------------------------------------------------------------------


@framework_group.command("set-test-binding")
@click.option("--framework-id", required=True)
@click.option("--requirement-id", required=True)
@click.option("--test-id", required=True)
@click.option("--asset-id", required=True, help="Asset to bind this Test to.")
@pass_context
def set_test_binding(ctx, framework_id, requirement_id, test_id, asset_id):
    """Bind a Test to a specific asset."""
    _execute(
        ctx,
        {
            "action": "set_test_binding",
            "framework_id": framework_id,
            "requirement_id": requirement_id,
            "test_id": test_id,
            "asset_id": asset_id,
        },
    )


@framework_group.command("clear-test-binding")
@click.option("--framework-id", required=True)
@click.option("--requirement-id", required=True)
@click.option("--test-id", required=True)
@pass_context
def clear_test_binding(ctx, framework_id, requirement_id, test_id):
    """Clear a Test binding (falls back to auto-bound or unmatched)."""
    _execute(
        ctx,
        {
            "action": "clear_test_binding",
            "framework_id": framework_id,
            "requirement_id": requirement_id,
            "test_id": test_id,
        },
    )


@framework_group.command("set-test-override")
@click.option("--framework-id", required=True)
@click.option("--requirement-id", required=True)
@click.option("--test-id", required=True)
@click.option(
    "--data",
    "data_input",
    required=True,
    help="Override JSON: {params?, disabled?, reason?}",
)
@pass_context
def set_test_override(ctx, framework_id, requirement_id, test_id, data_input):
    """Set per-test override (params, disable, reason)."""
    data = _parse_data_or_exit(data_input)
    _execute(
        ctx,
        {
            "action": "set_test_override",
            "framework_id": framework_id,
            "requirement_id": requirement_id,
            "test_id": test_id,
            "data": data,
        },
    )


@framework_group.command("reset-test-override")
@click.option("--framework-id", required=True)
@click.option("--requirement-id", required=True)
@click.option("--test-id", required=True)
@pass_context
def reset_test_override(ctx, framework_id, requirement_id, test_id):
    """Reset a single Test override."""
    _execute(
        ctx,
        {
            "action": "reset_test_override",
            "framework_id": framework_id,
            "requirement_id": requirement_id,
            "test_id": test_id,
        },
    )


@framework_group.command("reset-overrides")
@click.option("--framework-id", required=True)
@click.option("--requirement-id", required=True)
@pass_context
def reset_all_overrides(ctx, framework_id, requirement_id):
    """Reset all Test overrides on a Requirement."""
    _execute(
        ctx,
        {
            "action": "reset_all_overrides",
            "framework_id": framework_id,
            "requirement_id": requirement_id,
        },
    )


@framework_group.command("add-test")
@click.option("--framework-id", required=True)
@click.option("--requirement-id", required=True)
@click.option(
    "--data",
    "data_input",
    required=True,
    help="RequirementTestInput JSON: {type, pattern, params?, boundAssetId?}",
)
@pass_context
def add_test(ctx, framework_id, requirement_id, data_input):
    """Add a tenant-local custom Test to a Requirement."""
    data = _parse_data_or_exit(data_input)
    _execute(
        ctx,
        {
            "action": "add_custom_test",
            "framework_id": framework_id,
            "requirement_id": requirement_id,
            "data": data,
        },
    )


@framework_group.command("remove-test")
@click.option("--framework-id", required=True)
@click.option("--requirement-id", required=True)
@click.option("--test-id", required=True)
@pass_context
def remove_test(ctx, framework_id, requirement_id, test_id):
    """Remove a tenant-local custom Test."""
    _execute(
        ctx,
        {
            "action": "remove_custom_test",
            "framework_id": framework_id,
            "requirement_id": requirement_id,
            "test_id": test_id,
        },
    )


@framework_group.command("evaluate")
@click.option("--framework-id", required=True)
@click.option("--requirement-id", required=True)
@click.option("--test-id", default=None, help="Optional: only evaluate one Test.")
@pass_context
def evaluate(ctx, framework_id, requirement_id, test_id):
    """Manually trigger evaluation of Tests on a Requirement."""
    payload = {
        "action": "evaluate_tests",
        "framework_id": framework_id,
        "requirement_id": requirement_id,
    }
    if test_id:
        payload["test_id"] = test_id
    _execute(ctx, payload)


@framework_group.command("sweep")
@click.option("--framework-id", required=True)
@pass_context
def sweep(ctx, framework_id):
    """Re-evaluate every Test on every Requirement in one call (framework-wide).

    One call replaces a per-Requirement ``evaluate`` loop after a batch of
    binding/Test changes. Respects the SoA "Included = No" gate. Returns the
    full installed-framework projection with refreshed coverageState.
    """
    _execute(ctx, {"action": "sweep_installed", "framework_id": framework_id})


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_data_or_exit(value):
    from upscaler_cli.cli.helpers import parse_data

    try:
        return parse_data(value)
    except Exception as e:
        click.echo(str(e), err=True)
        sys.exit(1)


def _execute(ctx, payload, dry_run=False):
    execute_rest_action(
        ctx, payload, "/api/v1/frameworks", render=_render_human, dry_run=dry_run
    )


def _render_human(action, result):
    from upscaler_cli.formatters.json_fmt import format_json

    if not result.get("success"):
        click.echo(format_json(result))
        return

    data = result.get("data")

    if action == "list_installed" and isinstance(data, list):
        if not data:
            click.echo("(no installed frameworks)")
            return
        for item in data:
            fw = item.get("framework") or {}
            res = item.get("resolutionStatus") or {}
            click.echo(
                f"{fw.get('id', ''):28}  {fw.get('name', ''):30}  "
                f"v{fw.get('version', '')}  "
                f"resolved {res.get('resolved', 0)}/{res.get('total', 0)}"
            )
        return

    if action == "list_asset_contributions" and isinstance(data, list):
        if not data:
            click.echo("(no contributions)")
            return
        for item in data:
            verdict = item.get("verdict") or {}
            reasons = ", ".join(verdict.get("reasons") or [])
            click.echo(
                f"{item.get('frameworkId', ''):24}  "
                f"{item.get('requirementId', ''):16}  "
                f"{verdict.get('state', ''):10}  "
                f"{reasons}"
            )
        return

    if action == "list_asset_test_bindings" and isinstance(data, list):
        if not data:
            click.echo("(no test bindings)")
            return
        for row in data:
            test = row.get("test") or {}
            result_obj = test.get("result") or {}
            click.echo(
                f"{row.get('frameworkId', ''):24}  "
                f"{row.get('requirementId', ''):16}  "
                f"{test.get('id', ''):20}  "
                f"{test.get('pattern', ''):24}  "
                f"{result_obj.get('status', '-')}"
            )
        return

    click.echo(format_json(data))
