# CCagent · 个人任务分诊工具 (Task Triage Studio v3)

CCagent 是一个单用户、本机运行的轻量级任务分诊工具。专为独立创作者、自由职业者与开发者量身打造：
接收任意散漫文字（日常流水账、碎片记录、待办杂记），自动完成事项拆解、四领域归类（工作/生活/学习/娱乐）、艾森豪威尔四象限精准分诊，并给出具象且切中要害的**判断与落地建议**，无缝导出至 Obsidian / Notion 等主流 Todo 笔记软件。

---

## 🌟 v3 核心升级特性

1. **评估体系完全隔离与可信化 (Phase A)**：
   - 评测脚本 `tests/eval.py` 严格隔离生产数据库，不读写 `data/ccagent.db`，纠偏仅通过显式 `--corrections-file` 注入。
   - 异常独立归类统计（含超时、限流、4xx/5xx），准确率分母严格剔除 error 用例。
   - 自动生成结构化可读 Markdown 评测报告与人工质检评分表（具体性、依据可查性、有无套话）。
   - 提供 `tests/compare.py` 自动化横向对比脚本。
2. **精准智囊与动态纠正逻辑 (Phase B)**：
   - **智囊名称展示**：前端自动拉取 `/api/advisory` 原型库，依据展开中直接显示“核心变现与交付攻坚”等友好名称。
   - **`user_moved` 动态重算**：仅当当前象限/领域不同于 AI 原判时生效，拖拽回原位自动恢复为 0。
   - **AI 原判呈现**：当任务被拖拽后，理由行自动切换为弱色“AI 原判 Q1：…”并隐藏 advice 行，避免前后逻辑冲突。
   - **拖拽与领域改动 6 秒可撤销**：屏幕底部弹出 Toast 提示条，支持一键撤销恢复原状。
   - **设置抽屉纠偏管理**：新增“使用我的历史纠正”总开关与“当前生效纠正”只读列表，支持一键“忽略”测试干扰项。
3. **更清晰的去重与保底原因分类**：
   - 输入重复事项时，界面明确提示“已跳过 N 条重复事项”；若全部重复则保留输入框并给出解释。
   - 保底原因结构化分类映射（Key无效、限流429、服务繁忙5xx、请求超时、网络异常等）。
4. **原生 Markdown 导出规范升级**：
   - 去掉 emoji，格式规范为 `# 任务分流清单`、`## Q1 重要且紧急`、`> 判断：`、`> 建议：`。
   - 接口支持 `status=open`、`status=done` 与 `status=all`。

---

## 🚀 快速启动

### 1. 配置环境变量 (可选)
在项目根目录创建或编辑 `.env` 文件（或直接在 Web 界面右上角设置弹窗中输入保存）：
```ini
# 服务端口 (默认 8099)
PORT=8099

# 服务监听 Host (默认 127.0.0.1，仅本机)
HOST=127.0.0.1

# Google Gemini API Key
GEMINI_API_KEY=your_gemini_api_key

# 默认模型
GEMINI_MODEL=gemini-3.5-flash

# API 调用超时时间 (秒，默认 120)
GEMINI_TIMEOUT=120

# 允许跨域来源 (如桌宠开发调试端口)
ALLOWED_ORIGINS=http://localhost:3000,http://127.0.0.1:5000
```

### 2. 启动服务
```bash
python server.py
```
在浏览器中打开：**http://127.0.0.1:8099** 即可使用。

---

## 📁 目录结构

```text
CCagent/
├── data/
│   └── ccagent.db              # SQLite 数据库 (tasks, triage_runs, feedback_events, settings)
├── docs/
│   └── API.md                  # 对外接口规范 (供桌宠 CCbd 及第三方对接)
├── prompts/
│   ├── advisory_library.json   # 智囊团策略库 (14 个典型原型特征与建议风格)
│   ├── triage_prompt.md        # 生产分流提示词
│   └── variants/               # 评测候选提示词变体 (严禁直接替换生产)
│       ├── triage_v3_defs.md   # 显式定义紧急与重要
│       └── triage_v3_examples.md # 增加具象正反示例
├── tests/
│   ├── golden/
│   │   ├── cases.json          # 评估黄金用例集 (已确认)
│   │   ├── draft_cases.json    # 历史草稿
│   │   └── draft_cases_v2.json # A7 导出的规范草稿集 (需人工审核)
│   ├── results/                # 评估 json 与 md 报告 (严格脱敏)
│   ├── eval.py                 # 离线评估脚本 (完全隔离生产 DB)
│   └── compare.py              # 多模型/提示词横向指标对比脚本
├── tools/
│   ├── export_cases.py         # 数据库提取 AI 运行为草稿用例 (A7)
│   ├── ignore_test_corrections.py # 标记忽略测试纠偏数据 (B11)
│   └── stats.py                # 用户改动率与象限稳定性统计工具
├── .env                        # 配置文件 (受保护，禁止静态下载)
├── app.js                      # 前端交互与 API 联动逻辑
├── index.html                  # 极简阅读风交互界面
├── server.py                   # 后端原生 HTTP 服务 (ThreadingHTTPServer)
└── style.css                   # Editorial 极简设计样式
```

---

## 🛠️ 测试、评估与工具使用指南

### 1. 跑分评估 (tests/eval.py)
```bash
# 使用黄金用例评测
python tests/eval.py --label baseline

# 指定提示词变体进行评测
python tests/eval.py --prompt prompts/variants/triage_v3_defs.md --label v3_defs

# 显式指定测试纠偏文件评测
python tests/eval.py --corrections-file tests/golden/corrections.json --label with_corr

# 纯本地规则离线基准测试 (不消耗 API 配额)
python tests/eval.py --dry-run --label dryrun
```

### 2. 横向结果对比 (tests/compare.py)
```bash
# 自动汇总对比最近的评测报告
python tests/compare.py

# 对比指定实验文件
python tests/compare.py tests/results/eval_20261113_xxx_baseline.json tests/results/eval_20261113_xxx_v3_defs.json
```

### 3. 草稿用例导出 (tools/export_cases.py)
```bash
python tools/export_cases.py
```
将最近的 AI 分诊流水提取至 `tests/golden/draft_cases_v2.json`。

### 4. 测试纠偏数据管理 (tools/ignore_test_corrections.py)
```bash
# 查看所有被手动修改过的记录
python tools/ignore_test_corrections.py

# 忽略已知测试项 (如「阅读圣经与李敖著作」)
python tools/ignore_test_corrections.py --apply --keyword "阅读圣经与李敖著作"
```
