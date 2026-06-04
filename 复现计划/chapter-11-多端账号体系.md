# 第 11 章：多端账号体系升级

## 本章定位

这一章是在已有认证系统上的增强设计，目标是让项目从“只有小程序微信登录”升级为更完整的多端账号体系：

```text
Web 端：邮箱注册 / 邮箱登录
小程序端：微信 wx.login
统一：JWT 鉴权
后续：微信账号可以绑定邮箱账号
```

这个设计非常适合简历项目，因为它能体现你不只是会写一个登录接口，而是理解 **多端身份统一、账号绑定、JWT 鉴权、用户数据归属** 这些真实工程问题。

本章不追求复杂的邮箱验证码、找回密码、OAuth 扫码登录。先做一个清晰、可运行、可讲明白的版本。

---

## 为什么要做邮箱登录

当前项目中，小程序可以通过 `wx.login()` 登录，但 Web 端如果也想使用收藏、反馈、用户画像，就需要一个 Web 可用的登录方式。

不推荐 Web 端继续使用“粘贴微信 login code”的方式，因为：

- 普通 Web 用户拿不到 `wx.login()` code
- 这是开发调试手段，不是正式产品交互
- Web 端和小程序端的登录方式应该各自符合平台习惯

因此，Web 端更适合使用：

```text
邮箱 + 密码
```

小程序端继续使用：

```text
wx.login -> 后端换 openid -> 哈希 openid -> 签发 JWT
```

---

## 最终目标

完成后，系统应支持：

1. Web 用户可以用邮箱注册
2. Web 用户可以用邮箱登录
3. 登录成功后后端签发 JWT
4. Web 前端保存 JWT
5. Web 收藏接口可以正常使用
6. 小程序端继续使用微信登录
7. 收藏、反馈、用户行为都统一归属到 `user_id`
8. 后续支持“微信账号绑定邮箱账号”

用户身份演进如下：

```text
匿名访问
  -> Web 邮箱注册/登录
  -> 获得 email user_id
  -> JWT 访问收藏/反馈/画像

匿名访问
  -> 小程序 wx.login
  -> 获得 wechat user_id
  -> JWT 访问收藏/反馈/画像

后续增强
  -> 微信 user_id 绑定 email user_id
  -> 两端数据合并
```

---

## 推荐架构

推荐使用两张表，而不是把所有字段塞进一张 users 表。

### users

保存系统内部用户。

```sql
CREATE TABLE IF NOT EXISTS users (
    id              TEXT PRIMARY KEY,
    email           TEXT UNIQUE,
    password_hash   TEXT,
    created_at      TEXT DEFAULT (datetime('now')),
    updated_at      TEXT DEFAULT (datetime('now'))
);
```

说明：

- `id` 是系统内部统一用户 ID
- 邮箱用户和微信用户最终都应该归属到一个内部 `user_id`
- `password_hash` 只能存哈希，不能存明文密码

### wechat_identities

保存微信身份和内部用户的绑定关系。

```sql
CREATE TABLE IF NOT EXISTS wechat_identities (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id         TEXT NOT NULL,
    openid_hash     TEXT NOT NULL UNIQUE,
    created_at      TEXT DEFAULT (datetime('now')),
    FOREIGN KEY(user_id) REFERENCES users(id)
);
```

说明：

- 不保存原始 openid
- 继续使用当前项目里的 `sha256(salt:openid)[:24]` 思路
- `openid_hash -> user_id` 代表微信身份绑定到哪个系统用户

---

## 简化版也可以

如果你想先快速实现，也可以用一张表：

```sql
CREATE TABLE IF NOT EXISTS users (
    id              TEXT PRIMARY KEY,
    email           TEXT UNIQUE,
    password_hash   TEXT,
    openid_hash     TEXT UNIQUE,
    created_at      TEXT DEFAULT (datetime('now')),
    updated_at      TEXT DEFAULT (datetime('now'))
);
```

但更推荐两张表，因为后面如果增加 QQ、GitHub、手机号登录，两张表结构更容易扩展。

推荐简历项目采用：

```text
users + wechat_identities
```

这更像真实系统。

---

## 后端接口设计

### 邮箱注册

```text
POST /api/auth/email-register
```

请求：

```json
{
  "email": "student@example.com",
  "password": "12345678",
  "anonymousId": "anon_xxx"
}
```

响应：

```json
{
  "access_token": "jwt...",
  "token_type": "Bearer",
  "expires_in": 604800,
  "userId": "usr_xxx",
  "anonymousId": "anon_xxx"
}
```

注册成功后可以做两件事：

- 签发 JWT
- 把匿名行为事件绑定到 `user_id`

### 邮箱登录

```text
POST /api/auth/email-login
```

请求：

```json
{
  "email": "student@example.com",
  "password": "12345678",
  "anonymousId": "anon_xxx"
}
```

响应同注册接口。

### 当前用户

继续复用已有接口：

```text
GET /api/auth/me
```

用于前端刷新页面后确认 token 是否有效。

### 微信登录

继续复用已有接口：

```text
POST /api/auth/wechat-login
```

小程序端调用，不再让 Web 端粘贴 code。

### 绑定邮箱

后续增强：

```text
POST /api/auth/bind-email
```

请求：

```json
{
  "email": "student@example.com",
  "password": "12345678"
}
```

要求：

- 必须已登录
- 当前 JWT 代表微信用户
- 后端校验邮箱密码
- 校验成功后把微信身份绑定到邮箱用户
- 合并收藏、反馈、行为数据

这个接口可以后面再做，不是第一阶段必须完成。

---

## 密码存储要求

即使是学习项目，也不要明文存密码。

最低要求：

```text
password -> salt -> hash -> password_hash
```

可选方案：

1. 使用 Python 标准库 `hashlib.pbkdf2_hmac`
2. 使用 `passlib[bcrypt]`

为了少引依赖，可以先使用标准库：

```text
hash = pbkdf2_hmac("sha256", password, salt, iterations)
```

存储格式可以设计成：

```text
pbkdf2_sha256$iterations$salt$hash
```

登录时：

1. 读取 `password_hash`
2. 解析 salt 和迭代次数
3. 对用户输入密码重新计算 hash
4. 使用常量时间比较

---

## Web 前端改造

Web 端需要新增一个简单登录面板。

推荐最小功能：

- 邮箱输入框
- 密码输入框
- 注册按钮
- 登录按钮
- 登录状态显示
- 登出按钮

登录成功后：

- 保存 `access_token`
- 保存 `userId`
- 保存过期时间
- 收藏按钮自动可用

Web 的身份状态可以继续复用当前 `identity.ts` 的思路：

```text
anonymousId 始终存在
accessToken 有值表示已登录
userId 有值表示当前登录用户
```

---

## 小程序端改造

小程序端短期不需要邮箱登录。

小程序继续使用：

```text
wx.login -> /api/auth/wechat-login -> JWT
```

后续可以在“我的”页面提供：

```text
绑定邮箱
```

流程：

1. 用户已经微信登录
2. 输入邮箱和密码
3. 调 `/api/auth/bind-email`
4. 后端把当前微信身份绑定到邮箱账号
5. 以后 Web 和小程序可以共享同一个 `user_id`

---

## 用户数据归属

项目里这些表都应该使用统一的 `user_id`：

- `user_favorites`
- `feedback_submissions`
- `usage_events`
- `user_preference_profiles`

这样无论用户来自 Web 还是小程序，最终都能进入同一个画像体系。

如果未来做账号绑定，需要考虑数据合并：

```text
wechat_user_id -> email_user_id
```

合并动作包括：

- 收藏迁移
- 反馈归属更新
- 行为事件归属更新
- 用户画像重新计算

---

## 实现顺序

推荐按这个顺序做：

1. 新增 `users` 表
2. 新增密码哈希服务
3. 新增邮箱注册接口
4. 新增邮箱登录接口
5. Web 端加登录面板
6. Web 收藏功能接入真实 token
7. 小程序微信登录继续保留
8. 新增 `wechat_identities` 表
9. 调整微信登录，让微信身份归属到 `users.id`
10. 后续再做微信绑定邮箱

第一阶段只做到第 6 步就已经很有价值。

---

## 第一阶段完成标准

- [ ] Web 可以邮箱注册
- [ ] Web 可以邮箱登录
- [ ] 登录成功后可以收藏店铺
- [ ] 刷新页面后 token 仍然有效
- [ ] 后端不存明文密码
- [ ] 小程序微信登录不受影响
- [ ] 所有受保护接口继续通过 JWT 鉴权

---

## 第二阶段完成标准

- [ ] 小程序微信登录用户也写入 `users`
- [ ] `wechat_identities` 能记录 openid_hash 与 user_id 关系
- [ ] 已登录微信用户可以绑定邮箱
- [ ] 绑定后 Web 和小程序共享收藏数据
- [ ] 匿名行为可以合并到登录用户

---

## 简历表述

可以写：

> 设计多端统一身份体系：Web 端支持邮箱注册登录，小程序端支持微信 `wx.login`，后端统一签发 JWT，收藏、反馈、行为事件与用户画像通过 `user_id` 聚合；预留微信账号与邮箱账号绑定能力，实现多端身份融合。

如果只完成第一阶段，也可以写：

> 实现 Web 邮箱账号体系与 JWT 鉴权，支持登录后收藏、反馈和用户行为记录；小程序端保留微信登录入口，账号绑定能力按 `users + wechat_identities` 模型预留。

---

## 架构评价

这个方案是可行的，而且比“Web 游客登录”更适合简历。

原因：

- 邮箱登录是 Web 用户最容易理解的登录方式
- 小程序微信登录符合小程序平台习惯
- JWT 统一鉴权能让多端共享后端能力
- 账号绑定体现了真实产品的身份融合设计
- 不做邮箱验证码也合理，学习项目可以先把主链路跑通

注意边界：

- 不要声称已经做了完整账号安全体系
- 不要明文存密码
- 不要把微信 openid 原文入库
- 邮箱验证、找回密码、风控可以作为后续增强
