import axios from "axios";

const api = axios.create({
  baseURL: "/api/v1",
  timeout: 30000,
});

export const getDailySummary = (date) =>
  api.get("/dashboard/summary", { params: { target_date: date } });

export const getSummaryTable = (date) =>
  api.get("/dashboard/summary-table", { params: { target_date: date } });

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

export const getConfigs = (scope, scopeId) =>
  api.get("/config/", { params: { scope, scope_id: scopeId } });

export const updateConfig = (configKey, configValue, scope) =>
  api.put(`/config/${configKey}`, configValue, { params: { scope } });

export const getKeywordWeights = () =>
  api.get("/config/keyword-weights");

export const updateKeywordWeights = (weights) =>
  api.put("/config/keyword-weights", { weights, description: "关键词维度权重" });

export const getDishKnowledge = (dishId, dimension) =>
  api.get(`/config/knowledge/dish/${dishId}`, { params: { dimension } });

export const createSOPEntry = (data) =>
  api.post("/config/knowledge", data);

export const uploadPreview = (file) => {
  const formData = new FormData();
  formData.append("file", file);
  return api.post("/upload/preview", formData, {
    headers: { "Content-Type": "multipart/form-data" },
  });
};

export const uploadConfirm = (file, selectedIndices) => {
  const formData = new FormData();
  formData.append("file", file);
  formData.append("selected", JSON.stringify(selectedIndices));
  return api.post("/upload/confirm", formData, {
    headers: { "Content-Type": "multipart/form-data" },
  });
};

export const chatQuery = (question) =>
  api.post("/chat/query", null, { params: { question } });

export const getPresetQuestions = () =>
  api.get("/chat/presets");

export const healthCheck = () =>
  api.get("/health");
