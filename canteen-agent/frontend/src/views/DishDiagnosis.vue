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
      <!-- 基础信息 -->
      <el-card shadow="hover" style="margin-bottom: 16px">
        <template #header>📋 基础信息</template>
        <el-descriptions :column="3" border size="small">
          <el-descriptions-item label="菜品名称">{{ diagnosis.dish?.name || '-' }}</el-descriptions-item>
          <el-descriptions-item label="所属档口">{{ diagnosis.stall?.name || '-' }}</el-descriptions-item>
          <el-descriptions-item label="当班主厨">{{ diagnosis.chef?.name || '-' }}</el-descriptions-item>
          <el-descriptions-item label="单份成本">¥{{ diagnosis.dish?.unit_cost || '0.00' }}</el-descriptions-item>
          <el-descriptions-item label="当日销量">{{ diagnosis.today_stats?.total_reviews || 0 }} 份</el-descriptions-item>
          <el-descriptions-item label="当日差评率">
            <el-tag :type="(diagnosis.today_stats?.negative_rate || 0) > 0.05 ? 'danger' : 'success'">
              {{ ((diagnosis.today_stats?.negative_rate || 0) * 100).toFixed(1) }}%
            </el-tag>
          </el-descriptions-item>
        </el-descriptions>
      </el-card>

      <!-- 客诉原声 -->
      <el-card shadow="hover" style="margin-bottom: 16px">
        <template #header>🗣️ 客诉原声</template>
        <div v-if="diagnosis.negative_reviews?.length">
          <div
            v-for="(review, idx) in diagnosis.negative_reviews"
            :key="idx"
            class="review-item"
            v-html="highlightKeywords(review.raw_text)"
          />
        </div>
        <el-empty v-else description="暂无差评" />
      </el-card>

      <!-- 诊断报告 -->
      <el-card shadow="hover" style="margin-bottom: 16px" v-if="diagnosis.diagnosis">
        <template #header>🧠 AI 智能诊断</template>
        <el-descriptions :column="2" border>
          <el-descriptions-item label="冲突类型">
            <el-tag>{{ diagnosis.diagnosis.conflict_type || '-' }}</el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="置信度">
            <el-progress
              :percentage="(diagnosis.diagnosis.confidence || 0) * 100"
              :color="diagnosis.diagnosis.confidence >= 0.75 ? '#67c23a' : '#e6a23c'"
              :format="() => ((diagnosis.diagnosis.confidence || 0) * 100).toFixed(0) + '%'"
            />
          </el-descriptions-item>
        </el-descriptions>
      </el-card>

      <!-- 整改单 -->
      <el-card shadow="hover" v-if="diagnosis.diagnosis?.corrective_action">
        <template #header>📋 整改单</template>
        <div class="corrective-action" v-html="renderMarkdown(diagnosis.diagnosis.corrective_action)" />
        <div class="action-buttons">
          <el-button type="primary" @click="handleDispatch">下发至后厨</el-button>
          <el-button type="warning" @click="handleModify">修改后下发</el-button>
          <el-button @click="handleReject">驳回/忽略</el-button>
        </div>
      </el-card>
    </div>

    <el-empty v-else description="请输入菜品ID查询诊断报告" />
  </div>
</template>

<script setup>
import { ref } from "vue";
import { getDishDiagnosis, dispatchDiagnosis, rejectDiagnosis } from "../api";
import { marked } from "marked";

const dishId = ref("");
const diagnosis = ref(null);
const loading = ref(false);

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
  const keywords = ["太咸", "太淡", "太硬", "咬不动", "不熟", "火候不够", "分量", "太油", "异物", "拉肚子"];
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

function handleModify() {
  ElMessage.info("修改功能开发中...");
}

import { ElMessage } from "element-plus";
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
}
:deep(.keyword-highlight) {
  color: #f56c6c;
  font-weight: bold;
  background: #fef0f0;
  padding: 0 2px;
}
.corrective-action {
  background: #fafafa;
  padding: 16px;
  border-radius: 4px;
  line-height: 1.8;
  margin-bottom: 16px;
}
.action-buttons { display: flex; gap: 12px; }
</style>
