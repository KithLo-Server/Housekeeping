"""Runs Docker system prune commands and formats their results."""

import asyncio
from dataclasses import dataclass
from typing import Dict, Optional, Tuple

import config

PRUNE_COMMANDS: Dict[str, Tuple[str, ...]] = {
    "dangling": ("docker", "system", "prune", "-f"),
    "all": ("docker", "system", "prune", "-af"),
}

_MAX_OUTPUT_CHARS = 3500

_prune_lock = asyncio.Lock()


@dataclass
class PruneResult:
    choice: str
    command: str
    returncode: int
    output: str
    timed_out: bool = False


def command_for(choice: str) -> Optional[str]:
    command = PRUNE_COMMANDS.get(choice)
    return " ".join(command) if command else None


async def prune(choice: str) -> PruneResult:
    """Runs the prune command for ``choice``, serialized against other prunes."""
    command = PRUNE_COMMANDS.get(choice)
    if command is None:
        raise ValueError(f"Unsupported prune choice: {choice!r}")

    printable = " ".join(command)
    async with _prune_lock:
        try:
            process = await asyncio.create_subprocess_exec(
                *command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
        except FileNotFoundError:
            return PruneResult(
                choice=choice,
                command=printable,
                returncode=-1,
                output="Docker CLI was not found in the container.",
            )
        except OSError as exc:
            return PruneResult(
                choice=choice,
                command=printable,
                returncode=-1,
                output=f"Could not start Docker: {exc}",
            )

        try:
            stdout, _ = await asyncio.wait_for(
                process.communicate(),
                timeout=config.PRUNE_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError:
            process.kill()
            await process.communicate()
            return PruneResult(
                choice=choice,
                command=printable,
                returncode=-1,
                output=(
                    "Prune timed out after "
                    f"{config.PRUNE_TIMEOUT_SECONDS} seconds."
                ),
                timed_out=True,
            )

        output = stdout.decode("utf-8", errors="replace").strip()
        return PruneResult(
            choice=choice,
            command=printable,
            returncode=process.returncode or 0,
            output=output,
        )


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
