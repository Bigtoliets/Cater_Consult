import { defineStore } from "pinia";
import { ref } from "vue";
import { getDailySummary, getComplaintRadar } from "../api";

export const useDashboardStore = defineStore("dashboard", () => {
  const summary = ref(null);
  const radarData = ref([]);
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

  async function fetchRadar(date) {
    try {
      const res = await getComplaintRadar(date);
      radarData.value = res.data.radar;
    } catch (e) {
      // silent
    }
  }

  return { summary, radarData, loading, error, fetchSummary, fetchRadar };
});
