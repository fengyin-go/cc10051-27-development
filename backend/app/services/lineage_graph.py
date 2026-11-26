"""血缘关系图领域服务：管理主数据从源系统到分发的血缘边登记、核验与影响分析。

数据链路位置：治理元数据层，负责关联各加工环节的上下游节点，
为回滚与变更提供影响面数据。
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.services.base import BaseModuleService
from app.store import store


class LineageGraphService(BaseModuleService):
    MODULE = "lineage_graph"
    ENTITY = "血缘边"
    OPERATION_TERM = "关联"
    LIST_FIELDS = ["血缘边标识", "上游节点", "下游节点", "变换规则", "登记时间"]
    REQUIRED_FIELDS = ["血缘边标识", "上游节点", "下游节点"]
    STATUS_ORDER = ["已登记", "待核验", "失效"]
    ACTION_RULES = {"登记血缘": "已登记", "核验血缘": "待核验"}
    NEGATIVE_ACTIONS = []

    # ---- 业务扩展：血缘登记与影响分析 ----

    def trace_upstream(self, entry_id: int) -> list[str]:
        """追溯某血缘边的全部上游节点，输出来源链路。"""
        entry = store.find(self.MODULE, entry_id)
        if entry is None:
            return []
        chain: list[str] = [entry.get("上游节点", "")]
        current = entry.get("上游节点", "")
        for _ in range(8):
            parent = next((e for e in store.rows(self.MODULE)
                           if e.get("下游节点") == current and e.get("status") == "已登记"), None)
            if parent is None:
                break
            chain.append(parent.get("上游节点", ""))
            current = parent.get("上游节点", "")
        return chain

    def impact_analysis(self, node: str) -> list[str]:
        """对指定节点做下游影响分析，列出受影响链路。"""
        visited: set[str] = set()
        frontier = [node]
        while frontier:
            current = frontier.pop()
            for edge in store.rows(self.MODULE):
                if edge.get("上游节点") == current and edge.get("status") == "已登记":
                    downstream = edge.get("下游节点", "")
                    if downstream and downstream not in visited:
                        visited.add(downstream)
                        frontier.append(downstream)
        return sorted(visited)

    def register_edge(self, upstream: str, downstream: str, rule: str) -> str:
        """登记一条血缘边，自动带时间戳。"""
        edges = store.rows(self.MODULE)
        edge_id = max((int(r.get("id", 0)) for r in edges), default=0) + 1
        edge_key = f"edge-{upstream}-{downstream}-{edge_id}"
        edges.append({
            "id": edge_id,
            "血缘边标识": edge_key,
            "上游节点": upstream,
            "下游节点": downstream,
            "变换规则": rule,
            "登记时间": datetime.now(timezone.utc).isoformat(),
            "status": "已登记",
            "pending": False,
            "abnormal": False,
        })
        return edge_key

    def mark_stale_edges(self, module_name: str) -> int:
        """把指向停用模块的血缘边置为失效。"""
        stale = 0
        for edge in store.rows(self.MODULE):
            if edge.get("上游节点") == module_name and edge.get("status") == "已登记":
                edge["status"] = "失效"
                edge["abnormal"] = True
                stale += 1
        return stale

    def verify_edge(self, entry_id: int, both_sides: bool) -> str:
        """核验血缘边：确认上游节点在源系统登记中存在。"""
        entry = store.find(self.MODULE, entry_id)
        if entry is None:
            return "血缘边不存在"
        up_ok = any(r.get("系统标识") == entry.get("上游节点")
                    for r in store.rows("source_system"))
        if both_sides and up_ok:
            entry["status"] = "已登记"
            entry["pending"] = False
            return "血缘核验通过，上游节点已登记"
        entry["status"] = "待核验"
        entry["pending"] = True
        return "血缘待核验：上游节点未在源系统登记"

    def export_graph_snapshot(self) -> dict[str, Any]:
        """导出血缘图快照，供治理看板消费。"""
        rows = store.rows(self.MODULE)
        return {
            "edges": len(rows),
            "registered": sum(1 for r in rows if r.get("status") == "已登记"),
            "pending_verify": sum(1 for r in rows if r.get("status") == "待核验"),
            "stale": sum(1 for r in rows if r.get("status") == "失效"),
        }

    # ---- 对账回导：按回导映射明细校验来源，并并列给出旧边/新边 ----

    def reconciliation_trace(
        self,
        source_id: str,
        delivered_golden: str = "",
        package_code: str = "",
    ) -> dict[str, Any]:
        source_id = str(source_id or "").strip()
        delivered_golden = str(delivered_golden or "").strip()
        edges = store.rows(self.MODULE)

        source_system = source_id.split("-", 1)[0] if "-" in source_id else ""
        source_row = next(
            (s for s in store.rows("source_system")
             if s.get("系统标识") == source_system or s.get("系统标识") == source_id),
            None,
        )
        # 血缘追溯按回导的映射明细校验来源：上游节点必须能在源系统/映射明细中对上。
        mapping_rows = [
            m for m in store.rows("id_cross_map") if m.get("源系统标识") == source_id
        ]
        source_valid = bool(source_row or mapping_rows)

        old_edge = next(
            (e for e in edges
             if e.get("上游节点") == source_id
             and (not delivered_golden or e.get("下游节点") == delivered_golden)),
            None,
        )
        golden_now = ""
        current_maps = [m for m in mapping_rows if m.get("is_current") or m.get("status") == "已映射"]
        if current_maps:
            golden_now = str(sorted(
                current_maps, key=lambda m: int(m.get("mapping_version", 0) or 0)
            )[-1].get("金记录标识", ""))
        new_edge = next(
            (e for e in edges
             if e.get("上游节点") == source_id and e.get("下游节点") == golden_now
             and e.get("status") == "已登记"),
            None,
        )
        if new_edge is None and golden_now:
            new_edge = next(
                (e for e in edges
                 if e.get("上游节点") == source_id and e.get("下游节点") == golden_now),
                None,
            )

        return {
            "source_id": source_id,
            "source_system": source_system,
            "source_valid": source_valid,
            "source_registered_status": (source_row or {}).get("status", ""),
            "mapping_detail_count": len(mapping_rows),
            "package_code": package_code,
            "old_edge": old_edge,
            "new_edge": new_edge,
            "current_golden": golden_now,
            "message": (
                "来源校验通过；已并列给出文件所指旧边与目前可用新边"
                if source_valid else
                "来源校验未通过：回导明细的源标识在源系统登记与映射明细中均不存在"
            ),
        }

    def verify_reimport(self, items: list[dict[str, str]]) -> dict[str, Any]:
        """按回导的映射明细批量校验来源，返回每行的旧边/新边结论。"""
        traces = [
            self.reconciliation_trace(
                str(item.get("source_id", "")),
                str(item.get("delivered_golden", "")),
                str(item.get("package_code", "")),
            )
            for item in items
        ]
        return {
            "ok": all(t["source_valid"] for t in traces),
            "total": len(traces),
            "source_valid_count": sum(1 for t in traces if t["source_valid"]),
            "traces": traces,
        }
