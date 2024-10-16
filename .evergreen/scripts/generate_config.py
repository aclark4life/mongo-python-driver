# /// script
# requires-python = ">=3.9"
# dependencies = [
#   "shrub.py>=3.2.0",
#   "pyyaml>=6.0.2"
# ]
# ///

# Note: Run this file with `hatch run`, `pipx run`, or `uv run`.
from __future__ import annotations

from dataclasses import dataclass
from itertools import cycle, product, zip_longest
from typing import Any

from shrub.v3.evg_build_variant import BuildVariant
from shrub.v3.evg_project import EvgProject
from shrub.v3.evg_task import EvgTaskRef
from shrub.v3.shrub_service import ShrubService

##############
# Globals
##############

ALL_VERSIONS = ["4.0", "4.4", "5.0", "6.0", "7.0", "8.0", "rapid", "latest"]
CPYTHONS = ["3.9", "3.10", "3.11", "3.12", "3.13"]
PYPYS = ["pypy3.9", "pypy3.10"]
ALL_PYTHONS = CPYTHONS + PYPYS
MIN_MAX_PYTHON = [CPYTHONS[0], CPYTHONS[-1]]
BATCHTIME_WEEK = 10080
AUTH_SSLS = [("auth", "ssl"), ("noauth", "ssl"), ("noauth", "nossl")]
TOPOLOGIES = ["standalone", "replica_set", "sharded_cluster"]
SYNCS = ["sync", "async"]
DISPLAY_LOOKUP = dict(
    ssl=dict(ssl="SSL", nossl="NoSSL"),
    auth=dict(auth="Auth", noauth="NoAuth"),
    test_suites=dict(default="Sync", default_async="Async"),
    coverage=dict(coverage="cov"),
)
HOSTS = dict()


@dataclass
class Host:
    name: str
    run_on: str
    display_name: str
    expansions: dict[str, str]


_macos_expansions = dict(  # CSOT tests are unreliable on slow hosts.
    SKIP_CSOT_TESTS="true"
)

HOSTS["rhel8"] = Host("rhel8", "rhel87-small", "RHEL8", dict())
HOSTS["win64"] = Host("win64", "windows-64-vsMulti-small", "Win64", _macos_expansions)
HOSTS["win32"] = Host("win32", "windows-64-vsMulti-small", "Win32", _macos_expansions)
HOSTS["macos"] = Host("macos", "macos-14", "macOS", _macos_expansions)
HOSTS["macos-arm64"] = Host("macos-arm64", "macos-14-arm64", "macOS Arm64", _macos_expansions)


##############
# Helpers
##############


def create_variant(
    task_names: list[str],
    display_name: str,
    *,
    python: str | None = None,
    version: str | None = None,
    host: str | None = None,
    **kwargs: Any,
) -> BuildVariant:
    """Create a build variant for the given inputs."""
    task_refs = [EvgTaskRef(name=n) for n in task_names]
    kwargs.setdefault("expansions", dict())
    expansions = kwargs.pop("expansions", dict()).copy()
    host = host or "rhel8"
    run_on = [HOSTS[host].run_on]
    name = display_name.replace(" ", "-").lower()
    if python:
        expansions["PYTHON_BINARY"] = get_python_binary(python, host)
    if version:
        expansions["VERSION"] = version
    expansions.update(HOSTS[host].expansions)
    expansions = expansions or None
    return BuildVariant(
        name=name,
        display_name=display_name,
        tasks=task_refs,
        expansions=expansions,
        run_on=run_on,
        **kwargs,
    )


def get_python_binary(python: str, host: str) -> str:
    """Get the appropriate python binary given a python version and host."""
    if host in ["win64", "win32"]:
        if host == "win32":
            base = "C:/python/32"
        else:
            base = "C:/python"
        python = python.replace(".", "")
        return f"{base}/Python{python}/python.exe"

    if host == "rhel8":
        return f"/opt/python/{python}/bin/python3"

    if host in ["macos", "macos-arm64"]:
        return f"/Library/Frameworks/Python.Framework/Versions/{python}/bin/python3"

    raise ValueError(f"no match found for python {python} on {host}")


def get_display_name(base: str, host: str, **kwargs) -> str:
    """Get the display name of a variant."""
    display_name = f"{base} {HOSTS[host].display_name}"
    for key, value in kwargs.items():
        name = value
        if key == "version":
            if value not in ["rapid", "latest"]:
                name = f"v{value}"
        elif key == "python":
            if not value.startswith("pypy"):
                name = f"py{value}"
        elif key.lower() in DISPLAY_LOOKUP:
            name = DISPLAY_LOOKUP[key.lower()][value]
        else:
            raise ValueError(f"Missing display handling for {key}")
        display_name = f"{display_name} {name}"
    return display_name


def zip_cycle(*iterables, empty_default=None):
    """Get all combinations of the inputs, cycling over the shorter list(s)."""
    cycles = [cycle(i) for i in iterables]
    for _ in zip_longest(*iterables):
        yield tuple(next(i, empty_default) for i in cycles)


def generate_yaml(tasks=None, variants=None):
    """Generate the yaml for a given set of tasks and variants."""
    project = EvgProject(tasks=tasks, buildvariants=variants)
    out = ShrubService.generate_yaml(project)
    # Dedent by two spaces to match what we use in config.yml
    lines = [line[2:] for line in out.splitlines()]
    print("\n".join(lines))  # noqa: T201


##############
# Variants
##############


def create_ocsp_variants() -> list[BuildVariant]:
    variants = []
    batchtime = BATCHTIME_WEEK * 2
    expansions = dict(AUTH="noauth", SSL="ssl", TOPOLOGY="server")
    base_display = "OCSP test"

    # OCSP tests on rhel8 with all servers v4.4+ and all python versions.
    versions = [v for v in ALL_VERSIONS if v != "4.0"]
    for version, python in zip_cycle(versions, ALL_PYTHONS):
        host = "rhel8"
        variant = create_variant(
            [".ocsp"],
            get_display_name(base_display, host, version, python),
            python=python,
            version=version,
            host=host,
            expansions=expansions,
            batchtime=batchtime,
        )
        variants.append(variant)

    # OCSP tests on Windows and MacOS.
    # MongoDB servers on these hosts do not staple OCSP responses and only support RSA.
    for host, version in product(["win64", "macos"], ["4.4", "8.0"]):
        python = CPYTHONS[0] if version == "4.4" else CPYTHONS[-1]
        variant = create_variant(
            [".ocsp-rsa !.ocsp-staple"],
            get_display_name(base_display, host, version, python),
            python=python,
            version=version,
            host=host,
            expansions=expansions,
            batchtime=batchtime,
        )
        variants.append(variant)

    return variants


def create_server_variants() -> list[BuildVariant]:
    variants = []

    # Run the full matrix on linux with min and max CPython, and latest pypy.
    host = "rhel8"
    for python, (auth, ssl) in product([*MIN_MAX_PYTHON, PYPYS[-1]], AUTH_SSLS):
        display_name = f"Test {host}"
        expansions = dict(AUTH=auth, SSL=ssl, COVERAGE="coverage")
        display_name = get_display_name("Test", host, python=python, **expansions)
        variant = create_variant(
            [f".{t}" for t in TOPOLOGIES],
            display_name,
            python=python,
            host=host,
            tags=["coverage_tag"],
            expansions=expansions,
        )
        variants.append(variant)

    # Test the rest of the pythons on linux.
    for python, (auth, ssl), topology in zip_cycle(
        CPYTHONS[1:-1] + PYPYS[:-1], AUTH_SSLS, TOPOLOGIES
    ):
        display_name = f"Test {host}"
        expansions = dict(AUTH=auth, SSL=ssl)
        display_name = get_display_name("Test", host, python=python, **expansions)
        variant = create_variant(
            [f".{topology}"],
            display_name,
            python=python,
            host=host,
            expansions=expansions,
        )
        variants.append(variant)

    # Test a subset on each of the other platforms.
    for host in ("macos", "macos-arm64", "win64", "win32"):
        for (python, (auth, ssl), topology), sync in product(
            zip_cycle(MIN_MAX_PYTHON, AUTH_SSLS, TOPOLOGIES), SYNCS
        ):
            test_suite = "default" if sync == "sync" else "default_async"
            expansions = dict(AUTH=auth, SSL=ssl, TEST_SUITES=test_suite)
            display_name = get_display_name("Test", host, python=python, **expansions)
            variant = create_variant(
                [f".{topology}"],
                display_name,
                python=python,
                host=host,
                expansions=expansions,
            )
            variants.append(variant)

    return variants


##################
# Generate Config
##################

generate_yaml(variants=create_server_variants())
