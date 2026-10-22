<script setup lang="ts">
withDefaults(defineProps<{ name: string; size?: number }>(), { size: 20 })
const paths: Record<string, string> = {
  grid: 'M3 3h7v7H3z M14 3h7v7h-7z M3 14h7v7H3z M14 14h7v7h-7z',
  chart: 'M4 3v17h17 M8 15v-4 M13 15V7 M18 15V4',
  layers: 'm12 3 9 5-9 5-9-5 9-5Z M3 12l9 5 9-5 M3 16l9 5 9-5',
  search: 'm21 21-4.6-4.6 M19 11a8 8 0 1 1-16 0 8 8 0 0 1 16 0Z',
  database: 'M20 6c0 2.2-3.6 4-8 4S4 8.2 4 6s3.6-4 8-4 8 1.8 8 4Z M4 6v12c0 2.2 3.6 4 8 4s8-1.8 8-4V6 M4 12c0 2.2 3.6 4 8 4s8-1.8 8-4',
  arrow: 'M4 12h16 M14 6l6 6-6 6',
  chevron: 'm9 5 7 7-7 7',
  down: 'm6 9 6 6 6-6',
  upload: 'M12 16V3 M7 8l5-5 5 5 M4 15v5h16v-5',
  download: 'M12 3v13 M7 11l5 5 5-5 M4 16v5h16v-5',
  plus: 'M12 5v14 M5 12h14',
  check: 'm5 12 4 4L19 6',
  info: 'M12 11v6 M12 7h.01 M22 12a10 10 0 1 1-20 0 10 10 0 0 1 20 0Z',
  alert: 'M12 8v5 M12 17h.01 M10.3 3.7 2 18a2 2 0 0 0 1.7 3h16.6a2 2 0 0 0 1.7-3L13.7 3.7a2 2 0 0 0-3.4 0Z',
  clock: 'M12 6v6l4 2 M22 12a10 10 0 1 1-20 0 10 10 0 0 1 20 0Z',
  book: 'M12 5v16 M12 5C9 2 4 2 2 3v16c3-1 7-1 10 2 3-3 7-3 10-2V3c-2-1-7-1-10 2Z',
  external: 'M14 3h7v7 M21 3l-11 11 M10 3H3v18h18v-7',
  flask: 'M9 3h6 M10 3v7L4 20a1 1 0 0 0 .9 1h14.2a1 1 0 0 0 .9-1l-6-10V3 M8 14h8',
  shield: 'M12 2 3 6v6c0 5 9 10 9 10s9-5 9-10V6l-9-4Z m-4 10 3 3 5-5',
  close: 'm6 6 12 12 M6 18 18 6',
  file: 'M14 2H4v20h16V8l-6-6Z M14 2v6h6 M8 13h8 M8 17h5',
  refresh: 'M20 7v5h-5 M4 17v-5h5 M5 7a8 8 0 0 1 13-3l2 3 M4 17l2 3a8 8 0 0 0 13-3',
  trend: 'm3 6 6 6 4-4 8 10 M16 18h5v-5',
  spark: 'm12 3 2.5 6.5L21 12l-6.5 2.5L12 21l-2.5-6.5L3 12l6.5-2.5L12 3Z',
  menu: 'M4 6h16 M4 12h16 M4 18h16',
  code: 'm8 5-6 7 6 7 M16 5l6 7-6 7 M14 3l-4 18',
}
</script>

<template>
  <svg :width="size" :height="size" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path :d="paths[name] || paths.file" /></svg>
</template>
