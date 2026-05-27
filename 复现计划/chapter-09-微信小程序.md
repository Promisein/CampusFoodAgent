# 第 9 章：微信小程序

## 本章目标

搭建微信小程序端，实现与 Web 端功能对等的推荐交互体验，包括定位感知、匿名身份、反馈收藏。

## 前置知识

- 微信开发者工具的基本使用
- 小程序的四件套：`.js`（逻辑）/ `.wxml`（模板）/ `.wxss`（样式）/ `.json`（配置）
- `wx.request` / `wx.setStorageSync` / `wx.getLocation` 等微信 API

## 文件清单

```
miniprogram/
├── app.js                  # 小程序入口
├── app.json                # 全局配置（页面路由、TabBar、权限）
├── app.wxss                # 全局样式
├── sitemap.json
├── assets/
│   └── tabbar-v2/          # TabBar 图标
├── pages/
│   ├── index/              # ★ 首页（问询）
│   │   ├── index.js
│   │   ├── index.wxml
│   │   ├── index.wxss
│   │   └── index.json
│   ├── ads/                # 商家推荐
│   ├── profile/            # 我的
│   ├── profile-detail/     # 偏好设置
│   └── store-detail/       # 店铺详情
└── utils/
    ├── api.js              # ★ 后端 API 调用
    ├── config.js           # API 地址配置
    ├── identity.js          # ★ 匿名身份管理
    ├── analytics.js         # 埋点
    └── recommendation.js   # 推荐结果解析
```

---

## Step 1：项目配置

`project.config.json`（放在仓库根目录）：
```json
{
  "compileType": "miniprogram",
  "miniprogramRoot": "miniprogram/",
  "appid": "your-appid-here",
  "setting": {
    "es6": true,
    "minified": true
  },
  "libVersion": "3.15.1"
}
```

`miniprogram/app.json`：
```json
{
  "pages": [
    "pages/index/index",
    "pages/ads/index",
    "pages/profile/index",
    "pages/profile-detail/index",
    "pages/store-detail/index"
  ],
  "tabBar": {
    "color": "#8c96a8",
    "selectedColor": "#7b5b2a",
    "backgroundColor": "#f7f2e6",
    "list": [
      { "pagePath": "pages/index/index", "text": "问询", "iconPath": "assets/tabbar-v2/inquiry.png", "selectedIconPath": "assets/tabbar-v2/inquiry-active.png" },
      { "pagePath": "pages/ads/index", "text": "商家推荐", "iconPath": "assets/tabbar-v2/ads.png", "selectedIconPath": "assets/tabbar-v2/ads-active.png" },
      { "pagePath": "pages/profile/index", "text": "我的", "iconPath": "assets/tabbar-v2/profile.png", "selectedIconPath": "assets/tabbar-v2/profile-active.png" }
    ]
  },
  "window": {
    "navigationBarBackgroundColor": "#f7f2e6",
    "navigationBarTitleText": "成电吃什么",
    "backgroundColor": "#faf6f0"
  },
  "permission": {
    "scope.userLocation": { "desc": "用于优先推荐你附近可步行到达的店铺" }
  },
  "style": "v2"
}
```

---

## Step 2：API 配置与调用

创建 `miniprogram/utils/config.js`：

```javascript
const DEV_BASE_URL = "http://127.0.0.1:8000";
const PROD_BASE_URL = "https://chedian-eat-agent-mvp.onrender.com";
const FORCE_REMOTE_IN_DEV = false;  // 开发时 false 走本地，上线时 true 走生产

const API_BASE_URL = FORCE_REMOTE_IN_DEV ? PROD_BASE_URL : DEV_BASE_URL;

module.exports = { API_BASE_URL, DEV_BASE_URL, PROD_BASE_URL };
```

创建 `miniprogram/utils/api.js`：

```javascript
const { API_BASE_URL } = require("./config");
const identity = require("./identity");

/**
 * 通用请求封装。
 * - 自动附加 Authorization 头
 * - 401 时自动降级匿名身份
 * - 超时 90 秒（AI 推荐接口较慢）
 */
function request(method, path, data) {
  return new Promise((resolve, reject) => {
    const token = identity.getAuthToken();
    const header = { "Content-Type": "application/json; charset=utf-8" };
    if (token) header["Authorization"] = token;

    wx.request({
      url: `${API_BASE_URL}${path}`,
      method,
      header,
      data,
      timeout: 90000,
      success(res) {
        if (res.statusCode === 401) {
          // Token 过期，降级
          identity.clearAuthenticatedIdentity();
        }
        if (res.statusCode >= 200 && res.statusCode < 300) {
          resolve(res.data);
        } else {
          const detail = (res.data && (res.data.detail || res.data.error)) || `HTTP ${res.statusCode}`;
          reject(new Error(detail));
        }
      },
      fail(err) {
        reject(new Error(err.errMsg || "网络请求失败"));
      },
    });
  });
}

// ---- 业务 API ----
function fetchRecommendations(payload) {
  return request("POST", "/api/recommend", payload);
}

function submitFeedback(payload) {
  return request("POST", "/api/feedback", payload);
}

function fetchStoreDetail(name) {
  return request("GET", `/api/stores/detail?name=${encodeURIComponent(name)}`);
}

function fetchTodayRankings() {
  return request("GET", "/api/v1/rankings/today");
}

function trackUsageEvent(payload) {
  return request("POST", "/api/events/track", payload);
}

module.exports = {
  fetchRecommendations,
  submitFeedback,
  fetchStoreDetail,
  fetchTodayRankings,
  trackUsageEvent,
};
```

**对比 Web 端**：小程序用 `wx.request` 而非 `fetch`，Promise 封装逻辑完全一样。

---

## Step 3：匿名身份（小程序版）

创建 `miniprogram/utils/identity.js`：

```javascript
const STORAGE_KEY = "chedian.identity.v1";

function randomId() {
  const ts = Date.now().toString(36);
  const rand = Math.random().toString(36).slice(2, 10);
  return `anon_${ts}${rand}`;
}

let cachedIdentity = null;

function getCurrentIdentity() {
  if (cachedIdentity) return cachedIdentity;

  try {
    const raw = wx.getStorageSync(STORAGE_KEY);
    if (raw) {
      cachedIdentity = raw;

      // Token 过期检查
      if (cachedIdentity.accessToken && cachedIdentity.tokenExpiresAt) {
        if (Date.now() > cachedIdentity.tokenExpiresAt - 30000) {
          // 降级
          cachedIdentity.userId = null;
          cachedIdentity.accessToken = null;
          cachedIdentity.tokenType = null;
          cachedIdentity.tokenExpiresAt = null;
          saveIdentity(cachedIdentity);
        }
      }
      return cachedIdentity;
    }
  } catch (_) {}

  // 首次访问
  cachedIdentity = {
    anonymousId: randomId(),
    userId: null,
    accessToken: null,
    tokenType: null,
    tokenExpiresAt: null,
  };
  saveIdentity(cachedIdentity);
  return cachedIdentity;
}

function saveIdentity(obj) {
  wx.setStorageSync(STORAGE_KEY, obj);
}

function saveAuthenticatedIdentity(userId, anonymousId, auth) {
  const existing = getCurrentIdentity();
  const merged = {
    ...existing,
    anonymousId: anonymousId || existing.anonymousId,
    userId,
    accessToken: auth.access_token,
    tokenType: auth.token_type || "Bearer",
    tokenExpiresAt: Date.now() + (auth.expires_in || 604800) * 1000,
  };
  saveIdentity(merged);
  cachedIdentity = merged;
  return merged;
}

function clearAuthenticatedIdentity() {
  const existing = getCurrentIdentity();
  existing.userId = null;
  existing.accessToken = null;
  existing.tokenType = null;
  existing.tokenExpiresAt = null;
  saveIdentity(existing);
  cachedIdentity = existing;
}

function getAuthToken() {
  const id = getCurrentIdentity();
  if (id.accessToken) return `Bearer ${id.accessToken}`;
  return "";
}

module.exports = {
  getCurrentIdentity,
  saveAuthenticatedIdentity,
  clearAuthenticatedIdentity,
  getAuthToken,
};
```

**与 Web 版 identity.ts 的差异**：
- `localStorage` → `wx.setStorageSync / wx.getStorageSync`
- `crypto.randomUUID()` → 自研 `randomId()`
- 小程序支持 `saveAuthenticatedIdentity()` 和 `clearAuthenticatedIdentity()` 两个显式的状态切换函数

---

## Step 4：首页（问询页）

创建 `miniprogram/pages/index/index.wxml`：

```xml
<view class="page">
  <!-- 标题 -->
  <view class="hero-card">
    <text class="title">成电吃什么</text>
    <text class="subtitle">校园餐饮 AI 推荐助手</text>
  </view>

  <!-- 搜索区域 -->
  <view class="composer-card">
    <textarea
      value="{{query}}"
      placeholder="说说你的需求，比如：清水河，预算25，一个人想吃清淡的..."
      bindinput="onQueryInput"
      auto-height
    />
    <view class="location-row">
      <switch checked="{{useLocation}}" bindchange="onLocationToggle" />
      <text>优先推荐附近的店</text>
    </view>
    <button class="gold-btn" bindtap="onSubmit" loading="{{loading}}" disabled="{{loading}}">
      {{loading ? '思考中...' : '生成推荐'}}
    </button>

    <!-- 快捷提示 -->
    <view class="quick-prompts">
      <text class="chip" bindtap="onQuickPrompt" data-text="清水河，一个人吃清淡的">清水河·清淡·一人食</text>
      <text class="chip" bindtap="onQuickPrompt" data-text="沙河，聚餐吃辣">沙河·聚餐·吃辣</text>
      <text class="chip" bindtap="onQuickPrompt" data-text="西门附近，便宜好吃">西门·便宜好吃</text>
    </view>
  </view>

  <!-- 结果 -->
  <view class="results-panel" wx:if="{{results.length > 0}}">
    <view class="shop-card" wx:for="{{results}}" wx:key="name">
      <view class="card-header">
        <text class="shop-name">{{item.name}}</text>
        <text class="score">{{item.match_score * 100}}% 匹配</text>
      </view>
      <text class="reason">{{item.reason}}</text>
    </view>
  </view>

  <!-- 错误 -->
  <view class="error-card" wx:if="{{error}}">
    <text>{{error}}</text>
  </view>
</view>
```

创建 `miniprogram/pages/index/index.js`：

```javascript
const api = require("../../utils/api");
const identity = require("../../utils/identity");

Page({
  data: {
    query: "",
    loading: false,
    error: "",
    results: [],
    useLocation: false,
    latitude: null,
    longitude: null,
  },

  onQueryInput(e) {
    this.setData({ query: e.detail.value });
  },

  onQuickPrompt(e) {
    this.setData({ query: e.currentTarget.dataset.text });
  },

  onLocationToggle(e) {
    const useLocation = e.detail.value;
    this.setData({ useLocation });
    if (useLocation) {
      wx.getLocation({
        type: "gcj02",
        success: (res) => {
          this.setData({ latitude: res.latitude, longitude: res.longitude });
        },
        fail: () => {
          wx.showToast({ title: "定位失败", icon: "none" });
          this.setData({ useLocation: false });
        },
      });
    }
  },

  async onSubmit() {
    const { query, useLocation, latitude, longitude } = this.data;
    if (!query.trim()) return;

    this.setData({ loading: true, error: "", results: [] });

    try {
      const id = identity.getCurrentIdentity();
      const payload = {
        query,
        uid: id.anonymousId,
        anonymousId: id.anonymousId,
        userId: id.userId,
      };
      if (useLocation && latitude) {
        payload.location = { latitude, longitude };
      }

      const data = await api.fetchRecommendations(payload);
      this.setData({
        results: data.recommendations || [],
        answer: data.answer || "",
      });
    } catch (e) {
      this.setData({ error: e.message });
    } finally {
      this.setData({ loading: false });
    }
  },
});
```

---

## Step 5：全局样式

创建 `miniprogram/app.wxss`：

```css
page {
  background: linear-gradient(135deg, #faf6f0, #f7f2e6);
  font-family: "PingFang SC", "Noto Sans SC", sans-serif;
  color: #3d3d3d;
}

.glass-card {
  background: rgba(255, 255, 255, 0.72);
  border-radius: 16rpx;
  box-shadow: 0 8rpx 48rpx rgba(0, 0, 0, 0.06);
  padding: 32rpx;
  margin: 24rpx;
}

.gold-btn {
  background: linear-gradient(135deg, #c9a96e, #a8834a);
  color: #fff;
  border: none;
  border-radius: 16rpx;
  padding: 20rpx 48rpx;
  font-size: 30rpx;
}

.ghost-btn {
  background: transparent;
  color: #7b5b2a;
  border: 1px solid #c9a96e;
  border-radius: 16rpx;
  padding: 16rpx 32rpx;
  font-size: 26rpx;
}
```

**`rpx` 是什么？** 微信小程序专用长度单位。750rpx = 屏幕宽度，所以你在任何屏幕上都看到等比例的布局。

---

## Step 6：运行

1. 打开微信开发者工具
2. 导入项目 → 选择仓库根目录（不是 miniprogram 目录）
3. `project.config.json` 中的 `miniprogramRoot` 会自动指向 `miniprogram/`
4. 确保后端在 `:8000` 运行
5. 在开发者工具中调试

**如何在真机上测试？**
- 预览/真机调试模式
- 如果后端在本地 `127.0.0.1:8000`，手机访问不到
- 解决办法：部署后端到公网 → 改 `config.js` → 或者用内网穿透（ngrok/frp）→ 或者设置 `FORCE_REMOTE_IN_DEV = true` 使用已部署的生产环境

---

## 常见坑

| 坑 | 原因 | 解决 |
|---|---|---|
| `不在以下 request 合法域名列表中` | 小程序要求 HTTPS + 在后台配置服务器域名 | 开发阶段在开发者工具中勾选"不校验合法域名" |
| 手机上请求不到 localhost | 手机和电脑不在同一网络 | 用内网穿透或部署到公网 |
| `wx.getLocation` 返回空 | 用户拒绝了定位授权 | 引导用户去设置页开启 |
| TabBar 图标不显示 | 图标路径错误或图片格式不支持 | 确认图片在 `assets/tabbar-v2/` 下，使用 PNG 格式 |

## 章末检查

- [ ] 首页能输入查询并看到推荐结果
- [ ] 快捷提示能快速填充
- [ ] TabBar 三个标签页正常切换
- [ ] 匿名 ID 生成并持久化（重启不丢失）
- [ ] 定位开关能获取当前位置
- [ ] 中文显示正常
