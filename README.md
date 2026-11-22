# 职业投入快评工具

基于纯 Python 标准库（`http.server.ThreadingHTTPServer` + `sqlite3` + `urllib`）实现的职业投入决策快评工具。

## 启动方式

1. 复制 `.env.example` 为 `.env`，填写 `GEMINI_API_KEY`（也可在页面右上角“设置”中填写）。
2. 启动服务：
   ```bash
   python server.py
   ```
3. 浏览器访问：`http://127.0.0.1:8100`

## 运行单元测试

```bash
python -m unittest discover tests -v
```

