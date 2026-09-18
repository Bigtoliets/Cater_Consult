import axios from "axios";

const api = axios.create({
  baseURL: "/api/v1",
  timeout: 30000,
});

// ====== 日报 ======
export const getDailySummary = (date) =>
  api.get("/dashboard/summary", { params: { target_date: date } });

export const getSummaryTable = (date) =>
  api.get("/dashboard/summary-table", { params: { target_date: date } });

// ====== 菜品诊断 ======
export const getDishDiagnosis = (dishId) =>
  api.get(`/dishes/${dishId}/diagnosis`);

export const getDishReviews = (dishId, sentiment) =>
  api.get(`/dishes/${dishId}/reviews`, { params: { sentiment } });

export const dispatchDiagnosis = (dishId) =>
  api.post(`/dishes/${dishId}/diagnosis/dispatch`);

export const rejectDiagnosis = (dishId) =>
  api.post(`/dishes/${dishId}/diagnosis/reject`);

export const promoteDecision = (decisionId) =>
  api.post("/config/promote", { decision_id: decisionId });

// ====== 配置 ======
export const getConfigs = (scope, scopeId) =>
  api.get("/config/", { params: { scope, scope_id: scopeId } });

export const updateConfig = (configKey, configValue, scope) =>
  api.put(`/config/${configKey}`, configValue, { params: { scope } });

export const getKeywordWeights = () =>
  api.get("/config/keyword-weights");

export const updateKeywordWeights = (weights) =>
  api.put("/config/keyword-weights", { weights, description: "关键词维度权重" });

// ====== 知识库 ======
export const getDishKnowledge = (dishId, dimension) =>
  api.get(`/config/knowledge/dish/${dishId}`, { params: { dimension } });

export const createSOPEntry = (data) =>
  api.post("/config/knowledge", data);

export const deleteSOPEntry = (entryId) =>
  api.delete(`/config/knowledge/${entryId}`);

// ====== 数据同步 ======
export const syncReviews = (shopId) => {
  const params = shopId ? { shop_id: shopId } : {};
  return api.post("/sync", null, { params });
};

// ====== 店铺 ======
export const getShops = () => api.get("/shops");

// ====== 智能问答 ======
// SSE 流走原生 fetch（axios 不方便读流），这里只放 URL 构造和 turn 状态查询
export const CHAT_QUERY_URL = "/api/v1/chat/query";

export const chatResumeUrl = (turnId, sessionId) =>
  `/api/v1/chat/resume/${turnId}?session_id=${encodeURIComponent(sessionId)}`;

// turn_id / session_id 都由前端生成：断了以后凭它们续跑
// （追踪与恢复的实现见 agent/app/chat/turn_store.py）
export const getChatTurn = (turnId, sessionId) =>
  api.get(`/chat/turns/${turnId}`, { params: { session_id: sessionId } });

export const getPresetQuestions = () =>
  api.get("/chat/presets");

// ====== v3.0: 推送配置 ======
export const getPushConfig = () =>
  api.get("/config/", { params: { scope: "global", config_key: "push_rules" } });

export const updatePushConfig = (rules) =>
  api.put("/config/push_rules", { config_value: rules, description: "推送规则" }, { params: { scope: "global" } });

// ====== v3.0: 反馈追踪 ======
export const getFeedbackRecords = (dishId) =>
  api.get(`/dishes/${dishId}/feedback`);

// ====== 健康检查 ======
export const healthCheck = () =>
  api.get("/health");
