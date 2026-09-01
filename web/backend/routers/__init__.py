# -*- coding: utf-8 -*-
"""
routers 包 —— 按业务职责拆分的 FastAPI APIRouter 集合
========================================================
当前仅包含：
    evo.py  EVO 进化层路由（/api/evo/*，平行于经典路由）
后续如要拆分其他子路由（如 /api/admin、/api/reports），
在此目录下新增对应文件并在 app.py 中 include_router 即可。
"""

from .evo import router as evo_router

__all__ = ["evo_router"]
