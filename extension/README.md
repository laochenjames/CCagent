# CCagent 智囊团浏览器插件（Chrome / Edge Side Panel）

在逛 X（Twitter）或任意网页时，无需离开当前页面，直接在浏览器右侧边栏调用 CCagent 7 大智囊团 Agent。

## 安装步骤（30 秒）
1. 打开 Chrome 或 Edge，地址栏输入 `chrome://extensions`（Edge 为 `edge://extensions`）。
2. 打开右上角 **开发者模式（Developer mode）**。
3. 点击 **加载已解压的扩展程序（Load unpacked）**，选择本文件夹：`CCagent/extension`。

## 使用方式
1. **逛 X / Twitter 一键抓推文**：每条推文底部操作栏会出现一个 `CC` 按钮：
   - **直接点击**：将整条推文（含作者和链接）发送到右侧边栏当前 Agent 的输入框。
   - **按住 Shift 点击**：追加到「暂存篮」，攒够几条后一键合并发给「一法多解（芒格）」。
2. **任意网页划词右键**：选中任意文字 → 右键 → **发送到 CCagent 智囊团** → 选择 7 个 Agent 之一，或追加到暂存篮。
3. **快捷键**：选中文字后按 `Alt + C`，直接打开侧边栏并填入。
4. **绑定 Grok / API Key**：点击侧边栏右上角 **API**，填入你的 xAI Grok / Gemini / DeepSeek Key，点击「保存并同步」即可对所有 Agent 生效（留空则默认使用服务端免费额度）。
