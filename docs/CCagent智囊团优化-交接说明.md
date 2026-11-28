# CCagent · 智囊团优化 · 交接说明

整理日期：2026-11-28。用途：在新窗口里继续这项工作时，先让 Claude 读完本文件，再接着做。
本文只记录**我读代码审阅过的事实**和**已作出的决策**；没验证过的内容单独列在第 8 节。

---

## 1. 一句话现状

智囊团优化已经跑完两轮"方案 → AGENT 执行 → Claude 读代码审阅"。安全与正确性的缺陷已修好并核实；智囊输出契约已重写。**v1.2 补丁方案已写好，但 AGENT 还没有执行，也还没有审阅过**。真实 API Key 的诊断与评测一次都没跑过，由你来跑。

---

## 2. 项目与范围

- 代码目录：`E:\Doc\Python_daye\CCagent`（本地文件系统 MCP 需在新窗口里保持运行，Claude 才能读代码）。
- 根 `server.py`：提供职业体检（agent1），并把 `/agentN/...` 请求转发给子服务 agent2–agent10；负责 Host/Origin 校验、限流、额度（quota）、owner 身份（cookie → `owner_hash`）。
- **本轮优化对象**：agent4–agent10 的"智囊团"，即每个 Agent 里的 4 个分析视角（`council_notes`）。共用 `thinking_core.py`、`shared/thinking.js`、`shared/thinking.css`；每个 Agent 有 `config.json` + 精简的 `server.py` 薄壳 + `index.html`。
- 没动的部分：职业体检的 8 位智囊（`prompts/advisory_career.json`、`engine.py`、`score.py`，评级由代码规则决定，LLM 只补一句 insight 和 next_step）、agent2（任务分诊，有 `advisory_library.json`）、agent3（习惯）。这几块只做过评述。

---

## 3. 工作方式（沿用）

1. Claude 写方案文档，放在 `docs/`。
2. 你把方案交给 AGENT 执行，AGENT 汇报（改动清单、测试输出、逐条对照、额外汇报）。
3. 你把汇报贴给 Claude，Claude **通过文件系统 MCP 读代码**审阅，不只看汇报。已经发生过两次"汇报说已完成，代码里没做完"（见第 5 节 v1.1 审阅），所以这一步不能省。
4. 审阅发现的问题写成下一版补丁方案，回到第 2 步。
5. AGENT 没有真实 Key，也不能操作浏览器：凡涉及真实厂商响应、页面视觉效果的，只能由你验证。

你的偏好（Claude 应遵守）：客观中立、批判性思考，指出不切实际的想法并给出更专业的意见；穷举方法、探索到饱和；输出前先自查。

---

## 4. 轮次时间线与文档

| 文档（均在 `docs/`） | 内容 | 状态 |
|---|---|---|
| `实施方案-智囊团优化v1.md` | 阶段 A 安全与正确性、阶段 B 智囊契约+配置化、阶段 C 评测 | 已执行，已审阅 |
| `实施方案-智囊团优化v1.1-修补.md` | P0（错误信息、转发异常与总时限、`/api/route`）、P1（B1 补全、截断、校验、CSS、评测去恒真、基线、测试）、P2 | 已执行，已审阅 |
| `实施方案-智囊团优化v1.2-补丁.md` | G1 补全 F4、G2 测试夹具、G3 条目强制与回填、G4 长度上限、G5 schema 降级、G6 基线说明 | **已写好，待你交给 AGENT** |
| `docs/archive/council_backup_20261127/` | 改动前 agent4–10 的 `server.py` 备份 | **只读，不要改**；对照与基线都依赖它 |

---

## 5. 已完成并核实的内容（我读过代码）

**v1 阶段 A/B 的主体**
- agent7/agent10 的 pillars 键名统一（`content`→`value`，服务端归一化，前端兼容旧记录）。
- 历史记录按用户隔离：转发层先剥掉客户端传来的 `X-CC-Owner`，再写入服务端算出的 `owner_hash`；子服务托管模式按 owner 过滤，读写删都校验；`records` 表自动迁移出 `owner_hash` 列。
- SSRF：托管模式忽略请求体 `base_url`；子服务托管模式 `/api/test-connection` 返回 404；转发层对子服务 POST 前置校验 415/400/413。
- LLM 失败不再返回伪成功：托管且用服务端 Key 返回 503 固定文案，其余返回 502 并带脱敏原因；失败不写历史；转发层 `status >= 400` 退额度。
- 前端 `esc()` 转义（`shared/thinking.js`）、Gemini Key 改放请求头、`max_tokens=4096`、`MAX_TOKENS` 直接判失败、日志记 finishReason 和 token 数。
- 清理线程：托管模式下，首次访问某子 Agent 时才启动 6 小时一次的清理。

**v1.1 的修补（审阅核实）**
- 错误信息：解析 `error.message` 并脱敏，不再只剩一个 `{`。
- 转发层：超时 504、导入失败 502，均返回状态码使退额度生效；请求级总时限 `LLM_TOTAL_BUDGET`（默认 100 秒，小于转发层 120 秒）；修复重试仅在剩余时间 ≥ 35 秒时进行。
- `/api/route`：托管且无用户 Key 时只走规则路由。
- 截断改为 1.5 倍硬上限+标点处截断；`validate_result` 增加 title/summary/pillars/sections 校验，并回填 label/heading；CSS 补齐；评测加金丝雀串和"听话桩"负向测试；基线与盲评脚本；测试补到 Python 23 项（`test_thinking_core.py` 19 + `test_v24_phase1.py` 4）、前端 20 项。
- 托管空 owner 守卫；非托管 `/api/test-connection` 使用你输入的 Base URL。
- `.env` 核查：没有被 git 跟踪或提交过。

**我对 AGENT 汇报的修正（v1.1 审阅）**
- F4 汇报说"全部已搬入"，实际只完成一部分：agent7/10 备份里的"核心要求"（拒绝空泛鸡汤、落地清单的领域指引）没有搬入，`style_note` 是空的；sections 的 `count: "3-4"` 无备份依据；`test_f4` 只检查几个字数字样，查不出丢失。agent5 是对的。agent4/6/8/9 我没核对。

---

## 6. 待办（按顺序）

**你来做**
1. 把 `实施方案-智囊团优化v1.2-补丁.md` 交给 AGENT，拿到汇报后贴回新窗口。
2. **最优先的真实验证**：配置真实 Key，先跑 `python tools/diag_council.py`。重点看两件事：Gemini 是否接受 `responseSchema`（含 `enum`、嵌套数组，从未验证过）；`finishReason` 与 `thoughts` token（决定要不要给 Gemini 加 `thinkingBudget = 0`，没有证据不要盲加）。v1.2 的 G5 会加一道降级保险，但仍然要看真实结果。
3. 之后依次运行：`python tests/council_eval/baseline_old.py`、`python tests/council_eval/eval_council.py`、`python tests/council_eval/make_blind_sheet.py`，并按 `blind_sheet.md` 盲评（A/B 对应在 `blind_key.json`，评完再打开）。
4. 确认 D6（agent5 的"敌我友"措辞，当前没改）。

**AGENT 来做（v1.2）**：G1–G6，详见方案。

**Claude 来做**：读 v1.2 汇报对应的代码，重点核对 G1（agent4/6/8/9 的备份对照）、G3（条数强制与 tag 回填）、G5（schema 降级只触发一次且只针对 schema 相关的 400）。

---

## 7. 当前设计契约（以代码为准）

**智囊输出**（每个 Agent 恰好 4 席，`id`/`name`/`role` 由服务端按配置回填，不信任模型）：
- 每席：`stance`（`support`/`hold`/`oppose`/`need_info`）、`verdict`（目标 30–60 字）、`based_on`（用户输入中逐字出现的片段，或固定文本"用户未提供"）、`confidence`（`high`/`mid`/`low`）、`would_change_if`（目标 ≤30 字）、`action`（目标 ≤40 字）。
- 顶层：`decision`、`assumptions`（≤4）、`missing_info`（≤3）、`council_synthesis`（`consensus_text`、`tension_text`、`tension_between`）、`stance_counts`（服务端算）。
- `grounded`：服务端计算。`based_on` 为"用户未提供"一律算有依据；否则要求去空白后是 `raw_text` 或任一字段值的子串，且长度 ≥ 6（输入总长 < 30 时 ≥ 4）。不因 `grounded=false` 拒绝结果，前端显示灰色标记。
- 分歧规则：4 席立场完全相同 → 清空 `tension_text`；不同时，`tension_between` 必须含 ≥ 2 个立场不同的席位，否则清空。
- 校验失败触发**一次**修复重试，仍失败则按失败策略返回错误。长度超限按 1.5 倍硬上限在标点处截断。

**失败策略**：没有 fallback 伪分析。托管且用服务端 Key → 503 固定文案；其余 → 502 + 脱敏原因；不写历史；转发层退额度。

**限制**：`raw_text` ≤ 6000 字、单字段 ≤ 600 字、请求体 ≤ 64KB。默认模型 `gemini-3.5-flash-lite`。

**额度**：默认每 owner 每天 10 次、每 IP 30 次、全局 300 次；`/api/extract` 与 `/api/generate` **各扣 1 次**，所以一次完整分析约消耗 2 次（文案已改，计费未改）。

---

## 8. 决策记录

| 编号 | 决策 | 结果 |
|---|---|---|
| D1 | LLM 失败的行为 | 返回错误、不落库、不扣额度；不再展示模板分析 |
| D2 | 界面措辞 | "4 个分析视角（同一模型一次生成）"，不再称"独立顾问" |
| D3 | 输入上限 | 6000/600/64KB |
| D4 | 托管 `base_url` | 一律忽略请求体 |
| D5 | 历史隔离 | 托管按 owner 过滤；本机不过滤；旧记录托管下不可见 |
| D6 | agent5"敌我友"措辞 | 暂不改，待你决定 |
| D7 | 免费额度 | 只改文案，不动计费 |
| D8 | 过期的 `X-Frame-Options` 测试 | 改测 CSP `frame-ancestors`（扩展需要嵌入） |
| D9 | `/api/route` 托管无用户 Key | 只走规则路由 |
| D10/D11 | v1.2：agent7/10 的 `count` 与 schema 被拒的处理 | 见 v1.2 方案，默认值已写入 |

---

## 9. 未验证与已知风险（不要当成已确认）

- **从未验证过任何真实厂商**：Gemini 的 `responseSchema`、xAI、DeepSeek 的真实响应，AGENT 与我都没有 Key。
- 页面视觉效果没有任何人看过（AGENT 不能截图，我只读了 CSS）。
- 我没核对过：agent4/6/8/9 的 `config.json`、`cases.json`、`baseline_old.py`、`make_blind_sheet.py`、各 `index.html` 的改动、`:root` 里的 `--blue` 系列变量。
- 基线的含义：旧 prompt 经**新传输层**运行，所以"改前 vs 改后"的差异只来自 prompt 和输出契约。
- 转发层 504 后，子服务可能仍在继续并在稍后写入一条记录（概率低，因为子服务总预算 100 秒 < 转发 120 秒）。
- 清理线程只在某个子 Agent 首次被访问后才启动。
- `grounded` 的最短引用长度只是启发式；"用户未提供"永远算有依据，所以要看评测里的 `evasion_rate`。
- 免费额度的实际含义是约 5 次完整分析，而不是 10 次。

---

## 10. 后续议题（不在 v1.2）

- **深度模式**（两遍式红队，约 2 倍成本）：只有当真实评测显示单次调用的立场分布仍高度同质，才考虑。四路并行（约 5 倍成本）在没有评测证据前不考虑。
- **先看使用数据再决定投入**：10 个 Agent 结构相似，建议先统计各 Agent 的实际调用量，再决定把力气花在哪几个。
- `thinking_core` 与 `providers.py` 的收敛：AGENT 已确认 `providers.py` 没有通用 JSON 调用入口，需要先抽一个与业务无关的 `call_json(...)`。
- `innerHTML` 清理（AGENT 报过的位置，仍未处理）：`agent2/app.js`（L149、152、168、461、550、807–812、849、852、872）、`agent3/app.js`（L86、112、161、207、212、225、330–344、371、396–400）、根 `app.js`（L242、367、383、436、505、513、828、832）。行号以当时汇报为准，可能已变化。
- 职业体检（早先评述，未改）：评级权重与阈值是未校准的经验值；`RULES_VERSION` 仍为 "2.3"，旧会话不会按新规则重算（你的交接文档里也提到）。

---

## 11. 新窗口开场词（可直接粘贴）

> E:\Doc\Python_daye\CCagent 的本地文件系统 MCP 已运行。请先读 `docs/CCagent智囊团优化-交接说明.md`，再读 `docs/实施方案-智囊团优化v1.2-补丁.md`。我会把 AGENT 对 v1.2 的汇报贴给你，请你读对应代码审阅，不要只信汇报，并指出任何不实或没做完的地方。保持客观中立，有不切实际的想法直接指出。

---

## 12. 关键文件索引

| 文件 | 作用 |
|---|---|
| `thinking_core.py` | agent4–10 的共享后端：配置校验、prompt 构建、schema、`validate_result`、调用 LLM、HTTP 处理器 |
| `shared/thinking.js`、`shared/thinking.css` | 共享前端与样式 |
| `agentN/config.json`（N=4–10） | 每个 Agent 的智囊、字段、支柱、分节、各类提示 |
| `agentN/server.py` | 薄壳：加载配置，交给 `core.make_handler` |
| `server.py`（根） | 转发层、额度、限流、身份、`/api/route` |
| `tests/test_thinking_core.py` | 本轮的 Python 测试（19 项） |
| `tests/test_v24_phase1.py` | 职业体检的既有测试（4 项） |
| `tests/js/thinking.test.js` | 前端测试（XSS、兼容等） |
| `tests/council_eval/` | `cases.json`、`eval_council.py`、`baseline_old.py`、`make_blind_sheet.py`、`blind_sheet.md` |
| `tools/diag_council.py` | 真实 Key 的诊断脚本（逐条用例打印 finishReason、token、立场） |
| `docs/archive/council_backup_20261127/` | 改动前备份（只读） |
