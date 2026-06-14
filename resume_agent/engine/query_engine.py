from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from resume_agent.context.builder import build_context_pack
from resume_agent.engine.intent_router import route_intent
import json

from resume_agent.engine.query_loop import run_agent_loop
from resume_agent.engine.state import ResumeSessionState, ResumeStage
from resume_agent.engine.trace import TraceLogger
from resume_agent.model.openai_client import ChatModelClient, OpenAIChatModelClient
from resume_agent.tools.base import ToolContext, ToolPermission
from resume_agent.tools.builtins import create_builtin_registry
from resume_agent.tools.registry import ToolRegistry


@dataclass(frozen=True)
class EngineRequest:
    message: str
    project_dir: Path
    profile_file: Path | None = None
    company: str = "XX"
    role: str = "XX"
    jd_text: str | None = None
    jd_url: str | None = None
    history: list[dict] = field(default_factory=list)


@dataclass
class EngineResponse:
    status: str
    intent: str
    message: str
    changed_files: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    trace_path: str | None = None


class ResumeQueryEngine:
    def __init__(
        self,
        repo_root: Path | str,
        registry: ToolRegistry | None = None,
        model_client: ChatModelClient | None = None,
        allowed_permissions: set[ToolPermission] | None = None,
        max_turns: int = 12,
    ) -> None:
        self.repo_root = Path(repo_root).resolve()
        self.registry = registry or create_builtin_registry(self.repo_root)
        self.model_client = model_client or OpenAIChatModelClient(repo_root=self.repo_root)
        self.max_turns = max_turns
        self.allowed_permissions = allowed_permissions or {
            ToolPermission.READ,
            ToolPermission.WORKSPACE_WRITE,
            ToolPermission.EXPORT,
        }

    def submit_message(self, request: EngineRequest) -> EngineResponse:
        project_dir = request.project_dir.resolve()

        state = _merge_request_with_saved_state(request, _load_session_state(project_dir))

        # Read the static context once after session metadata has been restored.
        profile_content = _read_profile_file(state.profile_file)

        intent = route_intent(request.message, request.jd_text, request.jd_url)
        trace = TraceLogger(project_dir)
        trace.record(
            "user_message",
            {
                "message": request.message,
                "intent": intent.name,
                "project_dir": str(project_dir),
                "profile_file": str(state.profile_file) if state.profile_file else "",
            },
        )
        context_pack = build_context_pack(
            request.message,
            state,
            intent,
            self.registry,
            self.allowed_permissions,
            profile_content=profile_content,
        )
        trace.record("context", context_pack.data)

        try:
            messages = self._build_messages(request, context_pack.data)
            loop_result = run_agent_loop(
                model_client=self.model_client,
                registry=self.registry,
                messages=messages,
                context=context_pack.tool_context,
                allowed_permissions=self.allowed_permissions,
                trace=trace,
                max_turns=self.max_turns,
            )
            state.stage = ResumeStage.DONE
            state.changed_files = loop_result.changed_files
            response = EngineResponse(
                status="completed",
                intent=intent.name,
                message=loop_result.final_message or self._success_message(intent.name, loop_result.changed_files),
                changed_files=loop_result.changed_files,
                warnings=loop_result.warnings,
                trace_path=str(trace.path),
            )
            trace.record("final", response.__dict__)
            _save_session_state(state)
            return response
        except Exception as exc:  # noqa: BLE001
            warning = str(exc)
            response = EngineResponse(
                status="failed",
                intent=intent.name,
                message="ResumeQueryEngine failed before completing the requested workflow.",
                warnings=[warning],
                trace_path=str(trace.path),
            )
            trace.record("error", {"message": warning})
            trace.record("final", response.__dict__)
            _save_session_state(state)
            return response

    def _build_messages(self, request: EngineRequest, context_data: dict) -> list[dict]:
        request_data = {
            "project_dir": str(request.project_dir.resolve()),
            "profile_file": str(request.profile_file.resolve()) if request.profile_file else "",
            "company": request.company,
            "role": request.role,
            "jd_text": request.jd_text or "",
            "jd_url": request.jd_url or "",
        }
        return [
            {
                "role": "system",
                "content": (
                    "你是 OpenResume 的交互式简历 agent。你通过可用工具生成中文简历。\n\n"
                    "Pipeline 步骤（按顺序执行）：\n"
                    "1. import_profile — 将用户资料导入项目\n"
                    "2. normalize_profile — 抽取结构化 profile.json\n"
                    "3. add_jd_text — 录入岗位描述（如果用户提供了）\n"
                    "4. analyze_jd — 用 LLM 分析 JD，提取关键词和要求\n"
                    "5. build_resume_strategy — 生成策略和 spec_lock.json\n"
                    "6. generate_resume_modules — 综合 profile+JD+策略，用 LLM 生成简历内容\n"
                    "7. render_latex — 用 template1 渲染器将 resume_modules.json 转成 LaTeX\n"
                    "8. compile_pdf — 编译成 PDF\n\n"
                    "Revise 步骤（用户要求只调整某一段时优先执行）：\n"
                    "1. revise_resume_from_match_report — 如果已有 checks/match_report.json，优先读取报告并自动选择缺口最大的 section\n"
                    "2. read_resume_section — 没有匹配报告或用户指定 section 时，读取目标 section\n"
                    "3. revise_resume_section — 只改目标 section，自动 snapshot 并返回 diff\n"
                    "4. render_latex — 重新渲染 LaTeX\n"
                    "5. check_truthfulness/check_ats — 重新检查\n\n"
                    "Match Analysis 步骤（用户要求匹配度、岗位适配、评分时执行）：\n"
                    "1. match_analysis — 读取 JD 分析和 resume_modules，传 use_semantic_alignment=true 时加入 LLM 语义评估，输出 checks/match_report.json\n"
                    "2. compare_match_reports — 对比历史版本里的 match_report 和当前报告，输出 checks/match_trend.json\n\n"
                    "Job Hunt 步骤（用户要求找岗位、筛岗位时执行）：\n"
                    "1. search_jobs — 结合 query、location 和 profile/profile.json 搜索岗位，写入 jobs/jobs.jsonl\n"
                    "2. crawl_job_info — 已有岗位 URL 或 job_id 但缺少完整 JD 时，抓取详情并写入 jobs/job_details/<job_id>.json 与 jd/jd_raw.md\n"
                    "3. select_job — 用户选定某个 job_id 且已有足够 JD 文本后，写入 jobs/selected_job.json 和 jd/jd_raw.md，供后续 JD 分析与简历生成使用\n\n"
                    "规则：\n"
                    "1. 不要编造用户没有提供的经历、数字、公司、奖项。\n"
                    "2. 用户画像文件（静态上下文）已作为 [Static Context] 放在下面。\n"
                    "3. 工具参数中的路径必须使用下面用户请求元数据里的绝对路径。\n"
                    "4. 首次使用 import_profile 工具将用户文件导入项目。\n"
                    "5. 如果缺少 JD，先用中文简洁说明缺什么。\n"
                    "6. 不要直接写 LaTeX——用 generate_resume_modules + render_latex。\n"
                    "7. ONE-PAGE RULE：最终 PDF 必须刚好 1 页 A4。\n"
                    "8. 修改已有简历时，不要默认全量重生成；优先用 revise_resume_from_match_report 或 read_resume_section/revise_resume_section。\n"
                    "9. 每步完成后告诉用户当前进度，询问是否继续或调整。"
                ),
            },
            *request.history,
            {
                "role": "user",
                "content": (
                    request.message
                    + "\n\n[OpenResume context]\n"
                    + json.dumps(context_data, ensure_ascii=False, indent=2)
                    + "\n\n[Request metadata]\n"
                    + json.dumps(request_data, ensure_ascii=False, indent=2)
                ),
            },
        ]

    def _success_message(self, intent: str, changed_files: list[str]) -> str:
        if intent == "generate_resume":
            return f"Generated resume artifacts ({len(changed_files)} files changed)."
        if intent == "compile_pdf":
            return f"Compiled resume export ({len(changed_files)} files changed)."
        if intent == "job_hunt":
            return f"Generated job search artifacts ({len(changed_files)} files changed)."
        return "No workflow action was required."


def _read_profile_file(profile_file: Path | None) -> str:
    if profile_file is None:
        return ""
    path = profile_file.resolve()
    if not path.is_file():
        return ""
    try:
        return path.read_text(encoding="utf-8-sig")
    except OSError:
        return ""


def _load_session_state(project_dir: Path) -> ResumeSessionState | None:
    state_path = project_dir / "state.json"
    if not state_path.is_file():
        return None
    try:
        data = json.loads(state_path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    return ResumeSessionState.from_dict(data, project_dir)


def _merge_request_with_saved_state(
    request: EngineRequest,
    saved_state: ResumeSessionState | None,
) -> ResumeSessionState:
    project_dir = request.project_dir.resolve()
    profile_file = request.profile_file.resolve() if request.profile_file else None
    if profile_file is None and saved_state is not None:
        profile_file = saved_state.profile_file

    company = request.company
    if company == "XX" and saved_state is not None:
        company = saved_state.company

    role = request.role
    if role == "XX" and saved_state is not None:
        role = saved_state.role

    stage = saved_state.stage if saved_state is not None else ResumeStage.COLLECT_PROFILE
    changed_files = list(saved_state.changed_files) if saved_state is not None else []

    return ResumeSessionState(
        project_dir=project_dir,
        profile_file=profile_file,
        stage=stage,
        company=company,
        role=role,
        changed_files=changed_files,
    )


def _save_session_state(state: ResumeSessionState) -> None:
    state.project_dir.mkdir(parents=True, exist_ok=True)
    state_path = state.project_dir / "state.json"
    state_path.write_text(
        json.dumps(state.to_dict(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
