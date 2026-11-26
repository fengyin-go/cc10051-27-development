"""标识交叉映射 · 对账下载 / 回传确认领域服务。

承载题目要求的全部业务口径：

* 下载按申请方来源隔离，只交付该来源自己的实体与原标识，
  共用同一金记录的其他来源标识不会出现在文件里；
* 每份发出文件冻结唯一“映射依据（交付版）”，回传按交付版逐行确认，
  并指出交付之后出现的合法更正（G9 撤回 → G11 确认）；
* 同一核对文件反复提交时，已登记分歧按指纹只登记/确认一次，
  分歧始终保留实际关联的原发出批次；
* 回导明细交给血缘服务校验来源，并同时给出文件所指旧边与当前可用新边；
* 分歧可“沿原凭证对历史结账”或“换用新包”，意见状态持久在内存仓库，
  关页重开后仍能区分“待确认”与“已作用到关系”。
"""
from __future__ import annotations

import csv
import hashlib
import io
from datetime import datetime, timezone
from typing import Any

from app.scenario_data import (
    MAPPING_BATCH,
    NEW_PACKAGE,
    ORIGINAL_PACKAGE,
)
from app.services.lineage_graph import LineageGraphService
from app.store import store

# ---- CSV 表头与宽松别名（兼容通用导出清单和测试自制档） ----

CSV_HEADERS = [
    "行号", "核对行标识", "对账批次", "映射依据", "映射批次", "申请方来源",
    "实体编码", "实体名称", "源标识", "交付版金记录标识", "交付版发布状态",
    "核对意见", "意见说明", "建议金记录标识", "校验码",
]

HEADER_ALIASES: dict[str, list[str]] = {
    "line_no": ["行号", "序号", "line_no", "line"],
    "item_code": ["核对行标识", "行标识", "明细标识", "item_code", "item"],
    "package_code": ["对账批次", "发出批次", "原发出批次", "核对批次", "package_code", "package"],
    "basis": ["映射依据", "交付版", "交付版本", "basis"],
    "mapping_batch": ["映射批次", "mapping_batch", "map_batch"],
    "source_system": ["申请方来源", "来源系统", "来源系统标识", "source_system", "source"],
    "entity_code": ["实体编码", "entity_code", "entity"],
    "entity_name": ["实体名称", "entity_name"],
    # 注意：通用资源导出里“源系统标识”列装的就是 CRM-7 这类源记录原标识。
    "source_id": [
        "源标识", "源系统标识", "源记录标识", "原标识", "来源标识",
        "source_id", "source_identifier", "source_record_id",
    ],
    "delivered_golden": [
        "交付版金记录标识", "交付金记录", "金记录标识", "金记录",
        "golden_id", "golden",
    ],
    "delivered_publish_status": ["交付版发布状态", "发布状态", "publish_status"],
    "opinion": ["核对意见", "反馈意见", "意见", "opinion", "result"],
    "opinion_note": ["意见说明", "差异说明", "核对说明", "说明", "note", "comment", "remark"],
    "suggested_golden": ["建议金记录标识", "建议金记录", "suggested_golden", "proposed_golden"],
    "row_token": ["校验码", "行校验码", "token", "row_token", "check_code"],
}

CONFIRM_WORDS = {
    "无误", "一致", "相符", "确认", "无异议", "正确", "核对无误", "agree",
    "confirmed", "valid", "ok", "okay", "yes", "true",
}
DISPUTE_WORDS = {
    "有误", "不符", "不一致", "分歧", "有差异", "差异", "错误", "不同意",
    "异议", "待核实", "disagree", "diff", "difference", "mismatch", "wrong",
    "invalid", "no", "false",
}

OPINION_PENDING = "待确认"
OPINION_APPLIED = "已作用到关系"
OPINION_HISTORICAL = "已历史结账"

DISAGREEMENT_PENDING = "待处置"
DISAGREEMENT_HISTORICAL = "已办结·沿原凭证历史结账"
DISAGREEMENT_NEW_PACKAGE = "已办结·换用新包"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _norm(value: Any) -> str:
    return str(value if value is not None else "").strip().lstrip("'").strip()


def _classify_opinion(raw: str) -> str:
    text = _norm(raw).casefold()
    if not text:
        return "blank"
    if text in {w.casefold() for w in CONFIRM_WORDS}:
        return "confirm"
    if text in {w.casefold() for w in DISPUTE_WORDS}:
        return "dispute"
    for word in ("无误", "相符", "一致", "正确", "agree", "correct"):
        if word in text:
            return "confirm"
    for word in ("有误", "不符", "分歧", "差异", "错误", "异议", "disagree", "mismatch", "wrong"):
        if word in text:
            return "dispute"
    # 写了无法识别的内容，按“保留意见/需确认”处理，不静默当成相符。
    return "comment"


class ReconciliationService:
    MODULE = "id_cross_map"

    # ============ 读取侧 ============

    def state(self) -> dict[str, Any]:
        packages = [self._package_summary(p) for p in store.rows("recon_package")]
        disagreements = list(store.rows("recon_disagreement"))
        return {
            "sources": [
                {"code": r.get("系统标识"), "name": r.get("系统名称"), "status": r.get("status")}
                for r in store.rows("source_system")
                if r.get("系统标识") and not str(r.get("系统标识", "")).endswith("样例1")
                and not str(r.get("系统标识", "")).startswith("源系统登记样例")
            ],
            "mapping_batch": MAPPING_BATCH,
            "original_package": ORIGINAL_PACKAGE,
            "new_package": NEW_PACKAGE,
            "packages": packages,
            "disagreements": disagreements,
            "mappings": [
                {
                    "id": r.get("id"),
                    "source_system": r.get("source_system") or self._infer_source(r.get("源系统标识", "")),
                    "source_id": r.get("源系统标识"),
                    "golden_id": r.get("金记录标识"),
                    "mapping_batch": r.get("映射批次"),
                    "status": r.get("映射状态") or r.get("status"),
                    "is_current": bool(r.get("is_current", r.get("status") == "已映射")),
                    "mapping_version": r.get("mapping_version", ""),
                    "corrected_to": r.get("corrected_to", ""),
                }
                for r in store.rows(self.MODULE)
                if str(r.get("源系统标识", "")).startswith(("CRM-", "ERP-"))
            ],
            "golden_registry": store.rows("golden_registry"),
        }

    def _package_summary(self, pkg: dict[str, Any]) -> dict[str, Any]:
        items = pkg.get("items", [])
        return {
            "id": pkg.get("id"),
            "code": pkg.get("code"),
            "title": pkg.get("title"),
            "direction": pkg.get("direction"),
            "status": pkg.get("status"),
            "source_system": pkg.get("source_system"),
            "mapping_batch": pkg.get("mapping_batch"),
            "basis": pkg.get("basis"),
            "basis_label": pkg.get("basis_label"),
            "file_name": pkg.get("file_name"),
            "sent_at": pkg.get("sent_at"),
            "returned_at": pkg.get("returned_at"),
            "original_package_code": pkg.get("original_package_code"),
            "new_package_code": pkg.get("new_package_code"),
            "content_hash": pkg.get("content_hash"),
            "duplicate": pkg.get("duplicate", False),
            "resubmit_count": pkg.get("resubmit_count", 0),
            "item_count": len(items),
            "pending_count": sum(1 for i in items if i.get("opinion_status") == OPINION_PENDING),
            "applied_count": sum(1 for i in items if i.get("opinion_status") == OPINION_APPLIED),
            "adopted_opinions": [
                {
                    "opinion_id": i.get("opinion_id"),
                    "source_id": i.get("source_id"),
                    "golden_id": i.get("delivered_golden"),
                    "actual_golden": i.get("current_golden") or i.get("delivered_golden"),
                    "opinion": i.get("opinion"),
                    "opinion_note": i.get("opinion_note"),
                    "opinion_status": i.get("opinion_status"),
                    "adopted_at": i.get("adopted_at"),
                }
                for i in items if i.get("adopted")
            ],
        }

    def get_package(self, code: str) -> dict[str, Any] | None:
        pkg = self._find_package(code)
        if pkg is None:
            return None
        summary = self._package_summary(pkg)
        summary["items"] = pkg.get("items", [])
        return summary

    def _find_package(self, code: str) -> dict[str, Any] | None:
        code = _norm(code)
        return next((p for p in store.rows("recon_package") if _norm(p.get("code")) == code), None)

    def _find_return_by_hash(self, content_hash: str) -> dict[str, Any] | None:
        return next(
            (p for p in store.rows("recon_package")
             if p.get("direction") == "returned" and p.get("content_hash") == content_hash),
            None,
        )

    # ============ 来源 / 金记录 / 边 查询 ============

    def _infer_source(self, source_id: str) -> str:
        prefix = _norm(source_id).split("-", 1)[0]
        registered = {_norm(s.get("系统标识")) for s in store.rows("source_system")}
        return prefix if prefix in registered else ""

    def _source_registered(self, source_system: str) -> dict[str, Any]:
        row = next(
            (s for s in store.rows("source_system") if _norm(s.get("系统标识")) == source_system),
            None,
        )
        if row is None:
            return {"registered": False, "status": "未登记"}
        return {"registered": True, "status": row.get("status", "")}

    def _golden_info(self, golden_id: str) -> dict[str, Any]:
        golden_id = _norm(golden_id)
        reg = next((g for g in store.rows("golden_registry") if _norm(g.get("golden_id")) == golden_id), None)
        if reg is not None:
            return {
                "golden_id": golden_id,
                "eligible": bool(reg.get("eligible")),
                "publish_status": reg.get("publish_status"),
                "publish_batch": reg.get("publish_batch"),
                "superseded_by": reg.get("superseded_by", ""),
            }
        # 兜底：从金记录发布批次里识别 “Gxx/vN” 版本标识。
        pub = next(
            (p for p in store.rows("golden_publish")
             if _norm(p.get("版本标识", "")).split("/")[0] == golden_id),
            None,
        )
        if pub is not None:
            return {
                "golden_id": golden_id,
                "eligible": pub.get("status") == "已发布",
                "publish_status": pub.get("status"),
                "publish_batch": pub.get("发布批次"),
                "superseded_by": "",
            }
        return {"golden_id": golden_id, "eligible": False, "publish_status": "无发布记录",
                "publish_batch": "", "superseded_by": ""}

    def _mapping_rows(self, source_id: str) -> list[dict[str, Any]]:
        return [m for m in store.rows(self.MODULE) if _norm(m.get("源系统标识")) == source_id]

    def _current_mapping(self, source_id: str) -> dict[str, Any] | None:
        rows = self._mapping_rows(source_id)
        current = [m for m in rows if m.get("is_current") or m.get("status") == "已映射"]
        if not current:
            return None
        return sorted(current, key=lambda m: int(m.get("mapping_version", 0) or 0))[-1]

    def _edge_for(self, source_id: str, golden_id: str) -> dict[str, Any] | None:
        return next(
            (e for e in store.rows("lineage_graph")
             if _norm(e.get("上游节点")) == source_id and _norm(e.get("下游节点")) == golden_id),
            None,
        )

    def actual_golden(self, source_id: str) -> dict[str, Any]:
        source_id = _norm(source_id)
        current = self._current_mapping(source_id)
        if current is None:
            return {"ok": False, "source_id": source_id, "message": f"{source_id} 没有当前可用映射"}
        golden = _norm(current.get("金记录标识"))
        info = self._golden_info(golden)
        edge = self._edge_for(source_id, golden)
        return {
            "ok": True,
            "source_id": source_id,
            "source_system": current.get("source_system") or self._infer_source(source_id),
            "actual_golden": golden,
            "mapping_batch": current.get("映射批次"),
            "mapping_version": current.get("mapping_version"),
            "mapping_status": current.get("映射状态") or current.get("status"),
            "eligible": info["eligible"],
            "publish_status": info["publish_status"],
            "edge_code": edge.get("血缘边标识") if edge else "",
            "queried_at": _now(),
        }

    # ============ 对账下载 ============

    def build_download(self, source_system: str, package_code: str = "") -> tuple[str, str]:
        """返回 (文件名, CSV 文本)。

        指定 package_code 时下载冻结的原发出档；否则按申请方当前可用映射
        生成一份新的发出档（同一来源、同一映射依据只复用一个发出批次）。
        """
        source_system = _norm(source_system).upper()
        if not source_system:
            raise ValueError("请先选择申请方来源系统")
        source_info = self._source_registered(source_system)
        if not source_info["registered"]:
            raise ValueError(f"来源系统 {source_system} 未登记，不能申请对账清单")

        if package_code:
            pkg = self._find_package(package_code)
            if pkg is None:
                raise ValueError(f"对账批次 {package_code} 不存在")
            if _norm(pkg.get("source_system")) != source_system:
                # 来源隔离：不允许借下载名义取走别的申请方的档。
                raise PermissionError("该对账批次不属于当前申请方，禁止跨来源下载")
            return _norm(pkg.get("file_name")) or f"reconciliation_{source_system}_{pkg['code']}.csv", \
                self._render_csv(pkg)

        # 复用该来源当前依据对应的已发出批次（例如更正后的 V2 新包）。
        current_rows = [
            m for m in store.rows(self.MODULE)
            if (m.get("source_system") or self._infer_source(_norm(m.get("源系统标识")))) == source_system
            and (m.get("is_current") or m.get("status") == "已映射")
        ]
        if not current_rows:
            raise ValueError(f"{source_system} 当前没有可交付的已映射明细")
        batch = _norm(sorted(current_rows, key=lambda m: int(m.get("mapping_version", 0) or 0))[-1].get("映射批次"))
        basis = f"{batch}@current"
        existing = next(
            (p for p in store.rows("recon_package")
             if p.get("direction") == "sent" and _norm(p.get("source_system")) == source_system
             and p.get("mapping_batch") == batch and str(p.get("basis", "")).endswith("v2")),
            None,
        )
        if existing is not None:
            return _norm(existing.get("file_name")), self._render_csv(existing)

        code = self._next_code("REC", table="recon_package")
        basis = f"{batch}@v{len(current_rows) and max(int(m.get('mapping_version', 1) or 1) for m in current_rows)}"
        pkg = {
            "id": self._next_id("recon_package"),
            "code": code,
            "title": f"{source_system} 标识对账清单（{basis}）",
            "direction": "sent",
            "status": "待回传",
            "source_system": source_system,
            "mapping_batch": batch,
            "basis": basis,
            "basis_label": f"当前交付版 {basis}",
            "file_name": f"reconciliation_{source_system}_{code}.csv",
            "sent_at": _now(),
            "returned_at": "",
            "content_hash": "",
            "original_package_code": "",
            "resubmit_count": 0,
            "items": [self._item_from_mapping(idx, m, code, basis)
                      for idx, m in enumerate(current_rows, start=1)],
        }
        store.rows("recon_package").append(pkg)
        return pkg["file_name"], self._render_csv(pkg)

    def _item_from_mapping(self, line_no: int, mapping: dict[str, Any], code: str, basis: str) -> dict[str, Any]:
        source_id = _norm(mapping.get("源系统标识"))
        golden = _norm(mapping.get("金记录标识"))
        info = self._golden_info(golden)
        return {
            "line_no": line_no,
            "item_code": f"{code}-{line_no}",
            "source_system": mapping.get("source_system") or self._infer_source(source_id),
            "entity_code": "CUSTOMER",
            "entity_name": "客户",
            "source_id": source_id,
            "delivered_golden": golden,
            "delivered_publish_status": info["publish_status"],
            "mapping_batch": _norm(mapping.get("映射批次")),
            "basis": basis,
            "row_token": hashlib.sha1(f"{code}|{line_no}|{source_id}|{golden}".encode()).hexdigest()[:16],
            "opinion": "",
            "opinion_note": "",
            "suggested_golden": "",
            "opinion_status": OPINION_PENDING,
            "adopted": False,
            "disagreement_id": "",
        }

    def _render_csv(self, pkg: dict[str, Any]) -> str:
        output = io.StringIO()
        output.write("﻿")  # UTF-8 BOM，Excel 打开中文不乱码
        writer = csv.writer(output, lineterminator="\n")
        writer.writerow(CSV_HEADERS)
        for item in pkg.get("items", []):
            writer.writerow([
                item.get("line_no", ""),
                item.get("item_code", ""),
                pkg.get("code", ""),
                item.get("basis") or pkg.get("basis", ""),
                item.get("mapping_batch") or pkg.get("mapping_batch", ""),
                item.get("source_system") or pkg.get("source_system", ""),
                item.get("entity_code", ""),
                item.get("entity_name", ""),
                item.get("source_id", ""),
                item.get("delivered_golden", ""),
                item.get("delivered_publish_status", ""),
                item.get("opinion", ""),
                item.get("opinion_note", ""),
                item.get("suggested_golden", ""),
                item.get("row_token", ""),
            ])
        return output.getvalue()

    # ============ 解析 + 按交付版/来源/发布资格核对 ============

    def parse_submission(self, payload: dict[str, Any]) -> tuple[list[dict[str, str]], str, str]:
        """把上传内容解析成规范行，返回 (rows, source_system, package_code)。"""
        source_system = _norm(
            payload.get("source") or payload.get("source_system") or payload.get("applicant")
        ).upper()
        package_code = _norm(payload.get("package_code") or payload.get("batch_code") or payload.get("code"))
        rows_in = payload.get("rows")
        if not isinstance(rows_in, list):
            for key in ("items", "mappings", "details", "opinions", "data", "records"):
                candidate = payload.get(key)
                if isinstance(candidate, list):
                    rows_in = candidate
                    break
        if isinstance(rows_in, list) and rows_in and isinstance(rows_in[0], dict):
            raw_rows = rows_in
        else:
            content = str(
                payload.get("content") or payload.get("csv")
                or payload.get("file_content") or payload.get("text") or ""
            )
            file_name = _norm(payload.get("file_name") or payload.get("filename"))
            if not content and file_name:
                raise ValueError("没有读到文件内容")
            raw_rows = self._parse_content(content, file_name)

        rows: list[dict[str, str]] = []
        for raw in raw_rows:
            canonical = self._canonicalize(raw)
            if not canonical.get("source_id") and not canonical.get("delivered_golden"):
                continue
            rows.append(canonical)
        if not rows:
            raise ValueError("核对文件里没有可识别的映射明细行")

        if not source_system:
            source_system = _norm(rows[0].get("source_system")).upper() or \
                self._infer_source(rows[0].get("source_id", ""))
        if not package_code:
            package_code = _norm(rows[0].get("package_code"))
        return rows, source_system, package_code

    def _parse_content(self, content: str, file_name: str = "") -> list[dict[str, Any]]:
        text = content.lstrip("﻿")
        stripped = text.lstrip()
        if stripped.startswith(("[", "{")):
            import json
            data = json.loads(stripped)
            if isinstance(data, dict):
                for key in ("rows", "items", "mappings", "details", "opinions", "records", "data"):
                    if isinstance(data.get(key), list):
                        data = data[key]
                        break
                else:
                    data = []
            return list(data)
        reader = csv.reader(io.StringIO(text))
        all_rows = [r for r in reader if any(_norm(c) for c in r)]
        if len(all_rows) < 1:
            return []
        headers = all_rows[0]
        # 兼容无表头的极简档：CRM-7,G9,无误
        if not any(self._match_header(h) for h in headers):
            simple = []
            for cells in all_rows:
                row = {"source_id": cells[0] if len(cells) > 0 else "",
                       "delivered_golden": cells[1] if len(cells) > 1 else "",
                       "opinion": cells[2] if len(cells) > 2 else "",
                       "opinion_note": cells[3] if len(cells) > 3 else ""}
                simple.append(row)
            return simple
        dict_reader = csv.DictReader(io.StringIO(text))
        return list(dict_reader)

    def _match_header(self, header: str) -> str | None:
        h = _norm(header)
        for canonical, aliases in HEADER_ALIASES.items():
            if h in aliases:
                return canonical
        return None

    def _canonicalize(self, raw: dict[str, Any]) -> dict[str, str]:
        out: dict[str, str] = {}
        for key, value in raw.items():
            canonical = self._match_header(str(key))
            if canonical:
                out[canonical] = _norm(value)
        # 没有命中表头别名时，允许直接传规范键。
        for canonical in HEADER_ALIASES:
            if canonical in raw and canonical not in out:
                out[canonical] = _norm(raw.get(canonical))
        return out

    def verify(
        self,
        rows: list[dict[str, str]],
        source_system: str,
        package_code: str = "",
    ) -> dict[str, Any]:
        source_info = self._source_registered(source_system)
        pkg = self._resolve_package(rows, source_system, package_code)
        original_code = _norm(pkg.get("code")) if pkg else package_code

        verified: list[dict[str, Any]] = []
        changed = valid = disputed = 0
        for row in rows:
            source_id = _norm(row.get("source_id"))
            delivered = _norm(row.get("delivered_golden"))
            row_source = _norm(row.get("source_system")).upper() or source_system
            inferred = self._infer_source(source_id)
            applicant = source_system or row_source or inferred

            # 按来源核对映射明细：该源标识在服务端必须属于申请方来源。
            mappings = self._mapping_rows(source_id)
            mapping_sources = {
                _norm(m.get("source_system")).upper() or self._infer_source(_norm(m.get("源系统标识")))
                for m in mappings
            }
            source_ok = True
            source_messages: list[str] = []
            if not source_id:
                source_ok = False
                source_messages.append("缺少源标识")
            if applicant and mapping_sources and applicant not in mapping_sources:
                source_ok = False
                source_messages.append(
                    f"来源不符：{source_id} 属于 {'/'.join(sorted(s for s in mapping_sources if s)) or '其他来源'}，"
                    f"不属于申请方 {applicant}"
                )
            if not mappings:
                source_messages.append("服务端暂无该源标识的映射明细，将按回导明细登记校验")

            # 按交付版确认：优先校验行令牌/行标识，其次按源标识对快照。
            snapshot_item = self._match_snapshot_item(pkg, row, source_id)
            version_confirmed = False
            version_message = ""
            if snapshot_item is not None:
                if row.get("row_token") and _norm(row.get("row_token")) != _norm(snapshot_item.get("row_token")):
                    version_message = "校验码与交付版不一致"
                elif row.get("item_code") and _norm(row.get("item_code")) != _norm(snapshot_item.get("item_code")):
                    version_message = "核对行标识不属于该交付版"
                elif delivered and _norm(snapshot_item.get("delivered_golden")) != delivered:
                    version_message = (
                        f"回传金记录 {delivered} 与交付版 "
                        f"{snapshot_item.get('delivered_golden')} 不一致"
                    )
                else:
                    version_confirmed = True
                    version_message = "按交付版确认一致"
                    delivered = delivered or _norm(snapshot_item.get("delivered_golden"))
            elif pkg is not None:
                version_message = "在该交付版批次中找不到对应行"
            else:
                version_message = "未匹配到原发出批次，按当前服务端映射核对"

            delivered_info = self._golden_info(delivered) if delivered else None
            current_mapping = self._current_mapping(source_id)
            current_golden = _norm(current_mapping.get("金记录标识")) if current_mapping else ""
            current_info = self._golden_info(current_golden) if current_golden else None
            old_edge = self._edge_for(source_id, delivered) if delivered else None
            new_edge = self._edge_for(source_id, current_golden) if current_golden else None

            if not current_golden:
                relation_state = "no_current"
                relation_label = "当前无可用映射"
            elif delivered and current_golden == delivered:
                relation_state = "still_valid"
                relation_label = "仍有效"
                valid += 1
            else:
                relation_state = "changed"
                if delivered_info and delivered_info.get("superseded_by") == current_golden \
                        and current_info and current_info.get("eligible"):
                    relation_label = f"已变化：随后出现合法更正 {delivered}→{current_golden}"
                elif current_info and current_info.get("eligible"):
                    relation_label = f"已变化：交付版 {delivered} 已失效，当前为 {current_golden}"
                else:
                    relation_label = f"已变化：{delivered}→{current_golden}，但新金记录暂无发布资格"
                changed += 1

            opinion_kind = _classify_opinion(row.get("opinion", ""))
            if opinion_kind == "dispute":
                disputed += 1

            verified.append({
                "line_no": row.get("line_no") or len(verified) + 1,
                "source_system": applicant,
                "source_id": source_id,
                "entity_code": row.get("entity_code") or (snapshot_item or {}).get("entity_code", ""),
                "entity_name": row.get("entity_name") or (snapshot_item or {}).get("entity_name", ""),
                "delivered_golden": delivered,
                "delivered_publish_status": (delivered_info or {}).get("publish_status", ""),
                "delivered_eligible": (delivered_info or {}).get("eligible", False),
                "current_golden": current_golden,
                "current_eligible": (current_info or {}).get("eligible", False),
                "current_publish_status": (current_info or {}).get("publish_status", ""),
                "relation_state": relation_state,
                "relation_label": relation_label,
                "source_ok": source_ok,
                "source_messages": source_messages,
                "source_registered": source_info.get("registered", False),
                "source_status": source_info.get("status", ""),
                "version_confirmed": version_confirmed,
                "version_message": version_message,
                "package_code": _norm(row.get("package_code")) or original_code,
                "original_package_code": original_code,
                "basis": row.get("basis") or (_norm(pkg.get("basis")) if pkg else ""),
                "mapping_batch": row.get("mapping_batch") or (_norm(pkg.get("mapping_batch")) if pkg else MAPPING_BATCH),
                "old_edge_code": old_edge.get("血缘边标识") if old_edge else "",
                "old_edge_status": old_edge.get("status") if old_edge else "",
                "new_edge_code": new_edge.get("血缘边标识") if new_edge else "",
                "new_edge_status": new_edge.get("status") if new_edge else "",
                "opinion": row.get("opinion", ""),
                "opinion_kind": opinion_kind,
                "opinion_note": row.get("opinion_note", ""),
                "suggested_golden": row.get("suggested_golden", ""),
                "row_token": row.get("row_token", ""),
                "item_code": row.get("item_code", ""),
            })

        return {
            "ok": True,
            "source_system": source_system,
            "source_registered": source_info.get("registered", False),
            "source_status": source_info.get("status", ""),
            "package_code": _norm(pkg.get("code")) if pkg else package_code,
            "original_package_code": original_code,
            "basis": _norm(pkg.get("basis")) if pkg else "",
            "mapping_batch": _norm(pkg.get("mapping_batch")) if pkg else MAPPING_BATCH,
            "resolved_package": self._package_summary(pkg) if pkg else None,
            "rows": verified,
            "summary": {
                "total": len(verified),
                "changed": changed,
                "still_valid": valid,
                "disputed": disputed,
            },
        }

    def _resolve_package(
        self,
        rows: list[dict[str, str]],
        source_system: str,
        package_code: str,
    ) -> dict[str, Any] | None:
        if package_code:
            pkg = self._find_package(package_code)
            if pkg is not None:
                return pkg
        codes = {_norm(r.get("package_code")) for r in rows if r.get("package_code")}
        for code in codes:
            pkg = self._find_package(code)
            if pkg is not None:
                return pkg
        # 极简档/自制夹具：按 (来源, 源标识, 交付金记录) 集合匹配原发出批次。
        candidates: list[dict[str, Any]] = []
        wanted = {(_norm(r.get("source_id")), _norm(r.get("delivered_golden"))) for r in rows}
        for pkg in store.rows("recon_package"):
            if pkg.get("direction") != "sent":
                continue
            if source_system and _norm(pkg.get("source_system")).upper() != source_system:
                continue
            offered = {
                (_norm(i.get("source_id")), _norm(i.get("delivered_golden")))
                for i in pkg.get("items", [])
            }
            if wanted and wanted.issubset(offered):
                candidates.append(pkg)
        if not candidates:
            return None
        # 优先最早的原发出档（迟到的旧档应关联 V1，而不是更正后的 V2）。
        return sorted(candidates, key=lambda p: int(p.get("id", 0)))[0]

    def _match_snapshot_item(
        self,
        pkg: dict[str, Any] | None,
        row: dict[str, str],
        source_id: str,
    ) -> dict[str, Any] | None:
        if pkg is None:
            return None
        item_code = _norm(row.get("item_code"))
        token = _norm(row.get("row_token"))
        for item in pkg.get("items", []):
            if item_code and _norm(item.get("item_code")) == item_code:
                return item
            if token and _norm(item.get("row_token")) == token:
                return item
        if source_id:
            same = [i for i in pkg.get("items", []) if _norm(i.get("source_id")) == source_id]
            if len(same) == 1:
                return same[0]
            delivered = _norm(row.get("delivered_golden"))
            hit = next((i for i in same if _norm(i.get("delivered_golden")) == delivered), None)
            if hit:
                return hit
            return same[0] if same else None
        return None

    # ============ 回传提交（幂等 + 分歧只登记一次） ============

    def commit_return(self, payload: dict[str, Any]) -> dict[str, Any]:
        rows, source_system, package_code = self.parse_submission(payload)
        verification = self.verify(rows, source_system, package_code)
        source_system = verification["source_system"]
        original_code = verification.get("original_package_code") or verification.get("package_code") or ""

        fingerprint_source = "|".join(
            sorted(
                f"{r['source_id']}:{r['delivered_golden']}:{r['opinion']}"
                for r in verification["rows"]
            )
        )
        content_hash = hashlib.sha1(
            f"{source_system}|{original_code}|{fingerprint_source}".encode()
        ).hexdigest()

        existing = self._find_return_by_hash(content_hash)
        if existing is not None:
            existing["resubmit_count"] = int(existing.get("resubmit_count", 0)) + 1
            # 已登记分歧只确认一次：重复提交不新增，只累积提交痕迹。
            for d in store.rows("recon_disagreement"):
                if d.get("return_package_code") == existing.get("code"):
                    d["resubmit_count"] = int(d.get("resubmit_count", 1)) + 1
                    d["last_seen_at"] = _now()
            return {
                "ok": True,
                "duplicate": True,
                "message": (
                    f"该核对文件已提交过，已登记分歧只确认一次；"
                    f"仍关联实际原发出批次 {existing.get('original_package_code') or original_code}"
                ),
                "package": self.get_package(existing["code"]),
                "verification": verification,
            }

        return_id = self._next_id("recon_package")
        return_code = f"RET-{return_id:03d}"
        items: list[dict[str, Any]] = []
        created_disagreements: list[dict[str, Any]] = []

        for idx, vr in enumerate(verification["rows"], start=1):
            opinion_id = f"OP-{return_id}-{idx}"
            item = {
                "line_no": idx,
                "opinion_id": opinion_id,
                "item_code": vr.get("item_code") or f"{original_code}-{idx}",
                "source_system": vr.get("source_system"),
                "entity_code": vr.get("entity_code"),
                "entity_name": vr.get("entity_name"),
                "source_id": vr.get("source_id"),
                "delivered_golden": vr.get("delivered_golden"),
                "current_golden": vr.get("current_golden"),
                "relation_state": vr.get("relation_state"),
                "relation_label": vr.get("relation_label"),
                "mapping_batch": vr.get("mapping_batch"),
                "basis": vr.get("basis"),
                "row_token": vr.get("row_token"),
                "opinion": vr.get("opinion") or ("核对相符（空意见按无异议处理）"
                                                 if vr.get("relation_state") == "still_valid" else ""),
                "opinion_note": vr.get("opinion_note"),
                "suggested_golden": vr.get("suggested_golden"),
                "opinion_status": OPINION_PENDING,
                "adopted": False,
                "adopted_at": "",
                "disagreement_id": "",
                "version_confirmed": vr.get("version_confirmed"),
                "version_message": vr.get("version_message"),
            }

            needs_disagreement = vr["relation_state"] == "changed" or (
                vr.get("opinion_kind") == "dispute" and vr["relation_state"] == "still_valid"
            )
            if needs_disagreement:
                disagreement = self._register_disagreement(
                    vr, source_system, original_code, return_code, content_hash
                )
                item["disagreement_id"] = disagreement["code"]
                # 若分歧此前已存在（同指纹旧档），意见直接挂到同一条分歧。
                item["opinion_status"] = OPINION_PENDING
                created_disagreements.append(disagreement)
            elif vr["relation_state"] == "still_valid" and vr.get("opinion_kind") != "comment":
                # 仍有效且核对相符：意见自动作用到血缘关系（边核验）。
                self._apply_to_relation(item, return_code)
            items.append(item)

        returned_pkg = {
            "id": return_id,
            "code": return_code,
            "title": f"{source_system} 核对回传（对应原发出批次 {original_code or '未匹配'}）",
            "direction": "returned",
            "status": "部分待确认" if any(i["opinion_status"] == OPINION_PENDING for i in items) else "已办结",
            "source_system": source_system,
            "mapping_batch": verification.get("mapping_batch") or MAPPING_BATCH,
            "basis": verification.get("basis", ""),
            "basis_label": "回传核对结果",
            "file_name": payload.get("file_name", ""),
            "sent_at": "",
            "returned_at": _now(),
            "content_hash": content_hash,
            "original_package_code": original_code,
            "new_package_code": NEW_PACKAGE if vr_has_correction(verification) else "",
            "resubmit_count": 0,
            "items": items,
        }
        store.rows("recon_package").append(returned_pkg)

        # 把回传批次号回填到分歧。
        for d in created_disagreements:
            if not d.get("return_package_code"):
                d["return_package_code"] = return_code

        return {
            "ok": True,
            "duplicate": False,
            "message": f"回传已按交付版核对并登记，原发出批次 {original_code or '未匹配'}",
            "package": self.get_package(return_code),
            "verification": verification,
            "disagreements": created_disagreements,
        }

    def _register_disagreement(
        self,
        vr: dict[str, Any],
        source_system: str,
        original_code: str,
        return_code: str,
        content_hash: str,
    ) -> dict[str, Any]:
        kind = "mapping_changed" if vr["relation_state"] == "changed" else "opinion_dispute"
        fingerprint = hashlib.sha1(
            "|".join([
                original_code, vr.get("source_id", ""), vr.get("delivered_golden", ""),
                vr.get("current_golden", ""), kind,
            ]).encode()
        ).hexdigest()
        existing = next(
            (d for d in store.rows("recon_disagreement") if d.get("fingerprint") == fingerprint),
            None,
        )
        if existing is not None:
            # 同一分歧只确认一次：保留原登记与实际原发出批次，不新建。
            existing["resubmit_count"] = int(existing.get("resubmit_count", 1)) + 1
            seen = existing.setdefault("seen_return_codes", [])
            if return_code not in seen:
                seen.append(return_code)
            return existing

        did = self._next_id("recon_disagreement")
        current_info = self._golden_info(vr.get("current_golden", ""))
        has_new_edge = bool(vr.get("new_edge_code"))
        if vr["relation_state"] == "changed" and has_new_edge and current_info.get("eligible"):
            recommended = "new_package"
            recommend_reason = (
                f"新边 {vr.get('new_edge_code')} 可用且 "
                f"{vr.get('current_golden')} 具备发布资格，当前账务建议换用新包；"
                f"若仅对文件时点的历史账务结账，可沿原凭证 {original_code} 处理。"
            )
        else:
            recommended = "historical"
            recommend_reason = "未发现具备发布资格的可用新边，建议沿原发出凭证对历史结账。"
        record = {
            "id": did,
            "code": f"D-{did}",
            "fingerprint": fingerprint,
            "kind": kind,
            "title": (
                f"{vr.get('source_id')} 交付版 {vr.get('delivered_golden')} 与当前 "
                f"{vr.get('current_golden') or '空'} 不一致"
            ),
            "source_system": source_system,
            "source_id": vr.get("source_id"),
            "delivered_golden": vr.get("delivered_golden"),
            "current_golden": vr.get("current_golden"),
            "old_edge_code": vr.get("old_edge_code"),
            "new_edge_code": vr.get("new_edge_code"),
            "original_package_code": original_code,
            "mapping_batch": vr.get("mapping_batch") or MAPPING_BATCH,
            "return_package_code": return_code,
            "new_package_code": NEW_PACKAGE,
            "status": DISAGREEMENT_PENDING,
            "confirmed_once": True,
            "recommended_decision": recommended,
            "recommendation_reason": recommend_reason,
            "resubmit_count": 1,
            "seen_return_codes": [return_code],
            "resolution": "",
            "resolution_voucher": "",
            "handled_at": "",
            "created_at": _now(),
        }
        store.rows("recon_disagreement").append(record)
        return record

    # ============ 意见采纳 / 分歧处置 ============

    def adopt_opinion(self, opinion_id: str, adopted: bool = True) -> dict[str, Any]:
        pkg, item = self._find_opinion(opinion_id)
        if item is None or pkg is None:
            return {"ok": False, "message": f"意见 {opinion_id} 不存在"}
        if adopted:
            if item.get("relation_state") == "changed" and item.get("disagreement_id"):
                # 直接采纳当前新关系，等价于轻量“换用新包”。
                result = self.handle_disagreement(item["disagreement_id"], "new_package")
                if not result.get("ok"):
                    return result
            self._apply_to_relation(item, pkg.get("code", ""))
            self._refresh_package_status(pkg)
            return {"ok": True, "message": "意见已采纳并作用到映射/血缘关系", "package": self.get_package(pkg["code"])}
        item["adopted"] = False
        item["opinion_status"] = OPINION_PENDING
        item["adopted_at"] = ""
        self._refresh_package_status(pkg)
        return {"ok": True, "message": "已撤销采纳，意见回到待确认", "package": self.get_package(pkg["code"])}

    def _apply_to_relation(self, item: dict[str, Any], return_code: str) -> None:
        item["adopted"] = True
        item["opinion_status"] = OPINION_APPLIED
        item["adopted_at"] = _now()
        source_id = _norm(item.get("source_id"))
        golden = _norm(item.get("current_golden") or item.get("delivered_golden"))
        edge = self._edge_for(source_id, golden)
        if edge is not None:
            edge["last_reconciliation"] = f"核对意见已作用：{return_code} / {item.get('opinion_id', '')}"
            edge["reconciled_at"] = _now()
            if edge.get("status") == "待核验":
                edge["status"] = "已登记"
                edge["pending"] = False
        mapping = self._current_mapping(source_id)
        if mapping is not None and golden:
            mapping["last_reconciliation"] = f"{return_code} 采纳意见，确认实际金记录 {golden}"

    def handle_disagreement(self, code: str, decision: str, operator: str = "数据管理员") -> dict[str, Any]:
        d = next((x for x in store.rows("recon_disagreement") if _norm(x.get("code")) == _norm(code)), None)
        if d is None:
            return {"ok": False, "message": f"分歧 {code} 不存在"}
        decision = _norm(decision).lower()
        pkg, item = self._find_opinion_by_disagreement(d["code"])

        if decision in ("historical", "history", "原凭证", "沿原凭证对历史结账"):
            old_edge = next(
                (e for e in store.rows("lineage_graph") if e.get("血缘边标识") == d.get("old_edge_code")),
                None,
            )
            voucher = f"{d.get('original_package_code')} / {d.get('source_id')} / 交付版{d.get('delivered_golden')}"
            d["status"] = DISAGREEMENT_HISTORICAL
            d["resolution"] = "沿原凭证对历史结账：旧边保留为历史结账凭证，当前关系不回改"
            d["resolution_voucher"] = voucher
            d["handled_at"] = _now()
            d["operator"] = operator
            if old_edge is not None:
                old_edge["historical_settled"] = True
                old_edge["settlement_voucher"] = voucher
                old_edge["settled_at"] = _now()
                old_edge["settlement_disagreement"] = d["code"]
            if item is not None:
                item["opinion_status"] = OPINION_HISTORICAL
                item["adopted"] = False
                item["historical_settled"] = True
            if pkg is not None:
                self._refresh_package_status(pkg)
            return {
                "ok": True,
                "decision": "historical",
                "message": (
                    f"可沿原凭证 {voucher} 对历史结账；旧边 {d.get('old_edge_code')} "
                    f"作为历史凭证保留，当前仍使用新边 {d.get('new_edge_code')}"
                ),
                "disagreement": d,
                "old_edge": old_edge,
            }

        if decision in ("new_package", "new", "换用新包"):
            new_edge = next(
                (e for e in store.rows("lineage_graph") if e.get("血缘边标识") == d.get("new_edge_code")),
                None,
            )
            # 确保当前映射确实指向新金记录且具备发布资格。
            actual = self.actual_golden(_norm(d.get("source_id")))
            d["status"] = DISAGREEMENT_NEW_PACKAGE
            d["resolution"] = "换用新包：按更正后交付版确认当前映射与新边"
            d["resolution_voucher"] = d.get("new_package_code") or NEW_PACKAGE
            d["handled_at"] = _now()
            d["operator"] = operator
            if new_edge is not None:
                new_edge["adopted_by_reconciliation"] = d["code"]
                new_edge["adopted_at"] = _now()
                new_edge["status"] = "已登记"
                new_edge["pending"] = False
            if item is not None and pkg is not None:
                self._apply_to_relation(item, pkg.get("code", ""))
                item["disagreement_id"] = d["code"]
                self._refresh_package_status(pkg)
            return {
                "ok": True,
                "decision": "new_package",
                "message": (
                    f"已换用新包 {d.get('new_package_code')}，{d.get('source_id')} "
                    f"实际对应金记录 {actual.get('actual_golden') or d.get('current_golden')}，"
                    f"可在血缘图核对新边 {d.get('new_edge_code')}"
                ),
                "disagreement": d,
                "actual_golden": actual,
                "new_edge": new_edge,
            }

        return {"ok": False, "message": f"未知处置方式：{decision}（可选 historical / new_package）"}

    def _find_opinion(self, opinion_id: str) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
        for pkg in store.rows("recon_package"):
            for item in pkg.get("items", []):
                if _norm(item.get("opinion_id")) == _norm(opinion_id):
                    return pkg, item
        return None, None

    def _find_opinion_by_disagreement(self, code: str) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
        for pkg in store.rows("recon_package"):
            for item in pkg.get("items", []):
                if _norm(item.get("disagreement_id")) == _norm(code):
                    return pkg, item
        return None, None

    def _refresh_package_status(self, pkg: dict[str, Any]) -> None:
        items = pkg.get("items", [])
        if any(i.get("opinion_status") == OPINION_PENDING for i in items):
            pkg["status"] = "部分待确认"
        else:
            pkg["status"] = "已办结"

    # ============ 撤回 / 更正确认（场景可重放） ============

    def correct_mapping(self, source_id: str, to_golden: str = "") -> dict[str, Any]:
        source_id = _norm(source_id)
        rows = self._mapping_rows(source_id)
        if not rows:
            return {"ok": False, "message": f"{source_id} 没有映射可更正"}
        old_current = self._current_mapping(source_id)
        old_golden = _norm(old_current.get("金记录标识")) if old_current else ""
        target = _norm(to_golden) or next(
            (g.get("superseded_by") for g in store.rows("golden_registry")
             if _norm(g.get("golden_id")) == old_golden and g.get("superseded_by")),
            "",
        )
        if not target:
            return {"ok": False, "message": f"{old_golden} 没有登记随后的合法更正目标"}
        # 撤回旧映射与旧边。
        if old_current is not None:
            old_current["is_current"] = False
            old_current["status"] = "已撤回"
            old_current["映射状态"] = "已撤回"
            old_current["abnormal"] = True
            old_current["corrected_to"] = target
        old_edge = self._edge_for(source_id, old_golden)
        if old_edge is not None:
            old_edge["status"] = "失效"
            old_edge["abnormal"] = True
        # 已存在更正映射则直接置为当前，否则新建。
        new_mapping = next((m for m in rows if _norm(m.get("金记录标识")) == target), None)
        if new_mapping is None:
            new_id = self._next_id(self.MODULE)
            new_mapping = {
                "id": new_id, "status": "已映射", "pending": False, "abnormal": False,
                "映射批次": MAPPING_BATCH, "源系统标识": source_id, "金记录标识": target,
                "映射置信度": "0.99", "映射状态": "已映射",
                "source_system": self._infer_source(source_id),
                "mapping_version": 2, "is_current": True, "corrects": old_golden,
                "登记时间": _now(),
            }
            store.rows(self.MODULE).append(new_mapping)
        else:
            new_mapping["is_current"] = True
            new_mapping["status"] = "已映射"
            new_mapping["映射状态"] = "已映射"
        if self._edge_for(source_id, target) is None:
            LineageGraphService().register_edge(
                source_id, target, f"标识交叉映射/{MAPPING_BATCH}#v2"
            )
        return {
            "ok": True,
            "message": f"已撤回 {source_id}→{old_golden} 并更正确认到 {target}",
            "actual_golden": self.actual_golden(source_id),
        }

    def reset_scenario(self) -> dict[str, Any]:
        store.reset()
        return {"ok": True, "message": "对账场景已重置为种子状态（原发出 V1 / 新包 V2）"}

    # ============ 工具 ============

    def _next_id(self, table: str) -> int:
        rows = store.rows(table)
        return max((int(r.get("id", 0) or 0) for r in rows), default=0) + 1

    def _next_code(self, prefix: str, table: str) -> str:
        return f"{prefix}-{self._next_id(table):03d}"


def vr_has_correction(verification: dict[str, Any]) -> bool:
    return any(r.get("relation_state") == "changed" for r in verification.get("rows", []))


reconciliation_service = ReconciliationService()
