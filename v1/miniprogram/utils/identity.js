const STORAGE_KEY = "chedian.identity.v1";

function randomId() {
  const ts = Date.now().toString(36);
  const rand = Math.random().toString(36).slice(2, 10);
  return `anon_${ts}${rand}`;
}

let cachedIdentity = null;

function saveIdentity(identity) {
  cachedIdentity = identity;
  wx.setStorageSync(STORAGE_KEY, identity);
}

function getCurrentIdentity() {
  if (cachedIdentity) return cachedIdentity;

  const stored = wx.getStorageSync(STORAGE_KEY);
  if (stored && stored.anonymousId) {
    cachedIdentity = stored;
    return cachedIdentity;
  }

  cachedIdentity = {
    anonymousId: randomId(),
    userId: null,
    accessToken: null,
    tokenExpiresAt: null,
  };
  saveIdentity(cachedIdentity);
  return cachedIdentity;
}

function saveAuthenticatedIdentity(accessToken, userId, expiresIn) {
  const identity = getCurrentIdentity();
  identity.accessToken = accessToken;
  identity.userId = userId;
  identity.tokenExpiresAt = Date.now() + expiresIn * 1000;
  saveIdentity(identity);
  return identity;
}

function getAuthToken() {
  const identity = getCurrentIdentity();
  if (!identity.accessToken) return "";
  // 提前 30 秒过期降级
  if (identity.tokenExpiresAt && Date.now() > identity.tokenExpiresAt - 30000) {
    identity.accessToken = null;
    identity.userId = null;
    identity.tokenExpiresAt = null;
    saveIdentity(identity);
    return "";
  }
  return `Bearer ${identity.accessToken}`;
}

module.exports = {
  getCurrentIdentity,
  saveAuthenticatedIdentity,
  getAuthToken,
};
