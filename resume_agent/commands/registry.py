from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class SlashCommand:
    name: str
    description: str
    intent: str
    workflow: tuple[str, ...] = field(default_factory=tuple)
    aliases: tuple[str, ...] = field(default_factory=tuple)
    user_invocable: bool = True


@dataclass(frozen=True)
class SlashCommandInvocation:
    command: SlashCommand
    args: str
    raw: str


class SlashCommandRegistry:
    def __init__(self) -> None:
        self._commands: dict[str, SlashCommand] = {}
        self._aliases: dict[str, str] = {}

    def register(self, command: SlashCommand) -> None:
        name = _normalize_name(command.name)
        if not name:
            raise ValueError("slash command name is required")
        if name in self._commands or name in self._aliases:
            raise ValueError(f"duplicate slash command: {command.name}")

        aliases = tuple(_normalize_name(alias) for alias in command.aliases)
        for alias in aliases:
            if alias in self._commands or alias in self._aliases:
                raise ValueError(f"duplicate slash command alias: {alias}")

        normalized = SlashCommand(
            name=name,
            description=command.description,
            intent=command.intent,
            workflow=tuple(command.workflow),
            aliases=aliases,
            user_invocable=command.user_invocable,
        )
        self._commands[name] = normalized
        for alias in aliases:
            self._aliases[alias] = name

    def resolve(self, text: str) -> SlashCommandInvocation | None:
        stripped = text.strip()
        if not stripped.startswith("/"):
            return None
        token, _, args = stripped[1:].partition(" ")
        name = _normalize_name(token)
        if not name:
            return None
        command_name = self._aliases.get(name, name)
        command = self._commands.get(command_name)
        if command is None:
            return None
        return SlashCommandInvocation(command=command, args=args.strip(), raw=stripped)

    def commands(self) -> list[SlashCommand]:
        return [self._commands[name] for name in sorted(self._commands)]


def create_default_slash_command_registry() -> SlashCommandRegistry:
    registry = SlashCommandRegistry()
    registry.register(
        SlashCommand(
            name="generate",
            aliases=("gen", "draft"),
            description="Generate a targeted resume from profile and JD artifacts.",
            intent="generate_resume",
            workflow=(
                "import_profile",
                "normalize_profile",
                "add_jd_text",
                "analyze_jd",
                "build_resume_strategy",
                "generate_resume_modules",
                "render_latex",
                "check_truthfulness",
                "check_ats",
            ),
        )
    )
    registry.register(
        SlashCommand(
            name="revise",
            aliases=("edit",),
            description="Revise one resume section using user feedback without regenerating the whole resume.",
            intent="revise_resume",
            workflow=(
                "revise_resume_from_match_report",
                "read_resume_section",
                "revise_resume_section",
                "render_latex",
                "check_truthfulness",
                "check_ats",
                "match_analysis",
            ),
        )
    )
    registry.register(
        SlashCommand(
            name="compile",
            aliases=("pdf", "export"),
            description="Compile the current LaTeX resume into a PDF export.",
            intent="compile_pdf",
            workflow=("compile_pdf",),
        )
    )
    registry.register(
        SlashCommand(
            name="check",
            description="Run resume quality checks against current artifacts.",
            intent="check_resume",
            workflow=("check_truthfulness", "check_ats", "match_analysis"),
        )
    )
    registry.register(
        SlashCommand(
            name="match",
            aliases=("score", "fit"),
            description="Score and explain how well the current resume matches the current JD.",
            intent="match_analysis",
            workflow=("match_analysis",),
        )
    )
    registry.register(
        SlashCommand(
            name="job_hunt",
            aliases=("jobs",),
            description="Search and rank job opportunities for the current profile.",
            intent="job_hunt",
            workflow=("search_jobs",),
        )
    )
    return registry


def _normalize_name(value: str) -> str:
    return value.strip().lower().lstrip("/")
