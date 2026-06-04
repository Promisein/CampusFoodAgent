"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { fetchFavorites, getMe, removeFavorite } from "@/lib/api";
import { getAuthToken, getIdentity, logoutIdentity } from "@/lib/identity";

type PageState = "loading" | "not-logged-in" | "logged-in";

interface FavoriteItem {
  id: number;
  shop_id: number;
  shop_name: string;
  created_at: string;
}

export default function ProfilePage() {
  const [pageState, setPageState] = useState<PageState>("loading");
  const [userId, setUserId] = useState("");
  const [accountType, setAccountType] = useState("");
  const [favorites, setFavorites] = useState<FavoriteItem[]>([]);
  const [error, setError] = useState("");
  const [removingId, setRemovingId] = useState<Set<number>>(new Set());

  useEffect(() => {
    loadProfile();
  }, []);

  const loadProfile = async () => {
    setPageState("loading");
    setError("");

    const token = getAuthToken();
    if (!token) {
      setPageState("not-logged-in");
      return;
    }

    try {
      const me: any = await getMe();
      if (!me.authenticated || !me.userId) {
        // token 无效，清理登录态
        logoutIdentity();
        setPageState("not-logged-in");
        return;
      }

      setUserId(me.userId);
      // 账号类型
      if (me.userId.startsWith("em_")) {
        setAccountType("邮箱账号");
      } else if (me.userId.startsWith("wx_")) {
        setAccountType("微信账号");
      } else {
        setAccountType("系统账号");
      }

      // 加载收藏
      try {
        const data: any = await fetchFavorites();
        setFavorites(data.favorites || []);
      } catch {
        setFavorites([]);
      }

      setPageState("logged-in");
    } catch {
      // 网络错误或 token 失效
      logoutIdentity();
      setPageState("not-logged-in");
    }
  };

  const handleRemoveFavorite = async (shopId: number) => {
    setError("");
    setRemovingId((prev) => new Set(prev).add(shopId));
    try {
      await removeFavorite(shopId);
      setFavorites((prev) => prev.filter((f) => f.shop_id !== shopId));
    } catch (e: any) {
      setError(e.message || "取消收藏失败，请稍后再试");
    } finally {
      setRemovingId((prev) => {
        const next = new Set(prev);
        next.delete(shopId);
        return next;
      });
    }
  };

  const handleLogout = () => {
    logoutIdentity();
    setPageState("not-logged-in");
    setFavorites([]);
    setUserId("");
    setAccountType("");
  };

  const formatDate = (dateStr: string) => {
    try {
      const d = new Date(dateStr);
      return d.toLocaleDateString("zh-CN", {
        year: "numeric",
        month: "2-digit",
        day: "2-digit",
      });
    } catch {
      return dateStr;
    }
  };

  // ===== 加载中 =====
  if (pageState === "loading") {
    return (
      <div className="page">
        <header className="hero-card">
          <h1>个人中心</h1>
        </header>
        <div className="profile-card">
          <div className="skeleton skeleton-title" style={{ margin: "0 auto" }} />
          <div className="skeleton skeleton-text" style={{ margin: "12px auto 0" }} />
          <div className="skeleton skeleton-text short" style={{ margin: "8px auto 0" }} />
        </div>
      </div>
    );
  }

  // ===== 未登录 =====
  if (pageState === "not-logged-in") {
    return (
      <div className="page">
        <header className="hero-card">
          <h1>个人中心</h1>
        </header>
        <div className="profile-card">
          <div className="profile-avatar">
            <span className="avatar-placeholder">?</span>
          </div>
          <p className="profile-anon-text">当前为匿名用户</p>
          <p className="profile-hint">
            登录后可同步收藏记录，跨设备查看你的饭馆收藏。
          </p>
          <div className="profile-actions">
            <Link href="/" className="gold-btn" style={{ textDecoration: "none", textAlign: "center" }}>
              去登录
            </Link>
            <Link href="/" className="ghost-btn" style={{ textDecoration: "none", textAlign: "center", display: "inline-block", width: "100%", padding: "10px 24px", fontSize: "15px" }}>
              返回推荐页
            </Link>
          </div>
        </div>
      </div>
    );
  }

  // ===== 已登录 =====
  return (
    <div className="page">
      <header className="hero-card">
        <h1>个人中心</h1>
      </header>

      {/* 账号信息区 */}
      <div className="profile-card">
        <div className="profile-avatar">
          <span className="avatar-placeholder logged-in-avatar">
            {userId.slice(0, 2).toUpperCase()}
          </span>
        </div>
        <div className="profile-info">
          <div className="profile-info-row">
            <span className="profile-label">用户 ID</span>
            <span className="profile-value profile-userid">{userId}</span>
          </div>
          <div className="profile-info-row">
            <span className="profile-label">账号类型</span>
            <span className="profile-badge">{accountType}</span>
          </div>
          <div className="profile-info-row">
            <span className="profile-label">登录状态</span>
            <span className="profile-status">已登录</span>
          </div>
        </div>
        <div className="profile-actions">
          <button className="ghost-btn" onClick={handleLogout}>
            退出登录
          </button>
          <Link href="/" className="ghost-btn" style={{ textDecoration: "none" }}>
            返回推荐页
          </Link>
        </div>
      </div>

      {/* 错误提示 */}
      {error && <div className="error-card">{error}</div>}

      {/* 收藏饭馆区 */}
      <section className="favorites-section">
        <h2 className="section-title">
          我的收藏{favorites.length > 0 ? ` (${favorites.length})` : ""}
        </h2>

        {favorites.length === 0 ? (
          <div className="empty-card">
            <p>还没有收藏饭馆</p>
            <Link href="/" className="ghost-btn" style={{ textDecoration: "none", display: "inline-block", marginTop: "12px" }}>
              去首页推荐
            </Link>
          </div>
        ) : (
          <div className="favorites-list">
            {favorites.map((f) => {
              const isRemoving = removingId.has(f.shop_id);
              return (
                <div key={f.id} className="favorite-item">
                  <div className="favorite-info">
                    <span className="favorite-name">{f.shop_name}</span>
                    <span className="favorite-date">{formatDate(f.created_at)}</span>
                    <span className="favorite-shopid">ID: {f.shop_id}</span>
                  </div>
                  <button
                    className="remove-btn"
                    onClick={() => handleRemoveFavorite(f.shop_id)}
                    disabled={isRemoving}
                  >
                    {isRemoving ? "..." : "取消收藏"}
                  </button>
                </div>
              );
            })}
          </div>
        )}
      </section>
    </div>
  );
}
