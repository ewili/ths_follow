<script setup lang="ts">
defineProps<{
  state: string
  size?: 'default' | 'large'
}>()
</script>

<template>
  <span class="badge" :class="[state, size]">
    <span class="dot" />
  </span>
</template>

<style scoped>
.badge {
  display: inline-flex;
  align-items: center;
}

.dot {
  display: inline-block;
  width: 10px;
  height: 10px;
  border-radius: 50%;
  background: #c0c4cc;
}

.badge.large .dot {
  width: 12px;
  height: 12px;
}

.connected .dot,
.running .dot {
  background: #67c23a;
  box-shadow: 0 0 6px rgba(103, 194, 58, 0.5);
}

.error .dot {
  background: #f56c6c;
  box-shadow: 0 0 6px rgba(245, 108, 108, 0.5);
}

.stopped .dot {
  background: #e6a23c;
  box-shadow: 0 0 6px rgba(230, 162, 60, 0.5);
}
</style>
