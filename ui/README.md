# 玄武AI智能体股票团队分析系统前端

This directory contains the current single-page SPA shell for **玄武AI智能体股票团队分析系统**.

## Local development

The frontend is a standalone SPA under `ui/`, and it talks to the Python gateway on port `8501`.

### 1. Start the Python gateway

From the repository root:

```bash
python app.py
```

### 2. Configure frontend env

Copy the template:

```bash
copy .env.example .env
```

The default development proxy points at the local gateway on `8501`:

```env
VITE_APP_TITLE=玄武AI智能体股票团队分析系统
VITE_API_BASE=/api
VITE_API_PROXY_TARGET=http://127.0.0.1:8501
```

### 3. Start the UI shell

- `npm install`
- `npm run dev`
- `npm run build`
- `npm run preview`

The frontend dev server runs on [http://127.0.0.1:4173](http://127.0.0.1:4173) and proxies API calls to the gateway that serves the SPA and backend APIs on `8501`.

## Routes

The SPA uses explicit client-side routes:

- `/main` 工作台
- `/discover` 发现股票
- `/research` 研究情报
- `/portfolio` 持仓分析
- `/live-sim` 量化模拟
- `/his-replay` 历史回放
- `/ai-monitor` AI盯盘
- `/real-monitor` 实时监控

Optional future routes:

- `/history`
- `/settings`
- `/login`

## Docker / nginx deployment

Docker deploys the frontend and backend independently:

- `build/Dockerfile.ui` builds the SPA and serves it with `nginx`
- `build/nginx.conf` handles SPA history fallback and proxies `/api/` to the backend service
- `build/docker-compose.yml` starts:
  - `backend` on port `8501`
  - `frontend` on port `8080`

Frontend requests should stay under `/api/` so the same UI can work in both local proxy mode and nginx mode. The backend API health check lives at `/api/health`.
