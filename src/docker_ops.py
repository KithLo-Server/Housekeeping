"""Runs Docker commands and formats their results."""

import asyncio
import json
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import config

PRUNE_COMMANDS: Dict[str, Tuple[str, ...]] = {
    "dangling": ("docker", "system", "prune", "-f"),
    "all": ("docker", "system", "prune", "-af"),
}
PS_COMMAND = ("docker", "ps", "-s", "--format", "{{json .}}")

_MAX_OUTPUT_CHARS = 3500
_SHORT_ID_LENGTH = 12

_SIZE_RE = re.compile(
    r"^(?P<writable>[^(]+?)"
    r"(?:\s*\(virtual\s+(?P<virtual>[^)]+)\))?\s*$"
)

_prune_lock = asyncio.Lock()


@dataclass
class CommandResult:
    command: str
    returncode: int
    output: str
    timed_out: bool = False


@dataclass
class PruneResult:
    choice: str
    command: str
    returncode: int
    output: str
    timed_out: bool = False


@dataclass
class ContainerInfo:
    id: str
    name: str
    writable_size: str
    virtual_size: str


@dataclass
class ContainerListResult:
    containers: List[ContainerInfo] = field(default_factory=list)
    error: str = ""
    timed_out: bool = False


async def _run_docker(
    command: Tuple[str, ...], timeout: int
) -> CommandResult:
    printable = " ".join(command)
    try:
        process = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
    except FileNotFoundError:
        return CommandResult(
            printable, -1, "Docker CLI was not found in the container."
        )
    except OSError as exc:
        return CommandResult(printable, -1, f"Could not start Docker: {exc}")

    try:
        stdout, _ = await asyncio.wait_for(
            process.communicate(), timeout=timeout
        )
    except asyncio.TimeoutError:
        process.kill()
        await process.communicate()
        return CommandResult(
            printable,
            -1,
            f"Command timed out after {timeout} seconds.",
            timed_out=True,
        )

    output = stdout.decode("utf-8", errors="replace").strip()
    return CommandResult(printable, process.returncode or 0, output)


def command_for(choice: str) -> Optional[str]:
    command = PRUNE_COMMANDS.get(choice)
    return " ".join(command) if command else None


async def prune(choice: str) -> PruneResult:
    """Runs the prune command for ``choice``, serialized against other prunes."""
    command = PRUNE_COMMANDS.get(choice)
    if command is None:
        raise ValueError(f"Unsupported prune choice: {choice!r}")

    async with _prune_lock:
        result = await _run_docker(command, config.PRUNE_TIMEOUT_SECONDS)

    return PruneResult(
        choice=choice,
        command=result.command,
        returncode=result.returncode,
        output=result.output,
        timed_out=result.timed_out,
    )


def parse_size(value: str) -> Tuple[str, str]:
    """Splits Docker's combined size string into (writable, virtual)."""
    match = _SIZE_RE.match(value or "")
    if not match:
        return (value.strip(), "")
    writable = (match.group("writable") or "").strip()
    virtual = (match.group("virtual") or "").strip()
    return writable, virtual


def parse_containers(output: str) -> Tuple[List[ContainerInfo], str]:
    containers = []
    for line in output.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            return [], f"Could not parse docker ps output: {line[:200]}"
        if not isinstance(data, dict):
            return [], f"Unexpected docker ps output: {line[:200]}"

        writable, virtual = parse_size(str(data.get("Size") or ""))
        containers.append(
            ContainerInfo(
                id=str(data.get("ID") or "")[:_SHORT_ID_LENGTH],
                name=str(data.get("Names") or "\u2014"),
                writable_size=writable or "\u2014",
                virtual_size=virtual or "\u2014",
            )
        )
    return containers, ""


async def list_containers() -> ContainerListResult:
    result = await _run_docker(PS_COMMAND, config.PS_TIMEOUT_SECONDS)
    if result.timed_out:
        return ContainerListResult(error=result.output, timed_out=True)
    if result.returncode != 0:
        return ContainerListResult(
            error=result.output
            or f"docker ps failed (exit code {result.returncode})."
        )

    containers, error = parse_containers(result.output)
    return ContainerListResult(containers=containers, error=error)


def format_container_table(containers: List[ContainerInfo]) -> str:
    if not containers:
        return "No running containers."

    headers = ("ID", "NAME", "WRITABLE", "VIRTUAL")
    rows = [
        (item.id, item.name, item.writable_size, item.virtual_size)
        for item in containers
    ]
    widths = [
        max(len(header), *(len(row[index]) for row in rows))
        for index, header in enumerate(headers)
    ]

    def render(row: Tuple[str, ...]) -> str:
        return "  ".join(
            value.ljust(width) for value, width in zip(row, widths)
        ).rstrip()

    lines = [render(headers), render(tuple("-" * width for width in widths))]
    lines.extend(render(row) for row in rows)
    return "\n".join(lines)


def _reclaimed_line(output: str) -> Optional[str]:
    for line in output.splitlines():
        if "reclaimed" in line.lower():
            return line.strip()
    return None


def format_result(result: PruneResult) -> str:
    """Builds the Telegram message describing a finished prune."""
    label = (
        "All unused images"
        if result.choice == "all"
        else "Dangling images only"
    )

    if result.timed_out:
        return f"{label}\n\n{result.output}"

    if result.returncode != 0:
        details = result.output or "No error output was produced."
        return (
            f"{label} failed (exit code {result.returncode}).\n\n"
            f"{details[:_MAX_OUTPUT_CHARS]}"
        )

    reclaimed = _reclaimed_line(result.output)
    summary = [
        "Prune finished.",
        "",
        f"Mode: {label}",
        f"Command: {result.command}",
    ]
    if reclaimed:
        summary.append(f"{reclaimed}")
    if result.output:
        summary.extend(["", result.output[:_MAX_OUTPUT_CHARS]])
    else:
        summary.extend(["", "Nothing needed to be removed."])
    return "\n".join(summary)
