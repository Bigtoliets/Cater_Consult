import { defineStore } from "pinia";
import { ref } from "vue";
import { getDailySummary } from "../api";

export const useDashboardStore = defineStore("dashboard", () => {
  const summary = ref(null);
  const loading = ref(false);
  const error = ref(null);

  async function fetchSummary(date) {
    loading.value = true;
    error.value = null;
    try {
      const res = await getDailySummary(date);
      summary.value = res.data;
    } catch (e) {
      error.value = e.message;
    } finally {
      loading.value = false;
    }
  }

  return { summary, loading, error, fetchSummary };
});
