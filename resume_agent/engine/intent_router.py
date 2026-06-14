from __future__ import annotations

from dataclasses import dataclass

from resume_agent.commands.registry import create_default_slash_command_registry


@dataclass(frozen=True)
class RoutedIntent:
    name: str
    reason: str


def route_intent(message: str, jd_text: str | None = None, jd_url: str | None = None) -> RoutedIntent:
    slash = create_default_slash_command_registry().resolve(message)
    if slash is not None:
        return RoutedIntent(slash.command.intent, f"slash command /{slash.command.name}")

    text = message.lower()
    if _looks_like_job_hunt(message, text):
        return RoutedIntent("job_hunt", "user requested job search or role discovery")
    if (
        "match" in text
        or "score" in text
        or "匹配" in message
        or "适配" in message
        or "评分" in message
    ):
        return RoutedIntent("match_analysis", "user requested resume-JD match analysis")
    if "pdf" in text or "编译" in message or "导出" in message:
        return RoutedIntent("compile_pdf", "user requested PDF/export/compile")
    if jd_text or jd_url or "生成" in message or "简历" in message or "jd" in text:
        return RoutedIntent("generate_resume", "user requested resume generation or supplied JD")
    return RoutedIntent("chat", "no actionable resume workflow detected")


def _looks_like_job_hunt(message: str, text: str) -> bool:
    compound_terms = ("job hunt", "找工作", "找岗", "求职", "岗位搜索")
    if any(term in text for term in compound_terms):
        return True

    search_terms = ("找", "搜索", "搜", "看看", "查", "投递")
    job_terms = ("岗位", "职位", "招聘", "工作", "job", "jobs", "role")
    has_search = any(term in message for term in search_terms) or "search" in text
    has_job = any(term in message for term in job_terms)
    return has_search and has_job
