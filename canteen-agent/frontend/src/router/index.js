import { createRouter, createWebHistory } from "vue-router";

const routes = [
  { path: "/", redirect: "/dashboard" },
  {
    path: "/dashboard",
    name: "Dashboard",
    component: () => import("../views/DailyDashboard.vue"),
  },
  {
    path: "/diagnosis",
    name: "Diagnosis",
    component: () => import("../views/DishDiagnosis.vue"),
  },
  {
    path: "/diagnosis/:id",
    name: "DiagnosisDetail",
    component: () => import("../views/DishDiagnosis.vue"),
  },
  {
    path: "/config",
    name: "Config",
    component: () => import("../views/AgentConfig.vue"),
  },
  {
    path: "/chat",
    name: "Chat",
    component: () => import("../views/SmartChat.vue"),
  },
];

const router = createRouter({
  history: createWebHistory(),
  routes,
});

export default router;
