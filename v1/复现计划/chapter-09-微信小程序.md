# 第 9 章：微信小程序 MVP 接入

## 本章定位

本章不是把微信小程序做成完整上线产品，而是完成一个适合简历展示的 **小程序 MVP 接入**：

- 能在微信开发者工具中打开 `miniprogram/`
- 能用原生小程序基础 JS 开发
- 能请求后端 `/api/recommend`
- 能展示推荐卡片
- 能生成并持久化匿名身份
- 能预留 `wx.login()` 登录入口，用于后续收藏、用户画像、行为绑定

对这个项目来说，小程序端的价值是证明你具备 **多端接入能力**。核心亮点仍然是后端推荐系统：

`规则召回/初排 -> DeepSeek rerank -> 白名单防幻觉 -> 结构化推荐结果 -> 行为埋点/收藏/反馈`

所以本章目标是“小程序能跑通主链路”，不是追求复杂页面和完整商业化功能。

---

## 当前项目状态

你已经新增了微信小程序目录：

```text
miniprogram/
├── app.js
├── app.json
├── app.wxss
├── project.config.json
├── project.private.config.json
├── sitemap.json
├── pages/
│   ├── index/
│   │   ├── index.js
│   │   ├── index.wxml
│   │   ├── index.wxss
│   │   └── index.json
│   └── logs/
│       ├── logs.js
│       ├── logs.wxml
│       ├── logs.wxss
│       └── logs.json
└── utils/
    └── util.js
```

这是微信开发者工具生成的基础 JS 模板。第 9 章建议在这个模板上改造，而不是重新创建项目。

---

## 本章最终效果

完成后，小程序首页应支持：

1. 输入自然语言需求，例如：
   - `清水河，预算25，一个人想吃清淡的`
   - `龙湖附近，想吃米线`
   - `晚上夜宵，重口一点`
2. 点击“生成推荐”
3. 调用后端 `/api/recommend`
4. 展示 `deepseek_rerank` 或规则推荐返回的 `recommendations`
5. 每张推荐卡片展示：
   - 店名
   - 推荐理由
   - 匹配度
   - 校区/区域
   - 人均价格
6. 匿名 ID 存入 `wx.StorageSync`，后续埋点、收藏、登录绑定都能复用

---

## 技术路线

| 模块 | 技术 |
|---|---|
| 小程序类型 | 原生微信小程序 |
| 开发语言 | JavaScript |
| 页面模板 | WXML |
| 样式 | WXSS |
| 网络请求 | `wx.request` |
| 本地存储 | `wx.getStorageSync` / `wx.setStorageSync` |
| 登录预留 | `wx.login()` |
| 后端接口 | FastAPI |
| 推荐主接口 | `/api/recommend` |

不使用 TypeScript，不引入 Taro/uni-app/Vant，小程序端保持轻量。

---

## Step 1：确认项目配置

当前 `miniprogram/project.config.json` 已经存在。用微信开发者工具导入时，直接选择：

```text
C:\Users\Jianing\Desktop\CampusFoodAgent\miniprogram
```

注意：因为 `project.config.json` 在 `miniprogram/` 内，所以这里导入 `miniprogram` 目录即可，不需要选择仓库根目录。

`appid` 已经在配置文件中存在。如果后续只是本地学习和简历演示，也可以继续使用当前测试 AppID。

---

## Step 2：调整 app.json

基础模板里的页面只有：

```json
{
  "pages": [
    "pages/index/index",
    "pages/logs/logs"
  ]
}
```

第 9 章 MVP 阶段建议只保留首页即可，`logs` 可以保留为模板页，也可以后面删除。

推荐配置：

```json
{
  "pages": [
    "pages/index/index",
    "pages/logs/logs"
  ],
  "window": {
    "navigationBarTextStyle": "black",
    "navigationBarTitleText": "成电吃什么",
    "navigationBarBackgroundColor": "#f7f2e6",
    "backgroundColor": "#faf6f0"
  },
  "style": "v2",
  "componentFramework": "glass-easel",
  "sitemapLocation": "sitemap.json",
  "lazyCodeLoading": "requiredComponents"
}
```

不建议本章就做 TabBar。TabBar 意味着你要同时维护“首页/商家推荐/我的”等多个页面，会分散精力。

---

## Step 3：新增配置文件

建议新增：

```text
miniprogram/utils/config.js
```

用途：集中管理后端地址。

```javascript
const DEV_BASE_URL = "http://127.0.0.1:8000";
const PROD_BASE_URL = "https://your-backend-domain.example.com";

const API_BASE_URL = DEV_BASE_URL;

module.exports = {
  API_BASE_URL,
  DEV_BASE_URL,
  PROD_BASE_URL,
};
```

开发阶段如果请求本地后端，需要在微信开发者工具中勾选：

```text
详情 -> 本地设置 -> 不校验合法域名、web-view、TLS 版本以及 HTTPS 证书
```

真机调试时，手机访问不到电脑的 `127.0.0.1`，需要换成公网后端、局域网 IP 或内网穿透地址。

---

## Step 4：新增匿名身份模块

建议新增：

```text
miniprogram/utils/identity.js
```

核心目标：小程序端和 Web 端一样，也有一个稳定的匿名用户 ID。

```javascript
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
```

这里的设计点可以写进简历或面试讲解：

- 匿名优先，不强制登录
- 登录后再把匿名行为绑定到用户
- Web 与小程序共用同一种身份模型

---

## Step 5：新增 API 封装

建议新增：

```text
miniprogram/utils/api.js
```

```javascript
const { API_BASE_URL } = require("./config");
const identity = require("./identity");

function request(method, path, data) {
  return new Promise((resolve, reject) => {
    const headers = {
      "Content-Type": "application/json; charset=utf-8",
      "Accept": "application/json",
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
        const detail = res.data && (res.data.detail || res.data.error);
        reject(new Error(detail || `HTTP ${res.statusCode}`));
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

module.exports = {
  fetchRecommendations,
  addFavorite,
};
```

本章只要求 `fetchRecommendations()` 跑通。`addFavorite()` 可以先预留，等微信登录 token 跑通后再启用。

---

## Step 6：改造首页

把模板首页从“Hello World + 头像昵称”改成推荐页。

首页数据状态建议：

```javascript
data: {
  query: "",
  loading: false,
  error: "",
  answer: "",
  recommendations: [],
}
```

首页核心事件：

```javascript
onQueryInput(e) {
  this.setData({ query: e.detail.value });
}

onQuickPrompt(e) {
  this.setData({ query: e.currentTarget.dataset.text });
}

async onSubmit() {
  const query = this.data.query.trim();
  if (!query) return;

  this.setData({
    loading: true,
    error: "",
    answer: "",
    recommendations: [],
  });

  try {
    const data = await api.fetchRecommendations(query);
    this.setData({
      answer: data.answer || "",
      recommendations: data.recommendations || [],
    });
  } catch (e) {
    this.setData({ error: e.message || "推荐失败" });
  } finally {
    this.setData({ loading: false });
  }
}
```

小程序 WXML 中推荐卡片重点显示结构化结果：

```xml
<view class="shop-card" wx:for="{{recommendations}}" wx:key="name">
  <view class="shop-header">
    <text class="shop-name">{{item.name}}</text>
    <text class="score" wx:if="{{item.match_score}}">
      {{item.match_score * 100}}%
    </text>
  </view>
  <text class="reason">{{item.reason}}</text>
  <view class="meta-row">
    <text wx:if="{{item.campus}}">{{item.campus}}</text>
    <text wx:if="{{item.area}}">{{item.area}}</text>
    <text wx:if="{{item.avg_price}}">人均 ¥{{item.avg_price}}</text>
  </view>
</view>
```

注意：小程序模板里直接做复杂表达式能力有限。如果匹配度显示格式不理想，可以在 JS 里提前把 `match_score` 转成 `matchPercent`。

---

## Step 7：微信登录预留

Web 端不应该让用户手动粘贴 `wx.login()` code；真正的微信登录应该放在小程序端。

本章可以先预留一个登录函数：

```javascript
loginWithWechat() {
  wx.login({
    success: async (res) => {
      if (!res.code) {
        wx.showToast({ title: "登录失败", icon: "none" });
        return;
      }

      // 后续调用后端 /api/auth/wechat-login
      // body: { code: res.code, anonymousId }
    },
  });
}
```

是否本章必须完成登录？

不必须。

为了简历项目，本章最低标准是推荐主链路跑通。登录可以作为“后续增强”：

- 登录成功后拿 JWT
- 收藏接口带 Authorization
- 匿名行为绑定到 user_id
- 构建长期用户画像

---

## Step 8：收藏按钮策略

小程序推荐卡片可以先显示收藏按钮，但要注意：

- 未登录时点击收藏：提示“请先微信登录”
- 已登录时：调用 `/api/v1/favorites`
- 收藏不是本章最核心目标，推荐主链路优先

推荐逻辑：

```javascript
onFavoriteTap(e) {
  const item = e.currentTarget.dataset.item;
  const token = identity.getAuthToken();

  if (!token) {
    wx.showToast({ title: "请先微信登录", icon: "none" });
    return;
  }

  api.addFavorite(item.shop_id || item.id, item.name);
}
```

---

## Step 9：运行方式

1. 启动后端：

```bash
cd backend
uvicorn app.main:app --reload --port 8000
```

2. 打开微信开发者工具
3. 导入项目，选择：

```text
C:\Users\Jianing\Desktop\CampusFoodAgent\miniprogram
```

4. 开发阶段勾选“不校验合法域名”
5. 在首页输入：

```text
清水河，预算25，一个人想吃清淡的
```

6. 看到推荐卡片即通过本章

---

## 常见坑

| 问题 | 原因 | 解决 |
|---|---|---|
| `request:fail url not in domain list` | 小程序默认要求合法 HTTPS 域名 | 开发者工具勾选“不校验合法域名” |
| 真机访问不了 `127.0.0.1` | 手机的 localhost 不是电脑 | 使用公网后端、局域网 IP 或内网穿透 |
| 收藏接口 401 | 没有 JWT token | 先完成微信登录，或本章只做收藏按钮预留 |
| 推荐结果没有卡片 | 后端处于 `deepseek_api` 模式，只返回自由文本 | 推荐使用 `RECOMMEND_PROVIDER=deepseek_rerank` |
| 显示原始 JSON | 后端把 LLM 原文塞进 `answer` | rerank 模式应返回空 `answer` + 结构化 `recommendations` |

---

## 章末检查

- [ ] 微信开发者工具能打开 `miniprogram/`
- [ ] 首页不再是模板 `Hello World`
- [ ] 首页能输入自然语言需求
- [ ] 能请求后端 `/api/recommend`
- [ ] 能展示推荐卡片
- [ ] 匿名 ID 能写入并从 `wx.StorageSync` 读取
- [ ] `deepseek_rerank` 模式下不会显示原始 JSON
- [ ] 收藏按钮可以预留，未登录时有清晰提示

---

## 简历表述建议

本章完成后，可以在简历里写：

> 支持 Web 与微信小程序双端接入：Web 端用于完整 Demo 展示，小程序端基于原生 JavaScript 实现推荐主链路 MVP，复用后端推荐接口、匿名身份体系与后续微信登录扩展能力。

不要把小程序包装成“已完整上线的商业产品”。更准确的说法是：

> 微信小程序端 MVP 接入

这既真实，也足够体现工程能力。
