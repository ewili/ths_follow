# Follow Client Web

跟单端管理台前端（Vue 3 + Vite + Element Plus）。

## 开发

```bash
npm install
npm run dev
```

开发服务器默认 http://localhost:5174 ，API 代理到 `http://127.0.0.1:8100`。

需先启动后端：`follow-client/start.bat`。

## 构建

```bash
npm run build
```

产物输出到 `web/dist/`，由 FastAPI 静态托管。
