# CCagent 任务接口文档 (API Reference v3)

本文档面向单用户桌面使用，并为后续桌宠（CCbd）读取待办与打勾完成预留稳定接口。

---

## 1. 基础约定

- **服务地址**：`http://127.0.0.1:8099`（默认端口可通过环境变量 `PORT` 配置）
- **数据格式**：`application/json; charset=utf-8`
- **时间格式**：统一采用 UTC 微秒 ISO 8601 标准，结尾带 `Z`（例如：`2026-11-13T04:40:00.123456Z`）
- **超时与网络**：
  - 默认 API 调用超时为 120 秒，可通过环境变量 `GEMINI_TIMEOUT` 自定义覆盖。
  - 严格绑定本地回环网络 `127.0.0.1`，仅接受来自 `127.0.0.1` 和 `localhost` 的 Host 请求。
- **错误统一响应格式**：
  ```json
  { "error": "具体错误原因说明" }
  ```

---

## 2. 接口列表

### 2.1 任务列表查询 (GET `/api/tasks`)
桌宠轮询拉取当前未完成任务的主要接口。

- **Query 参数**：
  - `status`（可选）：`open`（进行中，默认）| `done`（已打勾完成）| `removed`（已软删除）。
  - `updated_after`（可选）：ISO 8601 时间戳（如 `2026-11-13T00:00:00Z`），支持增量轮询同步。
- **响应示例**：
  ```json
  {
    "tasks": [
      {
        "id": "t_20261112204316_d77282",
        "title": "健身与髋关节训练",
        "domain": "play",
        "quadrant": "q2",
        "status": "open",
        "reason": "因为身体维护与恢复是维持持续产出的底线，所以划入Q2；若其实身体严重不适需就医，则应为Q1。",
        "advice": "安排在下午精力低谷期进行，设定45分钟闹钟严格执行恢复动作",
        "factors": {
          "deadline": "无硬性截止",
          "consequence": "长期积累体能与防劳损",
          "reversible": true,
          "waiting_party": "",
          "money_related": false
        },
        "assumptions": ["身体无急性拉伤"],
        "confidence": "high",
        "probe": "",
        "expert_id": "PLAY_RIGID_RECOVERY",
        "ai_quadrant": "q2",
        "ai_domain": "play",
        "user_moved": 0,
        "correction_ignored": 0,
        "engine": "ai",
        "run_id": "run_20261112204222_6d4a50",
        "created_at": "2026-11-12T12:43:16.123456Z",
        "updated_at": "2026-11-12T12:43:16.123456Z",
        "done_at": null
      }
    ]
  }
  ```

---

### 2.2 任务打勾与更新 (PATCH `/api/tasks/{id}`)
桌宠打勾完成、用户手动修改标题、拖拽象限或点击切换领域的核心接口。

- **支持更新字段**：
  - `status`: `"open"` | `"done"` | `"removed"`（非法值返回 HTTP 400）
  - `quadrant`: `"q1"` | `"q2"` | `"q3"` | `"q4"` | `"candidate"`（非法值返回 HTTP 400）
  - `domain`: `"work"` | `"life"` | `"study"` | `"play"`（非法值返回 HTTP 400）
  - `title`: 字符串（自动 strip，若为空返回 HTTP 400）
  - `advice`: 字符串
  - `correction_ignored`: `0` | `1`（设为 1 则移出提示词纠偏候选）
- **v3 行为规范**：
  - **`user_moved` 动态重算**：当更新 `quadrant` 或 `domain` 时，系统按 `(quadrant != ai_quadrant or domain != ai_domain)` 重新计算；若用户将卡片拖回原位，`user_moved` 自动恢复为 0。
  - **历史记录**：所有变动自动写入 `feedback_events` 表，原始 `ai_quadrant` 与 `ai_domain` 永不覆盖。
- **响应**：
  ```json
  {
    "task": { ...更新后的任务完整对象... }
  }
  ```

---

### 2.3 手动新增任务 (POST `/api/tasks`)
- **请求体**：
  ```json
  {
    "title": "购买下季度服务器",
    "domain": "work",
    "quadrant": "q1",
    "reason": "基础服务续费，防止停摆",
    "advice": "登录控制台一键续费"
  }
  ```
- **响应**：HTTP 201，返回创建并入库的任务对象。

---

### 2.4 任务软删除 (DELETE `/api/tasks/{id}`)
- **说明**：将任务标记为 `status: "removed"` 并记录反馈事件，前端卡片随即消失，数据库完整保留历史日志。
- **响应**：`{ "status": "ok", "message": "Task soft-deleted" }`

---

### 2.5 智能分流解析 (POST `/api/triage`)
- **请求体**：
  ```json
  {
    "text": "明天下午2点交付客户A核心代码\n后天交电费\n晚上想打黑神话放松",
    "fallback": true
  }
  ```
- **响应**：
  ```json
  {
    "run_id": "run_20261113_xxx",
    "engine": "ai",
    "model": "gemini-3.5-flash",
    "fallback_reason": null,
    "tasks": [ ...新生成的任务数组... ],
    "skipped_duplicates": 0
  }
  ```
- **v3 错误分类**：若网络或 API 异常回退至保底规则，`fallback_reason` 输出规范分类：
  - `Key 无效或无权限` (401/403)
  - `请求被拒绝（可能是结构化输出参数）` (400)
  - `模型名或 Base URL 不存在` (404)
  - `限流` (429)
  - `服务繁忙` (5xx)
  - `请求超时`
  - `模型输出格式异常`
  - `网络异常`

---

### 2.6 查看智囊原型库 (GET `/api/advisory`)
- **说明**：获取当前生效的 14 个领域事件原型智囊策略。前端据此将内部 `expert_id` 转换为友好名称（如 `核心变现与交付攻坚`）。

---

### 2.7 读写本周重点与硬约束 Context
- **读取**：`GET /api/context` ➜ `{ "context": "本周重点交付自媒体视频..." }`
- **保存**：`PUT /api/context` ➜ Body: `{ "context": "本周重点交付自媒体视频..." }`

---

### 2.8 读写全局设置 (GET / PUT `/api/settings`)
- **读取**：`GET /api/settings` ➜ `{ "corrections_enabled": true, "context": "..." }`
- **保存**：`PUT /api/settings` ➜ Body: `{ "corrections_enabled": false }`
  *(关闭后分诊提示词里不再包含任何历史纠正段)*

---

### 2.9 查看历史纠正记录 (GET `/api/corrections`)
- **说明**：获取所有 `user_moved = 1` 的手动纠偏记录列表，支持设置弹窗中一键忽略。

---

### 2.10 导出待办清单 (GET `/api/export`)
- **Query 参数**：
  - `format`：`md`（默认，纯净 Markdown 任务列表）| `json`（完整字段数组）
  - `status`：`open`（默认）| `done` | `all`（`all` 导出全部未删除任务）
- **Markdown 格式规范（无 emoji）**：
  ```markdown
  # 任务分流清单 (2026-11-13)

  ## Q1 重要且紧急
  - [ ] 制作并剪辑自媒体视频 #work
    > 判断：因为符合本周核心交付目标，所以划入Q1；若其实只是随意收集素材，则应为Q2。
    > 建议：先整理前3个镜头粗剪大纲。
  ```
