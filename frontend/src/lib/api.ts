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
  // TextEncoder 默认 UTF-8，确保中文字符不被破坏
  const bytes = new TextEncoder().encode(json);
  return new Blob([bytes], { type: "application/json" });
}

async function apiPost<T>(
  path: string,
  body: Record<string, unknown>
): Promise<T> {
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

async function apiGet<T>(
  path: string,
  params?: Record<string, string>
): Promise<T> {
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

export async function fetchRecommendations(
  query: string,
  history?: unknown[]
): Promise<any> {
  const id = getIdentity();
  return apiPost("/api/recommend", {
    query,
    uid: id.anonymousId,
    anonymousId: id.anonymousId,
    userId: id.userId || undefined,
    history: history || [],
  });
}

export async function submitFeedback(data: Record<string, unknown>): Promise<any> {
  return apiPost("/api/v1/feedback", data);
}

export async function addFavorite(shopId: number, shopName: string): Promise<any> {
  return apiPost("/api/v1/favorites", { shop_id: shopId, shop_name: shopName });
}

export async function removeFavorite(shopId: number): Promise<any> {
  const token = getAuthToken();
  const base = resolveApiBaseUrl();
  const headers: Record<string, string> = {
    "Content-Type": "application/json; charset=utf-8",
    Accept: "application/json",
  };
  if (token) headers["Authorization"] = token;
  const resp = await fetch(`${base}/api/v1/favorites`, {
    method: "DELETE",
    headers,
    body: encodeJsonUtf8({ shop_id: shopId }),
  });
  if (!resp.ok) throw new Error(`API error ${resp.status}`);
  return resp.json();
}

export async function fetchFavorites(): Promise<any> {
  return apiGet("/api/v1/favorites");
}

export async function fetchStoreDetail(name: string): Promise<any> {
  return apiGet("/api/v1/stores/detail", { name });
}

export async function fetchStoreSuggestions(keyword: string): Promise<any> {
  return apiGet("/api/v1/stores/suggest", { keyword });
}

export async function fetchRankings(): Promise<any> {
  return apiGet("/api/v1/rankings/today");
}

export async function emailRegister(
  email: string,
  password: string,
  anonymousId: string
): Promise<any> {
  return apiPost("/api/auth/email-register", { email, password, anonymousId });
}

export async function getMe(): Promise<any> {
  return apiGet("/api/auth/me");
}

export async function emailLogin(
  email: string,
  password: string,
  anonymousId: string
): Promise<any> {
  return apiPost("/api/auth/email-login", { email, password, anonymousId });
}
