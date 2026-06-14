# 简历 Agent 实施计划

> 面向后续 agent/开发者执行：按阶段推进，不要把业务逻辑写进 VS Code 插件；插件只是 UI，真正的 agent harness、工具、记忆、PDF 编译都在本地 Python 后端。

**目标：** 把 OpenResume 从脚本式简历生成工具升级为本地简历生成与优化 agent，支持用户资料收集、JD 分析、公司定制简历、LaTeX PDF 导出、多轮编辑、反馈记忆，以及优先通过 VS Code 插件使用。

**架构：** 使用 Python 做可复用后端，借鉴 `claude-code-main` 的 harness 思路：外层 `QueryEngine` 管会话生命周期，内层 `query_loop` 管模型和工具调用，工具统一注册，MCP 作为外部能力边界，memory 独立维护，context builder 每轮构建上下文，trace 记录运行过程。Markdown 和结构化 artifact 是事实来源，模型只负责抽取、改写和决策，不能编造事实。

**技术栈：** Python 3.11+、OpenAI-compatible API、现有 `skills/resume-master/scripts`、Markdown、JSON、LaTeX/XeLaTeX、pytest、可选 FastAPI、本地 stdio MCP、TypeScript VS Code Extension。

---

## 0. 当前进度

已完成：

- Phase 0：清理源码区 Python/test 缓存，并记录清理审计。
- Phase 1：新增 pytest marker 和现有脚本 smoke tests。
- Phase 2：新增 `resume_agent/model/openai_client.py`，支持 `.env`/环境变量解析和 JSON 提取。
- Phase 3：新增 `resume_agent/tools/base.py`、`resume_agent/tools/registry.py`、`resume_agent/tools/builtins.py`，建立 Claude Code 风格的 Tool 抽象、权限过滤、执行生命周期、内置工具注册和脚本包装。
- Phase 4/5 基础版：新增 `resume_agent/engine/query_engine.py`、`query_loop.py`、`state.py`、`intent_router.py`、`trace.py` 和 `resume_agent/context/builder.py`，跑通 `ResumeQueryEngine` 的非网络简历生成 smoke flow。
- Phase 5 升级版：`query_loop.py` 已从固定工具计划升级为 LLM-driven tool-call loop：模型接收 messages/tools，返回 tool_calls，工具执行后结果以 `role=tool` 回灌给模型，循环直到最终回答。
- CLI：新增 `python resume_agent/cli.py chat` 交互式入口，并支持 `--once` 做单轮脚本化调用。
- 模型接入：新增 `OpenAIChatModelClient`，通过 OpenAI-compatible Chat Completions 调用 `.env` 中配置的 `API_KEY`、`BASE_URL`、`MODEL_NAME`，API key 不进入 repr/log。

当前验证：

```powershell
pytest -v
```

最近一次结果：`17 passed`。

下一步：

- 增强 `ResumeQueryEngine` 的多轮 artifact 状态恢复，让每轮自动读取当前项目状态摘要。
- 增加 memory store 和 feedback selector。
- 为 VS Code 插件增加 stdio/HTTP 后端协议。
- 把 `compile_pdf` 接入带错误修复的 LaTeX 编译流程。

## 1. 当前基线

已有可复用资产：

- `person/notes/`：候选人长期资料。
- `skills/resume-master/scripts/pipeline.py`：现有端到端演示管线。
- `skills/resume-master/scripts/llm/client.py`：现有 OpenAI-compatible 客户端，已支持读取 `.env`。
- `skills/resume-master/scripts/person_manager.py`：个人资料初始化、校验、合并。
- `skills/resume-master/scripts/source_to_profile/llm_normalize_profile.py`：资料结构化。
- `skills/resume-master/scripts/job_manager.py`：JD 文本/URL 录入。
- `skills/resume-master/scripts/jd_tools/jd_defaults.py`：JD 分析默认实现。
- `skills/resume-master/scripts/strategy/strategy_defaults.py`：简历策略默认实现。
- `skills/resume-master/scripts/generation/resume_builder.py`：Markdown 简历生成。
- `skills/resume-master/scripts/resume2latex.py`：Markdown 转 LaTeX。
- `skills/resume-master/scripts/render_pdf.py`：PDF 编译。
- `skills/resume-master/templates/latex/resume.cls`：LaTeX 简历模板。
- `claude-code-main/src/QueryEngine.ts`：会话级编排参考。
- `claude-code-main/src/query.ts`：模型-工具循环参考。
- `claude-code-main/src/Tool.ts`：工具接口与权限参考。
- `claude-code-main/src/tools.ts`：工具注册和 MCP 合并参考。
- `claude-code-main/src/context.ts`：上下文构建参考。
- `claude-code-main/src/memdir/`：文件型记忆参考。
- `claude-code-main/src/services/acp/agent.ts`：IDE 客户端桥接参考。

当前约束：

- 仓库根目录现在不是 git 仓库，实施时不能依赖 git checkpoint。
- `.env` 包含敏感 API 配置，任何日志、trace、文档都不能打印真实值。
- `claude-code-main` 只作为架构参考，不作为 OpenResume 的直接依赖。
- `README.md` 目前混入了一些架构讨论内容，后续需要把 README 重新收窄成安装和使用说明。

## 2. 推荐产品形态

第一阶段：本地 Python agent 后端。

```text
用户输入 / CLI / VS Code 插件
  -> resume_agent 后端
    -> ResumeQueryEngine
    -> query_loop
    -> tool registry
    -> memory
    -> LaTeX/PDF pipeline
```

第二阶段：VS Code 插件 MVP。

插件负责：

- 展示 `person/notes`。
- 展示岗位和简历版本。
- 提供聊天式简历编辑。
- 触发 JD 分析、生成、编译。
- 预览 Markdown、LaTeX、PDF。

插件不负责：

- 直接调用模型。
- 直接读 `.env`。
- 维护长期 memory。
- 实现简历生成业务逻辑。

第三阶段：Web。

Web 复用同一套后端 API，再新增鉴权、上传、下载、多用户存储、任务队列。

## 3. 目标目录结构

```text
resume_agent/
  __init__.py
  cli.py
  api/
    __init__.py
    server.py
  context/
    __init__.py
    builder.py
    prompt_packs.py
  engine/
    __init__.py
    intent_router.py
    query_engine.py
    query_loop.py
    state.py
    trace.py
  mcp/
    __init__.py
    client.py
    config.py
  memory/
    __init__.py
    policy.py
    selector.py
    store.py
  model/
    __init__.py
    openai_client.py
    schemas.py
  tools/
    __init__.py
    base.py
    registry.py
    profile_tools.py
    jd_tools.py
    strategy_tools.py
    resume_tools.py
    latex_tools.py
    quality_tools.py
tests/
  resume_agent/
    test_intent_router.py
    test_openai_client_config.py
    test_tool_registry.py
    test_context_builder.py
    test_memory_store.py
    test_query_engine_smoke.py
vscode-extension/
  package.json
  tsconfig.json
  src/
    extension.ts
    backendClient.ts
    chatPanel.ts
    resumeTree.ts
    pdfPreview.ts
```

## 4. Artifact 合同

agent 的事实来源必须落到文件，而不是只靠聊天上下文：

```text
projects/<project_id>/
  profile/
    profile.md
    profile.json
    fact_index.json
  jobs/
    <job_id>/
      jd/
        jd_raw.md
        jd_analysis.json
        keyword_map.json
      strategy/
        resume_strategy.md
        spec_lock.json
      drafts/
        resume.md
        resume_versions/
      checks/
        truthfulness_report.json
        ats_report.json
        length_report.json
        latex_report.json
      latex/
        resume.tex
        resume.cls
      exports/
        resume.md
        resume.pdf
  runs/
    <run_id>.jsonl
memory/
  MEMORY.md
  user_profile/
  feedback/
  project/
  company_preference/
  writing_style/
```

硬规则：简历里的强事实必须能追溯到 `profile.json`、`fact_index.json`、用户原始资料，或用户明确确认过的长期记忆。

## 5. Phase 0：仓库清理和基线确认

### Task 0.1：删除 Python 缓存

已执行：

```text
skills/resume-master/scripts/__pycache__/
skills/resume-master/scripts/shared/__pycache__/
```

验证命令：

```powershell
Get-ChildItem -Recurse -Force -File -Include '*.pyc' |
  Where-Object { $_.FullName -notlike '*\.venv\*' -and $_.FullName -notlike '*\claude-code-main\*' }
```

期望：无输出。

### Task 0.2：保留 `.venv/`，但保持忽略

`.venv/` 是可重建环境，但也是当前可运行环境。先不删除。

验证命令：

```powershell
Get-Content .gitignore
```

期望：包含 `.venv/`、`__pycache__/`、`*.py[cod]`、`.env`、LaTeX 临时文件。

### Task 0.3：人工确认 `examples/*.pdf`

这些 PDF 看起来是历史导出或示例文件，不能盲删。

验证命令：

```powershell
Get-ChildItem examples -File | Select-Object Name,Length,LastWriteTime
```

建议策略：保留 1 份视觉效果最好的 canonical sample，其余移到 `examples/archive/` 或删除。

### Task 0.4：后续清理 README

`README.md` 应只保留项目介绍、安装、快速开始、常用命令、文档链接。架构讨论迁移到：

- `docs/resume-agent-outline.md`
- `docs/resume-agent-implementation-plan.md`
- `docs/repository-cleanup-audit.md`

## 6. Phase 1：稳定现有脚本管线

### Task 1.1：为现有脚本增加 smoke tests

创建：

```text
tests/resume_master/test_pipeline_contracts.py
```

测试目标：

- `person_manager.py combine` 能生成 `profile/profile.md`。
- `job_manager.py add-text` 能写入 JD artifact。
- `resume2latex.py` 能把最小 Markdown 简历转成 `latex/resume.tex`。
- 默认测试不调用 LLM。

验证命令：

```powershell
pytest tests/resume_master -v
```

### Task 1.2：增加 pytest marker

创建：

```text
pytest.ini
```

内容：

```ini
[pytest]
markers =
    llm: requires configured OpenAI-compatible API
    latex: requires xelatex / MiKTeX / TeX Live
```

验证命令：

```powershell
pytest -m "not llm and not latex" -v
```

### Task 1.3：固定无 LLM 的演示路径

检查并强化：

```text
skills/resume-master/scripts/pipeline.py
```

要求：

- 保留现有 `--jd-text`、`--jd-file`、`--jd-url`。
- 保留或完善 `--profile-json`、`--jd-json`。
- 让端到端管线可以在不调用模型的情况下测试结构流。

验证命令：

```powershell
python skills/resume-master/scripts/pipeline.py --help
```

## 7. Phase 2：模型客户端层

### Task 2.1：抽出项目级 OpenAI-compatible client

创建：

```text
resume_agent/model/openai_client.py
tests/resume_agent/test_openai_client_config.py
```

行为：

- 从仓库根目录读取 `.env`。
- process env 优先于 `.env`。
- 支持 `OPENAI_API_KEY` 或 `API_KEY`。
- 支持 `OPENAI_BASE_URL` 或 `BASE_URL`。
- 支持 `OPENAI_MODEL`、`MODEL_NAME` 或 `MODEL`。
- 打印配置时永远不暴露 API key。

验证命令：

```powershell
pytest tests/resume_agent/test_openai_client_config.py -v
```

### Task 2.2：增加结构化 JSON 输出助手

修改：

```text
resume_agent/model/openai_client.py
```

行为：

- 提供 `complete_json(system: str, user: str) -> dict`。
- 兼容纯 JSON、```json fenced JSON```、以及模型前后夹杂短文本的情况。
- 支持注入 fake client，测试不需要真实网络。

验证命令：

```powershell
pytest tests/resume_agent/test_openai_client_config.py -v
```

## 8. Phase 3：工具抽象和注册中心

### Task 3.1：实现 Python Tool 接口

创建：

```text
resume_agent/tools/base.py
tests/resume_agent/test_tool_registry.py
```

每个工具包含：

- `name`
- `description`
- `input_schema`
- `read_only`
- `permission`
- `max_result_size`
- `validate(input)`
- `call(input, context)`

验证命令：

```powershell
pytest tests/resume_agent/test_tool_registry.py -v
```

### Task 3.2：实现 ToolRegistry

创建：

```text
resume_agent/tools/registry.py
```

行为：

- 按名称注册工具。
- 拒绝重复工具名。
- 按权限模式过滤工具。
- 输出模型可见的 tool schema。

验证命令：

```powershell
pytest tests/resume_agent/test_tool_registry.py -v
```

### Task 3.3：把现有脚本包装成工具

创建：

```text
resume_agent/tools/profile_tools.py
resume_agent/tools/jd_tools.py
resume_agent/tools/strategy_tools.py
resume_agent/tools/resume_tools.py
resume_agent/tools/latex_tools.py
resume_agent/tools/quality_tools.py
```

第一批内置工具：

- `read_person_notes`
- `combine_profile_markdown`
- `normalize_profile`
- `add_jd_text`
- `fetch_jd_url`
- `analyze_jd`
- `build_resume_strategy`
- `generate_resume_markdown`
- `generate_latex`
- `compile_pdf`
- `check_truthfulness`
- `check_ats`

## 9. Phase 4：状态、上下文和意图识别

### Task 4.1：定义会话状态

创建：

```text
resume_agent/engine/state.py
tests/resume_agent/test_context_builder.py
```

状态枚举：

- `COLLECT_PROFILE`
- `NORMALIZE_PROFILE`
- `FETCH_JD`
- `ANALYZE_JD`
- `BUILD_STRATEGY`
- `DRAFT_RESUME`
- `REVIEW`
- `EDIT`
- `COMPILE_PDF`
- `EXPORT`

验证：状态能 JSON 序列化和恢复。

### Task 4.2：实现分层 intent router

创建：

```text
resume_agent/engine/intent_router.py
tests/resume_agent/test_intent_router.py
```

规则：

- URL 或招聘链接 -> `FETCH_JD`
- 长 JD 文本 -> `ANALYZE_JD`
- “生成简历 / 做一版 / 投某公司” -> `DRAFT_RESUME`
- “压缩 / 改写 / 突出 / 不要写” -> `EDIT`
- “编译 / 导出 / PDF” -> `COMPILE_PDF`
- 缺资料时询问用户，不编造。

验证命令：

```powershell
pytest tests/resume_agent/test_intent_router.py -v
```

### Task 4.3：实现 context builder

创建：

```text
resume_agent/context/builder.py
resume_agent/context/prompt_packs.py
tests/resume_agent/test_context_builder.py
```

每轮 context pack 包含：

- 用户请求。
- 当前阶段。
- workspace 路径。
- 用户画像摘要。
- fact index 摘要。
- JD 摘要。
- 策略摘要。
- 当前简历版本摘要。
- 最近反馈。
- 可用工具。
- 禁止编造规则。

验证：context 不包含 `.env` 密钥值。

## 10. Phase 5：ResumeQueryEngine 和 query loop

### Task 5.1：实现 trace logger

创建：

```text
resume_agent/engine/trace.py
tests/resume_agent/test_query_engine_smoke.py
```

行为：

- 写入 `projects/<project_id>/runs/<run_id>.jsonl`。
- 记录用户输入、意图、工具调用、工具结果、模型摘要、错误、最终响应。
- 对 `.env` 值和 API key 做脱敏。

### Task 5.2：实现 query loop

创建：

```text
resume_agent/engine/query_loop.py
```

行为：

- 接收 model client、tool registry、context pack、max turns。
- 把工具 schema 传给模型。
- 执行模型请求的工具。
- 把工具结果放回下一轮。
- 到最终回答或 max turns 停止。
- 返回结构化 `QueryResult`。

验证：fake model 请求 fake tool，收到结果后输出 final answer。

### Task 5.3：实现 ResumeQueryEngine

创建：

```text
resume_agent/engine/query_engine.py
```

行为：

- 加载或初始化 session state。
- 路由 intent。
- 构建 context。
- 调用 query loop。
- 持久化 artifact 和 trace。
- 返回 UI 友好的结果：message、changed files、next actions、warnings。

## 11. Phase 6：记忆和反馈

### Task 6.1：实现文件型 memory store

创建：

```text
resume_agent/memory/store.py
resume_agent/memory/policy.py
tests/resume_agent/test_memory_store.py
```

memory 类型：

- `user_profile`
- `feedback`
- `project`
- `company_preference`
- `writing_style`
- `resume_version_note`

策略：

- 不保存密钥。
- 不把应属于 `profile.json` 的事实写成 memory。
- 长期 memory 写入需要用户明确确认。

### Task 6.2：实现 memory selector

创建：

```text
resume_agent/memory/selector.py
```

行为：

- 按公司、岗位、关键词、memory 类型选择相关记忆。
- 限制注入上下文的 memory 数量。
- 当前公司/岗位反馈优先于无关长期偏好。

## 12. Phase 7：MCP 边界

### Task 7.1：先支持本地 stdio MCP

创建：

```text
resume_agent/mcp/config.py
resume_agent/mcp/client.py
```

行为：

- 只支持本地 `stdio` MCP 作为 MVP。
- 从项目配置读取 MCP server。
- 把 MCP tools 转成统一 ToolRegistry 形状。

暂不做：

- SSE MCP。
- HTTP OAuth MCP。
- WebSocket MCP。
- 绕过登录、验证码或反爬。

## 13. Phase 8：CLI 和本地 API

### Task 8.1：增加 CLI

创建：

```text
resume_agent/cli.py
```

命令：

- `resume-agent init-project`
- `resume-agent add-jd`
- `resume-agent chat`
- `resume-agent generate`
- `resume-agent compile`

验证命令：

```powershell
python -m resume_agent.cli --help
```

### Task 8.2：增加本地 API

创建：

```text
resume_agent/api/server.py
```

可能修改：

```text
requirements.txt
```

API 能力：

- 创建 session。
- 提交 prompt。
- 查询 artifact。
- 查询 PDF 路径。
- 返回进度事件。

## 14. Phase 9：VS Code 插件 MVP

### Task 9.1：插件脚手架

创建：

```text
vscode-extension/package.json
vscode-extension/tsconfig.json
vscode-extension/src/extension.ts
```

注册命令：

- `openresume.startAgent`
- `openresume.generateResume`
- `openresume.compilePdf`
- `openresume.openChat`

验证命令：

```powershell
cd vscode-extension
npm install
npm run compile
```

### Task 9.2：插件后端客户端

创建：

```text
vscode-extension/src/backendClient.ts
```

行为：

- 启动或连接本地 Python 后端。
- 提交用户 prompt。
- 接收进度和最终响应。
- 插件不直接读取 `.env`。

### Task 9.3：插件 UI

创建：

```text
vscode-extension/src/chatPanel.ts
vscode-extension/src/resumeTree.ts
vscode-extension/src/pdfPreview.ts
```

MVP UI：

- 多轮简历编辑聊天面板。
- `person/notes`、jobs、drafts、exports 树视图。
- PDF 预览命令。

## 15. Phase 10：质量门禁

### Task 10.1：真实性检查

修改：

```text
resume_agent/tools/quality_tools.py
```

检查：

- 经历、项目、奖项、指标都必须映射到来源事实。
- 不允许凭空增加数字、公司、技术栈、职责。
- 风险 claim 在导出前提示。

### Task 10.2：ATS 和长度检查

修改：

```text
resume_agent/tools/quality_tools.py
```

检查：

- JD 关键词覆盖。
- 一页简历目标。
- LaTeX 前的格式风险。
- 中文/英文标点和列表一致性。

### Task 10.3：LaTeX 编译修复循环

当前状态：基础版已实现于 `resume_agent/tools/latex_tools.py`，包括 XeLaTeX 错误摘要、LLM 修复 `resume.tex`、重编译、one-page gate 和 `checks/export_quality.json`。

修改：

```text
resume_agent/tools/latex_tools.py
resume_agent/engine/query_loop.py
```

行为：

- 捕获 XeLaTeX `.log` 关键错误。
- 把错误摘要交给模型。
- 允许一次修复 `.tex` 或源 Markdown。
- 修复失败时给出明确错误，不让用户读长日志。

## 16. MVP 验收标准

MVP 完成时，下面这条链路能在本地跑通：

```text
用户维护 person/notes
用户粘贴 JD 文本或 URL
agent 生成/刷新 profile facts
agent 分析 JD
agent 生成简历策略
agent 生成 resume.md
agent 生成 resume.tex
agent 编译 resume.pdf
用户通过多轮对话反馈修改
agent 编辑同一个简历版本
agent 在用户允许时记录长期反馈
```

最高优先级验收标准：

- `exports/resume.pdf` 存在。
- 简历主要事实都能追溯到用户资料或已确认事实。
- `.env` 密钥没有出现在 trace、日志、context 或文档中。

## 17. 下一步实际执行顺序

1. 补 `tests/resume_master/test_pipeline_contracts.py`，先保护现有脚本管线。
2. 补 `pytest.ini`，区分普通测试、LLM 测试和 LaTeX 测试。
3. 创建 `resume_agent/model/openai_client.py`。
4. 创建 `resume_agent/tools/base.py` 和 `registry.py`。
5. 把现有脚本包装成 tools。
6. 创建 state、intent router、context builder。
7. 创建 query loop 和 `ResumeQueryEngine`。
8. 创建 memory store 和 feedback selector。
9. 创建 CLI。
10. 创建 VS Code 插件壳。
