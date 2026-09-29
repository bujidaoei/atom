# Atom

一个可以注册、生成、预览和验收的网页工作台。你用一句话描述小产品，小队先写可锁定的契约，确认后才生成页面。页面能在预览里点击，改动会存回项目。

这不是 [atoms.dev](https://atoms.dev/) 的官方产品。

## 本地运行

后端：

```bash
cd backend
uv sync --group dev
cp ../.env.example .env
uv run uvicorn app.main:app --reload --port 8000
```

前端：

```bash
cd frontend
npm install
npm run dev
```

打开 http://127.0.0.1:5173 。开发服务器会把 `/api` 转到 8000 端口。

`.env` 里至少要有 `ATOM_SECRET` 和 `ATOM_LLM_API_KEY`。密钥不要提交到仓库。

## 部署

服务器上准备 `.env` 后：

```bash
docker compose up -d --build
```

容器里由 Supervisor 同时拉起 nginx 和 API。页面默认走 80 端口，`/api` 转到本机的 uvicorn。SQLite 在名为 `atom-data` 的卷里。

80 端口已被占用时，把 `ATOM_HTTP_PORT` 改成空闲端口。如果只能挂在现有站点的子路径下，构建时设置 `VITE_BASE=/atom/`，并让前面的反向代理把 `/atom/` 转到容器的 80 端口。这时 `.env` 里的 `ATOM_COOKIE_PATH` 也写成 `/atom`。

## 测试

```bash
cd backend
uv run pytest
```
