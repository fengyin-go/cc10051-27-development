"""标识交叉映射 · 对账下载/回传确认，以及血缘回导校验的专用路由。

业务判断全部在 app.services 内完成，路由只做协议适配。
"""
from __future__ import annotations

import json
from typing import Any
from urllib.parse import parse_qsl

from fastapi import APIRouter, Query, Request
from fastapi.responses import Response

from app.services.lineage_graph import LineageGraphService
from app.services.reconciliation_service import reconciliation_service as svc

router = APIRouter(prefix="/api", tags=["对账回传"])


def _parse_multipart(body: bytes, boundary: str) -> dict[str, Any]:
    """极简 multipart 解析：不依赖 python-multipart，只取普通字段与文本文件。"""
    delim = ("--" + boundary).encode()
    payload: dict[str, Any] = {}
    for part in body.split(delim):
        part = part.removeprefix(b"\r\n").removesuffix(b"\r\n")
        if not part or part in (b"--", b"--\r\n"):
            continue
        if b"\r\n\r\n" not in part:
            continue
        raw_headers, content = part.split(b"\r\n\r\n", 1)
        headers = raw_headers.decode("utf-8", errors="replace")
        name = ""
        filename = ""
        for token in headers.replace(";", "\r\n").splitlines():
            token = token.strip()
            if token.lower().startswith("name="):
                name = token.split("=", 1)[1].strip('"')
            if token.lower().startswith("filename="):
                filename = token.split("=", 1)[1].strip('"')
        text = content.decode("utf-8-sig", errors="replace")
        if filename:
            payload["file_name"] = filename
            payload["content"] = text
        elif name:
            payload[name] = text
    return payload


async def _payload(request: Request) -> dict[str, Any]:
    """兼容 JSON、urlencoded、multipart、裸 CSV 文本等回传形态。"""
    ctype = request.headers.get("content-type", "")
    body = await request.body()
    if "application/json" in ctype:
        try:
            data = json.loads(body.decode("utf-8-sig"))
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}
    if "multipart/form-data" in ctype:
        boundary = ""
        for piece in ctype.split(";"):
            piece = piece.strip()
            if piece.startswith("boundary="):
                boundary = piece.split("=", 1)[1].strip().strip('"')
        if boundary:
            return _parse_multipart(body, boundary)
        return {}
    text = body.decode("utf-8-sig", errors="replace")
    if "application/x-www-form-urlencoded" in ctype:
        form = dict(parse_qsl(text, keep_blank_values=True))
        return form
    if text.strip():
        # 裸 CSV / 文本回传：来源可由 query 或源标识前缀推断。
        return {
            "content": text,
            "source": request.query_params.get("source", ""),
            "package_code": request.query_params.get("package_code", ""),
        }
    return {}


# ---------- 对账工作台聚合数据 ----------

@router.get("/id_cross_map/reconciliation/state")
def recon_state() -> dict[str, Any]:
    return svc.state()


@router.get("/id_cross_map/reconciliation/packages")
def recon_packages() -> dict[str, Any]:
    state = svc.state()
    return {"items": state["packages"], "total": len(state["packages"])}


@router.get("/id_cross_map/reconciliation/packages/{code}")
def recon_package_detail(code: str) -> dict[str, Any]:
    pkg = svc.get_package(code)
    if pkg is None:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail=f"对账批次 {code} 不存在")
    return pkg


# ---------- 对账下载（来源隔离 + 单一映射依据） ----------

@router.get("/id_cross_map/reconciliation/download")
def recon_download(
    source: str = Query(default="CRM"),
    package_code: str = Query(default=""),
) -> Response:
    try:
        file_name, csv_text = svc.build_download(source, package_code)
    except PermissionError as exc:
        from fastapi import HTTPException
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return Response(
        content=csv_text.encode("utf-8"),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{file_name}"'},
    )


# ---------- 回传预览 / 确认提交 ----------

@router.post("/id_cross_map/reconciliation/preview")
async def recon_preview(request: Request) -> dict[str, Any]:
    payload = await _payload(request)
    try:
        rows, source, package_code = svc.parse_submission(payload)
        return svc.verify(rows, source, package_code)
    except ValueError as exc:
        return {"ok": False, "message": str(exc), "rows": [], "summary": {}}


@router.post("/id_cross_map/reconciliation/commit")
async def recon_commit(request: Request) -> dict[str, Any]:
    payload = await _payload(request)
    try:
        return svc.commit_return(payload)
    except ValueError as exc:
        return {"ok": False, "message": str(exc)}


# 语义化别名：部分调用方可能把“回传确认”打到 /return 或 /upload。
@router.post("/id_cross_map/reconciliation/return")
async def recon_return_alias(request: Request) -> dict[str, Any]:
    return await recon_commit(request)


@router.post("/id_cross_map/reconciliation/upload")
async def recon_upload_alias(request: Request) -> dict[str, Any]:
    return await recon_commit(request)


# ---------- 意见采纳 / 分歧处置 ----------

@router.post("/id_cross_map/reconciliation/adopt-opinion")
async def recon_adopt(request: Request) -> dict[str, Any]:
    payload = await _payload(request)
    opinion_id = str(payload.get("opinion_id") or "")
    adopted = payload.get("adopted", True)
    return svc.adopt_opinion(opinion_id, bool(adopted))


@router.post("/id_cross_map/reconciliation/disagreements/{code}/handle")
async def recon_handle(code: str, request: Request) -> dict[str, Any]:
    payload = await _payload(request)
    decision = str(payload.get("decision") or payload.get("action") or "")
    operator = str(payload.get("operator") or "数据管理员")
    return svc.handle_disagreement(code, decision, operator)


# ---------- 实际金记录查询 / 场景重放 ----------

@router.get("/id_cross_map/actual-golden")
def actual_golden(source_id: str = Query(default="CRM-7")) -> dict[str, Any]:
    return svc.actual_golden(source_id)


@router.post("/id_cross_map/scenario/correct")
async def scenario_correct(request: Request) -> dict[str, Any]:
    payload = await _payload(request)
    return svc.correct_mapping(
        str(payload.get("source_id") or "CRM-7"),
        str(payload.get("to_golden") or ""),
    )


@router.post("/id_cross_map/scenario/reset")
def scenario_reset() -> dict[str, Any]:
    return svc.reset_scenario()


# ---------- 血缘：按回导明细校验来源 + 旧边/新边 ----------

@router.get("/lineage_graph/reconciliation-trace")
def lineage_trace(
    source_id: str = Query(...),
    delivered_golden: str = Query(default=""),
    package_code: str = Query(default=""),
) -> dict[str, Any]:
    return LineageGraphService().reconciliation_trace(source_id, delivered_golden, package_code)


@router.post("/lineage_graph/verify-reimport")
async def lineage_verify_reimport(request: Request) -> dict[str, Any]:
    payload = await _payload(request)
    items = payload.get("items") or payload.get("rows") or []
    if isinstance(items, dict):
        items = [items]
    return LineageGraphService().verify_reimport(list(items))
