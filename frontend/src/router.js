import { createRouter, createWebHistory } from 'vue-router'
import { getToken } from './api'
import LoginView from './views/LoginView.vue'
import RequirementsView from './views/RequirementsView.vue'
import RequirementDetailView from './views/RequirementDetailView.vue'
import NotificationsView from './views/NotificationsView.vue'
import ProjectsView from './views/ProjectsView.vue'
import StatsView from './views/StatsView.vue'

export const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/login', component: LoginView },
    { path: '/', redirect: '/requirements' },
    { path: '/requirements', component: RequirementsView },
    { path: '/requirements/:id', component: RequirementDetailView, props: true },
    { path: '/notifications', component: NotificationsView },
    { path: '/projects', component: ProjectsView },
    { path: '/projects/:id', component: ProjectsView, props: true },
    { path: '/stats', component: StatsView },
  ],
})

router.beforeEach((to) => {
  if (to.path !== '/login' && !getToken()) return '/login'
})
