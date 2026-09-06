# -*- coding: utf-8 -*-
"""
routers 包 —— 按业务职责拆分的 FastAPI APIRouter 集合
========================================================
当前包含：
    evo.py              EVO 进化层路由（/api/evo/*，平行于经典路由）
    factor_lib.py       因子库路由（/api/factor-lib/*，平行层，零侵入）
    multi_factor_202609.py  202609 多因子分析（/api/mf202609/*，平行层，零侵入）
    resonance.py        四重共振策略（/api/resonance/*，平行层，零侵入）
后续如要拆分其他子路由（如 /api/admin、/api/reports），
在此目录下新增对应文件并在 app.py 中 include_router 即可。
"""

from .evo import router as evo_router
from .factor_lib import router as factor_lib_router
from .multi_factor_202609 import router as mf202609_router
from .resonance import router as resonance_router

__all__ = ["evo_router", "factor_lib_router", "mf202609_router", "resonance_router"]
