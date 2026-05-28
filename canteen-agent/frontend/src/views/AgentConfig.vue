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
        <el-upload
          drag
          :auto-upload="false"
          :on-change="handleFileChange"
          accept=".csv,.xlsx,.xls"
        >
          <el-icon class="el-icon--upload"><upload-filled /></el-icon>
          <div class="el-upload__text">
            将评价文件拖到此处，或<em>点击上传</em>
          </div>
          <template #tip>
            <div class="el-upload__tip">
              支持 CSV / Excel 格式。请确保包含：评价时间、档口名称、评价内容
            </div>
          </template>
        </el-upload>
        <div v-if="uploadResult" style="margin-top: 16px">
          <el-alert
            :title="`上传完成：共 ${uploadResult.total_rows} 条，成功导入 ${uploadResult.imported} 条`"
            :type="uploadResult.errors?.length ? 'warning' : 'success'"
            :closable="true"
          />
          <el-table :data="uploadResult.preview" size="small" style="margin-top: 10px" v-if="uploadResult.preview?.length">
            <el-table-column prop="raw_text" label="评价内容" show-overflow-tooltip />
            <el-table-column prop="stall_name" label="档口" width="100" />
            <el-table-column prop="dish_name_raw" label="菜品" width="100" />
            <el-table-column prop="rating" label="评分" width="60" />
          </el-table>
        </div>
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

      <!-- 知识库 -->
      <el-tab-pane label="知识库" name="knowledge">
        <el-row :gutter="20">
          <el-col :span="8">
            <el-select v-model="selectedDishId" placeholder="选择菜品" filterable style="width: 100%">
              <el-option label="红烧肉 (D045)" :value="1" />
              <el-option label="麻婆豆腐 (D032)" :value="2" />
              <el-option label="宫保鸡丁 (D018)" :value="3" />
              <el-option label="清炒时蔬 (D051)" :value="4" />
            </el-select>
          </el-col>
          <el-col :span="8">
            <el-radio-group v-model="knowledgeDimension">
              <el-radio-button label="sop">SOP标准卡</el-radio-button>
              <el-radio-button label="cost">成本卡</el-radio-button>
              <el-radio-button label="food_safety">食安规范</el-radio-button>
            </el-radio-group>
          </el-col>
          <el-col :span="8">
            <el-upload :auto-upload="false" :show-file-list="false">
              <el-button>上传 .md / .pdf</el-button>
            </el-upload>
          </el-col>
        </el-row>
        <el-form style="margin-top: 16px" label-width="100px">
          <el-form-item label="条目标题">
            <el-input v-model="knowledgeForm.title" placeholder="例如：红烧肉炖煮工艺标准" />
          </el-form-item>
          <el-form-item label="条目内容">
            <el-input v-model="knowledgeForm.content" type="textarea" :rows="6" placeholder="请输入标准SOP内容（支持 Markdown）" />
          </el-form-item>
          <el-form-item>
            <el-button type="primary" @click="saveKnowledge">保存知识条目</el-button>
          </el-form-item>
        </el-form>
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<script setup>
import { ref } from "vue";
import { uploadCSV, updateConfig, createSOPEntry } from "../api";
import { ElMessage } from "element-plus";

const activeTab = ref("alert");

// 预警配置
const alertConfig = ref({
  foodSafetyThreshold: 3,
  negativeRateThreshold: 0.10,
  sensitiveWords: ["拉肚子", "食物中毒", "钢丝球", "变质"],
});

// RAG 配置
const ragConfig = ref({
  topK: 3,
  similarityThreshold: 0.6,
  poolSize: 20,
});

// AI 推理配置
const aiConfig = ref({
  confidenceThreshold: 0.75,
  weightSampleDensity: 0.3,
  weightSopMapping: 0.4,
  weightHistorySimilarity: 0.3,
});

// 上传结果
const uploadResult = ref(null);

// 知识库表单
const selectedDishId = ref(null);
const knowledgeDimension = ref("sop");
const knowledgeForm = ref({ title: "", content: "" });

async function handleFileChange(file) {
  try {
    const res = await uploadCSV(file.raw);
    uploadResult.value = res.data;
    ElMessage.success(`成功导入 ${res.data.imported} 条评价`);
  } catch (e) {
    ElMessage.error("上传失败：" + e.message);
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

async function saveKnowledge() {
  if (!selectedDishId.value) {
    ElMessage.warning("请先选择菜品");
    return;
  }
  await createSOPEntry({
    dish_id: selectedDishId.value,
    dimension: knowledgeDimension.value,
    title: knowledgeForm.value.title,
    content: knowledgeForm.value.content,
    metadata_json: {},
  });
  ElMessage.success("知识条目已保存");
  knowledgeForm.value = { title: "", content: "" };
}
</script>

<style scoped>
.page-header { margin-bottom: 20px; }
.page-header h3 { margin: 0; }
.form-tip { margin-left: 12px; color: #909399; font-size: 12px; }
</style>
