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

function saveIdentity(id: Identity) {
  cached = id;
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(id));
  } catch {}
}

export function getIdentity(): Identity {
  if (cached) return cached;

  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw) {
      const parsed: Identity = JSON.parse(raw);
      cached = parsed;

      // 检查 Token 是否即将过期（提前 30 秒降级）
      if (cached?.accessToken && cached?.tokenExpiresAt) {
        if (Date.now() > cached.tokenExpiresAt - 30_000) {
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
  cached = {
    anonymousId: randomId(),
    userId: null,
    accessToken: null,
    tokenExpiresAt: null,
  };
  saveIdentity(cached);
  return cached;
}

export function upgradeIdentity(
  accessToken: string,
  userId: string,
  expiresIn: number
) {
  const id = getIdentity();
  id.accessToken = accessToken;
  id.userId = userId;
  id.tokenExpiresAt = Date.now() + expiresIn * 1000;
  saveIdentity(id);
}

export function getAuthToken(): string {
  const id = getIdentity();
  if (id.accessToken) return `Bearer ${id.accessToken}`;
  return "";
}

export function logoutIdentity() {
  const id = getIdentity();
  id.accessToken = null;
  id.userId = null;
  id.tokenExpiresAt = null;
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(id));
  } catch {}
}
