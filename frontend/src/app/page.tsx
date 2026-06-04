"use client";

import { useEffect, useRef, useState } from "react";
import {
  addFavorite,
  emailLogin,
  emailRegister,
  fetchFavorites,
  fetchRankings,
  fetchRecommendations,
  fetchStoreSuggestions,
  removeFavorite,
} from "@/lib/api";
import { getAuthToken, getIdentity, logoutIdentity, upgradeIdentity } from "@/lib/identity";
import Link from "next/link";
import FeedbackPanel from "@/components/FeedbackPanel";

export default function Home() {
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(false);
  const [results, setResults] = useState<any[]>([]);
  const [answer, setAnswer] = useState("");
  const [error, setError] = useState("");
  const [feedbackOpen, setFeedbackOpen] = useState(false);
  const [rankings, setRankings] = useState<any[]>([]);
  const [suggestions, setSuggestions] = useState<string[]>([]);
  const [showSuggestions, setShowSuggestions] = useState(false);
  const [favIds, setFavIds] = useState<Set<number>>(new Set());
  const [favLoading, setFavLoading] = useState<Set<number>>(new Set());
  const [showLogin, setShowLogin] = useState(false);
  const [loginMode, setLoginMode] = useState<"login" | "register">("login");
  const [loginEmail, setLoginEmail] = useState("");
  const [loginPassword, setLoginPassword] = useState("");
  const [loginError, setLoginError] = useState("");
  const [loginLoading, setLoginLoading] = useState(false);
  const [loggedInUserId, setLoggedInUserId] = useState<string | null>(null);
  const suggestTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const getShopId = (item: any): number | null => {
    const raw = item.shop_id ?? item.shopId ?? item.id;
    const id = Number(raw);
    return Number.isFinite(id) ? id : null;
  };

  const getScore = (item: any): number | null => {
    const raw = item.score ?? item.match_score;
    const score = Number(raw);
    return Number.isFinite(score) ? score : null;
  };

  // 首页加载热门排行 + 已收藏列表 + 登录状态
  useEffect(() => {
    fetchRankings()
      .then((d: any) => setRankings(d.items || []))
      .catch(() => {});
    const id = getIdentity();
    if (id.userId) {
      setLoggedInUserId(id.userId);
      loadFavorites();
    }
  }, []);

  // 加载用户已收藏的店铺 ID 列表
  const loadFavorites = async () => {
    try {
      const data: any = await fetchFavorites();
      const ids: number[] = (data.favorites || []).map((f: any) => f.shop_id);
      setFavIds(new Set(ids));
    } catch {
      // 未登录或网络错误，收藏列表为空
    }
  };

  const handleToggleFavorite = async (shopId: number | null, shopName: string) => {
    setError("");
    if (!getAuthToken()) {
      setError("收藏需要先登录。请点击下方「登录」按钮注册或登录。");
      return;
    }
    if (shopId == null) {
      setError("当前推荐结果缺少店铺 ID，暂时不能收藏。");
      return;
    }
    if (favLoading.has(shopId)) return;
    setFavLoading((prev) => new Set(prev).add(shopId));
    try {
      if (favIds.has(shopId)) {
        await removeFavorite(shopId);
        setFavIds((prev) => {
          const next = new Set(prev);
          next.delete(shopId);
          return next;
        });
      } else {
        await addFavorite(shopId, shopName);
        setFavIds((prev) => new Set(prev).add(shopId));
      }
    } catch (e: any) {
      setError(e.message);
    } finally {
      setFavLoading((prev) => {
        const next = new Set(prev);
        next.delete(shopId);
        return next;
      });
    }
  };

  const handleSubmit = async () => {
    if (!query.trim()) return;
    setLoading(true);
    setError("");
    try {
      const data: any = await fetchRecommendations(query);
      setAnswer(data.answer || "");
      setResults(data.recommendations || []);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  };

  // 店名自动补全（输入时触发）
  const handleQueryChange = (value: string) => {
    setQuery(value);
    if (suggestTimer.current) clearTimeout(suggestTimer.current);
    if (value.trim().length < 2) {
      setSuggestions([]);
      setShowSuggestions(false);
      return;
    }
    suggestTimer.current = setTimeout(async () => {
      try {
        const data = await fetchStoreSuggestions(value);
        setSuggestions(data.suggestions || []);
        setShowSuggestions((data.suggestions || []).length > 0);
      } catch {
        setSuggestions([]);
        setShowSuggestions(false);
      }
    }, 250);
  };

  const handleSuggestionClick = (name: string) => {
    setQuery(name);
    setShowSuggestions(false);
  };

  // ---- 邮箱登录/注册 ----
  const openLogin = (mode: "login" | "register") => {
    setLoginMode(mode);
    setLoginEmail("");
    setLoginPassword("");
    setLoginError("");
    setShowLogin(true);
  };

  const closeLogin = () => {
    setShowLogin(false);
    setLoginEmail("");
    setLoginPassword("");
    setLoginError("");
  };

  const handleLoginSubmit = async () => {
    if (!loginEmail.trim() || !loginPassword.trim()) {
      setLoginError("请填写邮箱和密码");
      return;
    }
    setLoginLoading(true);
    setLoginError("");
    try {
      const id = getIdentity();
      const fn = loginMode === "register" ? emailRegister : emailLogin;
      const data: any = await fn(loginEmail.trim(), loginPassword, id.anonymousId);
      upgradeIdentity(data.access_token, data.userId, data.expires_in);
      setLoggedInUserId(data.userId);
      closeLogin();
      loadFavorites();
    } catch (e: any) {
      setLoginError(e.message || "操作失败");
    } finally {
      setLoginLoading(false);
    }
  };

  const handleLogout = () => {
    logoutIdentity();
    setLoggedInUserId(null);
    setFavIds(new Set());
    setError("");
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
        <div className="search-wrapper">
          <textarea
            value={query}
            onChange={(e) => handleQueryChange(e.target.value)}
            placeholder="说说你的需求，比如：清水河，预算25，一个人想吃清淡的..."
            rows={3}
            onKeyDown={(e) => {
              if ((e.metaKey || e.ctrlKey) && e.key === "Enter") handleSubmit();
            }}
          />
          {showSuggestions && (
            <ul className="suggestions-dropdown">
              {suggestions.map((s) => (
                <li key={s} onClick={() => handleSuggestionClick(s)}>
                  {s}
                </li>
              ))}
            </ul>
          )}
        </div>

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

        <div className="composer-footer">
          {loggedInUserId ? (
            <>
              <span className="login-status">已登录</span>
              <button className="ghost-btn" onClick={handleLogout}>登出</button>
            </>
          ) : (
            <>
              <button className="ghost-btn" onClick={() => openLogin("login")}>登录</button>
              <button className="ghost-btn" onClick={() => openLogin("register")}>注册</button>
            </>
          )}
          <button className="ghost-btn feedback-trigger" onClick={() => setFeedbackOpen(true)}>
            反馈新店 / 吃后评价
          </button>
          <Link href="/profile" className="ghost-btn" style={{ textDecoration: "none" }}>
            个人中心
          </Link>
        </div>
      </div>

      {/* 登录弹窗 */}
      {showLogin && (
        <div className="modal-overlay" onClick={closeLogin}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <h2>{loginMode === "register" ? "注册" : "登录"}</h2>
            <label className="field-label">邮箱</label>
            <input
              className="field-input"
              type="email"
              value={loginEmail}
              onChange={(e) => setLoginEmail(e.target.value)}
              placeholder="your@email.com"
              onKeyDown={(e) => e.key === "Enter" && handleLoginSubmit()}
            />
            <label className="field-label">密码</label>
            <input
              className="field-input"
              type="password"
              value={loginPassword}
              onChange={(e) => setLoginPassword(e.target.value)}
              placeholder="至少 6 位"
              onKeyDown={(e) => e.key === "Enter" && handleLoginSubmit()}
            />
            {loginError && <p className="error-text">{loginError}</p>}
            <div className="modal-actions">
              <button className="ghost-btn" onClick={closeLogin}>取消</button>
              <button
                className="gold-btn"
                style={{ width: "auto", marginTop: 0, padding: "8px 20px" }}
                onClick={handleLoginSubmit}
                disabled={loginLoading}
              >
                {loginLoading ? "处理中..." : loginMode === "register" ? "注册" : "登录"}
              </button>
            </div>
            <p className="login-switch">
              {loginMode === "login" ? (
                <>没有账号？<button className="link-btn" onClick={() => setLoginMode("register")}>去注册</button></>
              ) : (
                <>已有账号？<button className="link-btn" onClick={() => setLoginMode("login")}>去登录</button></>
              )}
            </p>
          </div>
        </div>
      )}

      {/* 错误 */}
      {error && <div className="error-card">{error}</div>}

      {/* 文本回答 */}
      {answer && <div className="answer-card">{answer}</div>}

      {/* 加载骨架 */}
      {loading && (
        <div className="results-panel">
          {[1, 2, 3].map((i) => (
            <div key={i} className="shop-card skeleton-card">
              <div className="skeleton skeleton-title" />
              <div className="skeleton skeleton-text" />
              <div className="skeleton skeleton-text short" />
            </div>
          ))}
        </div>
      )}

      {/* 推荐卡片 */}
      {!loading && results.length > 0 && (
        <div className="results-panel">
          {results.map((r: any, i: number) => {
            const shopId = getShopId(r);
            const score = getScore(r);
            const isFavorite = shopId != null && favIds.has(shopId);
            const isSaving = shopId != null && favLoading.has(shopId);

            return (
              <div key={`${r.name || "shop"}-${i}`} className="shop-card">
                <div className="shop-card-header">
                  <div className="shop-card-title">
                    <button
                      className={`fav-btn ${isFavorite ? "active" : ""}`}
                      onClick={() => handleToggleFavorite(shopId, r.name)}
                      disabled={isSaving}
                      title={isFavorite ? "取消收藏" : "收藏"}
                      aria-label={isFavorite ? "取消收藏" : "收藏"}
                    >
                      <span className="fav-icon">{isFavorite ? "★" : "☆"}</span>
                      <span>{isFavorite ? "已收藏" : "收藏"}</span>
                    </button>
                    <h3>{r.name}</h3>
                  </div>
                  {score != null && (
                    <span className="score-badge">匹配度 {(score * 100).toFixed(0)}%</span>
                  )}
                </div>
                <p className="shop-reason">{r.reason}</p>
                <div className="shop-meta">
                  {r.campus && <span className="shop-tag">{r.campus}</span>}
                  {r.avg_price != null && (
                    <span className="shop-tag">¥{r.avg_price}</span>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      )}

      {/* 热门排行 */}
      {!loading && results.length === 0 && rankings.length > 0 && (
        <section className="rankings-section">
          <h2 className="section-title">今日热门</h2>
          <div className="rankings-list">
            {rankings.map((item: any) => (
              <div
                key={item.rank}
                className="ranking-item"
                onClick={() => setQuery(item.query || item.name)}
              >
                <span className="ranking-rank">#{item.rank}</span>
                <div className="ranking-info">
                  <span className="ranking-name">{item.name}</span>
                  <span className="ranking-tag">{item.tag}</span>
                </div>
                {item.avg_price != null && (
                  <span className="ranking-price">¥{item.avg_price}</span>
                )}
              </div>
            ))}
          </div>
        </section>
      )}

      {/* 反馈弹窗 */}
      {feedbackOpen && <FeedbackPanel onClose={() => setFeedbackOpen(false)} />}
    </div>
  );
}
