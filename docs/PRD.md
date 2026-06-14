# OpenResume PRD — 简历生成优化项目

> **Product Requirements Document**  
> 版本：v1.1 (更新于 2026-06-14)  
> **当前状态：P0 全部完成 ✅ + 真实链路自动化 smoke test 已落地 ✅ + 多模板编译目录/cls 对齐已加固 ✅ + 平台集成进行中（FastAPI 后端已完成，Web 前端与 Skills 封装进行中）。核心生产线已端到端真实跑通（真实 LLM + Firecrawl + xelatex 出 PDF）。**

> **最近一次端到端验证（真实环境）**：
> `pipeline --search-query "字节跳动 AI Agent 开发工程师 上海" --allow-network --auto-select`
> 17 个阶段全部 `ok`（含 2 轮自动 revise loop），真实 Firecrawl 抓取字节跳动 JS 渲染岗位页成功（4557 字符真实 JD），全程无编码错误。详见 §3.6。
>
> **测试现状**：默认套件 `103 passed`（不含 4 个真实链路 smoke test）；3 个 `@pytest.mark.llm` / `@pytest.mark.latex` smoke test 已手动跑通，真实出 PDF。详见 §3.7。

---

## 1. 产品目标

OpenResume 的核心目标不是单点生成简历，而是完成一条可重复、可检查、可迭代的求职生产线：

```text
用户个人情况 / 项目 / 经历
  -> 结构化 profile + fact index
  -> 获取目标公司岗位介绍 / JD
  -> JD schema 化分析
  -> 简历策略
  -> 高匹配 resume_modules + Markdown 简历
  -> LaTeX / PDF 导出
  -> 匹配度、真实性、ATS、单页检查
  -> 根据报告定向修改
```

当前最优先的任务是把这条链路做成一个稳定的 P0 pipeline，而不是继续扩展面试、插件、多模板等外围能力。

---

## 2. 架构设计（三层模型）

### 2.0 设计理念：模仿 Claude Code 的 Agent 架构

OpenResume 采用与 Claude Code 类似的分层 Agent 架构，通过三层逐步加强的约束，实现"模型有自主决策空间"但"系统有安全护栏"的平衡：

#### **第 1 层：通用 Agent 框架（已完成 90%）**

最底层是通用 Agent 基础设施，模仿 Claude Code 的核心设计：

```
┌──────────────────────────────────────────────────┐
│  LLM API (OpenAI / Claude / 其他兼容模型)        │
│  • Tool use / function calling                    │
│  • 模型自由选择调用哪个工具                       │
└──────────────────────────┬───────────────────────┘
                           │
┌──────────────────────────▼───────────────────────┐
│  Tool Registry + Query Loop (query_loop.py)      │
│  • Tool 定义、schema、权限                        │
│  • 模型 → Tool Call → Tool Execution → 回灌      │
│  • Max turns 限制，防止死循环                    │
└──────────────────────────┬───────────────────────┘
                           │
┌──────────────────────────▼───────────────────────┐
│  Permission System (permissions.py)              │
│  • 粗粒度：NETWORK / WORKSPACE_WRITE / DELETE    │
│  • 细粒度：路径越界检查、敏感操作审批            │
└──────────────────────────┬───────────────────────┘
                           │
┌──────────────────────────▼───────────────────────┐
│  Artifact / State / Context                      │
│  • 会话状态、项目工作空间、可用工具列表          │
│  • 用户 profile 内容、JD 分析结果（作为 context）
└──────────────────────────────────────────────────┘
```

**特点**：
- ✅ 模型有充分的工具集和自主权
- ✅ 权限系统防止越界写入、恶意网络调用
- ✅ Trace 记录所有执行步骤
- ❌ 但模型可能漏步骤、乱序、或达到 max_turns 失败

#### **第 2 层：约束与质量门禁（已完成 75%）**

在通用框架之上，增加针对简历业务的约束：

```
┌──────────────────────────────────────────────────┐
│  Context Rules（context_builder.py）             │
│  • 系统 prompt 中注入 Pipeline 顺序建议          │
│  • 注入 One-Page Rule、真实性约束、JD 匹配要求   │
└──────────────────────────┬───────────────────────┘
                           │
┌──────────────────────────▼───────────────────────┐
│  Post-Tool Hooks（hooks.py）                    │
│  • generate_resume_modules → 自动执行            │
│      check_truthfulness                          │
│  • render_latex → 自动执行                       │
│      check_truthfulness + check_ats              │
│  • revise_resume_from_match_report → 自动执行    │
│      check_truthfulness + match_analysis         │
└──────────────────────────┬───────────────────────┘
                           │
┌──────────────────────────▼───────────────────────┐
│  Schema Validation + Repair（tools/base.py）   │
│  • JD Analysis Schema、Resume Modules Schema     │
│  • 坏结构自动 repair，仍失败则拒绝执行下一步    │
└──────────────────────────────────────────────────┘
```

**特点**：
- ✅ 自动触发质量检查，不依赖模型记起来
- ✅ Schema 校验确保数据结构完整
- ⚠️ 但这些约束仍无法保证"执行顺序"和"不漏步骤"

#### **第 3 层：确定性 Pipeline 流程（已完成 98% ✅）**

最上层是确定性的业务流程编排，已实现于 `resume_agent/engine/pipeline.py`：

```
❌ 缺失：resume_agent/engine/pipeline.py
✅ 已实现：resume_agent/engine/pipeline.py（ResumePipeline，下述阶段全部落地）

实现的设计：
┌──────────────────────────────────────────────────┐
│  Pipeline Orchestrator（需要新建）               │
│  • 不是"模型随意调用工具"                        │
│  • 而是"按固定阶段顺序执行"                      │
│                                                  │
│  Phase 1: preflight 检查                        │
│    ├─ 检查资料完整性                            │
│    ├─ 检查 LLM 配置                             │
│    └─ 检查网络权限                              │
│                                                  │
│  Phase 2: import_profile (必执行)               │
│    └─ 失败则中止                                │
│                                                  │
│  Phase 3: normalize_profile (必执行)            │
│    └─ 失败则中止                                │
│                                                  │
│  Phase 4: resolve_target_job (必执行)           │
│    ├─ 三选一：jd_text / jd_url / search_query   │
│    └─ 失败则中止                                │
│                                                  │
│  Phase 5-8: 核心生成链路 (按顺序)               │
│    ├─ analyze_jd → build_resume_strategy        │
│    ├─ generate_resume_modules (触发 hook)       │
│    ├─ render_latex (触发 hook)                  │
│    └─ compile_pdf (可选)                        │
│                                                  │
│  Phase 9-11: 检查链路 (按顺序)                  │
│    ├─ check_truthfulness                        │
│    ├─ check_ats                                 │
│    └─ match_analysis                            │
│                                                  │
│  Phase 12: pipeline_report 生成                 │
│    └─ 记录每个 Phase 的状态、输出、失败原因     │
│                                                  │
│  Revise Loop (可选)：                           │
│    如果 match_score < threshold：                │
│    ├─ 调用 revise_resume_from_match_report     │
│    ├─ 重新 render_latex + 检查                  │
│    └─ 重新 match_analysis                       │
│                                                  │
└──────────────────────────────────────────────────┘
```

**这一层的关键特点**：
- 🎯 流程完全确定性，不依赖模型决策
- 📋 每个 Phase 有明确的输入要求、成功条件、失败处理
- 📊 生成 pipeline_report.json，记录完整的执行历史
- ✅ 用户能看到"为什么成功"或"为什么失败"
- 🔄 框架控制流程，模型在需要的地方做 LLM 调用（如 generate_resume_modules）

#### **三层的关系图**

```
User Input
    │
    ▼
┌─────────────────────────────────────────────────────┐
│  Pipeline Orchestrator (第 3 层)                     │
│  确定性流程控制，不受模型决策影响                   │
└──────────┬──────────────────────────────────────────┘
           │
   ┌───────┴───────┐
   │               │
   ▼               ▼
Phase X       Phase Y
   │               │
   └───────┬───────┘
           │
┌──────────▼──────────────────────────────────────────┐
│  Constraint & Quality Gates (第 2 层)               │
│  • Context Rules 约束模型思路                       │
│  • Post-Tool Hooks 自动检查                         │
│  • Schema Validation 确保数据完整                   │
└──────────┬──────────────────────────────────────────┘
           │
   ┌───────┴───────────────────────────────────┐
   │                                           │
   ▼                                           ▼
tool_execute_with_hooks         permission_check
   │                                           │
   └───────┬───────────────────────────────────┘
           │
┌──────────▼──────────────────────────────────────────┐
│  Core Agent Framework (第 1 层)                      │
│  • LLM API + Tool Call Loop                         │
│  • Tool Registry + Query Loop                       │
│  • Permission System (路径、网络、敏感操作)        │
│  • Trace Logger                                      │
└─────────────────────────────────────────────────────┘
```

### 2.1 关键设计原则

**原则 1：模型有决策权，系统有护栏**
- ✅ 模型在"非 Critical Path 工具"上有自由选择权（如 search_jobs 的参数）
- ❌ 模型不能决定"是否执行 analyze_jd"这样的 Critical Phase
- ✅ Pipeline Orchestrator 确保了这一点

**原则 2：约束分层，从粗到细**
- 🔓 粗粒度：Permission（能不能调用这个工具）
- 🔒 中粒度：Context Rules（应该怎样调用）
- 🔐 细粒度：Post-Tool Hooks（调用后的自动检查）
- 🔒 最强：Pipeline Orchestrator（必须按流程）

**原则 3：可观测性优先**
- 📊 Trace: 记录每一步工具调用
- 📋 Pipeline Report: 记录每个 Phase 的状态
- 📄 Artifact: 保留所有中间产物，支持追溯
- 🔍 支持 revise 和 rollback

---

## 3. 当前已完成内容

以下状态来自当前代码和测试，不再按旧 PRD 的过期状态判断。

### 3.1 Harness 底座

| 模块 | 当前状态 | 关键文件 |
|---|---|---|
| Tool 抽象 | 已完成，统一 `FunctionTool`、schema、permission、handler | `resume_agent/tools/base.py` |
| Tool Registry | 已完成，支持注册、权限过滤、模型 schema 输出、执行时权限检查 | `resume_agent/tools/registry.py` |
| PermissionPolicy | 已完成，路径越界、NETWORK 审批、DELETE 拒绝、敏感写入确认 | `resume_agent/tools/permissions.py` |
| QueryEngine | 已完成基础会话生命周期、state、context、trace、tool loop 调用 | `resume_agent/engine/query_engine.py` |
| Query Loop | 已完成模型 tool-call loop，工具结果回灌，max turns | `resume_agent/engine/query_loop.py` |
| Context Builder | 已完成 artifact inventory、可用工具、规则注入 | `resume_agent/context/builder.py` |
| Hooks | 已完成 post-tool 质量门禁骨架 | `resume_agent/engine/hooks.py` |
| Trace | 已完成 JSONL run trace | `resume_agent/engine/trace.py` |
| Slash Commands | 已完成 `/generate` `/revise` `/compile` `/check` `/match` `/job_hunt` | `resume_agent/commands/registry.py` |

### 3.2 简历生成核心能力

| 能力 | 当前状态 | 关键文件 |
|---|---|---|
| 资料导入 | 已完成 `read_user_profile` / `import_profile` | `resume_agent/tools/profile_tools.py` |
| 资料结构化 | 已完成 `normalize_profile`，生成 `profile.json` / `fact_index.json` | `resume_agent/tools/profile_tools.py` |
| JD 文本录入 | 已完成 `add_jd_text` | `resume_agent/tools/jd_tools.py` |
| JD URL 拉取 | 已完成基础 `fetch_jd_url` | `resume_agent/tools/jd_tools.py` |
| JD 分析 schema | 已完成 `JD_ANALYSIS_SCHEMA`、validate、normalize | `resume_agent/schema/jd_analysis.py` |
| JD 分析 repair | 已接入 `analyze_jd`，坏结构会尝试一次 repair，仍失败则拒绝写入 | `resume_agent/tools/jd_tools.py` |
| 简历策略 | 已完成 `build_resume_strategy` | `resume_agent/tools/strategy_tools.py` |
| 简历模块生成 | 已完成 `generate_resume_modules`，含 schema 校验和 repair | `resume_agent/tools/resume_tools.py` |
| 多模板渲染 | 已完成 8 套模板渲染：`render_latex` 按 `resume_modules.json` 的 `template_id` 自动选择渲染器（可用 `template_id` 入参覆盖，未知值回退 `red_card`） | `resume_agent/tools/latex_tools.py` |
| PDF 编译 | 已完成 `compile_pdf`，含 LaTeX repair 和 one-page gate | `resume_agent/tools/latex_tools.py` |
| 质量检查 | 已完成 `check_truthfulness` / `check_ats` | `resume_agent/tools/quality_tools.py` |
| 匹配分析 | 已完成 `match_analysis` / `compare_match_reports` | `resume_agent/tools/match_tools.py` |
| 增量修改 | 已完成 section read/write/revise、基于 match report 的修改入口 | `resume_agent/tools/resume_section_tools.py` |
| 快照/回滚 | 已完成 snapshot / diff / rollback | `resume_agent/tools/artifact_tools.py` |
| Memory | 已完成 save / recall memory | `resume_agent/tools/memory_tools.py` |

### 3.3 岗位发现和外部工具边界

| 能力 | 当前状态 | 关键文件 |
|---|---|---|
| 岗位搜索 MVP | 已完成 `search_jobs`，默认 DuckDuckGo HTML 搜索，写 `jobs/jobs.jsonl` | `resume_agent/tools/job_hunt_tools.py` |
| 岗位选择 | 已完成 `select_job`，写 `jobs/selected_job.json` 和 `jd/jd_raw.md` | `resume_agent/tools/job_hunt_tools.py` |
| 岗位详情抓取 | 已完成 `crawl_job_info`，支持 URL 或 `job_id`，写 `jobs/job_details/<job_id>.json` 和 `jd/jd_raw.md` | `resume_agent/tools/job_hunt_tools.py` |
| Firecrawl adapter | 已完成 `/v1/scrape` REST adapter，返回 markdown 主内容；支持 `waitFor`（默认 5000ms，可配 `FIRECRAWL_WAIT_MS`）等待 JS 渲染，已验证可抓取字节跳动等客户端渲染岗位页 | `resume_agent/mcp/job_crawlers.py` |
| BOSS detail adapter | 已完成 `boss detail <securityId> --json` 只读详情 adapter | `resume_agent/mcp/job_crawlers.py` |
| MCP 配置 | 已完成 `.openresume/mcp.json` / `openresume.mcp.json` 读取 | `resume_agent/mcp/config.py` |
| MCP stdio client | 已完成最小 JSON-RPC stdio client | `resume_agent/mcp/client.py` |

注意：MCP client 已存在，但还没有把任意 MCP server 的 tools 动态转换并合并进 `ToolRegistry`。Firecrawl/BOSS 当前是 job crawler adapter，不是完整 MCP tool marketplace。

### 3.4 当前测试状态

最近一次主体验证命令：

```powershell
pytest tests/resume_agent tests/resume_master -m "not llm and not latex" -q
```

结果：

```text
89 passed, 1 deselected
```

说明：

- OpenResume 主体测试通过（含新增的 revise loop 触发回归测试、Firecrawl waitFor 测试）。
- 该命令不包含真实 LLM、真实 LaTeX 环境、真实招聘网站登录态测试。
- 真实 LLM + 真实 Firecrawl 的端到端链路已手动验证（见 §3.6），但尚未做成自动化 smoke test。
- 仓库内 `boss-cli/` 是独立子项目，依赖环境和测试门禁不作为 OpenResume 当前 harness 验收标准。

### 3.6 真实环境端到端验证（2026-06-13 新增）

首次用真实 LLM（DeepSeek-V4-Flash via SiliconFlow）+ 真实 Firecrawl 跑通完整 pipeline，命令：

```bash
python resume_agent/cli.py pipeline \
  --profile-file person/mytest_1.md \
  --company "字节跳动" --role "AI Agent 开发工程师" \
  --search-query "字节跳动 AI Agent 开发工程师 上海" \
  --location "上海" --allow-network --auto-select --min-match-score 60
```

结果：**17 个阶段全部 `ok`**（preflight → import → normalize → resolve_target_job → analyze_jd → strategy → generate_modules → render_latex → 三项检查 → match_analysis → 2 轮 revise loop 各含 revise+render+match）。

这一轮验证暴露并修复了 4 个真实 bug：

| # | 问题 | 根因 | 修复 |
|---|---|---|---|
| 1 | Firecrawl 抓字节跳动岗位页只拿到导航壳，JD 为空 | 页面客户端 JS 渲染，scrape 未等待 hydration | `firecrawl_scrape_job_url` 增加 `waitFor`（默认 5000ms，可配）+ 放宽 timeout。JD 从导航文字 → 4557 字符真实内容 |
| 2 | Windows 下子进程打印中文可能 `UnicodeEncodeError` | 子进程 stdout 默认 gbk 编码 | `run_script` 注入 `PYTHONIOENCODING=utf-8` / `PYTHONUTF8=1` |
| 3 | match_score 低于阈值时 revise loop 永不触发 | pipeline 读 `match_score`，但 `match_analysis` 工具返回的是 `overall_score`，键名不匹配恒为 0 | 新增 `_extract_match_score` 兼容两个键名 |
| 4 | revise loop 一触发就崩 | `revise_resume_from_match_report` 要求必填 `instruction`，pipeline 自动调用时未提供 | `instruction` 改为可选，缺省时从 match_report 缺口关键词自动生成默认指令 |

**已知局限（非 bug，待后续优化）**：

- match_analysis 语义打分波动较大（同一份简历多次打分差异明显），revise 后分数可能不单调上升。根因是轻量模型对中文语义对齐的打分一致性差。后续可考虑更强模型或多次取均值。
- 当候选人背景与岗位方向存在结构性差距时（如 CV/数据科学背景投前端 GUI Agent 岗），revise 在"不编造"约束下无法补出根本不存在的经历，匹配度天然偏低 —— 这是**正确且诚实**的行为，应通过 search 阶段的岗位-候选人方向预筛来缓解，而非放松真实性约束。

### 3.7 真实链路自动化 smoke test + 平台集成（2026-06-14 新增）

**真实链路 smoke test 已落地** —— `tests/resume_agent/test_pipeline_e2e_smoke.py`：

| 测试 | 标记 | 前置条件（缺失则 skip） | 覆盖 |
|---|---|---|---|
| `test_pipeline_real_llm_jd_text_to_modules` | `@llm` | API_KEY | 真实 LLM + 静态 JD → 校验 resume_modules / resume.tex / pipeline_report |
| `test_pipeline_real_llm_and_xelatex_to_pdf` | `@llm @latex` | API_KEY + xelatex | 全链路含真实 xelatex 编译 → 校验 resume.pdf 实际产出且非空 |
| `test_pipeline_real_firecrawl_crawls_js_job_page` | `@llm` | API_KEY + FIRECRAWL_API_KEY | search → auto-select → 真实抓取 JS 岗位页，断言 JD 正文 > 800 字符（非导航壳） |

- 三个测试均已在真实环境手动跑通：LLM 路径 ~225s、Firecrawl 路径 ~102s、含 PDF 编译 ~119s，**真实生成了一页 A4 中文简历 PDF**。
- 默认套件用 `-m "not llm and not latex"` 排除，CI 不受外部服务影响；本地按需 `-m llm` / `-m "llm and latex"` 触发。

**本轮又修复 2 个真实 pipeline bug（#5、#6）**：

| # | 问题 | 根因 | 修复 |
|---|---|---|---|
| 5 | `--compile` 始终静默失败，从不产出 PDF | pipeline 从未授予 `EXPORT` 权限，而 `compile_pdf` 工具要求该权限 | `compile_pdf=True` 时向 `allowed` 权限集加入 `ToolPermission.EXPORT`；新增不依赖 LLM 的快速回归测试锁定 |
| 6 | 多模板项目 xelatex 编译报 `<template>.cls not found` | `render_pdf.py` 的 cls 兜底写死只复制 `resume.cls`，不认识 8 套模板的 per-template cls（`red_card.cls` 等）；外部编译器又未把 cwd 切到 `latex/` | `render_pdf.py` 新增 `parse_documentclass()` 从 tex 解析真实类名 + `locate_cls_source()`/`ensure_cls()` 编译前自动把对应 `.cls` 复制进 `latex/`（已存在则不覆盖），编译仍在 `cwd=latex/` 运行。agent 现在自己完成目录/cls 对齐。新增 6 个纯函数回归测试 |

**平台集成 —— FastAPI 后端已完成**（`resume_agent/api/`）：

| 模块 | 说明 | 文件 |
|---|---|---|
| Job Runner | 后台线程跑 pipeline（耗时数分钟），内存态追踪 status/phases/outputs，支持轮询 | `resume_agent/api/jobs.py` |
| FastAPI App | `/api/health`、`/api/templates`、`POST /api/pipeline`、`/api/jobs/{id}`、`/api/jobs/{id}/artifact`、`/api/jobs/{id}/pdf`；含路径穿越防护、localhost 绑定、无鉴权（本地单用户工具） | `resume_agent/api/server.py` |
| 测试 | `TestClient` 路由/校验/防穿越测试 7 个，全部 mock runner 不跑真实 pipeline | `tests/resume_agent/test_api_server.py` |

**`template_id` 已端到端贯通**：`PipelineInput.template_id` → `render_latex`（含 revise loop 内的重渲染），CLI 新增 `--template`，API 请求体支持 `template_id`，覆盖 `resume_modules.json` 内置值。

**平台集成剩余**：Web 静态前端（`resume_agent/api/static/`，进行中）、Claude Code Skills 封装、README。

### 3.5 当前完成度总结

按功能模块统计当前完成进度（**2026-06-13 重要更新**）：

### 核心模块完成度

```
Core Infrastructure (工具框架)
▓▓▓▓▓▓▓▓▓░ 90% ✅
✓ Tool 抽象、Registry、权限系统、Query Engine、CLI 命令行

Data Processing (数据处理)
▓▓▓▓▓▓▓▓▓▓ 98% ✅
✓ Profile 导入/结构化、JD 分析、策略生成、Resume 模块生成
✓ 多模板 LaTeX 渲染（8 套）、PDF 编译
✓ schema validation + repair

Job Discovery (岗位发现)
▓▓▓▓▓▓▓▓░░ 85% ✅
✓ 搜索、选择、详情抓取
✓ Firecrawl adapter（支持 JS 渲染页 waitFor）、BOSS adapter
✓ resolve_target_job 统一入口（已完成！）
✓ 真实抓取字节跳动等 JS 渲染岗位页已验证
⚠ 缺少真实网站登录态、验证码处理

Quality & Analysis (质量检查)
▓▓▓▓▓▓▓▓▓░ 90% ✅
✓ 真实性检查、ATS 检查、匹配度分析
✓ 自动匹配度闭环（revise loop，真实环境已验证可触发并完整执行）
✓ pipeline_report（已完成！）
⚠ match_analysis 语义打分一致性待提升

Pipeline Orchestration (端到端流程)
▓▓▓▓▓▓▓▓▓▓ 98% ✅✅✅
✓ Pipeline Orchestrator（已完成！）
✓ resolve_target_job 统一入口（已完成！）
✓ pipeline_preflight 检查（已完成！）
✓ pipeline_report JSON 输出（已完成！）
✓ 完整的 12+ 阶段流程
✓ 自动 revise loop（真实环境已验证可触发并完整执行 2 轮）

Testing & E2E (测试覆盖)
▓▓▓▓▓▓▓▓▓░ 92% ✅
✓ 单元测试 103 passed（默认套件）
✓ Mock 测试完整
✓ artifact、hooks、agent_loop、builtin_tools、match_tools、pipeline revise loop、API 路由 等完整覆盖
✓ 真实链路自动化 smoke test 已落地（@pytest.mark.llm / @pytest.mark.latex，3 个，含真实出 PDF）
⚠ smoke test 尚未接入 CI 手动触发流水线

Multi-Template (多模板)
▓▓▓▓▓▓▓▓▓▓ 95% ✅
✓ 8 套语义化命名模板（red_card / navy_sidebar / teal_clean / minimal_bw /
  orange_warm / dark_sidebar / blue_modern / purple_tech）
✓ 每套含 .cls + Jinja2 partials + manifest + sample + renderer
✓ render_latex 按 template_id 自动选择
✓ template_id 端到端贯通：PipelineInput → render_latex，CLI --template、API template_id
✓ 编译目录/cls 对齐已加固：render_pdf.py 按 documentclass 自动复制 per-template cls，red_card 真实出 PDF
⚠ 真实 xelatex 下其余 7 套模板的逐一编译验证待补（部分用 tikz/paracol/tcolorbox）

Platform Integration (平台集成)
▓▓▓▓░░░░░░ 45% 🚧
✓ FastAPI 后端（pipeline/templates/jobs/artifact/pdf 端点 + 防穿越 + 测试）
🚧 Web 静态前端（进行中）
🚧 Claude Code Skills 封装（进行中）
⚠ 缺少 VS Code 插件
⚠ 缺少 MCP tools 动态注册
```

### 按优先级层级的完成度

**P0（必须完成）** ✅ **已全部完成！**
```
完成度: ▓▓▓▓▓▓▓▓▓░ 95%

✅ 基础工具链（Tool/Registry/权限系统）
✅ 个人资料处理（Profile/Fact Index）
✅ JD 分析处理（抓取/分析/Schema 校验）
✅ 简历生成链路（策略/模块/渲染/PDF）
✅ 质量检查工具（真实性/ATS/匹配度）
✅ Pipeline Orchestrator（确定性流程）← 已完成！
✅ resolve_target_job（统一岗位入口）← 已完成！
✅ pipeline_preflight（前置检查）← 已完成！
✅ pipeline_report.json（执行报告）← 已完成！
✅ 自动匹配度闭环（revise loop）← 已完成！
```

**P1（高优先级增强）**
```
已完成: ▓▓▓▓▓▓▓░░░ 70%
✓ BOSS detail adapter（已有）
✓ pipeline_tools 的 preflight 和 resolve_target_job
✓ Firecrawl JS 渲染页支持（waitFor）
✓ 多模板系统（8 套）
✓ 真实 LLM + 真实爬取的端到端手动验证
✓ 真实链路自动化 smoke test（@pytest.mark.llm / @pytest.mark.latex）
✓ 模板选择的 pipeline CLI 入口（--template）+ template_id 端到端贯通
⚠ 缺失：MCP tools 动态注册
⚠ 缺失：版本隔离 (projects/<id>/versions/)
⚠ 缺失：match_analysis 打分一致性提升
```

**P2/P3（进行中 / 延期）**
```
已完成: ▓▓░░░░░░░░ 20%
✓ API Server (FastAPI 后端已完成)
🚧 Web 前端 / Claude Code Skills 封装（进行中）
⚠ VS Code 插件: 0%
⚠ 模拟面试: 0%
```

### 关键缺口现状对标

| 缺口 | 当前状态 | 优先度 | 工作量 |
|---|---|---|---|
| ~~Pipeline Orchestrator~~ | ✅ **已完成** | P0 | 完成 |
| ~~resolve_target_job~~ | ✅ **已完成** | P0 | 完成 |
| ~~pipeline_preflight~~ | ✅ **已完成** | P0 | 完成 |
| ~~pipeline_report~~ | ✅ **已完成** | P0 | 完成 |
| ~~真实 E2E 验证（手动）~~ | ✅ **已完成**（真实 LLM + Firecrawl 跑通） | P0 | 完成 |
| ~~真实链路自动化 smoke test~~ | ✅ **已完成**（3 个，含真实出 PDF） | P0 | 完成 |
| ~~多模板系统~~ | ✅ **已完成**（8 套） | P1 | 完成 |
| ~~Firecrawl JS 渲染页支持~~ | ✅ **已完成**（waitFor） | P1 | 完成 |
| ~~模板选择 CLI 入口（--template）~~ | ✅ **已完成**（含 API template_id 贯通） | P1 | 完成 |
| ~~`--compile` 静默失败（EXPORT 权限）~~ | ✅ **已修复** | P0 | 完成 |
| ~~多模板编译 cls/目录对齐（agent 自编译）~~ | ✅ **已修复** | P0 | 完成 |
| ~~API Server~~ | ✅ **已完成**（FastAPI 后端 + 测试） | P2 | 完成 |
| Web 前端 | 🚧 进行中 | P2 | 0.5-1 day |
| Claude Code Skills 封装 | 🚧 进行中 | P2 | 0.5 day |
| match_analysis 打分一致性 | ⚠️ 待提升 | P1 | 1-2 days |
| MCP tools 动态注册 | ❌ 缺失 | P1 | 2 days |
| 版本隔离 (projects/<id>/) | ❌ 缺失 | P1 | 1-2 days |
| VS Code 插件 | ❌ 缺失 | P2 | 5+ days |

---

## 5. P0 实施完成总结

### Sprint 完成回顾

#### ✅ Sprint 0：定义 Pipeline 合同 — **已完成**

新增文件：
- ✅ `resume_agent/engine/pipeline.py` — 完整的 ResumePipeline 类
- ✅ `resume_agent/tools/pipeline_tools.py` — pipeline_preflight + resolve_target_job

数据结构：
- ✅ `PipelineInput` — 完整的输入参数定义
- ✅ `PipelineResult` — 完整的输出结果定义  
- ✅ `PipelinePhase` — 阶段执行记录

#### ✅ Sprint 1：实现 `resolve_target_job` — **已完成**

新增工具：
- ✅ `resolve_target_job(project_dir, jd_text, jd_url, search_query, company, role, ...)`
  - ✅ jd_text 路径 → `add_jd_text`
  - ✅ jd_url 路径 → `crawl_job_info` / `fetch_jd_url`
  - ✅ search 路径 → `search_jobs` → `crawl_job_info` → 用户选择或自动选择
  - ✅ 返回 `needs_user_input` 当歧义时

#### ✅ Sprint 2：实现 pipeline preflight — **已完成**

新增工具：
- ✅ `pipeline_preflight(project_dir, profile_file, jd_text, jd_url, ...)`
  - ✅ 检查 profile 文件存在性、可读性
  - ✅ 检查 JD 来源完整性
  - ✅ 检查 LLM 配置
  - ✅ 检查网络权限
  - ✅ 检查输出目录可写性
  - ✅ 返回 issues 列表或 status=ok

#### ✅ Sprint 3：实现 Pipeline Orchestrator — **已完成**

核心模块：
- ✅ `ResumePipeline.run(input)` — 固定阶段调用
  - ✅ Phase 0: preflight
  - ✅ Phase 1: import_profile
  - ✅ Phase 2: normalize_profile
  - ✅ Phase 3: resolve_target_job
  - ✅ Phase 4-8: 生成链路
  - ✅ Phase 9-11: 检查链路
  - ✅ Phase 12: revise loop（自动修改）
  - ✅ Phase 13: pipeline_report
- ✅ 每个 Phase 记录 status / outputs / error / duration
- ✅ 关键 Phase 失败则中止，非关键可继续
- ✅ 自动 revise loop（低于阈值反复修改）

#### ✅ Sprint 4：匹配度闭环 — **已完成**

自动修改逻辑：
- ✅ `match_analysis` 返回 match_score
- ✅ 如果 score < min_match_score 且次数 < max_revise_loops
  - ✅ 调用 `revise_resume_from_match_report`
  - ✅ 重新 `render_latex`
  - ✅ 重新 `check_truthfulness`
  - ✅ 重新 `match_analysis`
- ✅ 记录每次修改的 diff 和新 score

#### ✅ Sprint 5：CLI 支持 — **已完成**

命令行接口：
- ✅ `resume_agent/cli.py` 支持 `pipeline` 命令
- ✅ 参数支持：`--profile-file`, `--company`, `--role`, `--jd-url`, `--search-query`, `--allow-network`, `--compile`
- ✅ 输出：最终 artifact 路径 + pipeline_report.json

---

## 6. 下一步优先级 — 从 P0 Critical 转向 P1/P2

### 立即启动（P0-Critical 最后一步）

**真实链路自动化 smoke test**（🔴 **必须**）
```
背景: 真实 LLM + 真实 Firecrawl 的端到端链路已手动跑通（见 §3.6），
      下一步是把它固化成可重复的自动化测试，防止回归。

工作清单:
├─ [ ] 编写 smoke test：真实 LLM API 调用（@pytest.mark.llm）
├─ [ ] 编写 smoke test：真实 Firecrawl 爬取（含 JS 渲染页）
├─ [ ] 编写 smoke test：真实 xelatex 编译（@pytest.mark.latex），覆盖多套模板
├─ [ ] CI/CD：标记为 @pytest.mark.llm / @pytest.mark.latex，需手动触发
└─ [ ] 文档：说明如何本地运行真实 E2E 测试与所需环境变量

预期用时: 1-2 days
验收条件:
  - [ ] 真实用户输入从 pipeline 开始到 resume.pdf 生成，无需人工干预
  - [ ] pipeline_report.json 显示所有 Phase status=ok 或合理的 skipped
  - [ ] 生成的 PDF 确实是一页 A4 的中文简历（至少验证 1-2 套模板）
```

### P1 优先级增强（后续迭代）

**版本隔离** （🟡 重要）
```
目标: 支持多家公司、多个岗位的独立版本管理

设计：
  projects/<project_id>/
    ├─ jd/
    ├─ strategy/
    ├─ drafts/
    ├─ latex/
    ├─ checks/
    └─ exports/

工作量: 1-2 days
```

**MCP Tools 动态注册**（🟡 重要）
```
目标: 将任意 MCP server 的 tools 动态转为 FunctionTool

工作量: 2-3 days
```

**Firecrawl Search Adapter**（🟡 可选）
```
目标: 用 Firecrawl 的 /search 接口替代 DuckDuckGo

工作量: 1 day
```

### P2 延期功能

- [ ] API Server (3-5 days)
- [ ] VS Code 插件 (5+ days)
- [ ] 模拟面试 (需 P0 stable 后)

---

| 缺口 | 当前状态 | 为什么挡住 P0 |
|---|---|---|
| 缺少确定性的 pipeline orchestrator | 现在主要依赖模型在 query loop 中选择工具 | 模型可能漏步骤、跳检查、没有统一失败恢复 |
| 缺少 `resolve_target_job` | 已有 `search_jobs` / `crawl_job_info` / `select_job`，但没有统一入口 | 用户说“帮我投某公司某岗位”时，系统还不能稳定完成岗位解析、搜索、详情抓取和选择 |
| 缺少 pipeline preflight | 现在各工具各自报错 | 不能在开始前检查 profile、JD、网络、LLM、LaTeX、输出目录等条件 |
| 缺少 pipeline report | 目前有 trace 和分散检查报告 | 用户和开发者不能一眼看出每个阶段是否完成、失败在哪、是否可导出 |
| 缺少自动匹配度闭环 | 已有 `match_analysis` 和 revise 工具，但没有“低于阈值自动定向修改”的 orchestrator | 不能保证生成结果“匹配度高”，只能说“生成后可以检查” |
| 缺少 profile 完整度门禁 | `normalize_profile` 已有，但没有判断资料是否足够支撑目标岗位 | 容易在信息不足时生成泛化简历，或压不出亮点 |
| 缺少真实场景 E2E 验证 | 当前测试多为 fake model / fake crawler / no real latex | 无法证明真实用户输入 + 真实岗位 URL + 真实 LLM 能稳定跑完全链路 |
| 缺少公司/岗位版本隔离标准 | 现有 artifact 多在项目根目录 | 多家公司、多岗位会互相覆盖，难以比较版本 |

---

## 5. P0 实施路线图

### Sprint 0：定义 Pipeline 合同

新增或修改：

```text
resume_agent/engine/pipeline.py
resume_agent/tools/pipeline_tools.py
tests/resume_agent/test_pipeline_orchestrator.py
```

建议新增结构：

```python
TargetedResumePipelineInput:
    project_dir: str
    profile_file: str
    company: str = ""
    role: str = ""
    jd_text: str = ""
    jd_url: str = ""
    search_query: str = ""
    location: str = ""
    allow_network: bool = False
    compile_pdf: bool = True
    min_match_score: int = 75

TargetedResumePipelineResult:
    status: "completed" | "needs_user_input" | "failed"
    phases: list[PipelinePhase]
    outputs: dict
    warnings: list[str]
    next_actions: list[str]
```

验收：

- fake model + fake crawler 下，一条测试能从 `profile_file + jd_url` 跑到 `resume_modules.json`、`resume.tex`、`match_report.json`。
- 每个阶段都有明确输入、输出、错误信息。

### Sprint 1：实现 `resolve_target_job`

新增：

```text
resume_agent/tools/job_resolution_tools.py
```

能力：

```text
resolve_target_job(project_dir, company, role, jd_text, jd_url, search_query, location)
```

规则：

- 如果有 `jd_text`：直接 `add_jd_text`。
- 如果有 `jd_url`：优先 `crawl_job_info`，失败再退回 `fetch_jd_url`。
- 如果只有 `company/role/search_query`：调用 `search_jobs`，再对 top candidates 调 `crawl_job_info`。
- 如果搜索结果多且相似：返回 `needs_user_input`，不要替用户乱选。
- 成功后必须写 `jd/jd_raw.md`，并在 `jobs/selected_job.json` 或 `jobs/job_details/` 留痕。

验收：

- URL 路径、文本路径、搜索路径都各有测试。
- 搜索结果歧义时不会继续生成简历。

### Sprint 2：实现 pipeline preflight

新增：

```text
resume_agent/tools/pipeline_tools.py
```

能力：

```text
pipeline_preflight(project_dir, profile_file, jd_text, jd_url, allow_network, compile_pdf)
```

检查：

- `profile_file` 是否存在、是否可读、是否为空。
- 如果没有 JD 文本或 URL，是否有足够 `company/role/search_query`。
- `allow_network` 是否允许抓取岗位。
- LLM 配置是否存在，不打印密钥。
- 如果 `compile_pdf=true`，检查 `xelatex` 或已配置 LaTeX 环境。
- project_dir 是否可写。

验收：

- 缺资料时返回 `needs_user_input`，不进入生成。
- 缺网络授权时不调用 network tool。

### Sprint 3：实现确定性 pipeline orchestrator

新增：

```text
resume_agent/engine/pipeline.py
```

第一版不要依赖模型自由选择工具，而是按固定阶段调用 ToolRegistry：

```text
preflight
import_profile
normalize_profile
resolve_target_job
analyze_jd
build_resume_strategy
generate_resume_modules
render_latex
compile_pdf
check_truthfulness
check_ats
match_analysis
write pipeline_report
```

规则：

- 每一步必须记录 phase status。
- 工具失败时进入 `failed`，写入 `checks/pipeline_report.json`。
- 需要用户选择岗位时进入 `needs_user_input`，不能继续生成。
- 如果 `match_analysis` 分数低于阈值，进入 revise loop 或给出明确风险。

验收：

- `checks/pipeline_report.json` 包含所有阶段状态。
- `EngineResponse.changed_files` 能包含 pipeline 关键产物。

### Sprint 4：匹配度闭环

目标：从“能生成”升级为“能生成高匹配简历”。

新增逻辑：

```text
match_analysis
  -> 若 score >= min_match_score：通过
  -> 若 score < min_match_score：
       revise_resume_from_match_report
       render_latex
       check_truthfulness
       check_ats
       match_analysis again
```

限制：

- 默认最多 1-2 次 revise loop。
- 每次修改必须 snapshot 和 diff。
- 不能为了提高匹配度编造经历。

验收：

- 低匹配 fake report 会触发一次定向修改。
- 修改后重新写 `checks/match_report.json`。
- truthfulness 风险不通过时，pipeline 不能报告成功。

### Sprint 5：CLI 入口

新增命令：

```powershell
python resume_agent/cli.py pipeline `
  --profile-file person/mytest_1.md `
  --company "目标公司" `
  --role "AI Agent Engineer" `
  --jd-url "https://..." `
  --allow-network `
  --compile
```

或：

```powershell
python resume_agent/cli.py pipeline `
  --profile-file person/mytest_1.md `
  --search-query "AI Agent Engineer 上海" `
  --allow-network
```

验收：

- 命令能返回最终 artifact 路径。
- 无真实 LaTeX 环境时能跳过 compile 或明确失败在 compile phase。

---

## 6. P0 完成标准

P0 不是“某个工具存在”，而是下面这条真实用户路径能稳定完成。

### 5.1 必须满足

1. 用户提供个人资料文件，系统生成 `profile/profile.json` 和 `profile/fact_index.json`。
2. 用户提供 JD 文本、JD URL、或公司岗位方向，系统能得到 `jd/jd_raw.md`。
3. `analyze_jd` 产出的 JSON 必须通过 schema 校验。
4. 系统生成 `strategy/spec_lock.json`。
5. 系统生成 `drafts/resume.md` 和 `latex/resume_modules.json`。
6. `resume_modules.json` 必须通过 schema 校验。
7. 系统生成 `latex/resume.tex`。
8. 在 LaTeX 环境存在时，系统生成 `exports/resume.pdf`。
9. 系统写出 `checks/truthfulness_report.json`、`checks/ats_report.json`、`checks/match_report.json`。
10. 系统写出 `checks/pipeline_report.json`，说明每个阶段是否通过。
11. 若匹配度低于阈值，系统必须触发定向修改或明确报告未达标。
12. 不允许为了匹配 JD 编造用户未提供的事实。

### 5.2 推荐指标

| 指标 | P0 门槛 |
|---|---|
| pipeline 成功率 | fake model/fake crawler 测试 100% |
| match score | 默认阈值 75，可配置 |
| truthfulness | 高风险 claim 为 0，或明确阻断 |
| PDF 页数 | 1 页 A4 |
| artifact 完整性 | pipeline report 中所有 required outputs 存在 |

---

## 7. P1/P2/P3 剩余事项

### P1：岗位获取质量提升

当前 `search_jobs` 只是 DuckDuckGo HTML 搜索，适合 MVP，不适合稳定生产。

未完成：

- Firecrawl search adapter：从 query 找岗位 URL，再 crawl 详情。
- BOSS search adapter：封装 `boss search --json`，输出 OpenResume job schema。
- BOSS detail adapter 已有，但未和 BOSS search 形成完整闭环。
- 招聘网站登录态、验证码、反爬失败时的用户提示。
- 搜索结果排序：按目标公司、岗位名、地点、技能关键词、发布时间综合评分。

### P1：MCP tool registry 集成

当前已有：

- `resume_agent/mcp/config.py`
- `resume_agent/mcp/client.py`
- `resume_agent/mcp/job_crawlers.py`

未完成：

- 将 MCP `tools/list` 转为 `FunctionTool`。
- 将 MCP `tools/call` 接入 `ToolRegistry.execute`。
- MCP 工具权限映射。
- MCP 工具输出大小限制、trace、错误脱敏。
- CLI / config 文档。

### P1：公司/岗位版本隔离

当前多数产物仍写在项目根目录。

未完成：

```text
projects/<project_id>/jobs/<job_id>/
  jd/
  strategy/
  drafts/
  latex/
  checks/
  exports/
```

价值：

- 同一用户可以同时投不同公司。
- 同一公司多个岗位不会互相覆盖。
- `compare_match_reports` 能更自然地比较不同版本。

### P2：API Server

当前 `resume_agent/api/` 不存在。

未完成：

```text
POST /sessions
POST /sessions/:id/prompt
POST /sessions/:id/pipeline
GET  /sessions/:id/artifacts
GET  /sessions/:id/pdf
GET  /health
```

### P2：VS Code 插件

当前 `vscode-extension/` 不存在。

未完成：

- Chat panel。
- Artifact tree。
- PDF preview。
- Pipeline run button。
- Match report / diff view。

### P2：模拟面试

当前 `resume_agent/tools/interview_tools.py` 不存在，`ResumeStage.INTERVIEW` 不存在。

这不是当前最高优先级。等 P0 pipeline 稳定后再做。

### P3：多模板

✅ **已落地 8 套模板**（red_card / navy_sidebar / teal_clean / minimal_bw / orange_warm / dark_sidebar / blue_modern / purple_tech），每套含 `.cls` + Jinja2 partials + manifest + sample + renderer，`render_latex` 按 `template_id` 自动选择。

剩余事项：
- ✅ ~~模板选择的 pipeline CLI 入口（`--template`）~~ — 已完成，并贯通到 API `template_id`。
- 真实 xelatex 下各模板的编译验证（部分模板用到 tikz / paracol / tcolorbox，需确认编译环境完整）。
- 后续若做平台化，再补模板注册中心与 UI 选择。

---

## 8. 当前不要做的事

P0 已全部完成，平台集成进行中。当前阶段仍暂缓：

- 不优先做 VS Code 插件（先完成 Web 前端 + Skills 封装）。
- 不优先做模拟面试。
- 不优先做多模板市场。
- 不优先做全平台招聘网站爬虫。
- 不把 BOSS 投递、打招呼、聊天等敏感动作接进 agent。
- 不让模型自由决定整个 pipeline，pipeline 必须有确定性 orchestrator。
- API Server 绑定 localhost、无鉴权，不对公网暴露。

---

## 9. 下一步任务清单

P0 pipeline 主体（含 preflight / resolve_target_job / orchestrator / pipeline_report / CLI / revise loop）以及多模板系统均已完成并经真实环境验证。剩余按优先级：

1. ✅ ~~`pipeline_preflight` / `resolve_target_job` / `pipeline.py` orchestrator / `pipeline_report.json` / CLI `pipeline` 命令~~ — 已完成
2. ✅ ~~fake model + fake crawler 的 P0 E2E 测试~~ — 已完成
3. ✅ ~~真实 LLM + 真实 Firecrawl 端到端手动验证~~ — 已完成（见 §3.6）
4. ✅ ~~真实链路 `@pytest.mark.llm` / `@pytest.mark.latex` smoke test~~ — 已完成（见 §3.7，含真实出 PDF）
5. ✅ ~~CLI `pipeline` 增加 `--template`~~ — 已完成（含 API template_id 贯通）
6. ✅ ~~修复 `--compile` 静默失败（EXPORT 权限）~~ — 已完成
7. ✅ ~~API Server（FastAPI 后端）~~ — 已完成（见 §3.7）
8. **[进行中] Web 静态前端 + Claude Code Skills 封装 + README**
9. 提升 match_analysis 打分一致性（更强模型或多次取均值）
10. 公司/岗位版本隔离 `projects/<id>/versions/`
11. MCP tools 动态注册（`tools/list` → `FunctionTool`，`tools/call` → `ToolRegistry.execute`）
12. Firecrawl search adapter（替代 DuckDuckGo）、BOSS search adapter
13. 最后考虑 VS Code 插件 / 面试模拟

---

## 10. 术语

| 术语 | 说明 |
|---|---|
| Harness | Agent 运行框架，包括工具系统、权限、上下文、模型循环、trace |
| Pipeline | 固定阶段的业务流程，不依赖模型自由选择下一步 |
| JD Analysis | 岗位描述结构化分析结果 |
| Resume Modules | 模板渲染器消费的结构化简历数据，含 `template_id` 标识目标模板 |
| Match Report | 简历和 JD 的匹配分析报告 |
| Pipeline Report | 端到端流程阶段状态报告，是 P0 新增验收 artifact |
| MCP | 外部工具协议边界，本项目当前只实现最小 stdio client 和配置读取 |

