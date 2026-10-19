// pages/index/index.js
const api = require("../../utils/api");
const identity = require("../../utils/identity");

Page({
  data: {
    query: "",
    loading: false,
    error: "",
    answer: "",
    recommendations: [],
    favIds: [],
    favLoadingId: null,
    showLoginTip: false,
  },

  onLoad() {
    if (identity.getAuthToken()) {
      this.loadFavorites();
    }
  },

  buildRecommendationViewModels(recommendations, favIds, favLoadingId) {
    return (recommendations || []).map((r) => {
      const shopId = r.shop_id || r.id;
      return {
        ...r,
        shopId,
        shopName: r.name,
        isFavorite: favIds.includes(shopId),
        isFavLoading: favLoadingId === shopId,
        matchPercent: r.match_score != null ? (r.match_score * 100).toFixed(0) + "%" : "",
      };
    });
  },

  refreshRecommendationFavoriteState(favIds, favLoadingId = this.data.favLoadingId) {
    this.setData({
      favIds,
      recommendations: this.buildRecommendationViewModels(
        this.data.recommendations,
        favIds,
        favLoadingId
      ),
    });
  },

  // ---- 输入 ----
  onQueryInput(e) {
    this.setData({ query: e.detail.value });
  },

  // ---- 快捷提示 ----
  onQuickPrompt(e) {
    this.setData({ query: e.currentTarget.dataset.text });
  },

  // ---- 提交推荐 ----
  async onSubmit() {
    const query = this.data.query.trim();
    if (!query) {
      wx.showToast({ title: "请输入需求", icon: "none" });
      return;
    }

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
        recommendations: this.buildRecommendationViewModels(
          data.recommendations || [],
          this.data.favIds,
          this.data.favLoadingId
        ),
      });
    } catch (e) {
      this.setData({ error: e.message || "推荐失败" });
    } finally {
      this.setData({ loading: false });
    }
  },

  // ---- 加载已收藏列表 ----
  async loadFavorites() {
    try {
      const data = await api.fetchFavorites();
      const ids = (data.favorites || []).map((f) => f.shop_id);
      this.refreshRecommendationFavoriteState(ids);
    } catch (_) {
      // 未登录或网络错误，忽略
    }
  },

  // ---- 收藏切换 ----
  async onToggleFavorite(e) {
    const shopId = Number(e.currentTarget.dataset.shopId);
    const shopName = e.currentTarget.dataset.shopName;
    if (!shopId) return;

    const token = identity.getAuthToken();
    if (!token) {
      this.setData({ showLoginTip: true });
      setTimeout(() => this.setData({ showLoginTip: false }), 2000);
      return;
    }

    this.setData({
      favLoadingId: shopId,
      recommendations: this.buildRecommendationViewModels(this.data.recommendations, this.data.favIds, shopId),
    });

    try {
      if (this.data.favIds.includes(shopId)) {
        await api.removeFavorite(shopId);
        this.refreshRecommendationFavoriteState(this.data.favIds.filter((id) => id !== shopId), shopId);
      } else {
        await api.addFavorite(shopId, shopName);
        this.refreshRecommendationFavoriteState([...this.data.favIds, shopId], shopId);
      }
    } catch (e) {
      wx.showToast({ title: e.message || "操作失败", icon: "none" });
    } finally {
      this.setData({
        favLoadingId: null,
        recommendations: this.buildRecommendationViewModels(this.data.recommendations, this.data.favIds, null),
      });
    }
  },

  // ---- 微信登录 ----
  onLoginTap() {
    wx.login({
      success: async (res) => {
        if (!res.code) {
          wx.showToast({ title: "登录失败", icon: "none" });
          return;
        }
        try {
          const data = await api.wechatLogin(res.code);
          identity.saveAuthenticatedIdentity(data.access_token, data.userId, data.expires_in);
          wx.showToast({ title: "登录成功", icon: "success" });
          this.loadFavorites();
        } catch (e) {
          wx.showToast({ title: e.message || "登录失败", icon: "none", duration: 3000 });
        }
      },
      fail: () => {
        wx.showToast({ title: "wx.login 调用失败", icon: "none" });
      },
    });
  },
});
