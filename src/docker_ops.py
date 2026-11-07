"""Runs Docker commands and formats their results."""

import asyncio
import json
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

import config

PRUNE_COMMANDS: Dict[str, Tuple[str, ...]] = {
    "dangling": ("docker", "system", "prune", "-f"),
    "all": ("docker", "system", "prune", "-af"),
}
PS_COMMAND = ("docker", "ps", "-s", "--format", "{{json .}}")
IMAGE_LIST_COMMAND = ("docker", "system", "df", "-v")
IMAGE_REMOVE_PREFIX = ("docker", "image", "rm")

_MAX_OUTPUT_CHARS = 3500
_SHORT_ID_LENGTH = 12

_SIZE_RE = re.compile(
    r"^(?P<writable>[^(]+?)"
    r"(?:\s*\(virtual\s+(?P<virtual>[^)]+)\))?\s*$"
)

_mutation_lock = asyncio.Lock()


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


@dataclass
class ImageInfo:
    id: str
    name: str
    tag: str
    size: str
    shared_size: str
    unique_size: str
    containers: str


@dataclass
class ImageListResult:
    images: List[ImageInfo] = field(default_factory=list)
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

    async with _mutation_lock:
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


def _format_table(
    headers: Tuple[str, ...], rows: List[Tuple[str, ...]]
) -> str:
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


def format_container_table(containers: List[ContainerInfo]) -> str:
    if not containers:
        return "No running containers."

    headers = ("ID", "NAME", "WRITABLE", "VIRTUAL")
    rows = [
        (item.id, item.name, item.writable_size, item.virtual_size)
        for item in containers
    ]
    return _format_table(headers, rows)


async def remove_images(identifiers: Sequence[str]) -> CommandResult:
    """Runs docker image rm for one or more identifiers."""
    command = (*IMAGE_REMOVE_PREFIX, *identifiers)
    async with _mutation_lock:
        return await _run_docker(command, config.IMAGE_RM_TIMEOUT_SECONDS)


def format_remove_result(
    identifiers: Sequence[str], result: CommandResult
) -> str:
    joined = " ".join(identifiers)

    if result.timed_out:
        return f"Removing {joined} timed out.\n\n{result.output}"

    if result.returncode != 0:
        details = result.output or "No error output was produced."
        return (
            f"Could not remove {joined} "
            f"(exit code {result.returncode}).\n\n"
            f"{details[:_MAX_OUTPUT_CHARS]}"
        )

    summary = [
        "Image removed.",
        "",
        f"Identifiers: {joined}",
        f"Command: {result.command}",
    ]
    if result.output:
        summary.extend(["", result.output[:_MAX_OUTPUT_CHARS]])
    return "\n".join(summary)


def _is_named_image(image: ImageInfo) -> bool:
    return image.name not in ("", "<none>") and image.tag not in ("", "<none>")


def parse_images(output: str) -> Tuple[List[ImageInfo], str]:
    images = []
    parsing = False
    for raw in output.splitlines():
        line = raw.strip()
        if not line:
            if parsing:
                break
            continue
        if not parsing:
            if line.upper().startswith("REPOSITORY"):
                parsing = True
            continue

        tokens = line.split()
        if len(tokens) < 8:
            return [], (
                f"Could not parse docker system df output: {line[:200]}"
            )
        try:
            containers = int(tokens[-1])
        except ValueError:
            return [], (
                f"Could not parse container count: {line[:200]}"
            )

        images.append(
            ImageInfo(
                id=tokens[2][:_SHORT_ID_LENGTH],
                name=tokens[0],
                tag=tokens[1],
                size=tokens[-4],
                shared_size=tokens[-3],
                unique_size=tokens[-2],
                containers=str(containers),
            )
        )

    if not parsing:
        return [], "Could not find the Images section in docker system df output."

    named = [image for image in images if _is_named_image(image)]
    rest = [image for image in images if not _is_named_image(image)]
    return named + rest, ""


async def list_images() -> ImageListResult:
    result = await _run_docker(
        IMAGE_LIST_COMMAND, config.IMAGE_LIST_TIMEOUT_SECONDS
    )
    if result.timed_out:
        return ImageListResult(error=result.output, timed_out=True)
    if result.returncode != 0:
        return ImageListResult(
            error=result.output
            or f"docker system df failed (exit code {result.returncode})."
        )

    images, error = parse_images(result.output)
    return ImageListResult(images=images, error=error)


def format_image_table(images: List[ImageInfo]) -> str:
    if not images:
        return "No images."

    headers = (
        "ID",
        "NAME",
        "TAG",
        "SIZE",
        "SHARED",
        "UNIQUE",
        "CONTAINERS",
    )
    rows = [
        (
            item.id,
            item.name,
            item.tag,
            item.size,
            item.shared_size,
            item.unique_size,
            item.containers,
        )
        for item in images
    ]
    return _format_table(headers, rows)


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
