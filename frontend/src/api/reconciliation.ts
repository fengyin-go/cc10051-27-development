/** 标识交叉映射 · 对账下载/回传确认与血缘追溯接口封装。 */
import { request } from './client'

export type ReconSource = { code: string; name: string; status: string }

export type ReconItem = {
  line_no?: number
  opinion_id?: string
  item_code?: string
  source_system?: string
  entity_code?: string
  entity_name?: string
  source_id?: string
  delivered_golden?: string
  current_golden?: string
  relation_state?: string
  relation_label?: string
  mapping_batch?: string
  basis?: string
  opinion?: string
  opinion_note?: string
  suggested_golden?: string
  opinion_status?: string
  adopted?: boolean
  adopted_at?: string
  disagreement_id?: string
  version_confirmed?: boolean
  version_message?: string
  [key: string]: unknown
}

export type ReconPackageSummary = {
  id: number
  code: string
  title: string
  direction: 'sent' | 'returned' | string
  status: string
  source_system: string
  mapping_batch: string
  basis: string
  basis_label?: string
  file_name?: string
  sent_at?: string
  returned_at?: string
  original_package_code?: string
  new_package_code?: string
  content_hash?: string
  duplicate?: boolean
  resubmit_count?: number
  item_count?: number
  pending_count?: number
  applied_count?: number
  adopted_opinions?: Array<Record<string, unknown>>
  items?: ReconItem[]
}

export type Disagreement = {
  id: number
  code: string
  kind: string
  title: string
  source_system: string
  source_id: string
  delivered_golden: string
  current_golden: string
  old_edge_code: string
  new_edge_code: string
  original_package_code: string
  mapping_batch: string
  return_package_code: string
  new_package_code: string
  status: string
  confirmed_once: boolean
  recommended_decision?: string
  recommendation_reason?: string
  resubmit_count: number
  resolution?: string
  resolution_voucher?: string
  [key: string]: unknown
}

export type ReconState = {
  sources: ReconSource[]
  mapping_batch: string
  original_package: string
  new_package: string
  packages: ReconPackageSummary[]
  disagreements: Disagreement[]
  mappings: Array<Record<string, unknown>>
}

export type VerifyRow = ReconItem & {
  source_ok?: boolean
  source_messages?: string[]
  source_registered?: boolean
  old_edge_code?: string
  old_edge_status?: string
  new_edge_code?: string
  new_edge_status?: string
  opinion_kind?: string
}

export type PreviewResult = {
  ok: boolean
  message?: string
  source_system?: string
  source_registered?: boolean
  package_code?: string
  original_package_code?: string
  basis?: string
  mapping_batch?: string
  rows: VerifyRow[]
  summary?: { total: number; changed: number; still_valid: number; disputed: number }
}

export type CommitResult = {
  ok: boolean
  duplicate?: boolean
  message?: string
  package?: ReconPackageSummary
  verification?: PreviewResult
}

async function postJson<T>(path: string, body: unknown): Promise<T> {
  const response = await request(path, { method: 'POST', body: JSON.stringify(body ?? {}) })
  return (await response.json()) as T
}

export function fetchReconState(): Promise<ReconState> {
  return request('/api/id_cross_map/reconciliation/state').then((r) => r.json())
}

export function fetchPackage(code: string): Promise<ReconPackageSummary> {
  return request(`/api/id_cross_map/reconciliation/packages/${encodeURIComponent(code)}`).then((r) =>
    r.json(),
  )
}

export async function downloadReconCsv(source: string, packageCode = ''): Promise<void> {
  const query = new URLSearchParams({ source })
  if (packageCode) query.set('package_code', packageCode)
  const response = await request(`/api/id_cross_map/reconciliation/download?${query.toString()}`)
  if (!response.ok) {
    let detail = '对账下载失败'
    try {
      const data = await response.json()
      detail = data.detail || detail
    } catch {
      /* 保留默认提示 */
    }
    throw new Error(detail)
  }
  const url = URL.createObjectURL(await response.blob())
  const anchor = document.createElement('a')
  anchor.href = url
  const disposition = response.headers.get('Content-Disposition') ?? ''
  const matched = /filename="?([^"]+)"?/.exec(disposition)
  anchor.download = matched ? matched[1] : `reconciliation_${source}.csv`
  document.body.appendChild(anchor)
  anchor.click()
  document.body.removeChild(anchor)
  URL.revokeObjectURL(url)
}

export function previewRecon(body: {
  source?: string
  file_name?: string
  content?: string
  rows?: Record<string, unknown>[]
  package_code?: string
}): Promise<PreviewResult> {
  return postJson('/api/id_cross_map/reconciliation/preview', body)
}

export function commitRecon(body: {
  source?: string
  file_name?: string
  content?: string
  rows?: Record<string, unknown>[]
  package_code?: string
}): Promise<CommitResult> {
  return postJson('/api/id_cross_map/reconciliation/commit', body)
}

export function adoptOpinion(opinionId: string, adopted = true): Promise<CommitResult> {
  return postJson('/api/id_cross_map/reconciliation/adopt-opinion', {
    opinion_id: opinionId,
    adopted,
  })
}

export function handleDisagreement(
  code: string,
  decision: 'historical' | 'new_package' | string,
): Promise<{ ok: boolean; message: string; [k: string]: unknown }> {
  return postJson(`/api/id_cross_map/reconciliation/disagreements/${encodeURIComponent(code)}/handle`, {
    decision,
  })
}

export function fetchActualGolden(sourceId: string): Promise<Record<string, unknown>> {
  return request(
    `/api/id_cross_map/actual-golden?source_id=${encodeURIComponent(sourceId)}`,
  ).then((r) => r.json())
}

export function resetScenario(): Promise<{ ok: boolean; message: string }> {
  return postJson('/api/id_cross_map/scenario/reset', {})
}

export type LineageTrace = {
  source_id: string
  source_valid: boolean
  message: string
  old_edge: Record<string, unknown> | null
  new_edge: Record<string, unknown> | null
  current_golden: string
}

export function fetchLineageTrace(
  sourceId: string,
  deliveredGolden = '',
  packageCode = '',
): Promise<LineageTrace> {
  const query = new URLSearchParams({ source_id: sourceId })
  if (deliveredGolden) query.set('delivered_golden', deliveredGolden)
  if (packageCode) query.set('package_code', packageCode)
  return request(`/api/lineage_graph/reconciliation-trace?${query.toString()}`).then((r) => r.json())
}
