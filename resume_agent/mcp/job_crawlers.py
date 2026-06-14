from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable, Mapping
from urllib.parse import parse_qs, urlparse
from urllib.request import Request, urlopen

from resume_agent.mcp.config import load_mcp_config
from resume_agent.tools.base import ToolExecutionError


JobCrawlerFetcher = Callable[[str], dict[str, Any]]


def crawl_job_url(
    url: str,
    repo_root: Path | str,
    builtin_fetcher: JobCrawlerFetcher,
    backend: str | None = None,
    environ: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Route a URL to the right crawler backend.

    Priority (when no explicit ``backend`` given):
    1. FIRECRAWL_API_KEY set → firecrawl
    2. Fallback → urllib builtin fetcher

    BOSS 直聘 routing is handled upstream by ``_crawl_job_info_backend``
    when ``enable_boss=True`` is passed by the caller.
    """
    env = os.environ if environ is None else environ
    configured = (backend or load_mcp_config(repo_root, environ=env).job_crawler_backend).strip().lower()

    # Explicit backend override
    if configured not in {"", "builtin", "urllib", "default", "auto"}:
        if configured == "firecrawl":
            return firecrawl_scrape_job_url(url, environ=env)
        if configured == "boss":
            return boss_cli_job_detail(url, environ=env)
        raise ToolExecutionError(f"unknown job crawler backend: {configured}")

    # Auto: Firecrawl if key exists, else urllib
    firecrawl_key = str(env.get("FIRECRAWL_API_KEY") or "").strip()
    if firecrawl_key:
        return firecrawl_scrape_job_url(url, environ=env)
    return builtin_fetcher(url)


def _boss_available(env: Mapping[str, str]) -> bool:
    """Return True if BOSS credentials are available (env var or saved file)."""
    if str(env.get("BOSS_COOKIES") or "").strip():
        return True
    # Check saved credential file
    try:
        from pathlib import Path as _Path
        import json as _json
        cred_file = _Path.home() / ".config" / "boss-cli" / "credential.json"
        if cred_file.is_file():
            data = _json.loads(cred_file.read_text(encoding="utf-8"))
            return bool(data.get("cookies"))
    except Exception:  # noqa: BLE001
        pass
    return False


def firecrawl_scrape_job_url(
    url: str,
    environ: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    env = os.environ if environ is None else environ
    api_key = str(env.get("FIRECRAWL_API_KEY") or "").strip()
    if not api_key:
        raise ToolExecutionError("FIRECRAWL_API_KEY is required for firecrawl job crawler backend")

    endpoint = _firecrawl_endpoint(str(env.get("FIRECRAWL_API_URL") or "https://api.firecrawl.dev"))

    # Many job boards (e.g. jobs.bytedance.com) render the JD client-side via JS.
    # waitFor tells Firecrawl to wait N ms for the page to hydrate before scraping,
    # otherwise we only capture the static nav shell. Configurable via FIRECRAWL_WAIT_MS.
    try:
        wait_ms = int(str(env.get("FIRECRAWL_WAIT_MS") or "5000").strip())
    except ValueError:
        wait_ms = 5000
    wait_ms = max(0, min(wait_ms, 30000))

    payload_body: dict[str, Any] = {
        "url": url,
        "formats": ["markdown"],
        "onlyMainContent": True,
    }
    if wait_ms > 0:
        payload_body["waitFor"] = wait_ms

    body = json.dumps(payload_body).encode("utf-8")
    request = Request(
        endpoint,
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
    )

    try:
        with urlopen(request, timeout=max(30, wait_ms // 1000 + 30)) as response:
            payload = json.loads(response.read().decode("utf-8", errors="replace"))
    except Exception as exc:  # noqa: BLE001
        raise ToolExecutionError(f"Firecrawl scrape failed: {exc}") from exc

    if payload.get("success") is False:
        raise ToolExecutionError(f"Firecrawl scrape failed: {payload.get('error') or payload}")

    data = payload.get("data", payload)
    if not isinstance(data, Mapping):
        raise ToolExecutionError("Firecrawl scrape response did not contain an object payload")
    metadata = data.get("metadata", {})
    metadata = metadata if isinstance(metadata, Mapping) else {}
    markdown = str(data.get("markdown") or data.get("content") or "").strip()
    if not markdown:
        raise ToolExecutionError("Firecrawl scrape response did not contain markdown")

    return {
        "backend": "firecrawl",
        "title": str(metadata.get("title") or ""),
        "jd_text": markdown,
        "source_raw": markdown,
        "final_url": str(metadata.get("sourceURL") or metadata.get("url") or url),
        "platform": _platform_from_url(str(metadata.get("sourceURL") or url)),
    }


def boss_cli_job_detail(
    url: str,
    environ: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Fetch a BOSS 直聘 job detail.

    Tries two strategies in order:
    1. Python BossClient in-process (requires BOSS_COOKIES env or saved credential)
    2. subprocess ``boss detail <securityId> --json`` fallback
    """
    env = os.environ if environ is None else environ
    security_id = _boss_security_id(url)

    # Strategy 1: Python BossClient (fastest, no subprocess overhead)
    boss_cookies = str(env.get("BOSS_COOKIES") or "").strip()
    if boss_cookies or _boss_credential_file_exists():
        try:
            return _boss_python_job_detail(url, security_id, boss_cookies)
        except ToolExecutionError:
            raise
        except Exception as exc:  # noqa: BLE001
            # Fall through to subprocess strategy
            pass

    # Strategy 2: subprocess boss CLI
    if not security_id:
        raise ToolExecutionError("BOSS job crawler backend requires securityId in the URL")
    return _boss_subprocess_job_detail(url, security_id, env)


def _boss_python_job_detail(url: str, security_id: str, boss_cookies: str) -> dict[str, Any]:
    """Use boss-cli Python API to fetch job detail."""
    boss_cli_path = Path(__file__).resolve().parents[2] / "boss-cli"
    if boss_cli_path.is_dir() and str(boss_cli_path) not in sys.path:
        sys.path.insert(0, str(boss_cli_path))

    try:
        from boss_cli.auth import Credential, load_credential
        from boss_cli.client import BossClient
    except ImportError as exc:
        raise ToolExecutionError(f"boss-cli not importable: {exc}") from exc

    if boss_cookies:
        credential = Credential(
            {k.strip(): v.strip() for part in boss_cookies.split(";") if "=" in part
             for k, v in [part.split("=", 1)]}
        )
    else:
        credential = load_credential()
        if not credential:
            raise ToolExecutionError("No BOSS credential available (set BOSS_COOKIES in .env)")

    if not security_id:
        raise ToolExecutionError("BOSS job detail requires securityId in the URL")

    try:
        with BossClient(credential=credential) as client:
            data = client.get_job_detail(security_id)
    except Exception as exc:
        raise ToolExecutionError(f"BOSS job detail failed: {exc}") from exc

    if isinstance(data, dict) and data.get("code") not in (0, None, "0"):
        raise ToolExecutionError(f"BOSS job detail API error: {data.get('message') or data}")

    payload = data if isinstance(data, dict) else {}
    job_data = payload.get("data", payload)
    return _normalize_boss_detail(job_data if isinstance(job_data, dict) else payload, url)


def _boss_subprocess_job_detail(url: str, security_id: str, env: Mapping[str, str]) -> dict[str, Any]:
    """Subprocess fallback: call ``boss detail <securityId> --json``."""
    command = str(env.get("BOSS_CLI") or "boss").strip()
    subprocess_env = dict(os.environ)
    subprocess_env.update({k: str(v) for k, v in env.items()})
    try:
        proc = subprocess.run(
            [command, "detail", security_id, "--json"],
            text=True,
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            env=subprocess_env,
        )
    except OSError as exc:
        raise ToolExecutionError(f"BOSS CLI failed to start: {exc}") from exc
    if proc.returncode != 0:
        message = proc.stderr.strip() or proc.stdout.strip() or f"exit code {proc.returncode}"
        raise ToolExecutionError(f"BOSS CLI detail failed: {message}")

    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise ToolExecutionError("BOSS CLI detail did not return JSON") from exc
    if payload.get("ok") is False:
        raise ToolExecutionError(f"BOSS CLI detail failed: {payload}")

    data = payload.get("data", payload)
    if not isinstance(data, Mapping):
        raise ToolExecutionError("BOSS CLI detail response did not contain data")
    return _normalize_boss_detail(data, url)


def boss_python_search(
    query: str,
    city: str = "101020100",
    page: int = 1,
    page_size: int = 10,
    environ: Mapping[str, str] | None = None,
) -> list[dict[str, Any]]:
    """Search BOSS 直聘 jobs using the Python BossClient.

    Requires BOSS_COOKIES in environment or a saved credential file.
    Returns a list of raw job dicts from the BOSS API.
    """
    env = os.environ if environ is None else environ
    boss_cookies = str(env.get("BOSS_COOKIES") or "").strip()

    boss_cli_path = Path(__file__).resolve().parents[2] / "boss-cli"
    if boss_cli_path.is_dir() and str(boss_cli_path) not in sys.path:
        sys.path.insert(0, str(boss_cli_path))

    try:
        from boss_cli.auth import Credential, load_credential
        from boss_cli.client import BossClient
    except ImportError as exc:
        raise ToolExecutionError(f"boss-cli not importable: {exc}") from exc

    if boss_cookies:
        credential = Credential(
            {k.strip(): v.strip() for part in boss_cookies.split(";") if "=" in part
             for k, v in [part.split("=", 1)]}
        )
    else:
        credential = load_credential()
        if not credential:
            raise ToolExecutionError("No BOSS credential available (set BOSS_COOKIES in .env)")

    try:
        with BossClient(credential=credential) as client:
            result = client.search_jobs(query, city=city, page=page, page_size=page_size)
    except Exception as exc:
        raise ToolExecutionError(f"BOSS search failed: {exc}") from exc

    if isinstance(result, dict) and result.get("code") not in (0, None, "0"):
        raise ToolExecutionError(f"BOSS search API error: {result.get('message') or result}")

    jobs_data = result if isinstance(result, dict) else {}
    job_list = (
        jobs_data.get("zpData", {}).get("jobList")
        or jobs_data.get("data", {}).get("jobList")
        or jobs_data.get("jobList")
        or []
    )
    return [dict(job) for job in job_list if isinstance(job, dict)]


def _boss_credential_file_exists() -> bool:
    try:
        cred_file = Path.home() / ".config" / "boss-cli" / "credential.json"
        if cred_file.is_file():
            data = json.loads(cred_file.read_text(encoding="utf-8"))
            return bool(data.get("cookies"))
    except Exception:  # noqa: BLE001
        pass
    return False


def _normalize_boss_detail(data: Mapping[str, Any], url: str) -> dict[str, Any]:
    job = data.get("jobInfo", data)
    boss = data.get("bossInfo", {})
    brand = data.get("brandComInfo", {})
    job = job if isinstance(job, Mapping) else {}
    boss = boss if isinstance(boss, Mapping) else {}
    brand = brand if isinstance(brand, Mapping) else {}

    jd_text = str(job.get("postDescription") or job.get("jobDesc") or data.get("jobDesc") or "").strip()
    title = str(job.get("jobName") or "")
    company = str(brand.get("brandName") or job.get("brandName") or "")
    boss_name = str(boss.get("name") or "")

    return {
        "backend": "boss",
        "title": title,
        "company": company,
        "role": title,
        "salary": str(job.get("salaryDesc") or ""),
        "location": str(job.get("locationName") or job.get("cityName") or ""),
        "jd_text": jd_text,
        "source_raw": jd_text,
        "final_url": url,
        "platform": "boss",
        "posted_at": "",
        "recruiter": boss_name,
    }


def firecrawl_search_jobs(
    query: str,
    limit: int = 10,
    environ: Mapping[str, str] | None = None,
) -> list[dict[str, Any]]:
    """Search for job postings via the Firecrawl /v1/search endpoint.

    Returns a list of raw result dicts with keys: title, url, description.
    Raises ToolExecutionError if the API key is missing or the request fails.
    """
    env = os.environ if environ is None else environ
    api_key = str(env.get("FIRECRAWL_API_KEY") or "").strip()
    if not api_key:
        raise ToolExecutionError("FIRECRAWL_API_KEY is required for firecrawl job search")

    base = str(env.get("FIRECRAWL_API_URL") or "https://api.firecrawl.dev").rstrip("/")
    if not base.endswith("/v1"):
        base = base + "/v1"
    endpoint = base + "/search"

    body = json.dumps({"query": query, "limit": limit}).encode("utf-8")
    request = Request(
        endpoint,
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
    )

    try:
        with urlopen(request, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8", errors="replace"))
    except Exception as exc:  # noqa: BLE001
        raise ToolExecutionError(f"Firecrawl search failed: {exc}") from exc

    if payload.get("success") is False:
        raise ToolExecutionError(f"Firecrawl search failed: {payload.get('error') or payload}")

    raw_results = payload.get("data", [])
    if not isinstance(raw_results, list):
        raise ToolExecutionError("Firecrawl search response did not contain a list")

    results: list[dict[str, Any]] = []
    for item in raw_results:
        if not isinstance(item, Mapping):
            continue
        title = str(item.get("title") or item.get("metadata", {}).get("title") or "")
        url = str(item.get("url") or "")
        description = str(
            item.get("description")
            or item.get("markdown")
            or item.get("metadata", {}).get("description")
            or ""
        ).strip()
        results.append({"title": title, "url": url, "description": description})

    return results


def _firecrawl_endpoint(api_url: str) -> str:
    base = api_url.rstrip("/")
    if base.endswith("/v1"):
        return base + "/scrape"
    return base + "/v1/scrape"


def _boss_security_id(url: str) -> str:
    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    for key in ("securityId", "security_id", "securityid"):
        if query.get(key):
            return str(query[key][0])
    match = re.search(r"securityId=([^&#]+)", url, flags=re.IGNORECASE)
    return match.group(1) if match else ""


def _platform_from_url(url: str) -> str:
    host = urlparse(url).netloc.casefold()
    if "zhipin" in host or "boss" in host:
        return "boss"
    if "linkedin" in host:
        return "linkedin"
    if "lagou" in host:
        return "lagou"
    if "liepin" in host:
        return "liepin"
    return host or "web"
