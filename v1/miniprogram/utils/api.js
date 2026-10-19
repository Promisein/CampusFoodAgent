const { API_BASE_URL } = require("./config");
const identity = require("./identity");

function request(method, path, data) {
  return new Promise((resolve, reject) => {
    const headers = {
      "Content-Type": "application/json; charset=utf-8",
      Accept: "application/json",
    };

    const token = identity.getAuthToken();
    if (token) headers.Authorization = token;

    wx.request({
      url: `${API_BASE_URL}${path}`,
      method,
      data,
      header: headers,
      timeout: 90000,
      success(res) {
        if (res.statusCode >= 200 && res.statusCode < 300) {
          resolve(res.data);
          return;
        }
        const detail = (res.data && (res.data.detail || res.data.error)) || `HTTP ${res.statusCode}`;
        reject(new Error(detail));
      },
      fail(err) {
        reject(new Error(err.errMsg || "网络请求失败"));
      },
    });
  });
}

function fetchRecommendations(query) {
  const id = identity.getCurrentIdentity();
  return request("POST", "/api/recommend", {
    query,
    uid: id.anonymousId,
    anonymousId: id.anonymousId,
    userId: id.userId || undefined,
    history: [],
  });
}

function addFavorite(shopId, shopName) {
  return request("POST", "/api/v1/favorites", {
    shop_id: shopId,
    shop_name: shopName,
  });
}

function removeFavorite(shopId) {
  return request("DELETE", "/api/v1/favorites", {
    shop_id: shopId,
  });
}

function fetchFavorites() {
  return request("GET", "/api/v1/favorites");
}

function wechatLogin(code) {
  const id = identity.getCurrentIdentity();
  return request("POST", "/api/auth/wechat-login", {
    code,
    anonymousId: id.anonymousId,
  });
}

module.exports = {
  fetchRecommendations,
  addFavorite,
  removeFavorite,
  fetchFavorites,
  wechatLogin,
};
