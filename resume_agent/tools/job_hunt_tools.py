from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
import re
import sys
from html import unescape
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import quote_plus, urlparse
from urllib.request import Request, urlopen

from resume_agent.mcp.job_crawlers import boss_python_search, crawl_job_url, firecrawl_search_jobs
from resume_agent.tools.base import FunctionTool, ToolExecutionError, ToolPermission, ToolResult
from resume_agent.tools.tool_runtime import resolve_path


def create_job_hunt_tools(repo_root: Path) -> list[FunctionTool]:
    root = Path(repo_root).resolve()
    return [
        FunctionTool(
            name="boss_login",
            description=(
                "Launch a BOSS 直聘 QR code login in the terminal. "
                "The user scans once with the BOSS app; the credential is saved locally "
                "so subsequent search_jobs and crawl_job_info calls work without re-scanning."
            ),
            input_schema={
                "type": "object",
                "required": [],
                "properties": {},
            },
            read_only=False,
            permission=ToolPermission.NETWORK,
            handler=lambda input_data, context: _boss_login(),
        ),
        FunctionTool(
            name="search_jobs",
            description=(
                "Search job opportunities for the current profile, rank them by keyword fit, "
                "and write jobs/jobs.jsonl. "
                "Uses Firecrawl search (FIRECRAWL_API_KEY) by default. "
                "Set enable_boss=true to also use BOSS 直聘 API (requires BOSS_COOKIES or prior boss_login)."
            ),
            input_schema={
                "type": "object",
                "required": ["project_dir"],
                "properties": {
                    "project_dir": {"type": "string"},
                    "query": {"type": "string"},
                    "location": {"type": "string"},
                    "limit": {"type": "integer"},
                    "enable_boss": {"type": "boolean", "description": "Enable BOSS 直聘 search (default false)"},
                },
            },
            read_only=False,
            permission=ToolPermission.NETWORK,
            handler=lambda input_data, context: _search_jobs(root, input_data),
        ),
        FunctionTool(
            name="select_job",
            description=(
                "Select one previously searched job from jobs/jobs.jsonl and write jd/jd_raw.md "
                "plus jobs/selected_job.json."
            ),
            input_schema={
                "type": "object",
                "required": ["project_dir", "job_id"],
                "properties": {
                    "project_dir": {"type": "string"},
                    "job_id": {"type": "string"},
                },
            },
            read_only=False,
            permission=ToolPermission.WORKSPACE_WRITE,
            handler=lambda input_data, context: _select_job(root, input_data),
        ),
        FunctionTool(
            name="crawl_job_info",
            description=(
                "Fetch a known job posting URL or a job_id from jobs/jobs.jsonl, extract the main JD text, "
                "and write jobs/job_details/<job_id>.json plus jd/jd_raw.md. "
                "Uses Firecrawl for public pages (FIRECRAWL_API_KEY required); "
                "set enable_boss=true to use the BOSS 直聘 API for zhipin.com URLs."
            ),
            input_schema={
                "type": "object",
                "required": ["project_dir"],
                "properties": {
                    "project_dir": {"type": "string"},
                    "url": {"type": "string"},
                    "jd_url": {"type": "string"},
                    "job_id": {"type": "string"},
                    "company": {"type": "string"},
                    "role": {"type": "string"},
                    "enable_boss": {"type": "boolean", "description": "Enable BOSS 直聘 API for zhipin.com URLs (default false)"},
                },
            },
            read_only=False,
            permission=ToolPermission.NETWORK,
            handler=lambda input_data, context: _crawl_job_info(root, input_data),
        ),
    ]


def _boss_login() -> ToolResult:
    """Launch interactive BOSS 直聘 QR login and save credential."""
    boss_cli_path = Path(__file__).resolve().parents[2] / "boss-cli"
    if boss_cli_path.is_dir() and str(boss_cli_path) not in sys.path:
        sys.path.insert(0, str(boss_cli_path))

    try:
        import asyncio
        from boss_cli.auth import qr_login, save_credential
    except ImportError as exc:
        raise ToolExecutionError(f"boss-cli not available: {exc}") from exc

    try:
        credential = asyncio.run(qr_login())
        save_credential(credential)
    except Exception as exc:
        raise ToolExecutionError(f"BOSS login failed: {exc}") from exc

    return ToolResult(content={
        "status": "ok",
        "tool": "boss_login",
        "message": "BOSS 直聘 登录成功，凭证已保存。后续 search_jobs / crawl_job_info 将自动使用。",
        "cookies_count": len(credential.cookies),
    })


def _search_jobs(repo_root: Path, input_data: Mapping[str, Any]) -> ToolResult:
    project_dir = resolve_path(repo_root, str(input_data["project_dir"]))
    query = str(input_data.get("query") or "").strip()
    location = str(input_data.get("location") or "").strip()
    limit = _positive_int(input_data.get("limit"), default=10)
    enable_boss = bool(input_data.get("enable_boss", False))

    profile = _read_profile(project_dir)
    search_query = query or _default_query(profile)
    if not search_query:
        raise ToolExecutionError("search_jobs requires query input or profile skills/target_roles")

    raw_results = _search_jobs_backend(search_query, location, limit, enable_boss=enable_boss)
    jobs = _normalize_and_rank_jobs(raw_results, search_query, location, profile)
    jobs_path = project_dir / "jobs" / "jobs.jsonl"
    jobs_path.parent.mkdir(parents=True, exist_ok=True)
    jobs_path.write_text(
        "\n".join(json.dumps(job, ensure_ascii=False) for job in jobs) + ("\n" if jobs else ""),
        encoding="utf-8",
    )

    return ToolResult(
        content={
            "status": "ok",
            "tool": "search_jobs",
            "query": search_query,
            "location": location,
            "count": len(jobs),
            "top_jobs": jobs[:5],
            "outputs": {"jobs_index": str(jobs_path.resolve())},
        }
    )


def _select_job(repo_root: Path, input_data: Mapping[str, Any]) -> ToolResult:
    project_dir = resolve_path(repo_root, str(input_data["project_dir"]))
    job_id = str(input_data["job_id"]).strip()
    jobs_path = project_dir / "jobs" / "jobs.jsonl"
    if not jobs_path.is_file():
        raise ToolExecutionError(f"missing jobs index: {jobs_path}")

    jobs = [json.loads(line) for line in jobs_path.read_text(encoding="utf-8-sig").splitlines() if line.strip()]
    job = next((item for item in jobs if str(item.get("job_id")) == job_id), None)
    if job is None:
        raise ToolExecutionError(f"job_id not found in jobs index: {job_id}")

    selected_path = project_dir / "jobs" / "selected_job.json"
    selected_path.write_text(json.dumps(job, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    jd_dir = project_dir / "jd"
    jd_dir.mkdir(parents=True, exist_ok=True)
    jd_raw_path = jd_dir / "jd_raw.md"
    jd_raw_path.write_text(_job_to_jd_markdown(job), encoding="utf-8")

    return ToolResult(
        content={
            "status": "ok",
            "tool": "select_job",
            "job_id": job_id,
            "company": str(job.get("company") or ""),
            "role": str(job.get("role") or ""),
            "outputs": {
                "selected_job": str(selected_path.resolve()),
                "jd_raw": str(jd_raw_path.resolve()),
            },
        }
    )


def _crawl_job_info(repo_root: Path, input_data: Mapping[str, Any]) -> ToolResult:
    project_dir = resolve_path(repo_root, str(input_data["project_dir"]))
    job_id = str(input_data.get("job_id") or "").strip()
    url = str(input_data.get("url") or input_data.get("jd_url") or "").strip()
    enable_boss = bool(input_data.get("enable_boss", False))
    seed_job: dict[str, Any] = {}

    if job_id:
        seed_job = _load_job_by_id(project_dir, job_id)
        url = url or str(seed_job.get("jd_url") or "")
    if not url:
        raise ToolExecutionError("crawl_job_info requires url or a job_id with jd_url in jobs/jobs.jsonl")
    _validate_http_url(url)

    crawled = _crawl_job_info_backend(url, repo_root, enable_boss=enable_boss)
    job = _normalize_crawled_job(project_dir, url, crawled, input_data, seed_job)

    details_dir = project_dir / "jobs" / "job_details"
    details_dir.mkdir(parents=True, exist_ok=True)
    detail_path = details_dir / f"{_safe_filename(str(job['job_id']))}.json"
    detail_path.write_text(json.dumps(job, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    jobs_path = _upsert_job_index(project_dir, job)

    jd_dir = project_dir / "jd"
    jd_dir.mkdir(parents=True, exist_ok=True)
    jd_raw_path = jd_dir / "jd_raw.md"
    jd_raw_path.write_text(_job_to_jd_markdown(job), encoding="utf-8")

    return ToolResult(
        content={
            "status": "ok",
            "tool": "crawl_job_info",
            "job_id": str(job["job_id"]),
            "company": str(job.get("company") or ""),
            "role": str(job.get("role") or ""),
            "outputs": {
                "job_detail": str(detail_path.resolve()),
                "jobs_index": str(jobs_path.resolve()),
                "jd_raw": str(jd_raw_path.resolve()),
            },
        }
    )


def _read_profile(project_dir: Path) -> dict[str, Any]:
    profile_path = project_dir / "profile" / "profile.json"
    if not profile_path.is_file():
        return {}
    try:
        profile = json.loads(profile_path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {}
    return profile if isinstance(profile, dict) else {}


def _load_job_by_id(project_dir: Path, job_id: str) -> dict[str, Any]:
    jobs_path = project_dir / "jobs" / "jobs.jsonl"
    if not jobs_path.is_file():
        raise ToolExecutionError(f"missing jobs index: {jobs_path}")

    for line in jobs_path.read_text(encoding="utf-8-sig").splitlines():
        if not line.strip():
            continue
        try:
            job = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(job, dict) and str(job.get("job_id")) == job_id:
            return job
    raise ToolExecutionError(f"job_id not found in jobs index: {job_id}")


def _default_query(profile: Mapping[str, Any]) -> str:
    target_roles = _string_list(profile.get("target_roles"))
    skills = _string_list(profile.get("skills"))
    query_parts = []
    if target_roles:
        query_parts.append(target_roles[0])
    query_parts.extend(skills[:3])
    return " ".join(query_parts).strip()


def _normalize_and_rank_jobs(
    raw_results: list[dict[str, Any]],
    query: str,
    location: str,
    profile: Mapping[str, Any],
) -> list[dict[str, Any]]:
    skills = _string_list(profile.get("skills"))
    ranked: list[dict[str, Any]] = []
    for index, raw in enumerate(raw_results, start=1):
        job = {
            "platform": str(raw.get("platform") or _platform_from_url(str(raw.get("jd_url") or raw.get("url") or ""))),
            "company": str(raw.get("company") or "Unknown"),
            "role": str(raw.get("role") or raw.get("title") or "Unknown Role"),
            "salary": str(raw.get("salary") or ""),
            "location": str(raw.get("location") or location or ""),
            "jd_text": str(raw.get("jd_text") or raw.get("snippet") or raw.get("source_raw") or ""),
            "jd_url": str(raw.get("jd_url") or raw.get("url") or ""),
            "posted_at": str(raw.get("posted_at") or ""),
            "source_raw": str(raw.get("source_raw") or raw.get("snippet") or ""),
        }
        job["keywords"] = _extract_job_keywords(job, skills)
        job["match_score"] = _job_match_score(job, query, skills)
        job["job_id"] = _job_id(job, index)
        ranked.append(job)

    ranked.sort(key=lambda item: (-int(item["match_score"]), str(item["company"]), str(item["role"])))
    return _dedupe_jobs(ranked)


def _normalize_crawled_job(
    project_dir: Path,
    url: str,
    crawled: Mapping[str, Any],
    input_data: Mapping[str, Any],
    seed_job: Mapping[str, Any],
) -> dict[str, Any]:
    text = str(
        crawled.get("jd_text")
        or crawled.get("markdown")
        or crawled.get("text")
        or crawled.get("source_raw")
        or ""
    ).strip()
    if not text:
        raise ToolExecutionError("crawl_job_info could not extract JD text from the URL")

    title = str(crawled.get("title") or crawled.get("source_title") or "")
    title_role, title_company = _split_title(title)
    company = _first_nonempty(
        input_data.get("company"),
        crawled.get("company"),
        seed_job.get("company"),
        title_company,
        "Unknown",
    )
    role = _first_nonempty(
        input_data.get("role"),
        crawled.get("role"),
        seed_job.get("role"),
        title_role,
        crawled.get("title"),
        "Unknown Role",
    )
    job = {
        "platform": _first_nonempty(crawled.get("platform"), seed_job.get("platform"), _platform_from_url(url)),
        "company": str(company),
        "role": str(role),
        "salary": str(_first_nonempty(crawled.get("salary"), seed_job.get("salary"), _extract_salary(text), "")),
        "location": str(_first_nonempty(crawled.get("location"), seed_job.get("location"), "")),
        "jd_text": text,
        "jd_url": str(crawled.get("final_url") or seed_job.get("jd_url") or url),
        "posted_at": str(_first_nonempty(crawled.get("posted_at"), seed_job.get("posted_at"), "")),
        "source_raw": str(crawled.get("source_raw") or text),
        "source_title": title,
        "crawl_backend": str(crawled.get("backend") or "urllib"),
        "crawled_at": datetime.now(timezone.utc).isoformat(),
    }
    profile = _read_profile(project_dir)
    skills = _string_list(profile.get("skills"))
    job["keywords"] = _extract_job_keywords(job, skills)
    job["match_score"] = _job_match_score(job, str(job.get("role") or ""), skills)
    job["job_id"] = str(
        _first_nonempty(input_data.get("job_id"), seed_job.get("job_id"), _job_id(job, 1))
    )
    return job


def _upsert_job_index(project_dir: Path, job: Mapping[str, Any]) -> Path:
    jobs_path = project_dir / "jobs" / "jobs.jsonl"
    jobs_path.parent.mkdir(parents=True, exist_ok=True)
    jobs: list[dict[str, Any]] = []
    if jobs_path.is_file():
        for line in jobs_path.read_text(encoding="utf-8-sig").splitlines():
            if not line.strip():
                continue
            try:
                existing = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(existing, dict):
                jobs.append(existing)

    upserted = False
    result: list[dict[str, Any]] = []
    for existing in jobs:
        if str(existing.get("job_id")) == str(job.get("job_id")):
            merged = dict(existing)
            merged.update(job)
            result.append(merged)
            upserted = True
        else:
            result.append(existing)
    if not upserted:
        result.append(dict(job))

    jobs_path.write_text(
        "\n".join(json.dumps(item, ensure_ascii=False) for item in result) + "\n",
        encoding="utf-8",
    )
    return jobs_path


def _dedupe_jobs(jobs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    result: list[dict[str, Any]] = []
    for job in jobs:
        key = "|".join(
            [
                str(job.get("company", "")).casefold(),
                str(job.get("role", "")).casefold(),
                str(job.get("jd_url", "")).casefold(),
            ]
        )
        if key in seen:
            continue
        seen.add(key)
        result.append(job)
    return result


def _extract_job_keywords(job: Mapping[str, Any], skills: list[str]) -> list[str]:
    haystack = " ".join(
        [
            str(job.get("role") or ""),
            str(job.get("jd_text") or ""),
            str(job.get("source_raw") or ""),
        ]
    ).casefold()
    matched = [skill for skill in skills if skill.casefold() in haystack]
    return matched[:8]


def _job_match_score(job: Mapping[str, Any], query: str, skills: list[str]) -> int:
    haystack = " ".join(
        [
            str(job.get("role") or ""),
            str(job.get("jd_text") or ""),
            str(job.get("source_raw") or ""),
            str(job.get("company") or ""),
        ]
    ).casefold()
    query_terms = _query_terms(query) + skills
    matches = {term.casefold() for term in query_terms if term and term.casefold() in haystack}
    query_score = int(round((len(matches) / max(1, len({term.casefold() for term in query_terms if term}))) * 100))
    location_bonus = 10 if job.get("location") and str(job.get("location")).casefold() in query.casefold() else 0
    return min(100, query_score + location_bonus)


def _job_id(job: Mapping[str, Any], index: int) -> str:
    base = "-".join(filter(None, [_slug(str(job.get("company") or "")), _slug(str(job.get("role") or ""))])).strip("-")
    if not base:
        digest = hashlib.sha1((str(job.get("jd_url") or "") + str(index)).encode("utf-8")).hexdigest()[:10]
        return f"job-{digest}"
    return f"{base}-{index}"


def _job_to_jd_markdown(job: Mapping[str, Any]) -> str:
    lines = [
        "# JD Raw",
        "",
        f"- Company: {job.get('company', '')}",
        f"- Role: {job.get('role', '')}",
        f"- Platform: {job.get('platform', '')}",
        f"- Location: {job.get('location', '')}",
        f"- Salary: {job.get('salary', '')}",
        f"- URL: {job.get('jd_url', '')}",
        "",
        "## JD Text",
        "",
        str(job.get("jd_text") or ""),
        "",
    ]
    return "\n".join(lines)


def _crawl_job_info_backend(url: str, repo_root: Path | str | None = None, *, enable_boss: bool = False) -> dict[str, Any]:
    # BOSS 直聘 URLs: only route to boss backend when explicitly enabled
    host = urlparse(url).netloc.casefold()
    if enable_boss and ("zhipin.com" in host):
        from resume_agent.mcp.job_crawlers import _boss_available
        if _boss_available(os.environ):
            from resume_agent.mcp.job_crawlers import boss_cli_job_detail
            return boss_cli_job_detail(url)
    # All other URLs (and BOSS when enable_boss=False): crawl_job_url handles Firecrawl vs urllib
    return crawl_job_url(
        url=url,
        repo_root=repo_root or Path(__file__).resolve().parents[2],
        builtin_fetcher=_urllib_crawl_job_info_backend,
    )


def _urllib_crawl_job_info_backend(url: str) -> dict[str, Any]:
    request = Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36"
            )
        },
    )
    try:
        with urlopen(request, timeout=20) as response:
            charset = response.headers.get_content_charset() or "utf-8"
            html = response.read().decode(charset, errors="replace")
            final_url = response.geturl()
    except Exception as exc:  # noqa: BLE001
        raise ToolExecutionError(f"job detail crawl request failed: {exc}") from exc

    title = _extract_html_title(html)
    description = _extract_meta_content(html, "description")
    main_html = _extract_main_html(html)
    text = _html_to_text(main_html)
    if description and description not in text:
        text = f"{description}\n{text}".strip()

    return {
        "backend": "urllib",
        "title": title,
        "jd_text": text,
        "source_raw": text,
        "final_url": final_url,
        "platform": _platform_from_url(final_url),
    }


def _query_terms(query: str) -> list[str]:
    return [term for term in re.split(r"[\s,/|]+", query) if len(term.strip()) >= 2]


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _positive_int(value: Any, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(1, parsed)


def _first_nonempty(*values: Any) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _validate_http_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ToolExecutionError("crawl_job_info only supports http(s) URLs")


def _safe_filename(value: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "-", value.strip())
    return safe.strip(".-") or "job-detail"


def _extract_salary(text: str) -> str:
    patterns = [
        r"\b\d{1,3}\s*[kK]\s*[-~]\s*\d{1,3}\s*[kK]\b",
        r"\b\d{1,3}\s*[-~]\s*\d{1,3}\s*万\b",
        r"薪资\s*[：:]\s*([^\n，,；;]{2,30})",
        r"面议",
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return match.group(1).strip() if match.groups() else match.group(0).strip()
    return ""


def _slug(value: str) -> str:
    value = re.sub(r"[^A-Za-z0-9]+", "-", value.strip().lower())
    return value.strip("-")


def _platform_from_url(url: str) -> str:
    host = urlparse(url).netloc.casefold()
    if "linkedin" in host:
        return "linkedin"
    if "zhipin" in host or "boss" in host:
        return "boss"
    if "lagou" in host:
        return "lagou"
    if "liepin" in host:
        return "liepin"
    return host or "web"


def _extract_html_title(html: str) -> str:
    og_title = _extract_meta_content(html, "og:title")
    if og_title:
        return og_title
    match = re.search(r"(?is)<title[^>]*>(.*?)</title>", html)
    return _clean_html_text(match.group(1)) if match else ""


def _extract_meta_content(html: str, name: str) -> str:
    escaped = re.escape(name)
    patterns = [
        rf"(?is)<meta[^>]+(?:name|property)=['\"]{escaped}['\"][^>]+content=['\"]([^'\"]+)['\"][^>]*>",
        rf"(?is)<meta[^>]+content=['\"]([^'\"]+)['\"][^>]+(?:name|property)=['\"]{escaped}['\"][^>]*>",
    ]
    for pattern in patterns:
        match = re.search(pattern, html)
        if match:
            return _clean_html_text(match.group(1))
    return ""


def _extract_main_html(html: str) -> str:
    for pattern in (
        r"(?is)<article\b[^>]*>(.*?)</article>",
        r"(?is)<main\b[^>]*>(.*?)</main>",
        r"(?is)<(?:section|div)\b[^>]*(?:job|position|description|content|detail)[^>]*>(.*?)</(?:section|div)>",
    ):
        matches = re.findall(pattern, html)
        if matches:
            return max(matches, key=len)
    return html


def _html_to_text(html: str) -> str:
    html = re.sub(r"(?is)<(script|style|noscript|svg|iframe)\b.*?</\1>", " ", html)
    html = re.sub(r"(?is)<br\s*/?>", "\n", html)
    html = re.sub(r"(?is)</(p|div|li|h[1-6]|section|article|tr)>", "\n", html)
    text = re.sub(r"(?is)<[^>]+>", " ", html)
    text = unescape(text)
    lines = [re.sub(r"\s+", " ", line).strip() for line in text.splitlines()]

    result: list[str] = []
    previous = ""
    for line in lines:
        if not line or line == previous:
            continue
        result.append(line)
        previous = line
    return "\n".join(result).strip()


def _search_jobs_backend(query: str, location: str, limit: int, *, enable_boss: bool = False) -> list[dict[str, Any]]:
    # BOSS 直聘 direct API — only when explicitly enabled and credentials exist
    if enable_boss:
        boss_cookies = os.environ.get("BOSS_COOKIES", "").strip()
        if boss_cookies:
            try:
                return _boss_search_backend(query, location, limit)
            except ToolExecutionError:
                pass  # fall through to Firecrawl

    # Firecrawl search — default path for public job listings
    firecrawl_key = os.environ.get("FIRECRAWL_API_KEY", "").strip()
    if firecrawl_key:
        return _firecrawl_search_backend(query, location, limit)
    return _duckduckgo_search_backend(query, location, limit)


def _boss_search_backend(query: str, location: str, limit: int) -> list[dict[str, Any]]:
    """Search BOSS 直聘 directly via the Python BossClient."""
    # Map common city names to BOSS city codes
    city_code = _boss_city_code(location) or "100010000"  # 全国 default
    try:
        raw_jobs = boss_python_search(query, city=city_code, page_size=min(limit, 20))
    except ToolExecutionError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise ToolExecutionError(f"BOSS search failed: {exc}") from exc

    results: list[dict[str, Any]] = []
    for job in raw_jobs:
        security_id = str(job.get("securityId") or "")
        jd_url = (
            f"https://www.zhipin.com/job_detail/{security_id}.html"
            if security_id else ""
        )
        results.append({
            "company": str(job.get("brandName") or job.get("company") or "Unknown"),
            "role": str(job.get("jobName") or job.get("positionName") or "Unknown Role"),
            "salary": str(job.get("salaryDesc") or ""),
            "location": str(job.get("cityName") or job.get("areaDistrict") or location or ""),
            "jd_url": jd_url,
            "jd_text": str(job.get("skills") or job.get("postDescription") or ""),
            "source_raw": str(job.get("skills") or ""),
            "platform": "boss",
            "job_id_hint": security_id,
        })
    if not results:
        raise ToolExecutionError("BOSS search returned no results")
    return results


def _boss_city_code(location: str) -> str:
    """Map common city name fragments to BOSS city codes."""
    _CODES = {
        "上海": "101020100",
        "北京": "101010100",
        "深圳": "101280600",
        "广州": "101280100",
        "杭州": "101210100",
        "成都": "101270100",
        "武汉": "101200100",
        "南京": "101190100",
        "西安": "101110100",
        "全国": "100010000",
    }
    for name, code in _CODES.items():
        if name in location:
            return code
    return ""


def _firecrawl_search_backend(query: str, location: str, limit: int) -> list[dict[str, Any]]:
    search_query = " ".join(part for part in [query, location, "招聘"] if part).strip()
    try:
        raw = firecrawl_search_jobs(search_query, limit=limit)
    except Exception as exc:  # noqa: BLE001
        raise ToolExecutionError(f"Firecrawl job search failed: {exc}") from exc
    if not raw:
        raise ToolExecutionError("Firecrawl job search returned no results")
    results: list[dict[str, Any]] = []
    for item in raw:
        title = str(item.get("title") or "")
        url = str(item.get("url") or "")
        snippet = str(item.get("description") or "")
        role, company = _split_title(title)
        results.append({
            "company": company or "Unknown",
            "role": role or title,
            "jd_url": url,
            "jd_text": snippet,
            "source_raw": snippet,
            "platform": _platform_from_url(url),
        })
    return results


def _duckduckgo_search_backend(query: str, location: str, limit: int) -> list[dict[str, Any]]:
    search_query = " ".join(part for part in [query, location, "招聘"] if part).strip()
    url = "https://duckduckgo.com/html/?q=" + quote_plus(search_query)
    request = Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36"
            )
        },
    )
    try:
        with urlopen(request, timeout=20) as response:
            html = response.read().decode("utf-8", errors="replace")
    except Exception as exc:  # noqa: BLE001
        raise ToolExecutionError(f"job search request failed: {exc}") from exc

    results = _parse_duckduckgo_results(html, limit)
    if not results:
        raise ToolExecutionError("job search returned no results")
    return results


def _parse_duckduckgo_results(html: str, limit: int) -> list[dict[str, Any]]:
    from urllib.parse import unquote, urlparse, parse_qs

    blocks = re.findall(
        r'<a[^>]*class="result__a"[^>]*href="(?P<url>[^"]+)"[^>]*>(?P<title>.*?)</a>.*?'
        r'<a[^>]*class="result__snippet"[^>]*>(?P<snippet>.*?)</a>',
        html,
        flags=re.DOTALL | re.IGNORECASE,
    )
    results: list[dict[str, Any]] = []
    for raw_url, title, snippet in blocks[:limit]:
        # Unwrap DuckDuckGo redirect: //duckduckgo.com/l/?uddg=https%3A%2F%2F...
        url = unescape(raw_url)
        if url.startswith("//"):
            url = "https:" + url
        parsed = urlparse(url)
        qs = parse_qs(parsed.query)
        if "uddg" in qs:
            url = unquote(qs["uddg"][0])
        clean_title = _clean_html_text(title)
        clean_snippet = _clean_html_text(snippet)
        role, company = _split_title(clean_title)
        results.append(
            {
                "company": company or "Unknown",
                "role": role or clean_title,
                "jd_url": url,
                "jd_text": clean_snippet,
                "source_raw": clean_snippet,
                "platform": _platform_from_url(url),
            }
        )
    return results


def _clean_html_text(value: str) -> str:
    value = re.sub(r"<[^>]+>", " ", value)
    value = unescape(value)
    return re.sub(r"\s+", " ", value).strip()


def _split_title(title: str) -> tuple[str, str]:
    for separator in (" - ", " | ", " @ ", " — ", " – "):
        if separator in title:
            left, right = title.split(separator, 1)
            return left.strip(), right.strip()
    return title.strip(), ""
