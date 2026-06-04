<script setup lang="ts">
import FollowControlPanel from '@/components/FollowControlPanel.vue'
import FollowConfigPanel from '@/components/FollowConfigPanel.vue'
</script>

<template>
  <div class="shell">
    <aside class="sidebar">
      <div class="brand">
        <div class="brand-mark">FC</div>
        <div>
          <div class="brand-title">Follow Client</div>
          <div class="brand-subtitle">跟单端配置管理台</div>
        </div>
      </div>
      <div class="sidebar-note">
        配置喊单端地址和本地同花顺路径，启动后自动按比例跟单。
      </div>
    </aside>

    <main class="main">
      <header class="main-header">
        <h1 class="page-title">跟单端管理台</h1>
        <p class="page-subtitle">
          控制跟单引擎启停，管理喊单端地址、轮询间隔和兼容性参数。
        </p>
      </header>

      <section class="view-single">
        <FollowControlPanel />
        <FollowConfigPanel />
      </section>
    </main>
  </div>
</template>
