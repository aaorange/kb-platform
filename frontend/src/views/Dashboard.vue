<template>
  <div v-loading="loading">
    <!-- 指标卡 ×8 -->
    <el-row :gutter="16" style="margin-bottom: 16px">
      <el-col :span="6" v-for="card in statCards" :key="card.label" style="margin-bottom: 16px">
        <el-card shadow="hover" body-style="padding: 18px 20px">
          <div style="font-size: 26px; font-weight: bold; color: #409eff">{{ card.value }}</div>
          <div style="color: #909399; font-size: 13px; margin-top: 4px">{{ card.label }}</div>
        </el-card>
      </el-col>
    </el-row>

    <!-- 趋势 + 分类分布 -->
    <el-row :gutter="16" style="margin-bottom: 16px">
      <el-col :span="16">
        <el-card shadow="never">
          <template #header><span style="font-weight: 600">近 30 天问答趋势</span></template>
          <div ref="trendRef" style="height: 340px"></div>
        </el-card>
      </el-col>
      <el-col :span="8">
        <el-card shadow="never">
          <template #header><span style="font-weight: 600">问题分类分布</span></template>
          <div v-if="data.category_dist?.length" ref="categoryRef" style="height: 300px"></div>
          <el-empty v-else description="暂无引用数据" :image-size="60" />
        </el-card>
      </el-col>
    </el-row>

    <!-- 文档热度 + 高频问题 -->
    <el-row :gutter="16" style="margin-bottom: 16px">
      <el-col :span="12">
        <el-card shadow="never">
          <template #header><span style="font-weight: 600">文档热度 TOP 10（被引用次数）</span></template>
          <div v-if="data.doc_heat?.length" ref="docHeatRef" style="height: 320px"></div>
          <el-empty v-else description="暂无引用数据" :image-size="60" />
        </el-card>
      </el-col>
      <el-col :span="12">
        <el-card shadow="never">
          <template #header><span style="font-weight: 600">高频问题 TOP 10</span></template>
          <el-table :data="data.top_questions || []" stripe height="320">
            <el-table-column type="index" label="#" width="45" />
            <el-table-column prop="question" label="问题" min-width="240" show-overflow-tooltip />
            <el-table-column prop="count" label="次数" width="70" align="center">
              <template #default="{ row }">
                <el-tag type="danger" size="small">{{ row.count }}</el-tag>
              </template>
            </el-table-column>
          </el-table>
        </el-card>
      </el-col>
    </el-row>

    <!-- 拦截分析 + 满意度 -->
    <el-row :gutter="16">
      <el-col :span="12">
        <el-card shadow="never">
          <template #header><span style="font-weight: 600">权限拦截分析</span></template>
          <div style="padding: 4px">
            <div style="margin-bottom: 16px; color: #606266">
              涉及权限拦截的提问：
              <b style="color: #e6a23c; font-size: 18px">{{ data.blocked?.question_count ?? 0 }}</b> 次
              <span style="color: #909399; font-size: 12px">（这些提问检索到但无权查看的内容）</span>
            </div>
            <div style="font-size: 13px; color: #909399; margin-bottom: 8px">最常被拦截的文档：</div>
            <div v-for="d in data.blocked?.docs || []" :key="d.doc_id"
                 style="display: flex; justify-content: space-between; align-items: center; padding: 8px 4px; border-bottom: 1px dashed #ebeef5">
              <span style="font-size: 13px">{{ d.title }}</span>
              <el-tag type="warning" size="small">拦截 {{ d.count }} 次</el-tag>
            </div>
            <div v-if="!(data.blocked?.docs?.length)" style="color: #c0c4cc; padding: 16px 0; text-align: center">
              暂无拦截记录
            </div>
          </div>
        </el-card>
      </el-col>
      <el-col :span="12">
        <el-card shadow="never">
          <template #header><span style="font-weight: 600">满意度反馈趋势</span></template>
          <div v-if="data.satisfaction_trend?.length" ref="satisfactionRef" style="height: 280px"></div>
          <el-empty v-else description="暂无反馈数据，去问答页点 👍👎 吧" :image-size="60" />
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onBeforeUnmount, nextTick } from 'vue'
import * as echarts from 'echarts'
import api from '../api'

const data = ref({})
const loading = ref(false)
const trendRef = ref(null)
const categoryRef = ref(null)
const docHeatRef = ref(null)
const satisfactionRef = ref(null)
let charts = []

const statCards = computed(() => [
  { label: '问答总量', value: data.value.pv ?? 0 },
  { label: '提问用户', value: data.value.uv ?? 0 },
  { label: '知识覆盖率', value: (data.value.coverage_pct ?? 0) + '%' },
  { label: '满意度', value: data.value.satisfaction_pct != null ? data.value.satisfaction_pct + '%' : '—' },
  { label: '平均响应时间', value: (data.value.avg_response_ms ?? 0) + ' ms' },
  { label: 'Token 消耗', value: data.value.token_total ?? 0 },
  { label: '知识文档', value: data.value.total_units ?? 0 },
  { label: '知识缺口', value: data.value.total_gaps ?? 0 },
])

function renderTrend() {
  if (!trendRef.value || !data.value.trend?.length) return
  const chart = echarts.init(trendRef.value)
  const step = Math.max(1, Math.ceil(data.value.trend.length / 10))
  chart.setOption({
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'line', lineStyle: { color: '#c0c4cc' } },
      formatter: (params) => {
        let html = `<div style="font-weight:600;margin-bottom:6px">${params[0].axisValue}</div>`
        for (const p of params) {
          const isToken = p.seriesName === 'Token 消耗'
          const val = isToken ? Number(p.value).toLocaleString() : p.value
          const unit = isToken ? '' : ' 次'
          html += `<div style="display:flex;align-items:center;margin:3px 0">${p.marker}${p.seriesName}<b style="margin-left:16px;padding-left:12px">${val}${unit}</b></div>`
        }
        return html
      },
    },
    legend: { data: ['问答量', 'Token 消耗'], top: 4 },
    grid: { left: 55, right: 55, bottom: 32, top: 44 },
    xAxis: {
      type: 'category',
      boundaryGap: false,
      data: data.value.trend.map(t => t.date),
      axisLabel: { interval: step - 1, color: '#606266' },
      axisTick: { alignWithLabel: true },
    },
    yAxis: [
      {
        type: 'value', name: '问答量', minInterval: 1,
        splitLine: { lineStyle: { type: 'dashed', color: '#ebeef5' } },
      },
      {
        type: 'value', name: 'Token', splitLine: { show: false },
        axisLabel: { formatter: v => v >= 1000 ? (v / 1000) + 'k' : v },
      },
    ],
    series: [
      {
        name: '问答量', type: 'line', smooth: true, symbolSize: 6,
        data: data.value.trend.map(t => t.count),
        itemStyle: { color: '#409eff' },
        lineStyle: { width: 2.5 },
        areaStyle: { opacity: 0.15, color: '#409eff' },
      },
      {
        name: 'Token 消耗', type: 'line', smooth: true, symbolSize: 6, yAxisIndex: 1,
        data: data.value.trend.map(t => t.tokens),
        itemStyle: { color: '#67c23a' },
        lineStyle: { width: 2.5 },
      },
    ],
  })
  charts.push(chart)
}

function renderCategory() {
  if (!categoryRef.value) return
  const chart = echarts.init(categoryRef.value)
  chart.setOption({
    tooltip: { trigger: 'item', formatter: '{b}: {c} 次 ({d}%)' },
    legend: { bottom: 0, type: 'scroll' },
    series: [{
      type: 'pie', radius: ['38%', '62%'], center: ['50%', '44%'],
      label: { formatter: '{b}\n{d}%', fontSize: 11 },
      data: data.value.category_dist || [],
    }],
  })
  charts.push(chart)
}

function renderDocHeat() {
  if (!docHeatRef.value) return
  const chart = echarts.init(docHeatRef.value)
  const docs = [...(data.value.doc_heat || [])].reverse()
  chart.setOption({
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
    grid: { left: 200, right: 40, bottom: 20, top: 10 },
    xAxis: { type: 'value', minInterval: 1 },
    yAxis: {
      type: 'category',
      data: docs.map(d => d.title),
      axisLabel: { width: 190, overflow: 'truncate', fontSize: 11 },
    },
    series: [{
      type: 'bar', barWidth: 14,
      data: docs.map(d => d.count),
      itemStyle: { color: '#409eff', borderRadius: [0, 4, 4, 0] },
      label: { show: true, position: 'right' },
    }],
  })
  charts.push(chart)
}

function renderSatisfaction() {
  if (!satisfactionRef.value || !data.value.satisfaction_trend?.length) return
  const chart = echarts.init(satisfactionRef.value)
  const st = data.value.satisfaction_trend
  const step = Math.max(1, Math.ceil(st.length / 10))
  chart.setOption({
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'line', lineStyle: { color: '#c0c4cc' } },
      formatter: (params) => {
        let html = `<div style="font-weight:600;margin-bottom:6px">${params[0].axisValue}</div>`
        for (const p of params) {
          const unit = p.seriesName === '好评率' ? '%' : ' 次'
          html += `<div style="display:flex;align-items:center;margin:3px 0">${p.marker}${p.seriesName}<b style="margin-left:16px;padding-left:12px">${p.value}${unit}</b></div>`
        }
        return html
      },
    },
    legend: { data: ['👍 赞', '👎 踩', '好评率'], top: 4 },
    grid: { left: 45, right: 55, bottom: 32, top: 44 },
    xAxis: {
      type: 'category',
      data: st.map(s => s.date),
      axisLabel: { interval: step - 1, color: '#606266' },
    },
    yAxis: [
      { type: 'value', name: '次数', minInterval: 1, splitLine: { lineStyle: { type: 'dashed', color: '#ebeef5' } } },
      { type: 'value', name: '好评率 %', max: 100, splitLine: { show: false }, axisLabel: { formatter: '{value}%' } },
    ],
    series: [
      { name: '👍 赞', type: 'bar', data: st.map(s => s.pos), itemStyle: { color: '#67c23a' }, barWidth: 18 },
      { name: '👎 踩', type: 'bar', data: st.map(s => s.neg), itemStyle: { color: '#f56c6c' }, barWidth: 18 },
      {
        name: '好评率', type: 'line', smooth: true, yAxisIndex: 1,
        data: st.map(s => s.rate), itemStyle: { color: '#409eff' },
      },
    ],
  })
  charts.push(chart)
}

function handleResize() {
  charts.forEach(c => c.resize())
}

async function loadData() {
  loading.value = true
  try {
    const res = await api.getDashboardFull()
    data.value = res.data
    await nextTick()
    renderTrend()
    renderCategory()
    renderDocHeat()
    renderSatisfaction()
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  loadData()
  window.addEventListener('resize', handleResize)
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', handleResize)
  charts.forEach(c => c.dispose())
  charts = []
})
</script>
