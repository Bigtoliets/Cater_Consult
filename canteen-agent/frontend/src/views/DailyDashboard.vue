<template>
  <div class="daily-dashboard">
    <div class="page-header">
      <h3>📊 每日菜品质量日报</h3>
      <el-date-picker
        v-model="selectedDate"
        type="date"
        placeholder="选择日期"
        value-format="YYYY-MM-DD"
      />
    </div>

    <el-row :gutter="20" v-loading="loading">
      <!-- 全局情绪指数 -->
      <el-col :span="10">
        <el-card shadow="hover">
          <template #header>全局情绪指数</template>
          <v-chart :option="sentimentChartOption" style="height: 250px" v-if="summary" />
          <el-empty v-else description="暂无数据" />
          <div class="stats-row" v-if="summary">
            <el-statistic title="总评价数" :value="summary.total_reviews" />
            <el-statistic title="好评率" :value="(summary.positive_rate * 100).toFixed(0) + '%'" />
            <el-statistic title="差评率" :value="(summary.negative_rate * 100).toFixed(0) + '%'" />
          </div>
        </el-card>
      </el-col>

      <!-- 红黑榜 -->
      <el-col :span="14">
        <el-card shadow="hover">
          <template #header>红黑榜</template>
          <el-row :gutter="20">
            <el-col :span="12">
              <h4 style="color: #67c23a">🏆 零差评 TOP3</h4>
              <el-table :data="topGoodList" size="small" v-if="topGoodList.length">
                <el-table-column type="index" label="#" width="40" />
                <el-table-column prop="dish_name" label="菜品名" />
                <el-table-column prop="count" label="好评数" width="80" />
              </el-table>
              <el-empty v-else description="暂无" :image-size="60" />
            </el-col>
            <el-col :span="12">
              <h4 style="color: #f56c6c">⚠️ 红牌预警 TOP3</h4>
              <el-table :data="topBadList" size="small" v-if="topBadList.length">
                <el-table-column type="index" label="#" width="40" />
                <el-table-column prop="dish_name" label="菜品名" />
                <el-table-column prop="count" label="差评数" width="80" />
              </el-table>
              <el-empty v-else description="暂无" :image-size="60" />
            </el-col>
          </el-row>
        </el-card>
      </el-col>
    </el-row>

    <el-row :gutter="20" style="margin-top: 20px">
      <!-- 槽点雷达图 -->
      <el-col :span="12">
        <el-card shadow="hover">
          <template #header>槽点雷达图</template>
          <v-chart :option="radarChartOption" style="height: 300px" v-if="radarData.length" />
          <el-empty v-else description="暂无槽点数据" />
        </el-card>
      </el-col>

      <!-- 核心改进摘要表格（可展开） -->
      <el-col :span="12">
        <el-card shadow="hover">
          <template #header>📝 核心改进摘要（AI 融合决策）</template>
          <el-table :data="summaryTable" size="small" v-if="summaryTable.length" max-height="350">
            <el-table-column type="expand">
              <template #default="{ row }">
                <div v-for="(d, i) in row.decisions" :key="i" style="display:flex;align-items:center;justify-content:space-between;padding:6px 12px;border-bottom:1px dashed #ebeef5">
                  <span style="flex:1;font-size:12px;color:#606266">{{ d.corrective_action?.slice(0, 120) }}{{ d.corrective_action?.length > 120 ? '...' : '' }}</span>
                  <el-button type="success" size="small" :icon="Star" :disabled="!d.decision_id" @click="handleLike(d.decision_id)" style="margin-left:8px">飞升金标</el-button>
                </div>
                <el-empty v-if="!row.decisions?.length" description="无子决策" :image-size="40" />
              </template>
            </el-table-column>
            <el-table-column prop="dish_name" label="菜品" width="90" />
            <el-table-column prop="negative_count" label="决策数" width="65" align="center" />
            <el-table-column prop="corrective_summary" label="AI 融合摘要" show-overflow-tooltip min-width="180" />
          </el-table>
          <el-empty v-else description="暂无数据" :image-size="60" />
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, watch } from "vue";
import { use } from "echarts/core";
import { PieChart, RadarChart } from "echarts/charts";
import { TitleComponent, TooltipComponent, LegendComponent } from "echarts/components";
import { CanvasRenderer } from "echarts/renderers";
import VChart from "vue-echarts";
import { useDashboardStore } from "../stores/dashboard";
import { getSummaryTable, promoteDecision } from "../api";
import { Star } from "@element-plus/icons-vue";
import { ElMessage } from "element-plus";

use([PieChart, RadarChart, TitleComponent, TooltipComponent, LegendComponent, CanvasRenderer]);

const store = useDashboardStore();
const summaryTable = ref([]);

function todayStr() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

const selectedDate = ref(todayStr());
const loading = ref(false);

watch(selectedDate, (newVal) => {
  if (newVal) loadData(newVal);
});

const summary = computed(() => store.summary);
const radarData = computed(() => store.radarData);

const topGoodList = computed(() => {
  if (!summary.value?.top_good) return [];
  return summary.value.top_good.map((item) => ({
    dish_name: item.dish_name || `菜品 #${item.dish_id || "?"}`,
    count: item.count,
  }));
});

const topBadList = computed(() => {
  if (!summary.value?.top_bad) return [];
  return summary.value.top_bad.map((item) => ({
    dish_name: item.dish_name || `菜品 #${item.dish_id || "?"}`,
    count: item.count,
  }));
});

const sentimentChartOption = computed(() => ({
  tooltip: { trigger: "item" },
  series: [{
    type: "pie",
    radius: ["50%", "75%"],
    data: [
      { value: summary.value?.positive_rate * 100 || 0, name: "好评", itemStyle: { color: "#67c23a" } },
      { value: summary.value?.neutral_rate * 100 || 0, name: "中性", itemStyle: { color: "#e6a23c" } },
      { value: summary.value?.negative_rate * 100 || 0, name: "差评", itemStyle: { color: "#f56c6c" } },
    ],
    label: { formatter: "{b}\n{d}%" },
  }],
}));

const radarChartOption = computed(() => ({
  tooltip: {},
  radar: {
    indicator: radarData.value.map(d => ({ name: d.name, max: Math.max(d.value * 1.5, 10) })),
  },
  series: [{
    type: "radar",
    data: [{ value: radarData.value.map(d => d.value), name: "投诉分布", areaStyle: { color: "rgba(245,108,108,0.3)" } }],
  }],
}));

async function loadData(dateStr) {
  loading.value = true;
  await Promise.all([store.fetchSummary(dateStr), store.fetchRadar(dateStr), fetchSummaryTable(dateStr)]);
  loading.value = false;
}

async function fetchSummaryTable(dateStr) {
  try {
    const res = await getSummaryTable(dateStr);
    summaryTable.value = res.data.table || [];
  } catch { summaryTable.value = []; }
}

async function handleLike(decisionId) {
  try {
    const res = await promoteDecision(decisionId);
    if (res.data?.status === "promoted") {
      ElMessage.success("🎉 已飞升至金标准库！");
    } else {
      ElMessage.warning("未找到该决策");
    }
  } catch (e) {
    ElMessage.error("飞升失败：" + (e.response?.data?.detail || e.message));
  }
}

onMounted(() => loadData(selectedDate.value));
</script>

<style scoped>
.page-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 20px;
}
.page-header h3 { margin: 0; }
.stats-row {
  display: flex;
  justify-content: space-around;
  margin-top: 15px;
}
.ai-summary {
  line-height: 1.8;
  color: #606266;
  font-size: 14px;
}
</style>
