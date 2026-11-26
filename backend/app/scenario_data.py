"""标识交叉映射 · 对账回传场景的示例数据。

这里固化题目描述的完整血缘时点，保证新起服务即可演练：

1. CRM 申请方曾经下载过交付版 v1 对账档，其中为 CRM-7 → G9、CRM-8 → G12；
2. 意见未回传前，CRM-7 → G9 的原映射被撤回，金记录合法更正为 G11，
   于是血缘图上同时存在文件所指的旧边 edge-CRM-7-G9（失效）
   与目前可用的新边 edge-CRM-7-G11（已登记）；
3. ERP-3 同样映射到 G11：两个来源系统共用同一金记录，
   但 CRM 的对账档绝不允许出现 ERP-3 的原标识；
4. REC-...-V2 是更正后的“新包”，同一映射批次 MAP-202611-CRM。
"""
from __future__ import annotations

from typing import Any

MAPPING_BATCH = "MAP-202611-CRM"
ORIGINAL_PACKAGE = "REC-20261120-CRM-V1"
NEW_PACKAGE = "REC-20261125-CRM-V2"

SCENARIO_TABLES: dict[str, list[dict[str, Any]]] = {
    "source_system": [
        {
            "id": 101, "status": "已接入", "pending": False, "abnormal": False,
            "系统标识": "CRM", "系统名称": "CRM客户系统", "数据域": "客户主数据",
            "同步频率": "实时", "责任人": "王敏",
        },
        {
            "id": 102, "status": "已接入", "pending": False, "abnormal": False,
            "系统标识": "ERP", "系统名称": "ERP订单系统", "数据域": "客户主数据",
            "同步频率": "每小时", "责任人": "李强",
        },
    ],
    # 金记录发布资格台账：只有处于“已发布”批次的金记录才具备对账可用资格。
    "golden_registry": [
        {
            "id": 1, "golden_id": "G9", "实体编码": "CUSTOMER",
            "publish_batch": "PUB-G9-20261101", "version_label": "v9",
            "publish_status": "已撤回", "eligible": False,
            "superseded_by": "G11",
            "note": "合并生还规则修正，G9 发布已回滚，合法更正为 G11",
        },
        {
            "id": 2, "golden_id": "G11", "实体编码": "CUSTOMER",
            "publish_batch": "PUB-G11-20261124", "version_label": "v11",
            "publish_status": "已发布", "eligible": True,
            "superseded_by": "",
            "note": "更正后金记录，已随 PUB-G11-20261124 发布",
        },
        {
            "id": 3, "golden_id": "G12", "实体编码": "CUSTOMER",
            "publish_batch": "PUB-G12-20261115", "version_label": "v12",
            "publish_status": "已发布", "eligible": True,
            "superseded_by": "",
            "note": "稳定金记录",
        },
    ],
    "golden_publish": [
        {
            "id": 101, "status": "已回滚", "pending": False, "abnormal": True,
            "发布批次": "PUB-G9-20261101", "实体编码": "CUSTOMER",
            "金记录数": 1, "发布时间": "2026-11-01 10:00", "版本标识": "G9/v9",
        },
        {
            "id": 102, "status": "已发布", "pending": False, "abnormal": False,
            "发布批次": "PUB-G11-20261124", "实体编码": "CUSTOMER",
            "金记录数": 1, "发布时间": "2026-11-24 16:30", "版本标识": "G11/v11",
        },
        {
            "id": 103, "status": "已发布", "pending": False, "abnormal": False,
            "发布批次": "PUB-G12-20261115", "实体编码": "CUSTOMER",
            "金记录数": 1, "发布时间": "2026-11-15 09:30", "版本标识": "G12/v12",
        },
    ],
    "id_cross_map": [
        {
            "id": 101, "status": "已撤回", "pending": False, "abnormal": True,
            "映射批次": MAPPING_BATCH, "源系统标识": "CRM-7", "金记录标识": "G9",
            "映射置信度": "0.99", "映射状态": "已撤回",
            "source_system": "CRM", "mapping_version": 1, "is_current": False,
            "corrected_to": "G11",
            "撤回原因": "合并生还规则修正，原映射撤回并更正确认到 G11",
            "登记时间": "2026-11-20 09:00",
        },
        {
            "id": 102, "status": "已映射", "pending": False, "abnormal": False,
            "映射批次": MAPPING_BATCH, "源系统标识": "CRM-7", "金记录标识": "G11",
            "映射置信度": "0.99", "映射状态": "已映射",
            "source_system": "CRM", "mapping_version": 2, "is_current": True,
            "corrects": "G9",
            "更正说明": "撤回 CRM-7→G9 后，按 PUB-G11-20261124 更正确认到 G11",
            "登记时间": "2026-11-24 16:40",
        },
        {
            "id": 103, "status": "已映射", "pending": False, "abnormal": False,
            "映射批次": MAPPING_BATCH, "源系统标识": "CRM-8", "金记录标识": "G12",
            "映射置信度": "1.00", "映射状态": "已映射",
            "source_system": "CRM", "mapping_version": 1, "is_current": True,
            "登记时间": "2026-11-20 09:00",
        },
        {
            "id": 104, "status": "已映射", "pending": False, "abnormal": False,
            "映射批次": MAPPING_BATCH, "源系统标识": "ERP-3", "金记录标识": "G11",
            "映射置信度": "0.97", "映射状态": "已映射",
            "source_system": "ERP", "mapping_version": 1, "is_current": True,
            "登记时间": "2026-11-21 11:00",
        },
    ],
    "lineage_graph": [
        {
            "id": 101, "status": "失效", "pending": False, "abnormal": True,
            "血缘边标识": "edge-CRM-7-G9",
            "上游节点": "CRM-7", "下游节点": "G9",
            "变换规则": f"标识交叉映射/{MAPPING_BATCH}#v1",
            "登记时间": "2026-11-20 09:00",
            "edge_role": "旧边", "source_system": "CRM",
            "mapping_batch": MAPPING_BATCH, "mapping_version": "v1",
            "superseded_by": "edge-CRM-7-G11",
            "撤回原因": "CRM-7→G9 原映射已撤回，合法更正为 G11",
        },
        {
            "id": 102, "status": "已登记", "pending": False, "abnormal": False,
            "血缘边标识": "edge-CRM-7-G11",
            "上游节点": "CRM-7", "下游节点": "G11",
            "变换规则": f"标识交叉映射/{MAPPING_BATCH}#v2",
            "登记时间": "2026-11-24 16:40",
            "edge_role": "新边", "source_system": "CRM",
            "mapping_batch": MAPPING_BATCH, "mapping_version": "v2",
            "supersedes": "edge-CRM-7-G9",
        },
        {
            "id": 103, "status": "已登记", "pending": False, "abnormal": False,
            "血缘边标识": "edge-CRM-8-G12",
            "上游节点": "CRM-8", "下游节点": "G12",
            "变换规则": f"标识交叉映射/{MAPPING_BATCH}#v1",
            "登记时间": "2026-11-20 09:00",
            "edge_role": "当前边", "source_system": "CRM",
            "mapping_batch": MAPPING_BATCH, "mapping_version": "v1",
        },
        {
            "id": 104, "status": "已登记", "pending": False, "abnormal": False,
            "血缘边标识": "edge-ERP-3-G11",
            "上游节点": "ERP-3", "下游节点": "G11",
            "变换规则": f"标识交叉映射/{MAPPING_BATCH}#v1",
            "登记时间": "2026-11-21 11:00",
            "edge_role": "当前边", "source_system": "ERP",
            "mapping_batch": MAPPING_BATCH, "mapping_version": "v1",
        },
    ],
    "recon_package": [
        {
            "id": 1,
            "code": ORIGINAL_PACKAGE,
            "title": "CRM 标识对账清单（11月上期 · 交付版 v1）",
            "direction": "sent",
            "status": "待回传",
            "source_system": "CRM",
            "mapping_batch": MAPPING_BATCH,
            "basis": f"{MAPPING_BATCH}@v1",
            "basis_label": "交付版 v1（CRM-7→G9）",
            "file_name": f"reconciliation_CRM_{ORIGINAL_PACKAGE}.csv",
            "sent_at": "2026-11-20 18:00",
            "returned_at": "",
            "content_hash": "",
            "original_package_code": "",
            "resubmit_count": 0,
            "items": [
                {
                    "line_no": 1, "item_code": f"{ORIGINAL_PACKAGE}-1",
                    "source_system": "CRM", "entity_code": "CUSTOMER",
                    "entity_name": "客户", "source_id": "CRM-7",
                    "delivered_golden": "G9",
                    "mapping_batch": MAPPING_BATCH, "basis": f"{MAPPING_BATCH}@v1",
                    "row_token": "rt-CRM7-G9-v1",
                    "opinion": "", "opinion_note": "", "suggested_golden": "",
                    "opinion_status": "待确认",
                    "adopted": False, "disagreement_id": "",
                },
                {
                    "line_no": 2, "item_code": f"{ORIGINAL_PACKAGE}-2",
                    "source_system": "CRM", "entity_code": "CUSTOMER",
                    "entity_name": "客户", "source_id": "CRM-8",
                    "delivered_golden": "G12",
                    "mapping_batch": MAPPING_BATCH, "basis": f"{MAPPING_BATCH}@v1",
                    "row_token": "rt-CRM8-G12-v1",
                    "opinion": "", "opinion_note": "", "suggested_golden": "",
                    "opinion_status": "待确认",
                    "adopted": False, "disagreement_id": "",
                },
            ],
        },
        {
            "id": 2,
            "code": NEW_PACKAGE,
            "title": "CRM 标识对账清单（更正后新包 · 交付版 v2）",
            "direction": "sent",
            "status": "待回传",
            "source_system": "CRM",
            "mapping_batch": MAPPING_BATCH,
            "basis": f"{MAPPING_BATCH}@v2",
            "basis_label": "更正后新包 v2（CRM-7→G11）",
            "file_name": f"reconciliation_CRM_{NEW_PACKAGE}.csv",
            "sent_at": "2026-11-25 09:00",
            "returned_at": "",
            "content_hash": "",
            "original_package_code": "",
            "resubmit_count": 0,
            "items": [
                {
                    "line_no": 1, "item_code": f"{NEW_PACKAGE}-1",
                    "source_system": "CRM", "entity_code": "CUSTOMER",
                    "entity_name": "客户", "source_id": "CRM-7",
                    "delivered_golden": "G11",
                    "mapping_batch": MAPPING_BATCH, "basis": f"{MAPPING_BATCH}@v2",
                    "row_token": "rt-CRM7-G11-v2",
                    "opinion": "", "opinion_note": "", "suggested_golden": "",
                    "opinion_status": "待确认",
                    "adopted": False, "disagreement_id": "",
                },
                {
                    "line_no": 2, "item_code": f"{NEW_PACKAGE}-2",
                    "source_system": "CRM", "entity_code": "CUSTOMER",
                    "entity_name": "客户", "source_id": "CRM-8",
                    "delivered_golden": "G12",
                    "mapping_batch": MAPPING_BATCH, "basis": f"{MAPPING_BATCH}@v2",
                    "row_token": "rt-CRM8-G12-v2",
                    "opinion": "", "opinion_note": "", "suggested_golden": "",
                    "opinion_status": "待确认",
                    "adopted": False, "disagreement_id": "",
                },
            ],
        },
    ],
    "recon_disagreement": [],
}


def install_scenario(seed_rows: dict[str, list[dict[str, Any]]]) -> None:
    """把场景行追加进种子表；新表直接登记。幂等，方便重置时重复调用。"""
    for table, rows in SCENARIO_TABLES.items():
        bucket = seed_rows.setdefault(table, [])
        existing_ids = {int(row.get("id", -1)) for row in bucket}
        for row in rows:
            if int(row.get("id", -1)) not in existing_ids:
                bucket.append(row)
