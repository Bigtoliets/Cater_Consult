<template>
  <div class="agent-config">
    <div class="page-header">
      <h3>⚙️ 系统配置</h3>
    </div>

    <el-tabs v-model="activeTab" type="border-card">
      <!-- 预警规则 -->
      <el-tab-pane label="预警规则" name="alert">
        <el-form label-width="140px">
          <el-form-item label="食安异物告警阈值">
            <el-input-number v-model="alertConfig.foodSafetyThreshold" :min="1" :max="10" />
            <span class="form-tip">1小时内同一菜品N条异物投诉即触发告警</span>
          </el-form-item>
          <el-form-item label="差评率告警阈值">
            <el-input-number v-model="alertConfig.negativeRateThreshold" :min="0.01" :max="1" :step="0.01" :precision="2" />
            <span class="form-tip">当日某菜品差评率超过此值触发预警</span>
          </el-form-item>
          <el-form-item label="敏感词订阅">
            <el-select
              v-model="alertConfig.sensitiveWords"
              multiple
              filterable
              allow-create
              placeholder="输入敏感词后回车添加"
              style="width: 400px"
            >
              <el-option label="拉肚子" value="拉肚子" />
              <el-option label="食物中毒" value="食物中毒" />
              <el-option label="钢丝球" value="钢丝球" />
              <el-option label="变质" value="变质" />
              <el-option label="异味" value="异味" />
              <el-option label="头发" value="头发" />
              <el-option label="虫子" value="虫子" />
            </el-select>
          </el-form-item>
          <el-form-item>
            <el-button type="primary" @click="saveAlertConfig">保存预警配置</el-button>
          </el-form-item>
        </el-form>
      </el-tab-pane>

      <!-- RAG 检索 -->
      <el-tab-pane label="RAG检索" name="rag">
        <el-form label-width="140px">
          <el-form-item label="Top-K 检索数量">
            <el-input-number v-model="ragConfig.topK" :min="1" :max="10" />
          </el-form-item>
          <el-form-item label="相似度阈值">
            <el-input-number v-model="ragConfig.similarityThreshold" :min="0.1" :max="1" :step="0.05" :precision="2" />
          </el-form-item>
          <el-form-item label="连接池大小">
            <el-input-number v-model="ragConfig.poolSize" :min="5" :max="50" />
          </el-form-item>
          <el-form-item>
            <el-button type="primary" @click="saveRagConfig">保存检索配置</el-button>
          </el-form-item>
        </el-form>
      </el-tab-pane>

      <!-- 数据源 -->
      <el-tab-pane label="数据源" name="datasource">
        <el-alert
          title="评论数据已接入 MySQL 数据库。点击「同步数据」读取未同步的评论，并自动分发到 Agent 分析。"
          type="info"
          :closable="false"
          style="margin-bottom: 16px"
        />
        <el-form label-width="100px" style="max-width: 600px">
          <el-form-item label="店铺筛选">
            <el-select v-model="selectedShop" clearable placeholder="全部店铺" style="width: 260px">
              <el-option v-for="s in shops" :key="s.id" :label="s.name" :value="s.id" />
            </el-select>
          </el-form-item>
          <el-form-item>
            <el-button type="primary" :loading="syncing" @click="handleSync">🔄 同步数据</el-button>
          </el-form-item>
        </el-form>

        <!-- 同步结果 -->
        <el-alert
          v-if="syncResult"
          :title="syncResult.synced ? `同步完成：${syncResult.synced} 条评论、${syncResult.dish_count} 个菜品` : '无新增评论'"
          :type="syncResult.synced ? 'success' : 'info'"
          :closable="true"
          @close="syncResult = null"
          style="margin-top: 16px"
        >
          <span v-if="syncResult.batch_id">批次号：{{ syncResult.batch_id }}</span>
        </el-alert>
      </el-tab-pane>

      <!-- AI 推理 -->
      <el-tab-pane label="AI推理" name="ai">
        <el-form label-width="140px">
          <el-form-item label="置信度阈值">
            <el-slider v-model="aiConfig.confidenceThreshold" :min="0.5" :max="0.95" :step="0.05" show-input />
          </el-form-item>
          <el-form-item label="权重：样本密度">
            <el-slider v-model="aiConfig.weightSampleDensity" :min="0" :max="1" :step="0.05" show-input />
          </el-form-item>
          <el-form-item label="权重：SOP 映射度">
            <el-slider v-model="aiConfig.weightSopMapping" :min="0" :max="1" :step="0.05" show-input />
          </el-form-item>
          <el-form-item label="权重：历史相似度">
            <el-slider v-model="aiConfig.weightHistorySimilarity" :min="0" :max="1" :step="0.05" show-input />
          </el-form-item>
          <el-form-item>
            <el-button type="primary" @click="saveAiConfig">保存推理配置</el-button>
          </el-form-item>
        </el-form>
      </el-tab-pane>

      <!-- 关键词维度权重 -->
      <el-tab-pane label="关键词权重" name="keywordWeights">
        <el-form label-width="140px">
          <el-alert title="调整各投诉维度的权重，影响 Agent 分析时的优先级。推荐「安全」和「卫生」保持较高权重。" type="info" :closable="false" style="margin-bottom: 16px" />
          <el-form-item v-for="(val, key) in keywordWeights" :key="key" :label="dimensionLabel(key)">
            <el-slider v-model="keywordWeights[key]" :min="0.5" :max="10" :step="0.5" show-input style="width: 300px" />
          </el-form-item>
          <el-form-item>
            <el-button type="primary" @click="saveKeywordWeights">保存权重配置</el-button>
            <el-button @click="resetKeywordWeights">恢复默认</el-button>
          </el-form-item>
        </el-form>
      </el-tab-pane>


    </el-tabs>
  </div>
</template>

<script setup>
import { ref, onMounted } from "vue";
import { syncReviews, getShops, updateConfig, getKeywordWeights, updateKeywordWeights } from "../api";
import { ElMessage } from "element-plus";

const activeTab = ref("alert");

const alertConfig = ref({
  foodSafetyThreshold: 3,
  negativeRateThreshold: 0.10,
  sensitiveWords: ["拉肚子", "食物中毒", "钢丝球", "变质"],
});

const ragConfig = ref({
  topK: 3,
  similarityThreshold: 0.6,
  poolSize: 20,
});

const aiConfig = ref({
  confidenceThreshold: 0.75,
  weightSampleDensity: 0.3,
  weightSopMapping: 0.4,
  weightHistorySimilarity: 0.3,
});

const DEFAULT_WEIGHTS = {
  "口味": 1.0, "卫生": 3.0, "分量": 1.0, "温度": 1.0,
  "口感": 1.5, "价格": 1.0, "服务": 1.0, "安全": 5.0,
};
const keywordWeights = ref({ ...DEFAULT_WEIGHTS });

function dimensionLabel(key) {
  const map = { "口味": "口味", "卫生": "卫生", "分量": "分量", "温度": "温度", "口感": "口感", "价格": "价格", "服务": "服务", "安全": "安全" };
  return map[key] || key;
}

async function loadKeywordWeights() {
  try {
    const res = await getKeywordWeights();
    if (res.data?.weights) {
      keywordWeights.value = { ...DEFAULT_WEIGHTS, ...res.data.weights };
    }
  } catch {}
}

async function saveKeywordWeights() {
  try {
    await updateKeywordWeights(keywordWeights.value);
    ElMessage.success("关键词权重已保存，后续 Agent 分析将使用新权重");
  } catch (e) {
    ElMessage.error("保存失败：" + (e.response?.data?.detail || e.message));
  }
}

function resetKeywordWeights() {
  keywordWeights.value = { ...DEFAULT_WEIGHTS };
  ElMessage.info("已恢复默认权重");
}

onMounted(() => {
  loadKeywordWeights();
  loadShops();
});

// 数据同步相关
const shops = ref([]);
const selectedShop = ref(null);
const syncing = ref(false);
const syncResult = ref(null);

async function loadShops() {
  try {
    const res = await getShops();
    shops.value = res.data.shops || [];
  } catch {}
}

async function handleSync() {
  syncing.value = true;
  syncResult.value = null;
  try {
    const res = await syncReviews(selectedShop.value);
    syncResult.value = res.data;
    ElMessage.success(res.data.synced ? `成功同步 ${res.data.synced} 条评论` : "暂无新增评论");
  } catch (e) {
    ElMessage.error("同步失败：" + (e.response?.data?.detail || e.message));
  } finally {
    syncing.value = false;
  }
}

async function saveAlertConfig() {
  await updateConfig("sensitive_words", { config_value: alertConfig.value }, "global");
  ElMessage.success("预警配置已保存");
}

async function saveRagConfig() {
  await updateConfig("rag_params", { config_value: ragConfig.value }, "global");
  ElMessage.success("检索配置已保存");
}

async function saveAiConfig() {
  await updateConfig("ai_inference", { config_value: aiConfig.value }, "global");
  ElMessage.success("推理配置已保存");
}


</script>

<style scoped>
.page-header { margin-bottom: 20px; }
.page-header h3 { margin: 0; }
.form-tip { margin-left: 12px; color: #909399; font-size: 12px; }
</style>
