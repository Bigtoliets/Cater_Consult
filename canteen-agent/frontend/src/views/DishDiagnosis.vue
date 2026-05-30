<template>
  <div class="dish-diagnosis">
    <div class="page-header">
      <h3>🔍 菜品单项诊断</h3>
      <el-input
        v-model="dishId"
        placeholder="输入菜品ID"
        style="width: 200px"
        @keyup.enter="loadDiagnosis"
      >
        <template #append>
          <el-button @click="loadDiagnosis" :loading="loading">查询</el-button>
        </template>
      </el-input>
    </div>

    <div v-if="diagnosis" v-loading="loading">
      <el-card shadow="hover" style="margin-bottom: 16px">
        <template #header>📋 基础信息</template>
        <el-descriptions :column="3" border size="small">
          <el-descriptions-item label="菜品名称">{{ diagnosis.dish?.name || '-' }}</el-descriptions-item>
          <el-descriptions-item label="所属档口">{{ diagnosis.stall?.name || '-' }}</el-descriptions-item>
          <el-descriptions-item label="当班主厨">{{ diagnosis.chef?.name || '-' }}</el-descriptions-item>
          <el-descriptions-item label="单份成本">¥{{ diagnosis.dish?.unit_cost || '0.00' }}</el-descriptions-item>
          <el-descriptions-item label="当日评价">{{ diagnosis.today_stats?.total_reviews || 0 }} 条</el-descriptions-item>
          <el-descriptions-item label="当日差评率">
            <el-tag :type="(diagnosis.today_stats?.negative_rate || 0) > 0.05 ? 'danger' : 'success'">
              {{ ((diagnosis.today_stats?.negative_rate || 0) * 100).toFixed(1) }}%
            </el-tag>
          </el-descriptions-item>
        </el-descriptions>
      </el-card>

      <el-card shadow="hover" style="margin-bottom: 16px" v-if="diagnosis.diagnosis">
        <template #header>🧠 AI 改进摘要</template>
        <el-alert
          :title="diagnosis.diagnosis.summary || '暂无一句话摘要'"
          :type="diagnosis.diagnosis.human_review_required ? 'error' : 'warning'"
          :closable="false"
          show-icon
          style="margin-bottom: 16px"
        />
        <div class="improvement-detail" v-html="renderMarkdown(diagnosis.diagnosis.corrective_action || '暂无详细分析')" />
        <div class="action-buttons">
          <el-button type="primary" @click="handleDispatch">下发至后厨</el-button>
          <el-button @click="handleReject">驳回/忽略</el-button>
          <el-button type="success" :icon="Star" @click="handlePromote" :loading="promoting" :disabled="!diagnosis.diagnosis.decision_id">
            设为金标
          </el-button>
        </div>
      </el-card>

      <el-card shadow="hover">
        <template #header>🗣️ 评价列表（共{{ diagnosis.reviews?.length || 0 }}条）</template>
        <div v-if="diagnosis.reviews?.length">
          <div v-for="(review, idx) in diagnosis.reviews" :key="idx" class="review-item">
            <el-tag
              :type="review.sentiment === 'negative' ? 'danger' : review.sentiment === 'positive' ? 'success' : 'info'"
              size="small"
              style="margin-right: 8px"
            >
              {{ review.sentiment === 'negative' ? '差评' : review.sentiment === 'positive' ? '好评' : '中性' }}
            </el-tag>
            <span v-html="highlightKeywords(review.raw_text)" />
            <span v-if="review.reviewed_at" class="review-time">{{ review.reviewed_at }}</span>
          </div>
        </div>
        <el-empty v-else description="暂无评价" />
      </el-card>
    </div>

    <el-empty v-else description="请输入菜品ID查询诊断报告" />
  </div>
</template>

<script setup>
import { ref } from "vue";
import { getDishDiagnosis, dispatchDiagnosis, rejectDiagnosis, promoteDecision } from "../api";
import { marked } from "marked";
import { Star } from "@element-plus/icons-vue";
import { ElMessage } from "element-plus";

const dishId = ref("");
const diagnosis = ref(null);
const loading = ref(false);
const promoting = ref(false);

async function loadDiagnosis() {
  if (!dishId.value) return;
  loading.value = true;
  try {
    const res = await getDishDiagnosis(dishId.value);
    diagnosis.value = res.data;
  } catch (e) {
    ElMessage.error("查询失败：" + e.message);
  } finally {
    loading.value = false;
  }
}

function highlightKeywords(text) {
  if (!text) return "";
  const keywords = ["太咸", "太淡", "太硬", "咬不动", "不熟", "太油", "异物", "拉肚子", "不新鲜", "太贵", "分量少"];
  let result = text;
  keywords.forEach(kw => {
    result = result.replace(new RegExp(kw, "g"), `<span class="keyword-highlight">${kw}</span>`);
  });
  return result;
}

function renderMarkdown(text) {
  if (!text) return "";
  return marked(text);
}

async function handleDispatch() {
  await dispatchDiagnosis(dishId.value);
  ElMessage.success("整改单已下发至后厨");
}

async function handleReject() {
  await rejectDiagnosis(dishId.value);
  ElMessage.info("整改单已驳回");
}

async function handlePromote() {
  const decisionId = diagnosis.value?.diagnosis?.decision_id;
  if (!decisionId) { ElMessage.warning("该诊断报告缺少决策ID"); return; }
  promoting.value = true;
  try {
    const res = await promoteDecision(decisionId);
    if (res.data?.status === "promoted") {
      ElMessage.success("🎉 已飞升至金标准库！该方案将作为标杆经验供后续参考");
    } else if (res.data?.status === "not_found") {
      ElMessage.warning("未在经验库中找到该决策");
    }
  } catch (e) {
    ElMessage.error("飞升失败：" + (e.response?.data?.detail || e.message));
  } finally {
    promoting.value = false;
  }
}
</script>

<style scoped>
.page-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 20px;
}
.page-header h3 { margin: 0; }
.review-item {
  padding: 8px 0;
  border-bottom: 1px dashed #ebeef5;
  line-height: 1.6;
  display: flex;
  align-items: flex-start;
}
.review-time {
  margin-left: auto;
  color: #909399;
  font-size: 12px;
  white-space: nowrap;
}
:deep(.keyword-highlight) {
  color: #f56c6c;
  font-weight: bold;
  background: #fef0f0;
  padding: 0 2px;
}
.improvement-detail {
  background: #fafafa;
  padding: 16px;
  border-radius: 4px;
  line-height: 1.8;
  margin-bottom: 16px;
}
.action-buttons { display: flex; gap: 12px; }
</style>
