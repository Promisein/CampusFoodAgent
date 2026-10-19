# 第 8 章：Next.js 前端

## 本章目标

用 Next.js 15 搭建 Web 前端，实现自然语言搜索框 → 推荐卡片 → 反馈收藏的完整交互。

## 前置知识

- React 基础（组件、useState、useEffect）
- Next.js App Router 基础（`"use client"` 是什么意思）
- fetch API 的用法
- CSS 基础（Flexbox、CSS 变量）

## 文件清单

```
frontend/
├── package.json
├── next.config.mjs
├── tsconfig.json
├── .env.local
├── .env.local.example
└── src/
    ├── app/
    │   ├── globals.css          # ★ 全局样式
    │   ├── layout.tsx            # 根布局
    │   └── page.tsx              # ★ 主页面（所有 UI 在这里）
    ├── components/
    │   └── FeedbackPanel.tsx     # 反馈弹窗
    └── lib/
        ├── api.ts                # ★ 后端 API 调用封装
        └── identity.ts            # ★ 匿名身份管理
```

---

## Step 1：项目初始化

```bash
cd frontend
npm init -y
npm install next@latest react@latest react-dom@latest
npm install -D typescript @types/react @types/node
```

`package.json` 的 scripts：
```json
{
  "scripts": {
    "dev": "next dev -p 3000",
    "build": "next build",
    "start": "next start -p 3000",
    "lint": "next lint"
  }
}
```

`next.config.mjs`：
```js
const nextConfig = {
  reactStrictMode: true,
};
export default nextConfig;
```

`.env.local`：
```
NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
```

---

## Step 2：匿名身份管理

创建 `frontend/src/lib/identity.ts`：

```typescript
const STORAGE_KEY = "chedian.identity.v1";

export interface Identity {
  anonymousId: string;
  userId: string | null;
  accessToken: string | null;
  tokenExpiresAt: number | null;
}

function randomId(): string {
  const ts = Date.now().toString(36);
  const rand = Math.random().toString(36).slice(2, 10);
  return `anon_${ts}${rand}`;
}

let cached: Identity | null = null;

export function getIdentity(): Identity {
  if (cached) return cached;

  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw) {
      cached = JSON.parse(raw);

      // 检查 Token 是否过期
      if (cached?.accessToken && cached?.tokenExpiresAt) {
        if (Date.now() > cached.tokenExpiresAt - 30_000) {
          // 即将过期，降级回匿名
          cached.userId = null;
          cached.accessToken = null;
          cached.tokenExpiresAt = null;
          saveIdentity(cached);
        }
      }
      return cached;
    }
  } catch {}

  // 首次访问，生成匿名 ID
  cached = { anonymousId: randomId(), userId: null, accessToken: null, tokenExpiresAt: null };
  saveIdentity(cached);
  return cached;
}

function saveIdentity(id: Identity) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(id));
}

export function getAuthToken(): string {
  const id = getIdentity();
  if (id.accessToken) return `Bearer ${id.accessToken}`;
  return "";
}
```

**设计解读**：
- `getIdentity()` 每次调用都检查 Token 是否即将过期（提前 30 秒），过期则自动降级匿名
- 内存缓存 `cached` 避免频繁读 localStorage
- 匿名 ID 格式：`anon_<时间戳36进制><随机数>`，不依赖后端生成

---

## Step 3：API 调用封装

创建 `frontend/src/lib/api.ts`：

```typescript
import { getAuthToken, getIdentity } from "./identity";

function resolveApiBaseUrl(): string {
  if (typeof window !== "undefined") {
    // 检查环境变量
    const env = process.env.NEXT_PUBLIC_API_BASE_URL;
    if (env) return env;

    // localhost 检测
    if (window.location.hostname === "localhost") {
      return "http://localhost:8000";
    }
  }
  // 生产环境
  return "https://chedian-eat-agent-mvp.onrender.com";
}

function encodeJsonUtf8(data: unknown): Blob {
  const json = JSON.stringify(data);
  return new Blob([json], { type: "application/json" });
}

async function apiPost<T>(path: string, body: Record<string, unknown>): Promise<T> {
  const url = `${resolveApiBaseUrl()}${path}`;
  const token = getAuthToken();

  const headers: Record<string, string> = {
    "Content-Type": "application/json; charset=utf-8",
    Accept: "application/json",
  };
  if (token) headers["Authorization"] = token;

  const resp = await fetch(url, {
    method: "POST",
    headers,
    body: encodeJsonUtf8(body),
  });

  if (!resp.ok) {
    const errorText = await resp.text();
    throw new Error(`API error ${resp.status}: ${errorText}`);
  }

  return resp.json();
}

async function apiGet<T>(path: string, params?: Record<string, string>): Promise<T> {
  const base = resolveApiBaseUrl();
  const url = new URL(`${base}${path}`);
  if (params) {
    Object.entries(params).forEach(([k, v]) => url.searchParams.set(k, v));
  }

  const token = getAuthToken();
  const headers: Record<string, string> = { Accept: "application/json" };
  if (token) headers["Authorization"] = token;

  const resp = await fetch(url.toString(), { headers });
  if (!resp.ok) throw new Error(`API error ${resp.status}`);
  return resp.json();
}

// ---- 业务 API ----
export async function fetchRecommendations(query: string, history?: unknown[]) {
  const id = getIdentity();
  return apiPost("/api/recommend", {
    query,
    uid: id.anonymousId,
    anonymousId: id.anonymousId,
    userId: id.userId,
    history: history || [],
  });
}

export async function submitFeedback(data: Record<string, unknown>) {
  return apiPost("/api/feedback", data);
}

export async function fetchStoreDetail(name: string) {
  return apiGet("/api/stores/detail", { name });
}

export async function fetchRankings() {
  return apiGet("/api/v1/rankings/today");
}
```

**为什么用 `Blob` 而不是直接传 JSON 字符串？**
有些浏览器的 `fetch` 在传 JSON 字符串时会破坏 UTF-8 编码（尤其是中文字符）。用 `TextEncoder` 创建 Blob 并显式设置 `charset=utf-8` 可以避免这个问题。

---

## Step 4：主页面

创建 `frontend/src/app/page.tsx`。这是整个前端唯一的页面，包含：
1. 搜索框（textarea）
2. 快捷提示按钮
3. 推荐结果卡片
4. 反馈弹窗

```tsx
"use client";

import { useState } from "react";
import { fetchRecommendations, submitFeedback } from "@/lib/api";
import FeedbackPanel from "@/components/FeedbackPanel";

export default function Home() {
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(false);
  const [results, setResults] = useState<any[]>([]);
  const [answer, setAnswer] = useState("");
  const [error, setError] = useState("");
  const [feedbackOpen, setFeedbackOpen] = useState(false);

  const handleSubmit = async () => {
    if (!query.trim()) return;
    setLoading(true);
    setError("");
    try {
      const data = await fetchRecommendations(query);
      setAnswer(data.answer || "");
      setResults(data.recommendations || []);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  };

  const quickPrompts = [
    "清水河，预算25，一个人想吃清淡的",
    "沙河，同学聚餐，吃辣的",
    "西门附近，想吃面，便宜点的",
    "晚上吃夜宵，有什么推荐？",
  ];

  return (
    <div className="page">
      {/* 标题 */}
      <header className="hero-card">
        <h1>成电吃什么</h1>
        <p className="subtitle">校园餐饮 AI 推荐助手</p>
      </header>

      {/* 搜索框 */}
      <div className="composer-card">
        <textarea
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="说说你的需求，比如：清水河，预算25，一个人想吃清淡的..."
          rows={3}
          onKeyDown={(e) => {
            if ((e.metaKey || e.ctrlKey) && e.key === "Enter") handleSubmit();
          }}
        />
        <button className="gold-btn" onClick={handleSubmit} disabled={loading}>
          {loading ? "思考中..." : "生成推荐"}
        </button>

        <div className="quick-prompts">
          {quickPrompts.map((p) => (
            <button key={p} className="ghost-btn" onClick={() => setQuery(p)}>
              {p}
            </button>
          ))}
        </div>

        <button className="ghost-btn feedback-trigger" onClick={() => setFeedbackOpen(true)}>
          反馈新店 / 吃后评价
        </button>
      </div>

      {/* 错误 */}
      {error && <div className="error-card">{error}</div>}

      {/* 文本回答 */}
      {answer && <div className="answer-card">{answer}</div>}

      {/* 推荐卡片 */}
      {results.length > 0 && (
        <div className="results-panel">
          {results.map((r: any, i: number) => (
            <div key={i} className="shop-card">
              <div className="shop-card-header">
                <h3>{r.name}</h3>
                {r.match_score != null && (
                  <span className="score-badge">匹配度 {(r.match_score * 100).toFixed(0)}%</span>
                )}
              </div>
              <p className="shop-reason">{r.reason}</p>
            </div>
          ))}
        </div>
      )}

      {/* 反馈弹窗 */}
      {feedbackOpen && <FeedbackPanel onClose={() => setFeedbackOpen(false)} />}
    </div>
  );
}
```

---

## Step 5：全局样式

创建 `frontend/src/app/globals.css`。设计要点：

```css
/* CSS 变量 —— 银杏主题色系 */
:root {
  --gold: #c9a96e;
  --gold-light: #f7f2e6;
  --beige: #faf6f0;
  --brown: #7b5b2a;
  --text: #3d3d3d;
  --text-light: #8c96a8;
  --card-bg: rgba(255, 255, 255, 0.72);
  --shadow: 0 4px 24px rgba(0, 0, 0, 0.06);
}

body {
  background: linear-gradient(135deg, var(--beige), var(--gold-light));
  font-family: "PingFang SC", "Noto Sans SC", sans-serif;
  color: var(--text);
  min-height: 100vh;
}

/* 玻璃态卡片 */
.glass-card {
  background: var(--card-bg);
  backdrop-filter: blur(12px);
  border: 1px solid rgba(201, 169, 110, 0.18);
  border-radius: 16px;
  box-shadow: var(--shadow);
  padding: 24px;
}

/* 金色主按钮 */
.gold-btn {
  background: linear-gradient(135deg, var(--gold), #a8834a);
  color: #fff;
  border: none;
  border-radius: 8px;
  padding: 10px 24px;
  cursor: pointer;
  font-size: 15px;
}

.gold-btn:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

/* 骨架加载动画 */
@keyframes shimmer {
  0% { background-position: -200px 0; }
  100% { background-position: 200px 0; }
}

.skeleton {
  background: linear-gradient(90deg, #f0f0f0 25%, #e0e0e0 50%, #f0f0f0 75%);
  background-size: 400px 100%;
  animation: shimmer 1.5s infinite;
  border-radius: 8px;
}
```

完整样式文件参考原项目的 `globals.css`(~1934 行)，包含了完整的响应式设计、卡片布局、反馈面板样式、动画等。

---

## Step 6：验证

```bash
cd frontend
npm run dev
# 打开 http://localhost:3000

# 确认后端在 :8000 运行
cd backend
uvicorn app.main:app --reload --port 8000
```

1. 在搜索框输入"清水河，一个人吃清淡的"→ 点生成推荐 → 看到推荐卡片
2. 点反馈按钮 → 弹出表单 → 提交后关闭
3. 打开浏览器 DevTools → Network 标签 → 确认请求正确发送到 `localhost:8000`

---

## 常见坑

| 坑 | 原因 | 解决 |
|---|---|---|
| CORS 错误 | 后端没配前端端口 | 确认后端 `CORS_ALLOW_ORIGINS` 含 `localhost:3000` |
| 中文乱码 | Content-Type 缺 charset | 前端用 `encodeJsonUtf8`，后端用 `Utf8ResponseMiddleware` |
| `NEXT_PUBLIC_API_BASE_URL` 不生效 | Next.js 需要在构建时注入 | 改 `.env.local` 后重启 `npm run dev` |
| 页面白屏 | React 报错没显示 | 打开浏览器控制台看错误 |

## 章末检查

- [ ] 搜索框输入后能看到推荐结果
- [ ] 快捷提示按钮能快速填充输入
- [ ] 加载中有骨架/loading 状态
- [ ] 错误时显示错误信息而非白屏
- [ ] 中文显示正常无乱码
- [ ] 反馈弹窗能打开并提交
