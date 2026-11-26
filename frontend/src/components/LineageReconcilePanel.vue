<template>
  <section class="lineage-recon" data-testid="lineage-reconciliation-panel">
    <!-- 从标识交叉映射的分歧入口跳转过来：并列旧边/新边并办理 -->
    <article v-if="disagreement" class="lr-card focus-card" data-testid="lineage-disposition">
      <h3>血缘入口 · 分歧处置 {{ disagreement.code }}</h3>
      <p class="muted">{{ disagreement.title }}</p>
      <p class="muted small">
        实际关联原发出批次 <strong>{{ disagreement.original_package_code }}</strong>
        ｜ 映射批次 {{ disagreement.mapping_batch }}
      </p>
      <p v-if="disagreement.recommendation_reason && String(disagreement.status).startsWith('待')"
         class="recommend-text" data-testid="lineage-recommend">
        办理判断：{{ disagreement.recommendation_reason }}
      </p>

      <div class="edge-compare">
        <div class="edge-box old" data-testid="old-edge">
          <span class="edge-tag">文件所指旧边</span>
          <strong>{{ trace?.old_edge?.['血缘边标识'] || disagreement.old_edge_code }}</strong>
          <span>{{ disagreement.source_id }} → {{ disagreement.delivered_golden }}</span>
          <span class="badge pending">
            {{ trace?.old_edge?.['status'] || '失效' }}
          </span>
          <span class="small muted">{{ trace?.old_edge?.['撤回原因'] || '原映射已撤回，可作为历史结账凭证' }}</span>
          <span v-if="trace?.old_edge?.['historical_settled']"
                class="ok-text small" data-testid="old-edge-voucher">
            已沿原凭证历史结账：{{ trace?.old_edge?.['settlement_voucher'] }}
          </span>
        </div>
        <div class="edge-box new" data-testid="new-edge">
          <span class="edge-tag">目前可用新边</span>
          <strong>{{ trace?.new_edge?.['血缘边标识'] || disagreement.new_edge_code }}</strong>
          <span>{{ disagreement.source_id }} → {{ disagreement.current_golden }}</span>
          <span class="badge applied">{{ trace?.new_edge?.['status'] || '已登记' }} · 可用</span>
          <span class="small muted">{{ trace?.message }}</span>
        </div>
      </div>

      <p v-if="resultMessage" class="ok-text" data-testid="lineage-handle-message">{{ resultMessage }}</p>
      <p v-if="errorMessage" class="error-text">{{ errorMessage }}</p>

      <div v-if="String(disagreement.status).startsWith('待')" class="btn-row">
        <button class="btn" type="button" data-testid="lineage-decision-historical"
                @click="handle('historical')">
          沿原凭证对历史结账
        </button>
        <button class="btn primary" type="button" data-testid="lineage-decision-new-package"
                @click="handle('new_package')">
          换用新包
        </button>
      </div>
      <p v-else class="ok-text" data-testid="lineage-disposition-done">
        该分歧已办理：{{ disagreement.status }} — {{ disagreement.resolution }}
      </p>

      <div class="btn-row">
        <button type="button" class="btn ghost" data-testid="back-to-id-cross-map" @click="goBack">
          返回标识交叉映射核对意见
        </button>
      </div>
    </article>

    <!-- 血缘追溯按回导的映射明细校验来源 -->
    <article class="lr-card" data-testid="reimport-verify-card">
      <h3>按回导映射明细校验来源与血缘</h3>
      <div class="verify-form">
        <label>
          <span>源标识</span>
          <input v-model="sourceId" data-testid="reimport-source-id" placeholder="CRM-7" />
        </label>
        <label>
          <span>回导交付版金记录</span>
          <input v-model="deliveredGolden" data-testid="reimport-delivered-golden" placeholder="G9" />
        </label>
        <button class="btn primary" type="button" data-testid="verify-reimport" @click="verify">
          按回导明细校验来源
        </button>
      </div>
      <div v-if="trace" class="trace-result" data-testid="reimport-trace">
        <p :class="trace.source_valid ? 'ok-text' : 'error-text'">
          {{ trace.source_valid ? '✓ 来源校验通过' : '✗ 来源校验未通过' }}：{{ trace.message }}
        </p>
        <div class="edge-compare">
          <div class="edge-box old" data-testid="trace-old-edge">
            <span class="edge-tag">文件所指旧边</span>
            <strong>{{ edgeText(trace.old_edge, '血缘边标识') || '未找到' }}</strong>
            <span v-if="trace.old_edge">
              {{ edgeText(trace.old_edge, '上游节点') }} → {{ edgeText(trace.old_edge, '下游节点') }}
              （{{ edgeText(trace.old_edge, 'status') }}）
            </span>
          </div>
          <div class="edge-box new" data-testid="trace-new-edge">
            <span class="edge-tag">目前可用新边</span>
            <strong>{{ edgeText(trace.new_edge, '血缘边标识') || '未找到' }}</strong>
            <span v-if="trace.new_edge">
              {{ edgeText(trace.new_edge, '上游节点') }} → {{ edgeText(trace.new_edge, '下游节点') }}
              （{{ edgeText(trace.new_edge, 'status') }}）
            </span>
          </div>
        </div>
      </div>
    </article>
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import {
  fetchLineageTrace,
  fetchReconState,
  handleDisagreement,
  type Disagreement,
  type LineageTrace,
} from '@/api/reconciliation'

const route = useRoute()
const router = useRouter()
const disagreement = ref<Disagreement | null>(null)
const trace = ref<LineageTrace | null>(null)
const sourceId = ref('CRM-7')
const deliveredGolden = ref('G9')
const resultMessage = ref('')
const errorMessage = ref('')

function edgeText(edge: Record<string, unknown> | null, key: string): string {
  if (!edge) return ''
  const value = edge[key]
  return value === undefined || value === null ? '' : String(value)
}

async function loadDisagreement(code: string): Promise<void> {
  try {
    const state = await fetchReconState()
    disagreement.value = state.disagreements.find((d) => d.code === code) ?? null
    const querySource = typeof route.query.source_id === 'string' ? route.query.source_id : ''
    const queryDelivered = typeof route.query.delivered === 'string' ? route.query.delivered : ''
    if (disagreement.value) {
      sourceId.value = querySource || disagreement.value.source_id
      deliveredGolden.value = queryDelivered || disagreement.value.delivered_golden
    }
    await verify()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '分歧信息读取失败'
  }
}

async function verify(): Promise<void> {
  errorMessage.value = ''
  try {
    trace.value = await fetchLineageTrace(sourceId.value, deliveredGolden.value)
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '血缘校验失败'
  }
}

async function handle(decision: 'historical' | 'new_package'): Promise<void> {
  if (!disagreement.value) return
  const result = await handleDisagreement(disagreement.value.code, decision)
  if (!result.ok) {
    errorMessage.value = result.message
    return
  }
  resultMessage.value = result.message
  await loadDisagreement(disagreement.value.code)
}

function goBack(): void {
  const returnCode = disagreement.value?.return_package_code
  void router.push({
    path: '/id_cross_map',
    query: returnCode ? { batch: returnCode } : {},
  })
}

onMounted(async () => {
  const code = typeof route.query.disagreement === 'string' ? route.query.disagreement : ''
  const focus = typeof route.query.focus === 'string' ? route.query.focus : ''
  if (code) {
    await loadDisagreement(code)
  } else if (focus) {
    sourceId.value = focus
    deliveredGolden.value = ''
    await verify()
  } else {
    // 直接从侧边栏进入血缘图时，也立即给出场景的旧边/新边校验结果。
    await verify()
  }
})

watch(
  () => route.query.disagreement,
  (code) => {
    if (typeof code === 'string' && code) void loadDisagreement(code)
  },
)
</script>

<style scoped>
.lineage-recon { display: flex; flex-direction: column; gap: 12px; margin: 12px 0; }
.lr-card { background: #fff; border: 1px solid var(--border); border-radius: 10px; padding: 14px 16px; }
.focus-card { border-left: 4px solid var(--brand); }
.lr-card h3 { margin: 0 0 8px; font-size: 15px; }
.muted { color: var(--muted); }
.small { font-size: 12.5px; }
.recommend-text { background: #eff8ff; border: 1px solid #b2ddff; color: #1849a9; border-radius: 6px; padding: 7px 10px; font-size: 12.5px; }
.btn-row { display: flex; gap: 8px; flex-wrap: wrap; margin-top: 10px; align-items: center; }
.verify-form { display: flex; gap: 10px; align-items: flex-end; flex-wrap: wrap; }
.verify-form label { display: flex; flex-direction: column; gap: 4px; font-size: 12px; color: var(--muted); }
.verify-form input { border: 1px solid var(--border); border-radius: 6px; padding: 7px 9px; font-size: 13px; min-width: 200px; }
.edge-compare { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin: 10px 0; }
@media (max-width: 900px) { .edge-compare { grid-template-columns: 1fr; } }
.edge-box { border-radius: 8px; padding: 10px 12px; display: flex; flex-direction: column; gap: 4px; font-size: 13px; }
.edge-box.old { background: #fffaeb; border: 1px solid #fedf89; }
.edge-box.new { background: #ecfdf3; border: 1px solid #abefc6; }
.edge-tag { font-size: 11px; color: var(--muted); }
.badge { display: inline-block; align-self: flex-start; border-radius: 999px; padding: 2px 10px; font-size: 12px; }
.badge.applied { background: #dcfae6; color: #067647; }
.badge.pending { background: #fef0c7; color: #b54708; }
.ok-text { color: #067647; font-size: 13.5px; }
.error-text { color: #b42318; font-size: 13px; }
.trace-result { margin-top: 10px; }
</style>
