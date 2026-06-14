# OpenResume Pipeline 全流程梳理

本文按真实执行顺序，梳理 OpenResume 从「用户输入」到「交付简历 PDF」的完整链路，包括每一步调用的工具、产出的文件、以及失败时的处理逻辑。全流程由 `pipeline.py` 的 ResumePipeline 确定性编排——顺序写死在代码里，不依赖大模型自己决定下一步。

---

## 第 0 步：用户端输入

用户端以个人资料、文本内容输入。三类输入可以同时提供，也可以只给一部分：

- **个人资料**：一份 markdown / PDF / Word / Excel / PPT 文件，或一段自由文本，描述候选人的真实经历——教育、工作、项目、技能、奖项。这是简历内容的唯一事实来源。
- **目标岗位**：三选一——直接粘贴的 JD 文本、招聘页 URL、或者「公司 + 岗位 + 关键词」让 Agent 自己去搜。
- **运行参数**：选用哪套模板、是否联网、是否编译 PDF、匹配分阈值、最多修订几轮。

输入通过 CLI（`pipeline` 命令）或 FastAPI 接口进入系统，归一成一个 PipelineInput 对象交给编排器。

---

## 第 1 阶段：preflight（预检）

**调用工具**：`pipeline_preflight`

进入正式流程前先体检：校验 profile 文件是否存在、项目目录是否可写、联网开关与必要的 API key 是否就绪、目标岗位信息是否足够。

- 缺关键输入 → 返回 `needs_user_input`，把缺什么列清楚后中止，不让后面白跑。
- 校验通过 → 继续，非致命问题进 warnings。

---

## 第 2 阶段：import_profile（导入资料）

**调用工具**：`import_profile`（非 markdown 源文件先经 `import_pdf_source` / `import_docx_source` / `import_excel_source` / `import_pptx_source` / `import_url_source` 转成 markdown）

把用户的原始资料复制进项目工作区，统一成 markdown 落到 `profile/` 目录。从这一刻起，项目工作区里的副本成为后续所有步骤的事实基准，与用户原文件解耦。

---

## 第 3 阶段：normalize_profile（结构化抽取）

**调用工具**：`normalize_profile`（内部调 LLM）

大模型把自由文本资料抽取成结构化数据：

- `profile/profile.json` —— 结构化的候选人档案（教育、经历、项目、技能等字段）。
- `profile/fact_index.json` —— 事实索引，把每一条可验证的经历、数字、公司、奖项编号登记。

这一步是「真实性」的地基：后续生成的简历内容只能引用 fact_index 里登记过的事实，编造的内容会在质量检查阶段被揪出来。

---

## 第 4 阶段：resolve_target_job（确定目标岗位）

**调用工具**：`resolve_target_job`，内部按输入类型分派到子流程：

- **给了 JD 文本** → 直接写入 `jd/jd_raw.md`。
- **给了招聘页 URL** → 调 `fetch_jd_url`（底层走 Firecrawl 无头浏览器，抓 JS 动态渲染的招聘页并清洗成 markdown），写入 `jd/jd_raw.md`。
- **给了搜索关键词** → 调 `search_jobs` 结合 profile 检索岗位，写 `jobs/jobs.jsonl`；命中后调 `crawl_job_info` 抓取选中岗位的完整详情；最后 `select_job` 确定目标，写 `jobs/selected_job.json` + `jd/jd_raw.md`。

若开启了 `auto_select`，Agent 自动选最匹配的岗位；否则返回候选清单，请用户选定后重跑。这一阶段保证：**进入分析的永远是一份真实、完整的 JD**——源头不准，后面全是空中楼阁。

---

## 第 5 阶段：analyze_jd（JD 分析）

**调用工具**：`analyze_jd`（内部调 LLM）

大模型解析 `jd_raw.md`，提取出岗位真正要什么：硬性技能、关键词、业务背景、HR 筛选时的命中点。产出 `jd/jd_analysis.md`，作为后续策略和匹配评分的依据。

---

## 第 6 阶段：build_resume_strategy（策略生成）

**调用工具**：`build_resume_strategy`（内部调 LLM）

综合 `profile.json` 和 `jd_analysis.md`，决定这份简历的打法：突出哪些经历、弱化哪些、用户经历里的哪些点如何映射到岗位关键词、各模块的篇幅配比。产出：

- `strategy/resume_strategy.md` —— 人类可读的策略说明。
- `strategy/spec_lock.json` —— 锁定的结构化规格，供生成阶段严格遵循。

---

## 第 7 阶段：generate_resume_modules（内容生成）

**调用工具**：`generate_resume_modules`（内部调 LLM，输出经 JSON Schema 校验 + repair）

大模型按策略生成简历的结构化内容，同时落两份产出：

- `drafts/resume.md` —— 可编辑的 markdown 草稿。
- `latex/resume_modules.json` —— 结构化数据，供模板渲染器使用。

输出强制经过 JSON Schema 校验，结构不合法时自动触发 LLM repair 重试，保证下游渲染拿到的永远是合法数据。

---

## 第 8 阶段：render_latex（LaTeX 渲染）

**调用工具**：`render_latex`

Jinja2 渲染器把 `resume_modules.json` 套进选定的模板（8 套之一，如 red_card / navy_sidebar），生成 `latex/resume.tex`。模型全程不直接写 LaTeX——只产数据，排版由确定性的渲染器负责，保证版式稳定。

---

## 第 9 阶段：compile_pdf（编译，可选）

**调用工具**：`compile_pdf`（需 EXPORT 权限，仅在用户要求时授予）

xelatex 把 `resume.tex` 编译成 `exports/resume.pdf`，并强制 1 页 A4 门禁。编译失败（如本地没装 TeX）不致命，记一条 warning 后继续往质量检查走。

---

## 第 10 阶段：check_truthfulness（真实性检查）

**调用工具**：`check_truthfulness`

逐条比对简历内容与 `fact_index.json`，凡是简历里出现、但事实索引里查无对应的经历、数字、公司、奖项，一律标记为「疑似编造」。产出 `checks/truthfulness_report.json`。

---

## 第 11 阶段：check_ats（ATS 检查）

**调用工具**：`check_ats`

从机器筛选视角检查简历：JD 关键词覆盖率、格式是否对 ATS（简历筛选系统）友好、有无解析障碍。产出 `checks/ats_report.json`。

---

## 第 12 阶段：match_analysis（匹配度评分）

**调用工具**：`match_analysis`

读取 `jd_analysis.md` 与 `resume_modules.json`，给出 0–100 的匹配分和分模块缺口报告：精确关键词匹配 + LLM 语义对齐两路结合。产出 `checks/match_report.json`，其中 `overall_score` 决定是否触发下一阶段的修订闭环。

---

## 第 13 阶段：revise loop（自动修订闭环）

**调用工具**：`revise_resume_from_match_report` → `render_latex` → `match_analysis`（循环）

当匹配分低于阈值（`min_match_score`）时，自动进入定向修订：

1. `revise_resume_from_match_report` 读取匹配报告，挑出缺口最大的 section，只改这一段（自动 snapshot 旧版本，返回 diff）。
2. 重新 `render_latex` 渲染。
3. 重新 `match_analysis` 评分。

循环最多 `max_revise_loops` 轮（默认 2 轮）。达标即停；轮次用尽仍不达标，**如实记一条 warning 并给出建议**（补充 profile 内容 / 降低阈值），不强行「刷分」造假。

---

## 第 14 阶段：pipeline_report（汇总报告）

**调用工具**：内部 `_write_pipeline_report` + `_collect_outputs`

把每个阶段的执行状态（ok / skipped / failed / needs_input）、耗时、产出文件、失败原因写进 `pipeline_report.json`，并收集最终产物清单。用户一眼能看清：跑到哪一步、哪步成功、哪步垮了、为什么。

---

## 横切能力（贯穿全流程，非单独阶段）

这些机制不属于某一个阶段，而是在每一次工具调用时自动生效：

- **权限治理（PermissionPolicy）**：每次工具调用前后双重检查——写路径越界拦截、NETWORK 必须显式审批、DELETE 默认拒、敏感写需双重确认。pipeline 默认只授予 READ + WORKSPACE_WRITE，联网和编译按需追加 NETWORK / EXPORT。
- **质量门禁（Post-tool Hooks）**：生成 / 渲染 / 修订类工具执行后，自动触发对应的真实性、ATS、匹配度检查，不依赖模型自觉去调。
- **上下文压缩**：交互式对话场景下，长对话的早期轮次被压成结构化摘要，profile / JD 等关键事实永不被截断。
- **版本管理（Artifacts）**：`snapshot_artifacts` / `diff_artifact` / `rollback_artifact` 让每次修订都有快照、可对比、可回滚，存于 `versions/`。
- **记忆系统（Memory）**：`save_memory` / `recall_memory` 持久化用户偏好与历史反馈，跨会话复用。
- **全链路追踪（Trace）**：每一步决策与工具调用以 JSONL 记录，便于复盘与调试。

---

## 一句话总结

用户端用个人资料、文本内容输入 → 预检 → 导入并结构化资料（建立事实索引）→ 锁定真实 JD → 分析 JD → 定策略 → 生成内容 → 渲染 LaTeX → 编译 PDF → 真实性 / ATS / 匹配度三重检查 → 不达标自动定向修订（最多 2 轮）→ 汇总报告。整条链路顺序由代码强制、内容由大模型填空、安全由权限层兜底。
