"use client";

import { useState } from "react";
import { submitFeedback } from "@/lib/api";
import { getIdentity } from "@/lib/identity";

interface Props {
  onClose: () => void;
}

export default function FeedbackPanel({ onClose }: Props) {
  const [storeName, setStoreName] = useState("");
  const [rating, setRating] = useState(0);
  const [recommendDish, setRecommendDish] = useState("");
  const [comment, setComment] = useState("");
  const [sceneTags, setSceneTags] = useState("");
  const [tasteTags, setTasteTags] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [done, setDone] = useState(false);
  const [error, setError] = useState("");

  const handleSubmit = async () => {
    if (!storeName.trim()) {
      setError("请输入店铺名称");
      return;
    }

    setSubmitting(true);
    setError("");
    try {
      const id = getIdentity();
      await submitFeedback({
        feedbackType: "dining_feedback",
        storeName: storeName.trim(),
        rating: rating || undefined,
        sceneTags: sceneTags.trim() || undefined,
        tasteTags: tasteTags.trim() || undefined,
        recommendDish: recommendDish.trim() || undefined,
        comment: comment.trim() || undefined,
        uid: id.anonymousId,
        anonymousId: id.anonymousId,
        userId: id.userId || undefined,
      });
      setDone(true);
    } catch (e: any) {
      setError(e.message || "提交失败");
    } finally {
      setSubmitting(false);
    }
  };

  if (done) {
    return (
      <div className="modal-overlay" onClick={onClose}>
        <div className="modal" onClick={(e) => e.stopPropagation()}>
          <h2>感谢反馈</h2>
          <p style={{ margin: "16px 0", color: "var(--text-light)" }}>
            你的评价会帮助我们改进推荐结果
          </p>
          <button className="gold-btn" onClick={onClose}>
            关闭
          </button>
        </div>
      </div>
    );
  }

  const starButtons = [];
  for (let i = 1; i <= 5; i++) {
    starButtons.push(
      <button
        key={i}
        type="button"
        className={`star-btn ${i <= rating ? "active" : ""}`}
        onClick={() => setRating(i === rating ? 0 : i)}
        aria-label={`${i}星`}
      >
        {i <= rating ? "★" : "☆"}
      </button>
    );
  }

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <h2>反馈评价</h2>

        <label className="field-label">
          店铺名称 <span className="required">*</span>
        </label>
        <input
          className="field-input"
          value={storeName}
          onChange={(e) => setStoreName(e.target.value)}
          placeholder="如：学子餐厅"
        />

        <label className="field-label">评分</label>
        <div className="star-row">{starButtons}</div>

        <label className="field-label">推荐菜品</label>
        <input
          className="field-input"
          value={recommendDish}
          onChange={(e) => setRecommendDish(e.target.value)}
          placeholder="如：宫保鸡丁"
        />

        <label className="field-label">场景标签（可选，逗号分隔）</label>
        <input
          className="field-input"
          value={sceneTags}
          onChange={(e) => setSceneTags(e.target.value)}
          placeholder="如：一人食，赶时间"
        />

        <label className="field-label">口味标签（可选，逗号分隔）</label>
        <input
          className="field-input"
          value={tasteTags}
          onChange={(e) => setTasteTags(e.target.value)}
          placeholder="如：清淡，少油"
        />

        <label className="field-label">评价留言</label>
        <textarea
          className="field-input"
          value={comment}
          onChange={(e) => setComment(e.target.value)}
          rows={3}
          placeholder="说说你的感受..."
        />

        {error && <p className="error-text">{error}</p>}

        <div className="modal-actions">
          <button className="ghost-btn" onClick={onClose}>
            取消
          </button>
          <button className="gold-btn" onClick={handleSubmit} disabled={submitting}>
            {submitting ? "提交中..." : "提交反馈"}
          </button>
        </div>
      </div>
    </div>
  );
}
