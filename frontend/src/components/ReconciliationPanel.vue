<template>
  <section class="recon-panel" data-testid="reconciliation-panel" aria-label="标识交叉映射对账工作台">
    <div class="recon-head">
      <h3>对账下载与回传确认</h3>
      <p class="recon-tip">
        下载只包含申请方自己的实体与来源原标识；两个系统共用同一金记录时，
        不会带出对方的原标识。每份发出文件冻结唯一映射依据，回传按交付版确认。
      </p>
    </div>

    <!-- 1. 下载 / 回传入口 -->
    <div class="recon-grid">
      <article class="recon-card" data-testid="recon-download-card">
        <h4>① 对账下载</h4>
        <label class="recon-field">
          <span>申请方来源系统</span>
          <select v-model="source" data-testid="recon-source">
            <option v-for="s in state?.sources ?? []" :key="s.code" :value="s.code">
              {{ s.code }} · {{ s.name }}（{{ s.status }}）
            </option>
          </select>
        </label>
        <div class="recon-btn-row">
          <button class="btn primary" type="button" data-testid="recon-download"
                  :disabled="busy" @click="onDownloadCurrent">
            对账下载
          </button>
          <span class="muted small">按所选申请方下载当前交付版；原 CRM-7→G9 档请点下方批次</span>
          <button class="btn ghost" type="button" data-testid="recon-load-late"
                  @click="loadLateSample">
            载入迟到旧档（CRM-7→G9）
          </button>
          <button class="btn ghost" type="button" data-testid="recon-reset"
                  @click="onReset">
            重置演练场景
          </button>
        </div>
        <p v-if="downloadError" class="error-text" data-testid="recon-download-error">{{ downloadError }}</p>

        <ul class="sent-list" data-testid="sent-package-list">
          <li v-for="p in sentPackages" :key="p.code" :data-testid="`sent-item-${p.code}`">
            <div class="sent-meta">
              <strong>{{ p.code }}</strong>
              <span>{{ p.title }}</span>
              <span class="muted">{{ p.basis_label || p.basis }} · 发出 {{ p.sent_at }}</span>
            </div>
            <button class="btn" type="button" :data-testid="`download-package-${p.code}`"
                    @click="onDownloadPackage(p.code)">
              {{ p.code === originalPackageCode ? '下载 CRM-7→G9 原档' : '下载该发出档' }}
            </button>
          </li>
        </ul>
      </article>

      <article class="recon-card" data-testid="recon-return-card">
        <h4>② 填意见后回传确认</h4>
        <label class="recon-field">
          <span>选择填好意见的核对文件（CSV / JSON / TXT）</span>
          <input ref="fileInput" type="file" accept=".csv,.json,.txt"
                 data-testid="recon-file-input" @change="onFileChange" />
        </label>
        <label class="recon-field">
          <span>或直接粘贴核对内容（CSV 文本 / JSON）</span>
          <textarea v-model="pasted" rows="4" data-testid="recon-paste"
                    placeholder="源标识,金记录标识,核对意见&#10;CRM-7,G9,无误&#10;CRM-8,G12,无误"></textarea>
        </label>
        <div class="recon-btn-row">
          <button class="btn" type="button" data-testid="recon-paste-preview" @click="previewPasted">
            预览粘贴内容
          </button>
          <button class="btn primary" type="button" data-testid="recon-commit"
                  :disabled="committing" @click="onCommit">
            {{ committing ? '回传核对中…' : '回传确认' }}
          </button>
          <span class="muted small">选择文件后点此上传并按交付版核对</span>
        </div>
        <p v-if="notice" class="notice-text" data-testid="recon-notice">{{ notice }}</p>
        <p v-if="errorMessage" class="error-text" data-testid="recon-error">{{ errorMessage }}</p>
      </article>
    </div>

    <!-- 2. 回传预览：一条已变化 + 一条仍有效 -->
    <article v-if="preview" class="recon-card preview-card" data-testid="recon-preview">
      <h4>③ 回传预览 · 按交付版确认</h4>
      <p class="preview-summary" data-testid="recon-preview-summary">
        共 {{ preview.summary?.total ?? preview.rows.length }} 条：
        <strong class="badge changed">已变化 {{ preview.summary?.changed ?? 0 }} 条</strong>
        <strong class="badge valid">仍有效 {{ preview.summary?.still_valid ?? 0 }} 条</strong>
        <span v-if="preview.original_package_code" class="muted">
          匹配原发出批次 {{ preview.original_package_code }}（依据 {{ preview.basis }}）
        </span>
      </p>
      <table class="data-table preview-table">
        <thead>
          <tr>
            <th>源标识</th>
            <th>交付版金记录</th>
            <th>当前实际金记录</th>
            <th>关系核对</th>
            <th>交付版确认</th>
            <th>来源/发布资格</th>
            <th>核对意见</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in preview.rows" :key="String(row.source_id)"
              :data-testid="`preview-row-${row.source_id}`">
            <td>{{ row.source_id }}</td>
            <td>{{ row.delivered_golden }}</td>
            <td data-testid="preview-actual-golden">{{ row.current_golden || '—' }}</td>
            <td>
              <span v-if="row.relation_state === 'still_valid'"
                    class="badge valid" data-testid="relation-valid">仍有效</span>
              <span v-else-if="row.relation_state === 'changed'"
                    class="badge changed" data-testid="relation-changed">
                已变化 · 合法更正 {{ row.delivered_golden }}→{{ row.current_golden }}
              </span>
              <span v-else class="badge unknown">{{ row.relation_label }}</span>
              <div class="muted small">{{ row.relation_label }}</div>
            </td>
            <td>
              <span :class="row.version_confirmed ? 'ok-text' : 'warn-text'">
                {{ row.version_confirmed ? '✓ ' : '' }}{{ row.version_message }}
              </span>
            </td>
            <td>
              <span :class="row.source_ok ? 'ok-text' : 'error-text'">
                {{ row.source_ok ? '来源核对通过' : '来源不符' }}
              </span>
              <div class="muted small">
                {{ row.current_publish_status || row.delivered_publish_status }}
              </div>
              <div v-for="msg in row.source_messages" :key="msg" class="warn-text small">{{ msg }}</div>
            </td>
            <td>{{ row.opinion || '（空意见）' }}<div class="muted small">{{ row.opinion_note }}</div></td>
          </tr>
        </tbody>
      </table>
      <div class="recon-btn-row">
        <button class="btn primary" type="button" data-testid="recon-confirm-commit"
                :disabled="committing" @click="onCommit">
          确认回传并登记
        </button>
        <button class="btn" type="button" data-testid="recon-submit"
                :disabled="committing" @click="onCommit">
          提交核对结果
        </button>
      </div>
    </article>

    <!-- 3. 实际金记录查询 -->
    <article class="recon-card" data-testid="actual-golden-card">
      <h4>同一映射批次回导后 · 查询实际对应的金记录</h4>
      <div class="recon-btn-row">
        <input v-model="goldenQuery" class="recon-input" data-testid="actual-golden-input"
               placeholder="输入源标识，如 CRM-7" @keyup.enter="queryActualGolden" />
        <button class="btn" type="button" data-testid="actual-golden-query" @click="queryActualGolden">
          查询实际对应金记录
        </button>
        <button class="btn ghost" type="button" data-testid="goto-lineage-graph"
                @click="goLineageFocus">
          进入血缘关系图核对
        </button>
      </div>
      <div v-if="actualGolden" class="actual-result" data-testid="actual-golden-result">
        <template v-if="actualGolden.ok">
          <strong>{{ actualGolden.source_id }}</strong>
          当前实际对应金记录：
          <strong class="golden-id" data-testid="actual-golden-id">{{ actualGolden.actual_golden }}</strong>
          <span class="muted">
            （映射批次 {{ actualGolden.mapping_batch }} · 边 {{ actualGolden.edge_code }} ·
            发布状态 {{ actualGolden.publish_status }}）
          </span>
        </template>
        <span v-else class="warn-text">{{ actualGolden.message }}</span>
      </div>
    </article>

    <!-- 4. 对账批次：原发出批次关联 + 实际采纳意见 + 分歧 -->
    <article class="recon-card" data-testid="recon-batches">
      <h4>对账批次 · 实际采纳的意见</h4>
      <div class="batch-layout">
        <ul class="batch-list">
          <li v-for="p in allPackages" :key="p.code">
            <button type="button" class="batch-item"
                    :class="{ active: selectedCode === p.code }"
                    :data-testid="`recon-batch-${p.code}`"
                    @click="openPackage(p.code)">
              <span class="batch-code">{{ p.code }}</span>
              <span class="batch-tags">
                <span class="tag" :data-direction="p.direction">
                  {{ p.direction === 'sent' ? '发出档' : '回传档' }}
                </span>
                <span class="tag status" :data-status="p.status">{{ p.status }}</span>
                <span v-if="p.duplicate" class="tag dup">重复提交</span>
              </span>
              <span class="muted small">
                {{ p.source_system }} · 待确认 {{ p.pending_count ?? 0 }} ·
                已作用 {{ p.applied_count ?? 0 }}
                <template v-if="p.original_package_code"> · 原发出 {{ p.original_package_code }}</template>
              </span>
            </button>
          </li>
          <li v-if="!allPackages.length" class="muted">暂无对账批次</li>
        </ul>

        <div v-if="detail" class="batch-detail" data-testid="recon-batch-detail">
          <header class="detail-head">
            <h5>{{ detail.code }} · {{ detail.title }}</h5>
            <p class="muted small">
              映射批次 {{ detail.mapping_batch }} ｜ 映射依据 {{ detail.basis }}
              <template v-if="detail.original_package_code">
                ｜ <strong>实际关联原发出批次：{{ detail.original_package_code }}</strong>
              </template>
              <template v-if="detail.resubmit_count">
                ｜ 重复提交 {{ detail.resubmit_count }} 次（分歧不重复登记）
              </template>
            </p>
          </header>

          <p class="status-legend" data-testid="opinion-status-legend">
            状态区分：仍待确认的意见标记为
            <span class="badge pending">待确认</span>
            ；核对相符或已换用新包的意见标记为
            <span class="badge applied">已作用到关系</span>
            ；沿原凭证结账的意见标记为
            <span class="badge historical">已历史结账</span>
            。关闭页面再打开，这些状态仍按对账批次保留。
          </p>

          <table class="data-table opinion-table">
            <thead>
              <tr>
                <th>源标识</th><th>交付版→当前</th><th>核对意见</th>
                <th>意见状态（重开页面仍保留）</th><th>操作</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="item in detail.items ?? []" :key="item.opinion_id || item.item_code"
                  :data-testid="`opinion-row-${item.source_id}`">
                <td>{{ item.source_id }}</td>
                <td>{{ item.delivered_golden }} → {{ item.current_golden || item.delivered_golden }}</td>
                <td>{{ item.opinion || '—' }}<div class="muted small">{{ item.opinion_note }}</div></td>
                <td>
                  <span class="badge" :class="statusClass(item.opinion_status)"
                        :data-testid="`opinion-status-${item.opinion_id || item.source_id}`">
                    {{ item.opinion_status }}
                  </span>
                </td>
                <td class="row-actions">
                  <button v-if="item.opinion_status === '待确认'" class="link" type="button"
                          :data-testid="`adopt-opinion-${item.opinion_id || item.source_id}`"
                          @click="onAdopt(item.opinion_id || '', true)">
                    采纳并作用到关系
                  </button>
                  <button v-if="item.disagreement_id" class="link" type="button"
                          :data-testid="`lineage-disposition-${item.disagreement_id}`"
                          @click="goDisposition(String(item.disagreement_id), item)">
                    从血缘入口继续分歧处置
                  </button>
                </td>
              </tr>
            </tbody>
          </table>

          <div class="adopted-box" data-testid="adopted-opinions">
            <h6>实际采纳的意见（已作用到关系）</h6>
            <ul v-if="detail.adopted_opinions?.length">
              <li v-for="a in detail.adopted_opinions" :key="String(a.opinion_id)"
                  :data-testid="`adopted-${a.source_id}`">
                <strong>{{ a.source_id }}</strong> 采纳意见「{{ a.opinion || a.opinion_note || '核对相符' }}」
                → 实际金记录 <strong>{{ a.actual_golden }}</strong>
                <span class="badge applied">已作用到关系</span>
              </li>
            </ul>
            <p v-else class="muted small">暂无已采纳并作用到关系的意见。</p>
          </div>
        </div>
      </div>
    </article>

    <!-- 5. 分歧列表与处置 -->
    <article v-for="d in state?.disagreements ?? []" :key="d.code"
             class="recon-card disagreement-card" :data-testid="`disagreement-${d.code}`">
      <div class="disagreement-head">
        <h4>分歧 {{ d.code }}：{{ d.title }}</h4>
        <span class="badge" :class="disputeStatusClass(d.status)"
              :data-testid="`disagreement-status-${d.code}`">{{ d.status }}</span>
      </div>
      <p class="muted small">
        来源 {{ d.source_system }} ｜ 实际关联原发出批次
        <strong>{{ d.original_package_code }}</strong> ｜ 映射批次 {{ d.mapping_batch }}
        ｜ 同一文件重复提交 {{ d.resubmit_count }} 次，分歧只确认一次
      </p>
      <p v-if="d.recommendation_reason && String(d.status).startsWith('待')"
         class="recommend-text" :data-testid="`recommend-${d.code}`">
        办理判断：{{ d.recommendation_reason }}
      </p>
      <div class="edge-compare">
        <div class="edge-box old" data-testid="disagreement-old-edge">
          <span class="edge-tag">文件所指旧边</span>
          <strong>{{ d.old_edge_code }}</strong>
          <span>{{ d.source_id }} → {{ d.delivered_golden }}（已撤回/失效，可作历史凭证）</span>
        </div>
        <div class="edge-box new" data-testid="disagreement-new-edge">
          <span class="edge-tag">目前可用新边</span>
          <strong>{{ d.new_edge_code }}</strong>
          <span>{{ d.source_id }} → {{ d.current_golden }}（已登记，发布资格有效）</span>
        </div>
      </div>
      <p v-if="d.resolution" class="ok-text" data-testid="disagreement-resolution">
        办理结果：{{ d.resolution }}<br />
        <span class="muted">凭证：{{ d.resolution_voucher }}</span>
      </p>
      <div v-if="String(d.status).startsWith('待')" class="recon-btn-row">
        <button class="btn" type="button" :data-testid="`decision-historical-${d.code}`"
                @click="onHandle(d.code, 'historical')">
          沿原凭证对历史结账
        </button>
        <button class="btn primary" type="button" :data-testid="`decision-new-package-${d.code}`"
                @click="onHandle(d.code, 'new_package')">
          换用新包（{{ d.new_package_code }}）
        </button>
        <button class="btn ghost" type="button" :data-testid="`goto-lineage-${d.code}`"
                @click="goDisposition(d.code)">
          进入血缘关系图核对
        </button>
      </div>
    </article>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import {
  fetchActualGolden as fetchActualGoldenApi,
  adoptOpinion,
  commitRecon,
  downloadReconCsv,
  fetchPackage,
  fetchReconState,
  handleDisagreement,
  previewRecon,
  resetScenario,
  type CommitResult,
  type Disagreement,
  type PreviewResult,
  type ReconPackageSummary,
  type ReconState,
} from '@/api/reconciliation'

const LATE_STORAGE_KEY = 'icm-recon-selected-batch'

const route = useRoute()
const router = useRouter()

const state = ref<ReconState | null>(null)
const source = ref('CRM')
const selectedCode = ref('')
const detail = ref<ReconPackageSummary | null>(null)
const preview = ref<PreviewResult | null>(null)
const pasted = ref('')
const fileInput = ref<HTMLInputElement | null>(null)
const pending = ref<{ source: string; file_name: string; content: string } | null>(null)
const busy = ref(false)
const committing = ref(false)
const notice = ref('')
const errorMessage = ref('')
const downloadError = ref('')
const goldenQuery = ref('CRM-7')
const actualGolden = ref<Record<string, unknown> | null>(null)

const sentPackages = computed(() => (state.value?.packages ?? []).filter((p) => p.direction === 'sent'))
const allPackages = computed(() => state.value?.packages ?? [])
const originalPackageCode = computed(() => state.value?.original_package ?? 'REC-20261120-CRM-V1')

function statusClass(status?: string): string {
  if (status === '已作用到关系') return 'applied'
  if (status === '已历史结账') return 'historical'
  return 'pending'
}

function disputeStatusClass(status?: string): string {
  return String(status ?? '').startsWith('待') ? 'pending' : 'applied'
}

async function loadState(): Promise<void> {
  state.value = await fetchReconState()
  if (!state.value.sources.some((s) => s.code === source.value) && state.value.sources[0]) {
    source.value = state.value.sources[0].code
  }
}

async function openPackage(code: string): Promise<void> {
  selectedCode.value = code
  window.localStorage.setItem(LATE_STORAGE_KEY, code)
  try {
    detail.value = await fetchPackage(code)
    await router.replace({ query: { ...route.query, batch: code } })
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '批次读取失败'
  }
}

async function onDownloadCurrent(): Promise<void> {
  downloadError.value = ''
  busy.value = true
  try {
    await downloadReconCsv(source.value)
    notice.value = `已生成 ${source.value} 申请方的对账下载，文件只含该来源的实体与原标识。`
  } catch (error) {
    downloadError.value = error instanceof Error ? error.message : '对账下载失败'
  } finally {
    busy.value = false
  }
}

async function onDownloadPackage(code: string): Promise<void> {
  downloadError.value = ''
  const pkg = state.value?.packages.find((p) => p.code === code)
  try {
    await downloadReconCsv(pkg?.source_system || source.value, code)
  } catch (error) {
    downloadError.value = error instanceof Error ? error.message : '对账下载失败'
  }
}

async function readFile(file: File): Promise<string> {
  return await file.text()
}

async function onFileChange(event: Event): Promise<void> {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  if (!file) return
  errorMessage.value = ''
  const content = await readFile(file)
  pending.value = { source: source.value, file_name: file.name, content }
  await runPreview(pending.value)
}

async function previewPasted(): Promise<void> {
  if (!pasted.value.trim()) {
    errorMessage.value = '请先粘贴核对内容，或选择核对文件'
    return
  }
  pending.value = { source: source.value, file_name: 'pasted.csv', content: pasted.value }
  await runPreview(pending.value)
}

async function runPreview(payload: { source: string; file_name: string; content: string }): Promise<void> {
  errorMessage.value = ''
  try {
    preview.value = await previewRecon(payload)
    if (preview.value.ok === false) {
      errorMessage.value = preview.value.message || '预览核对失败'
    }
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '预览核对失败'
  }
}

async function onCommit(): Promise<void> {
  errorMessage.value = ''
  notice.value = ''
  let payload = pending.value
  if (!payload && pasted.value.trim()) {
    payload = { source: source.value, file_name: 'pasted.csv', content: pasted.value }
  }
  if (!payload) {
    // 没有可提交内容时，把“回传确认”当作选文件入口，兼容 filechooser 交互。
    errorMessage.value = '请先选择填好意见的核对文件，或粘贴核对内容'
    fileInput.value?.click()
    return
  }
  committing.value = true
  try {
    const result: CommitResult = await commitRecon(payload)
    if (!result.ok) {
      errorMessage.value = result.message || '回传确认失败'
      return
    }
    notice.value = result.duplicate ? `重复提交已识别：${result.message}` : result.message || '回传完成'
    preview.value = result.verification ?? preview.value
    pending.value = payload
    await loadState()
    if (result.package?.code) await openPackage(result.package.code)
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '回传确认失败'
  } finally {
    committing.value = false
  }
}

async function onAdopt(opinionId: string, adopted: boolean): Promise<void> {
  if (!opinionId) return
  const result = await adoptOpinion(opinionId, adopted)
  notice.value = result.message || '意见已处理'
  await loadState()
  if (selectedCode.value) detail.value = await fetchPackage(selectedCode.value)
}

async function onHandle(code: string, decision: string): Promise<void> {
  errorMessage.value = ''
  try {
    const result = await handleDisagreement(code, decision)
    if (!result.ok) {
      errorMessage.value = result.message
      return
    }
    notice.value = result.message
    await loadState()
    if (selectedCode.value) detail.value = await fetchPackage(selectedCode.value)
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '分歧办理失败'
  }
}

async function queryActualGolden(): Promise<void> {
  try {
    actualGolden.value = await fetchActualGoldenApi(goldenQuery.value.trim() || 'CRM-7')
  } catch (error) {
    actualGolden.value = { ok: false, message: error instanceof Error ? error.message : '实际金记录查询失败' }
  }
}

function goDisposition(code: string, item?: { source_id?: string }): void {
  const d: Disagreement | undefined = state.value?.disagreements.find((x) => x.code === code)
  void router.push({
    path: '/lineage_graph',
    query: {
      disagreement: code,
      source_id: item?.source_id || d?.source_id || 'CRM-7',
      delivered: d?.delivered_golden || 'G9',
      batch: d?.original_package_code || '',
    },
  })
}

function goLineageFocus(): void {
  void router.push({ path: '/lineage_graph', query: { focus: goldenQuery.value || 'CRM-7' } })
}

async function loadLateSample(): Promise<void> {
  // 构造下游在 V1 交付档上填完意见后迟到的旧档。
  const content = [
    '行号,核对行标识,对账批次,映射依据,映射批次,申请方来源,实体编码,实体名称,源标识,交付版金记录标识,交付版发布状态,核对意见,意见说明,建议金记录标识,校验码',
    '1,REC-20261120-CRM-V1-1,REC-20261120-CRM-V1,MAP-202611-CRM@v1,MAP-202611-CRM,CRM,CUSTOMER,客户,CRM-7,G9,已撤回,无误,我方按交付版核对CRM-7即G9,,rt-CRM7-G9-v1',
    '2,REC-20261120-CRM-V1-2,REC-20261120-CRM-V1,MAP-202611-CRM@v1,MAP-202611-CRM,CRM,CUSTOMER,客户,CRM-8,G12,已发布,无误,,,rt-CRM8-G12-v1',
  ].join('\n')
  source.value = 'CRM'
  pending.value = { source: 'CRM', file_name: 'late_REC-20261120-CRM-V1.csv', content }
  pasted.value = content
  await runPreview(pending.value)
}

async function onReset(): Promise<void> {
  await resetScenario()
  preview.value = null
  detail.value = null
  selectedCode.value = ''
  notice.value = '演练场景已重置：CRM-7→G9 原发出档 V1、更正后新包 V2 已就绪。'
  window.localStorage.removeItem(LATE_STORAGE_KEY)
  await loadState()
}

onMounted(async () => {
  try {
    await loadState()
    await queryActualGolden()
    const queryBatch = typeof route.query.batch === 'string' ? route.query.batch : ''
    const stored = window.localStorage.getItem(LATE_STORAGE_KEY) || ''
    const code = queryBatch || stored
    if (code && state.value?.packages.some((p) => p.code === code)) {
      await openPackage(code)
    } else {
      const latestReturned = state.value?.packages.find((p) => p.direction === 'returned')
      if (latestReturned) await openPackage(latestReturned.code)
    }
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '对账工作台初始化失败'
  }
})
</script>

<style scoped>
.recon-panel {
  background: #f8fafc;
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 14px 16px;
  margin: 12px 0 16px;
}
.recon-head h3 { margin: 0 0 4px; font-size: 16px; }
.recon-tip { margin: 0 0 12px; color: var(--muted); font-size: 12.5px; line-height: 1.6; }
.recon-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
@media (max-width: 1100px) { .recon-grid { grid-template-columns: 1fr; } }
.recon-card {
  background: #fff; border: 1px solid var(--border); border-radius: 8px;
  padding: 12px 14px; margin-bottom: 12px;
}
.recon-grid .recon-card { margin-bottom: 0; }
.recon-card h4 { margin: 0 0 10px; font-size: 14px; }
.recon-card h5 { margin: 0 0 6px; font-size: 13.5px; }
.recon-card h6 { margin: 10px 0 6px; font-size: 13px; }
.recon-field { display: flex; flex-direction: column; gap: 4px; font-size: 12.5px; margin-bottom: 10px; }
.recon-field span { color: var(--muted); }
.recon-field select, .recon-field textarea, .recon-input {
  border: 1px solid var(--border); border-radius: 6px; padding: 7px 9px; font-size: 13px; font-family: inherit;
}
.recon-input { min-width: 240px; }
.recon-btn-row { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; margin: 6px 0; }
.sent-list, .batch-list { list-style: none; margin: 10px 0 0; padding: 0; display: flex; flex-direction: column; gap: 8px; }
.sent-list li { display: flex; justify-content: space-between; gap: 10px; align-items: center; border-top: 1px dashed var(--border); padding-top: 8px; }
.sent-meta { display: flex; flex-direction: column; gap: 2px; font-size: 12.5px; }
.muted { color: var(--muted); }
.small { font-size: 12px; }
.notice-text { color: #067647; font-size: 13px; margin: 6px 0 0; }
.error-text { color: #b42318; font-size: 13px; margin: 6px 0 0; }
.ok-text { color: #067647; font-size: 12.5px; }
.warn-text { color: #b54708; font-size: 12.5px; }
.preview-summary { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; font-size: 13px; }
.badge {
  display: inline-block; border-radius: 999px; padding: 2px 10px; font-size: 12px;
  background: #eef2f6; color: #475467; white-space: nowrap;
}
.badge.valid, .badge.applied { background: #dcfae6; color: #067647; }
.badge.changed, .badge.pending { background: #fef0c7; color: #b54708; }
.badge.historical { background: #e0e7ff; color: #3730a3; }
.badge.unknown { background: #fee4e2; color: #b42318; }
.preview-table, .opinion-table { margin-top: 8px; }
.batch-layout { display: grid; grid-template-columns: 320px 1fr; gap: 12px; }
@media (max-width: 1100px) { .batch-layout { grid-template-columns: 1fr; } }
.batch-item {
  width: 100%; text-align: left; background: #fff; border: 1px solid var(--border);
  border-radius: 8px; padding: 8px 10px; cursor: pointer; display: flex; flex-direction: column; gap: 4px;
}
.batch-item.active { border-color: var(--brand); box-shadow: 0 0 0 1px var(--brand) inset; }
.batch-code { font-weight: 600; font-size: 12.5px; }
.batch-tags { display: flex; gap: 6px; flex-wrap: wrap; }
.tag { font-size: 11px; border-radius: 4px; padding: 1px 7px; background: #eef2f6; color: #475467; }
.tag[data-direction='returned'] { background: #e0f2fe; color: #075985; }
.tag.dup { background: #fef0c7; color: #b54708; }
.batch-detail { border: 1px solid var(--border); border-radius: 8px; padding: 10px 12px; }
.detail-head { margin-bottom: 8px; }
.status-legend { font-size: 12.5px; color: #475467; background: #f8fafc; border: 1px dashed var(--border); border-radius: 6px; padding: 8px 10px; display: flex; gap: 6px; align-items: center; flex-wrap: wrap; margin: 0 0 10px; }
.adopted-box { margin-top: 12px; background: #f6fef9; border: 1px solid #abefc6; border-radius: 8px; padding: 8px 12px; }
.adopted-box ul { margin: 6px 0 0; padding-left: 18px; display: flex; flex-direction: column; gap: 6px; font-size: 13px; }
.actual-result { margin-top: 8px; font-size: 14px; }
.golden-id { color: #067647; font-size: 16px; }
.disagreement-card { border-left: 4px solid #f79009; }
.disagreement-head { display: flex; justify-content: space-between; align-items: center; gap: 10px; }
.disagreement-head h4 { margin: 0; }
.recommend-text { background: #eff8ff; border: 1px solid #b2ddff; color: #1849a9; border-radius: 6px; padding: 7px 10px; font-size: 12.5px; margin: 6px 0; }
.edge-compare { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin: 8px 0; }
@media (max-width: 900px) { .edge-compare { grid-template-columns: 1fr; } }
.edge-box { border-radius: 8px; padding: 9px 11px; display: flex; flex-direction: column; gap: 3px; font-size: 12.5px; }
.edge-box.old { background: #fffaeb; border: 1px solid #fedf89; }
.edge-box.new { background: #ecfdf3; border: 1px solid #abefc6; }
.edge-tag { font-size: 11px; color: var(--muted); }
</style>
