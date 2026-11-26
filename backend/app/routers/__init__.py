"""业务路由汇总：专用对账/血缘路由在前，通用资源路由兜底分派。"""
from __future__ import annotations

from app.routers import reconciliation, resource

ROUTERS = [reconciliation, resource]
