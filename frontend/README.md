# Call Me Frontend

一个最小可用的 React 19 + TanStack Router + Tailwind v3 + shadcn/ui + Jotai 前端，用于对接 `plugins/call_me` 后端服务。

## 运行

```bash
cd plugins/call_me/frontend
bun install
bun run dev
```

默认对接：`http://127.0.0.1:8989`，可用环境变量覆盖：

```bash
VITE_CALL_ME_BASE_URL=http://127.0.0.1:8989 bun run dev
```

## 构建

```bash
bun run build
```

产物输出到：`plugins/call_me/static`（Vite outDir）。
