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

          <div v-if="hasPending" class="resume-banner">
            <span>上次的回答还没跑完，可以接着看。</span>
            <el-button size="small" type="primary" :loading="isStreaming" @click="resumePendingTurn">
              继续上次回答
            </el-button>
            <el-button size="small" text @click="discardPendingTurn">忽略</el-button>
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

        <div class="quick-stats">
          <div class="stat-item">
            <span class="stat-label">💡 基于双库 RAG 检索</span>
            <span style="font-size:12px;color:#909399">金标 × 0.7 · 普通 × 0.3</span>
          </div>
          <div class="stat-item">
            <span class="stat-label">📚 可查询历史决策原因</span>
            <span style="font-size:12px;color:#909399">如"为什么红烧肉要延长炖煮？"</span>
          </div>
        </div>
      </el-col>
    </el-row>
  </div>
</template>

<script setup>
import { ref, nextTick, onMounted } from "vue";
import { CHAT_QUERY_URL, chatResumeUrl, getChatTurn, getPresetQuestions } from "../api";
import { marked } from "marked";

const messages = ref([]);
const inputText = ref("");
const isStreaming = ref(false);
const streamingContent = ref("");
const chatMessages = ref(null);
const presetQuestions = ref([]);
const hasPending = ref(false);

// ── 会话与「没跑完的 turn」的本地标识 ────────────────────────
// turn_id 由前端生成：断线/刷新后凭它调 resume 接着看
// （checkpoint 存在 agent 侧 Redis，保留 24h）
const SESSION_KEY = "fb_chat_session";
const PENDING_KEY = "fb_pending_turn";

function uuid() {
  if (typeof crypto !== "undefined" && crypto.randomUUID) return crypto.randomUUID();
  return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0;
    return (c === "x" ? r : (r & 0x3) | 0x8).toString(16);
  });
}

function getSessionId() {
  let sid = null;
  try {
    sid = localStorage.getItem(SESSION_KEY);
  } catch (e) {
    sid = null;
  }
  if (!sid) {
    sid = "web-" + uuid().replace(/-/g, "").slice(0, 16);
    try {
      localStorage.setItem(SESSION_KEY, sid);
    } catch (e) {
      // localStorage 不可用时退化成「单次会话」
    }
  }
  return sid;
}

function readPending() {
  try {
    return JSON.parse(localStorage.getItem(PENDING_KEY) || "null");
  } catch (e) {
    return null;
  }
}

function writePending(pending) {
  try {
    if (pending) localStorage.setItem(PENDING_KEY, JSON.stringify(pending));
    else localStorage.removeItem(PENDING_KEY);
  } catch (e) {
    // 存不了也不影响本次问答，只是刷新后接不上
  }
  hasPending.value = !!pending;
}

onMounted(async () => {
  try {
    const res = await getPresetQuestions();
    presetQuestions.value = res.data.presets || [];
  } catch (e) {
    presetQuestions.value = [
      "查询昨日客诉最多的菜品",
      "生成上周三层食堂的综合改进报告",
      "为什么今天红烧肉评价这么差？",
      "本周食品安全相关投诉汇总",
    ];
  }
  // 刷新/重开页面：先探测有没有没跑完的 turn，有就接着看
  const pending = readPending();
  hasPending.value = !!pending;
  if (pending) await resumePendingTurn();
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

  const sessionId = getSessionId();
  const turnId = uuid();

  messages.value.push({ role: "user", content: text });
  inputText.value = "";
  scrollToBottom();
  // 先把 turn_id 记下来，再发请求：这样首帧还没到就断线也接得上
  writePending({ turn_id: turnId, session_id: sessionId, question: text, started_at: Date.now() });

  await runStream(CHAT_QUERY_URL, { question: text, session_id: sessionId, turn_id: turnId });
}

async function resumePendingTurn() {
  const pending = readPending();
  if (!pending || isStreaming.value) return;

  let status = null;
  try {
    status = (await getChatTurn(pending.turn_id, pending.session_id)).data;
  } catch (e) {
    status = e?.response?.data || null; // 410 已过期 / 404 不属于本会话 / 503 agent 挂了
  }

  if (status?.status === "completed" && status.final_answer) {
    messages.value.push({ role: "ai", content: status.final_answer });
    writePending(null);
    scrollToBottom();
    return;
  }
  if (status?.status === "running") {
    if (pending.question) messages.value.push({ role: "user", content: pending.question });
    await runStream(chatResumeUrl(pending.turn_id, pending.session_id), null);
    return;
  }
  // 已过期 / 已放弃 / 探不到：清掉本地记录，别让用户对着一个死 turn 反复点
  writePending(null);
  if (status?.error) {
    messages.value.push({ role: "ai", content: "上次的分析已经接不上了：" + status.error });
  }
}

function discardPendingTurn() {
  writePending(null);
}

async function runStream(url, body) {
  isStreaming.value = true;
  streamingContent.value = "";
  try {
    const response = await fetch(url, {
      method: "POST",
      headers: body ? { "Content-Type": "application/json" } : undefined,
      body: body ? JSON.stringify(body) : undefined,
    });
    if (!response.ok) {
      messages.value.push({ role: "ai", content: "抱歉，无法继续：" + (await readError(response)) });
      return;
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const frames = buffer.split("\n\n");
      buffer = frames.pop() || "";
      for (const frame of frames) handleFrame(frame);
    }
    if (buffer) handleFrame(buffer);
  } catch (e) {
    // 断线：这里故意不清 pending —— 这正是「继续上次回答」要接住的场景
    messages.value.push({ role: "ai", content: "连接中断了，可以点「继续上次回答」接着看。" });
  } finally {
    isStreaming.value = false;
    streamingContent.value = "";
    scrollToBottom();
  }
}

function handleFrame(raw) {
  const line = raw.split("\n").find((l) => l.startsWith("data: "));
  if (!line) return;
  let data;
  try {
    data = JSON.parse(line.slice(6));
  } catch (e) {
    return; // 忽略解析错误
  }

  if (data.turn_id) {
    const pending = readPending();
    if (!pending) {
      writePending({ turn_id: data.turn_id, session_id: data.session_id || getSessionId(), started_at: Date.now() });
    } else if (pending.turn_id !== data.turn_id) {
      writePending({ ...pending, turn_id: data.turn_id });
    }
  }
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
    writePending(null);
  }
  if (data.error) {
    messages.value.push({ role: "ai", content: "抱歉，回答中断了：" + data.error });
    streamingContent.value = "";
    if (data.abandoned) writePending(null);
  }
}

async function readError(response) {
  try {
    const body = await response.json();
    return body.error || `HTTP ${response.status}`;
  } catch (e) {
    return `HTTP ${response.status}`;
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

.resume-banner {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 10px;
  padding: 8px 12px;
  background: #f2f7ff;
  border: 1px solid #d6e4ff;
  border-radius: 6px;
  font-size: 13px;
  color: #4a5b7a;
}

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

.quick-stats {
  margin-top: 16px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.stat-item {
  padding: 10px 12px;
  background: #f5f7fa;
  border-radius: 6px;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.stat-label {
  font-size: 14px;
  color: #303133;
  font-weight: 500;
}
</style>
