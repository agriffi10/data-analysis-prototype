"""Both Lake Formation registrations cover a whole BUCKET, which is why a deeper prefix needs no grant.

Three app-managed folders are moving one segment deeper, under ``system_settings/``. Whether that
move needs a Lake Formation change depends entirely on how the two data locations are registered:
a registration at the bucket ARN covers every prefix inside it for ever, and a registration
narrowed to a prefix would stop covering the new depth the moment the folders moved — silently,
because LF answers a missing data-location grant as an access error at query time and nothing
offline would say why.

The arc's answer is "no LF change is needed". This is that answer read out of the Terraform rather
than assumed, so that the day someone narrows a registration to a prefix is the day this names it.

**The module ARGUMENT is read too, not just the resource.** ``modules/analytics`` registers
``var.user_space_bucket_arn``, which tells you nothing on its own — the value comes from the root
module's call. Three module calls pass a variable of that name, so the call is selected BY NAME
rather than by taking the first match, which would be a different module's argument reading as
this one's.

Attributes:
  INFRA: The Terraform tree.
  REGISTRATIONS: The registration resource each module declares, and the ARN expression it must
    carry — spelled out, because the property under test is that the expression is an unadorned
    bucket reference rather than merely that it exists.
  ANALYTICS_CALL: The root-module call whose argument supplies the analytics registration's ARN.
"""

import pathlib

from tf_blocks import argument, blocks, module_calls

INFRA = pathlib.Path(__file__).resolve().parent.parent / "infra"

REGISTRATIONS = {
    "modules/analytics/lakeformation.tf": ("user_space", "var.user_space_bucket_arn"),
    "modules/shared-spaces/lakeformation.tf": ("shared_space", "aws_s3_bucket.shared_space.arn"),
}

ANALYTICS_CALL = "analytics"


def test_these_are_the_ONLY_lake_formation_registrations_in_the_tree() -> None:
    """"Both registrations" is a claim about the TREE, and this is what makes it one.

    The two assertions below read two named files. If a third data location were registered
    anywhere else — narrowed to a prefix, as a new module's own bootstrap — those two would still
    pass and the claim that a deeper prefix needs no grant would be false for it.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If any file declares a registration this module does not read.
    """
    found = {
        f"{path.relative_to(INFRA).as_posix()}::{name}"
        for path in sorted(INFRA.rglob("*.tf"))
        for name in blocks(path.read_text(), "aws_lakeformation_resource")
    }
    expected = {f"{relative}::{name}" for relative, (name, _) in REGISTRATIONS.items()}

    assert found == expected, {
        "unread registrations": sorted(found - expected),
        "declared but gone": sorted(expected - found),
    }


def test_both_registrations_name_a_whole_bucket_and_not_a_prefix() -> None:
    """A registration carrying a ``/`` suffix would be a prefix registration, and the move would break.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If a registration is gone, renamed, or narrowed to a prefix.
    """
    for relative, (name, expected) in REGISTRATIONS.items():
        declared = blocks((INFRA / relative).read_text(), "aws_lakeformation_resource")

        assert name in declared, f"{relative} no longer declares aws_lakeformation_resource.{name}: {sorted(declared)}"

        arn = argument(declared[name], "arn").strip()

        assert "/" not in arn, (
            f"{relative}: {name} registers {arn!r}, which names a PREFIX. A prefix registration stops "
            "covering the app-managed folders once they move a segment deeper, and Lake Formation "
            "reports that as a query-time access error rather than as a missing grant."
        )
        assert arn == expected, f"{relative}: {name} registers {arn!r}, not the bare bucket {expected!r}"


def test_the_analytics_registration_is_handed_a_bucket_arn_by_the_root_module() -> None:
    """The variable's VALUE, without which the assertion above is about a name and not a location.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If the call is gone, passes no such argument, or passes a prefix.
    """
    calls = module_calls((INFRA / "main.tf").read_text())

    assert ANALYTICS_CALL in calls, f"main.tf no longer calls module {ANALYTICS_CALL!r}: {sorted(calls)}"

    passed = argument(calls[ANALYTICS_CALL], "user_space_bucket_arn").strip()

    assert passed, f"the {ANALYTICS_CALL} call passes no user_space_bucket_arn"
    assert passed.startswith('"arn:aws:s3:::') and passed.endswith('"'), (
        f"the {ANALYTICS_CALL} call passes {passed!r}, which this test can no longer read as a bucket ARN"
    )
    assert "/" not in passed, (
        f"the {ANALYTICS_CALL} call passes {passed!r} — a key or prefix, not a bucket, so the "
        "registration covers less than the whole bucket"
    )
