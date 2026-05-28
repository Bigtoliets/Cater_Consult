<template>
  <div class="smart-chat">
    <div class="page-header">
      <h3>💬 智能问答</h3>
    </div>

    <el-row :gutter="20" style="height: calc(100vh - 180px)">
      <!-- 对话区域 -->
      <el-col :span="16">
        <el-card shadow="hover" class="chat-card">
          <div class="chat-messages" ref="chatMessages">
            <div v-if="messages.length === 0" class="welcome-message">
              <p>👋 你好！我是食堂品控智能助手。</p>
              <p>你可以问我关于菜品质量、客诉分析、改进建议等方面的问题。</p>
            </div>

            <div
              v-for="(msg, idx) in messages"
              :key="idx"
              :class="['message', msg.role === 'user' ? 'user-message' : 'ai-message']"
            >
              <div class="message-avatar">
                {{ msg.role === 'user' ? '👤' : '🤖' }}
              </div>
              <div class="message-content">
                <div v-html="renderMarkdown(msg.content)" />
                <!-- 动态数据卡片 -->
                <div v-if="msg.dataCards?.length" class="data-cards">
                  <el-card
                    v-for="(card, ci) in msg.dataCards"
                    :key="ci"
                    shadow="hover"
                    class="data-card"
                  >
                    <template #header>{{ card.title }}</template>
                    <div v-html="card.content" />
                  </el-card>
                </div>
              </div>
            </div>

            <div v-if="isStreaming" class="message ai-message">
              <div class="message-avatar">🤖</div>
              <div class="message-content">
                <span v-html="renderMarkdown(streamingContent)" />
                <span class="cursor-blink">|</span>
              </div>
            </div>
          </div>

          <div class="chat-input">
            <el-input
              v-model="inputText"
              placeholder="输入你的问题..."
              @keyup.enter="sendMessage"
              :disabled="isStreaming"
            >
              <template #append>
                <el-button
                  @click="sendMessage"
                  :loading="isStreaming"
                  :disabled="!inputText.trim()"
                >
                  发送
                </el-button>
              </template>
            </el-input>
          </div>
        </el-card>
      </el-col>

      <!-- 快捷问询 -->
      <el-col :span="8">
        <el-card shadow="hover">
          <template #header>📌 预设快捷问询</template>
          <div class="preset-list">
            <el-tag
              v-for="(q, idx) in presetQuestions"
              :key="idx"
              class="preset-tag"
              @click="sendPreset(q)"
              effect="plain"
              type="info"
            >
              {{ q }}
            </el-tag>
          </div>
        </el-card>

        <el-card shadow="hover" style="margin-top: 16px">
          <template #header>📊 快速统计</template>
          <el-statistic title="今日评价数" :value="125" />
          <el-statistic title="活跃档口" :value="15" />
          <el-statistic title="待处理差评" :value="8" />
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<script setup>
import { ref, nextTick, onMounted } from "vue";
import { getPresetQuestions } from "../api";
import { marked } from "marked";

const messages = ref([]);
const inputText = ref("");
const isStreaming = ref(false);
const streamingContent = ref("");
const chatMessages = ref(null);
const presetQuestions = ref([]);

onMounted(async () => {
  try {
    const res = await getPresetQuestions();
    presetQuestions.value = res.data.presets || [];
  } catch (e) {
    presetQuestions.value = [
      "查询昨日客诉最多的档口",
      "生成上周三层食堂的综合改进报告",
      "为什么今天红烧肉评价这么差？",
      "本周食品安全相关投诉汇总",
    ];
  }
});

function scrollToBottom() {
  nextTick(() => {
    if (chatMessages.value) {
      chatMessages.value.scrollTop = chatMessages.value.scrollHeight;
    }
  });
}

async function sendMessage() {
  const text = inputText.value.trim();
  if (!text || isStreaming.value) return;

  messages.value.push({ role: "user", content: text });
  inputText.value = "";
  scrollToBottom();

  isStreaming.value = true;
  streamingContent.value = "";

  try {
    // 使用 SSE 流式获取回复
    const response = await fetch("/api/v1/chat/query?question=" + encodeURIComponent(text), {
      method: "POST",
    });

    const reader = response.body.getReader();
    const decoder = new TextDecoder();

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      const chunk = decoder.decode(value, { stream: true });
      const lines = chunk.split("\n");

      for (const line of lines) {
        if (line.startsWith("data: ")) {
          try {
            const data = JSON.parse(line.slice(6));
            if (data.content) {
              streamingContent.value += data.content;
              scrollToBottom();
            }
            if (data.done) {
              messages.value.push({
                role: "ai",
                content: streamingContent.value,
                dataCards: data.cards || [],
              });
              streamingContent.value = "";
            }
            if (data.error) {
              messages.value.push({ role: "ai", content: "抱歉，处理出错：" + data.error });
              streamingContent.value = "";
            }
          } catch (e) {
            // 忽略解析错误
          }
        }
      }
    }
  } catch (e) {
    messages.value.push({ role: "ai", content: "抱歉，请求失败：" + e.message });
  } finally {
    isStreaming.value = false;
    streamingContent.value = "";
    scrollToBottom();
  }
}

function sendPreset(question) {
  inputText.value = question;
  sendMessage();
}

function renderMarkdown(text) {
  if (!text) return "";
  return marked(text);
}
</script>

<style scoped>
.page-header { margin-bottom: 20px; }
.page-header h3 { margin: 0; }

.chat-card {
  height: 100%;
  display: flex;
  flex-direction: column;
}

.chat-messages {
  flex: 1;
  overflow-y: auto;
  padding: 16px;
  background: #fafafa;
  border-radius: 4px;
  margin-bottom: 16px;
  min-height: 400px;
}

.welcome-message {
  text-align: center;
  color: #909399;
  padding: 60px 0;
  font-size: 16px;
}

.message {
  display: flex;
  margin-bottom: 16px;
}

.user-message { justify-content: flex-end; }
.ai-message { justify-content: flex-start; }

.message-avatar {
  width: 36px;
  height: 36px;
  border-radius: 50%;
  background: #e8e8e8;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 18px;
  flex-shrink: 0;
}

.message-content {
  max-width: 75%;
  padding: 10px 14px;
  border-radius: 8px;
  margin: 0 10px;
  line-height: 1.6;
  font-size: 14px;
}

.user-message .message-content {
  background: #409eff;
  color: #fff;
}

.ai-message .message-content {
  background: #fff;
  border: 1px solid #e4e7ed;
}

.cursor-blink {
  animation: blink 1s infinite;
  color: #409eff;
}

@keyframes blink {
  0%, 50% { opacity: 1; }
  51%, 100% { opacity: 0; }
}

.chat-input { padding: 0; }

.preset-list {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.preset-tag {
  cursor: pointer;
}

.preset-tag:hover {
  color: #409eff;
  border-color: #409eff;
}

.data-cards {
  margin-top: 10px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.data-card {
  font-size: 13px;
}
</style>
