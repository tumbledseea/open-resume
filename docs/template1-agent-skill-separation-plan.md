# Template1 简历生成与 Skill/Agent 分离实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 先完成 OpenResume 自己的 agent 系统：把 `skills/resume-master` 从 `resume_agent` 中解耦为可复用 skill 能力包，同时基于 `skills/resume-master/examples/半成品.pdf` 拆出 `template1` 模块化 LaTeX 模板，实现“用户上传资料 -> 端到端意图识别 -> 抽取教育/实习/项目/奖项模块 -> 填入 template1 -> 生成 PDF”。

**Architecture:** `resume_agent` 只负责 Claude Code 风格 harness：会话、意图、上下文、LLM/tool loop、权限、trace、状态恢复。`skills/resume-master` 负责领域能力：资料解析、模块 schema、模板资源、LaTeX 渲染、PDF 编译。两者通过稳定 tool contract / skill manifest 通信，避免 agent 直接依赖 skill 内部脚本细节。

**Tech Stack:** Python 3.11+、OpenAI-compatible Chat Completions、pytest、PyMuPDF/fitz PDF 分析、LaTeX/XeLaTeX、Jinja2、JSON Schema、Markdown、现有 `resume_agent` harness 和 `skills/resume-master` 脚本。

---

## 0. 当前结论：最需要优化什么

按你给的“resume_agent vs Claude Code 架构对比”，现在最该优先补的不是继续堆工具，而是这 5 个点：

1. **Skill/Agent 边界不清**
   - 当前 `resume_agent/tools/builtins.py` 直接知道 `skills/resume-master/scripts/*` 的路径、参数、输出。
   - 这会导致 `resume-master` 很难作为独立 skill 放入别人的 agent 系统。
   - 应改成：skill 暴露 manifest + tool provider + schema；agent 只加载和调用。

2. **模板不是模块化资产**
   - 现在 LaTeX 模板主要是 `templates/latex/resume.cls`，缺少“模板实例”的结构。
   - `半成品.pdf` 已经有明确版式，但没有拆成 `header/education/experience/project/awards` 模块。
   - 应把 `template1` 变成可复用模板包，而不是让 LLM 每次自由写 TeX。

3. **用户资料抽取没有“模块 slot”概念**
   - 当前 profile normalization 抽成 `profile.json`，但没有专门面向模板的 `resume_modules.json`。
   - 你现在要的是：教育经历填教育模块，实习经历填实习模块，项目经历填项目模块，奖项填奖项模块。
   - 应新增模块化抽取 schema，作为模板渲染的唯一输入。

4. **QueryEngine 缺少项目状态感知**
   - 现在 engine 能 LLM tool-call loop，但 context 还是偏静态。
   - 需要像 Claude Code 一样每轮注入当前 artifact 状态：已上传文件、已抽取模块、当前模板、已生成 PDF、上次错误。

5. **缺少端到端可验证用户路径**
   - 目前工具测试很多，但还缺一个目标验收链路：
   - `profile_file + template1 -> resume_modules.json -> resume.tex -> resume.pdf`
   - 这条链路要先稳定，再做 Web/VS Code 插件。

## 1. 已完成的 PDF 初步分析

源 PDF：

```text
skills/resume-master/examples/半成品.pdf
```

已生成辅助分析文件：

```text
skills/resume-master/examples/template1/source-preview.png
skills/resume-master/examples/template1/source-text.txt
skills/resume-master/examples/template1/source-blocks.json
```

PDF 基本信息：

```text
pages: 1
page rect: 595.92 x 842.88 pt
```

视觉结构：

- 顶部：红色横条。
- 背景：浅灰蓝底，右上有浅色曲线水印。
- Header：左上姓名，下一行联系方式，右上头像。
- Section title：红色图标 + 红色标题 + 横线。
- Section body：白色圆角卡片，轻微阴影/边框。
- 内容模块：教育、实习/工作、项目、荣誉奖项/证书。

从 `source-blocks.json` 得到的模块位置：

```text
header.name:           bbox [22.7, 46.5, 67.7, 68.0]
header.contact:        bbox [22.7, 73.8, 320.7, 85.7]
education.title:       bbox [22.7, 112.8, 92.4, 131.1]
education.body:        bbox [35.4, 144.1, 560.1, 205.7]
experience.title:      bbox [22.7, 222.3, 123.0, 240.6]
experience.body:       bbox [35.4, 252.1, 560.1, 433.1]
projects.title:        bbox [22.7, 450.3, 92.4, 468.6]
projects.body:         bbox [35.4, 480.9, 212.8, 493.8]
awards.title:          bbox [22.7, 509.6, 123.0, 527.9]
awards.body:           bbox [35.4, 542.6, 560.1, 587.5]
```

## 2. 目标目录结构

### 2.1 Skill 侧：`skills/resume-master`

新增或整理为：

```text
skills/resume-master/
  SKILL.md
  skill.json                         # 新增：可被 agent/plugin 加载的 manifest
  tools/
    resume_master_tools.py           # 新增：对外 tool provider，不依赖 resume_agent
  schemas/
    resume_modules.schema.json       # 新增：模块抽取输出 schema
    template_manifest.schema.json    # 新增：模板定义 schema
  examples/
    半成品.pdf
    template1/
      source-preview.png             # 已生成：视觉参考
      source-text.txt                # 已生成：文本抽取参考
      source-blocks.json             # 已生成：坐标参考
      template_manifest.json         # 新增：模板元数据
      layout_notes.md                # 新增：PDF 模块拆解说明
      latex/
        template1.cls                # 新增：template1 专属 document class 或 style
        main.tex.j2                  # 新增：完整文档 Jinja2 模板
        partials/
          header.tex.j2
          section.tex.j2
          education.tex.j2
          experience.tex.j2
          projects.tex.j2
          awards.tex.j2
      sample/
        resume_modules.json          # 新增：从半成品抽取的样例模块数据
        resume.tex                   # 新增：样例渲染结果
        resume.pdf                   # 新增：样例编译结果
  scripts/
    module_extract/
      extract_resume_modules.py      # 新增：LLM/规则抽取模块
    renderers/
      render_template1.py            # 新增：resume_modules.json -> resume.tex
```

### 2.2 Agent 侧：`resume_agent`

新增或调整为：

```text
resume_agent/
  skills/
    loader.py                        # 新增：加载 skill.json / tool provider
    contracts.py                     # 新增：SkillToolSpec / SkillManifest 类型
  context/
    artifact_state.py                # 新增：读取当前 project artifact 状态摘要
  engine/
    intent_router.py                 # 增强：识别 template1/module-generation intent
    query_engine.py                  # 增强：每轮注入 artifact_state
  tools/
    builtins.py                      # 收敛：只放 agent 原生工具，不直接写 skill 业务逻辑
```

## 3. 核心数据合同

### 3.1 `resume_modules.json`

模板渲染不直接吃自由文本，而吃稳定模块 schema：

```json
{
  "template_id": "template1",
  "language": "zh-CN",
  "header": {
    "name": "张三",
    "phone": "123456",
    "email": "a@example.com",
    "location": "上海",
    "photo": "figures/photo.jpg"
  },
  "modules": [
    {
      "module_id": "education",
      "title": "教育经历",
      "items": [
        {
          "school": "华东师范大学",
          "badges": ["985", "211"],
          "degree": "硕士",
          "major": "大数据技术与工程",
          "college": "数据科学与工程学院",
          "time": "2025年09月 - 2028年07月",
          "location": "上海",
          "details": ["研究方向：大模型幻觉检测及缓解、有害内容检测"]
        }
      ]
    },
    {
      "module_id": "experience",
      "title": "实习/工作经历",
      "items": [
        {
          "organization": "公司名称",
          "role": "大模型应用实习生",
          "time": "2025年04月 - 2025年10月",
          "project": "项目可研报告自动生成与幻觉缓解",
          "bullets": [
            {"label": "背景", "text": "一句话背景"},
            {"label": "技术方案", "text": "一句话方案"},
            {"label": "结果效益", "text": "一句话结果"}
          ]
        }
      ]
    },
    {
      "module_id": "projects",
      "title": "项目经历",
      "items": [
        {
          "name": "OpenResume",
          "role": "后端/Agent",
          "time": "",
          "bullets": ["自动生成简历的 agent skill"]
        }
      ]
    },
    {
      "module_id": "awards",
      "title": "荣誉奖项/证书",
      "items": [
        {"name": "APMCM亚太杯数学建模比赛三等奖", "time": "2025年03月"}
      ]
    }
  ],
  "quality_constraints": {
    "page_limit": 1,
    "max_experience_bullets": 3,
    "max_project_bullets": 3,
    "max_awards": 5
  }
}
```

### 3.2 `template_manifest.json`

模板能力声明：

```json
{
  "template_id": "template1",
  "name": "红色图标卡片式中文单页简历",
  "source_pdf": "../半成品.pdf",
  "page": {"size": "a4", "orientation": "portrait"},
  "required_modules": ["header", "education", "experience", "projects", "awards"],
  "optional_modules": ["skills", "summary", "certifications"],
  "renderer": "scripts/renderers/render_template1.py",
  "schema": "schemas/resume_modules.schema.json"
}
```

## 4. 端到端目标流程

用户输入：

```text
python resume_agent/cli.py chat --profile-file person/my_profile.md --once "按照 template1 生成一版简历 PDF"
```

Agent 目标行为：

```text
[agent] 我会先读取你的资料，识别教育/实习/项目/奖项模块。
[agent] 然后使用 template1 渲染 LaTeX。
[agent] 最后编译 PDF，并检查是否一页。
```

内部工具链：

```text
read_user_profile
  -> extract_resume_modules(template_id=template1)
  -> render_template1_latex
  -> compile_pdf
  -> check_truthfulness
  -> check_layout_one_page
```

关键原则：

- LLM 可参与“抽取与归类”，但最终输出必须是 `resume_modules.json`。
- LaTeX 不由 LLM 自由生成，而由 deterministic renderer 根据 `resume_modules.json` 和 template partials 生成。
- 事实必须来自 `profile_file` / `profile.md` / `profile.json` / `fact_index.json`。
- 模板视觉应尽量贴近 `半成品.pdf`，但首版先保证结构正确、单页、可编译。

## 5. 分阶段实施计划

### Phase 1：固化 template1 分析资产

**Files:**

- Create: `skills/resume-master/examples/template1/layout_notes.md`
- Create: `skills/resume-master/examples/template1/template_manifest.json`
- Create: `skills/resume-master/examples/template1/sample/resume_modules.json`

**Tasks:**

- [ ] 把 `source-preview.png` 中的视觉结构写成 `layout_notes.md`。
- [ ] 把教育/实习/项目/奖项的字段映射写成 `sample/resume_modules.json`。
- [ ] 写 `template_manifest.json`，声明 template1 需要哪些模块和 renderer。

**Verification:**

```powershell
python -m json.tool skills/resume-master/examples/template1/template_manifest.json
python -m json.tool skills/resume-master/examples/template1/sample/resume_modules.json
```

Expected: JSON valid.

### Phase 2：定义模块 schema

**Files:**

- Create: `skills/resume-master/schemas/resume_modules.schema.json`
- Test: `tests/resume_master/test_resume_modules_schema.py`

**Tasks:**

- [ ] 定义 `header`、`modules[]`、`module_id`、`items[]`。
- [ ] 限定 module_id 枚举：`education`、`experience`、`projects`、`awards`、`skills`、`summary`。
- [ ] 写测试校验 sample JSON 通过。
- [ ] 写测试校验缺少 `header.name` 失败。

**Verification:**

```powershell
pytest tests/resume_master/test_resume_modules_schema.py -v
```

Expected: schema tests pass.

### Phase 3：实现 template1 LaTeX partials

**Files:**

- Create: `skills/resume-master/examples/template1/latex/template1.cls`
- Create: `skills/resume-master/examples/template1/latex/main.tex.j2`
- Create: `skills/resume-master/examples/template1/latex/partials/header.tex.j2`
- Create: `skills/resume-master/examples/template1/latex/partials/section.tex.j2`
- Create: `skills/resume-master/examples/template1/latex/partials/education.tex.j2`
- Create: `skills/resume-master/examples/template1/latex/partials/experience.tex.j2`
- Create: `skills/resume-master/examples/template1/latex/partials/projects.tex.j2`
- Create: `skills/resume-master/examples/template1/latex/partials/awards.tex.j2`

**Template decomposition:**

- `header.tex.j2`
  - 姓名：大号黑体。
  - 联系方式：电话/邮箱/城市一行。
  - 头像：右上角可选。
- `section.tex.j2`
  - 红色圆形图标位。
  - 红色标题。
  - 横线。
- `education.tex.j2`
  - 学校左侧，时间右侧。
  - 985/211 badge。
  - 专业/学历/学院/全日制。
  - 研究方向。
- `experience.tex.j2`
  - 公司左侧，时间右侧。
  - 角色。
  - `label: text` bullet。
  - 控制最多 3 个 bullets。
- `projects.tex.j2`
  - 项目名加粗。
  - 可选角色/时间。
  - 2-3 bullets。
- `awards.tex.j2`
  - 左侧奖项名，右侧时间。

**Verification:**

```powershell
python skills/resume-master/scripts/renderers/render_template1.py `
  --modules skills/resume-master/examples/template1/sample/resume_modules.json `
  --output skills/resume-master/examples/template1/sample/resume.tex
```

Expected: `resume.tex` generated and contains template1 sections.

### Phase 4：实现 deterministic renderer

**Files:**

- Create: `skills/resume-master/scripts/renderers/render_template1.py`
- Test: `tests/resume_master/test_template1_renderer.py`

**Behavior:**

- 读取 `resume_modules.json`。
- 校验 schema。
- 用 Jinja2 partials 生成完整 `resume.tex`。
- 复制 `template1.cls`。
- 输出到指定 project 的 `latex/resume.tex`。
- 不调用 LLM。

**Verification:**

```powershell
pytest tests/resume_master/test_template1_renderer.py -v
```

Expected: renderer writes `.tex`, includes education/experience/projects/awards.

### Phase 5：实现模块抽取工具

**Files:**

- Create: `skills/resume-master/scripts/module_extract/extract_resume_modules.py`
- Test: `tests/resume_master/test_module_extract.py`

**Behavior:**

- 输入：`--profile-md <path>`、`--template template1`、`--output <resume_modules.json>`。
- 优先使用 LLM 结构化抽取。
- 如果 LLM 不可用，使用规则 fallback 至少抽出 header 和明显 section。
- 输出必须符合 `resume_modules.schema.json`。

**Prompt 规则：**

- 只抽取原文存在事实。
- 按模板模块归类。
- 不要补全日期、学校、公司、指标。
- 信息不确定写入 `needs_user_confirmation`。

**Verification:**

```powershell
pytest tests/resume_master/test_module_extract.py -v
```

Expected: fixture profile can extract education/experience/projects/awards.

### Phase 6：把 template1 能力暴露为 skill tools

**Files:**

- Create: `skills/resume-master/tools/resume_master_tools.py`
- Create: `skills/resume-master/skill.json`
- Modify: `resume_agent/skills/loader.py`
- Modify: `resume_agent/tools/builtins.py`

**Skill tools:**

- `extract_resume_modules`
- `render_template1_latex`
- `compile_pdf`
- `check_template1_layout`

**Separation rule:**

- `skills/resume-master/tools/resume_master_tools.py` 不 import `resume_agent`。
- `resume_agent` 可以 import skill tool provider，或者通过 manifest 动态加载。
- agent 只知道 tool schema，不知道 skill 内部脚本布局。

**Verification:**

```powershell
pytest tests/resume_agent/test_skill_loader.py -v
pytest tests/resume_agent/test_builtin_tools.py -v
```

Expected: resume-master skill tools appear in registry.

### Phase 7：增强 QueryEngine 的端到端意图识别

**Files:**

- Modify: `resume_agent/engine/intent_router.py`
- Modify: `resume_agent/context/artifact_state.py`
- Modify: `resume_agent/context/builder.py`
- Test: `tests/resume_agent/test_template1_intent.py`

**Intent cases:**

- “按照 template1 生成简历”
  - `template_id=template1`
  - expected workflow: extract modules -> render -> compile
- “把我的教育经历放到教育模块”
  - stage: module extraction/edit
- “只生成 latex，不编译”
  - render only
- “用半成品模板”
  - map to `template1`

**Verification:**

```powershell
pytest tests/resume_agent/test_template1_intent.py -v
```

Expected: common Chinese prompts route to template1 module workflow.

### Phase 8：实现端到端 CLI 验收

**Files:**

- Modify: `resume_agent/cli.py`
- Test: `tests/resume_agent/test_template1_e2e.py`

**Command:**

```powershell
python resume_agent/cli.py chat `
  --profile-file person/my_profile.md `
  --project-dir projects/template1_demo `
  --once "按照 template1 生成一版中文简历 PDF"
```

**Expected artifacts:**

```text
projects/template1_demo/profile/profile.md
projects/template1_demo/profile/resume_modules.json
projects/template1_demo/latex/resume.tex
projects/template1_demo/latex/template1.cls
projects/template1_demo/exports/resume.pdf
projects/template1_demo/checks/template1_layout.json
projects/template1_demo/runs/<run_id>.jsonl
```

**Verification:**

```powershell
pytest tests/resume_agent/test_template1_e2e.py -v
```

Expected: E2E creates `resume_modules.json` and `resume.tex`; PDF check can be marked `latex` if XeLaTeX availability differs by machine.

## 6. 建议先做的最小 MVP

先不要同时做 MCP、插件市场、完整 memory。当前最小闭环应该是：

```text
template1 manifest
  -> resume_modules.schema.json
  -> sample resume_modules.json
  -> render_template1.py
  -> extract_resume_modules.py
  -> skill tool provider
  -> QueryEngine template1 intent
  -> CLI E2E
```

这条链路完成后，`resume-master` 才真正像一个 skill：

- 可以被你的 `resume_agent` 加载。
- 未来也可以被别人的 agent 通过 manifest/tool schema 调用。
- 模板不依赖某个 agent 的内部实现。

## 7. 暂缓项

这些重要，但不应该挡住 template1 MVP：

- MCP stdio/HTTP 接入。
- 多模板自动选择。
- 多 provider fallback。
- 复杂权限审批 UI。
- 流式 token 输出。
- 长短期 memory。
- VS Code 插件。

等 template1 E2E 通过后，再把这些 Claude Code 风格能力逐层补上。

## 8. 完成标准

这个计划完成时，必须能证明：

1. `skills/resume-master/examples/template1` 是独立模板包。
2. `resume_modules.json` 是模板渲染的稳定输入。
3. `render_template1.py` 不调用 LLM，也能从 sample JSON 生成 TeX。
4. `extract_resume_modules.py` 能从用户资料抽取教育/实习/项目/奖项模块。
5. `resume_agent` 通过 skill tool contract 调用 resume-master，而不是硬编码内部脚本路径。
6. CLI 端到端命令能生成 `latex/resume.tex`，在有 XeLaTeX 时能生成 PDF。
