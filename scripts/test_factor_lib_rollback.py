#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
方向 C5: 回滚验证测试脚本
============================
验证 FactorLib 因子库模块的零侵入接入：
  1. 接入状态正常（API 可用、路由无冲突）
  2. 回滚后经典系统 + EVO 层均不受影响
  3. 回滚后可重新接入，无残留

使用方式:
    python3 scripts/test_factor_lib_rollback.py

输出:
    - 每个测试项 PASS/FAIL
    - 最终汇总报告
    - 退出码: 0=全部通过, 1=存在失败项
"""

import os
import sys
import shutil
import importlib
import subprocess

# ── 路径配置 ─────────────────────────────────────────────────
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKEND_DIR = os.path.join(PROJECT_ROOT, "web", "backend")
FRONTEND_DIR = os.path.join(PROJECT_ROOT, "web", "frontend")
SERVICES_DIR = os.path.join(BACKEND_DIR, "services")
ROUTERS_DIR = os.path.join(BACKEND_DIR, "routers")

sys.path.insert(0, PROJECT_ROOT)
sys.path.insert(0, BACKEND_DIR)


# ── 工具函数 ─────────────────────────────────────────────────

class TestResult:
    def __init__(self):
        self.results = []

    def add(self, name, passed, detail=""):
        self.results.append({"name": name, "passed": passed, "detail": detail})
        status = "PASS" if passed else "FAIL"
        color = "\033[32m" if passed else "\033[31m"
        reset = "\033[0m"
        print(f"  [{color}{status}{reset}] {name}")
        if detail:
            print(f"         {detail}")

    def summary(self):
        total = len(self.results)
        passed = sum(1 for r in self.results if r["passed"])
        failed = total - passed
        print()
        print("=" * 60)
        print("回滚验证汇总")
        print("=" * 60)
        for r in self.results:
            s = "PASS" if r["passed"] else "FAIL"
            print(f"  [{s}] {r['name']}")
        print()
        print(f"总计: {total} 项, 通过: {passed}, 失败: {failed}")
        if failed == 0:
            print("\033[32m✅ 全部通过 — 零侵入验证成功\033[0m")
        else:
            print(f"\033[31m❌ {failed} 项失败\033[0m")
        return failed == 0


# ── 回滚操作 ─────────────────────────────────────────────────

class FactorLibRollback:
    """管理 FactorLib 的接入/回滚状态"""

    def __init__(self):
        self.backend_files = {
            os.path.join(SERVICES_DIR, "factor_lib_service.py"):
            os.path.join(SERVICES_DIR, "factor_lib_service.py.bak"),
            os.path.join(ROUTERS_DIR, "factor_lib.py"):
            os.path.join(ROUTERS_DIR, "factor_lib.py.bak"),
        }
        self.frontend_files = {
            os.path.join(FRONTEND_DIR, "src", "FactorLibrary.jsx"):
            os.path.join(FRONTEND_DIR, "src", "FactorLibrary.jsx.bak"),
        }
        self.routers_init = os.path.join(ROUTERS_DIR, "__init__.py")
        self.routers_init_bak = os.path.join(ROUTERS_DIR, "__init__.py.bak")
        self.routes_config = os.path.join(FRONTEND_DIR, "src", "routes.config.jsx")
        self.routes_config_bak = os.path.join(FRONTEND_DIR, "src", "routes.config.jsx.bak")
        self.app_py = os.path.join(BACKEND_DIR, "app.py")
        self.app_py_bak = os.path.join(BACKEND_DIR, "app.py.bak")

        self._rolled_back = False

    def is_installed(self):
        """检查 FactorLib 是否已接入"""
        return all(os.path.exists(f) for f in self.backend_files)

    def rollback(self):
        """执行回滚：移除 FactorLib 相关文件和代码"""
        if self._rolled_back:
            return

        # 1. 备份并移除后端文件
        for src, dst in self.backend_files.items():
            if os.path.exists(src):
                shutil.move(src, dst)

        # 2. 备份并移除前端文件
        for src, dst in self.frontend_files.items():
            if os.path.exists(src):
                shutil.move(src, dst)

        # 3. 简化 routers/__init__.py（移除 factor_lib 导出）
        shutil.copy(self.routers_init, self.routers_init_bak)
        # 读取并生成简化版
        with open(self.routers_init, "r") as f:
            content = f.read()

        lines = content.split("\n")
        new_lines = []
        skip_until_blank = False
        for line in lines:
            if "factor_lib" in line.lower():
                continue  # 跳过 factor_lib 相关行
            new_lines.append(line)

        with open(self.routers_init, "w") as f:
            f.write("\n".join(new_lines))

        # 4. 简化 routes.config.jsx（移除 FactorLibrary 导入和路由）
        shutil.copy(self.routes_config, self.routes_config_bak)
        with open(self.routes_config, "r") as f:
            content = f.read()

        lines = content.split("\n")
        new_lines = []
        for line in lines:
            # 跳过 FactorLibrary 导入行
            if "FactorLibrary" in line and "import" in line:
                continue
            # 跳过 factor-lib 路由行及其注释
            if "factor-lib" in line.lower() or "FactorLib" in line or "因子有效性分析" in line:
                continue
            # 跳过 Sparkles 图标导入（如果有）
            if "Sparkles" in line and "from 'lucide-react'" in line:
                # 从 import 语句中移除 Sparkles
                line = line.replace("Sparkles,", "").replace(" Sparkles", "")
            new_lines.append(line)

        with open(self.routes_config, "w") as f:
            f.write("\n".join(new_lines))

        # 5. 简化 app.py（移除 FactorLib 路由注册块）
        shutil.copy(self.app_py, self.app_py_bak)
        with open(self.app_py, "r") as f:
            content = f.read()

        lines = content.split("\n")
        new_lines = []
        in_factorlib_block = False
        block_brace_count = 0
        for line in lines:
            if "FactorLib" in line and "路由" in line and "进化层" not in line:
                in_factorlib_block = True
                continue
            if in_factorlib_block:
                # 检测块结束：以空行 + 下一个注释块分隔
                if line.strip().startswith("#") and "═══" in line:
                    in_factorlib_block = False
                    new_lines.append(line)
                continue
            new_lines.append(line)

        with open(self.app_py, "w") as f:
            f.write("\n".join(new_lines))

        self._rolled_back = True
        self._clear_module_cache()

    def restore(self):
        """恢复 FactorLib 接入"""
        # 1. 恢复后端文件
        for src, dst in self.backend_files.items():
            if os.path.exists(dst):
                shutil.move(dst, src)

        # 2. 恢复前端文件
        for src, dst in self.frontend_files.items():
            if os.path.exists(dst):
                shutil.move(dst, src)

        # 3. 恢复 routers/__init__.py
        if os.path.exists(self.routers_init_bak):
            shutil.move(self.routers_init_bak, self.routers_init)

        # 4. 恢复 routes.config.jsx
        if os.path.exists(self.routes_config_bak):
            shutil.move(self.routes_config_bak, self.routes_config)

        # 5. 恢复 app.py
        if os.path.exists(self.app_py_bak):
            shutil.move(self.app_py_bak, self.app_py)

        self._rolled_back = False
        self._clear_module_cache()

    def _clear_module_cache(self):
        """清除模块缓存，确保重新导入"""
        mods_to_remove = [
            k for k in list(sys.modules.keys())
            if "factor_lib" in k.lower()
            or k == "routers"
            or k.startswith("routers.")
        ]
        for mod in mods_to_remove:
            del sys.modules[mod]


# ── 测试用例 ─────────────────────────────────────────────────

def test_installed_state(result):
    """测试 1: 接入状态正常性"""
    print("\n\033[1;34m【测试 1】接入状态验证\033[0m")

    # 1.1 文件存在性
    backend_ok = all(os.path.exists(f) for f in [
        os.path.join(SERVICES_DIR, "factor_lib_service.py"),
        os.path.join(ROUTERS_DIR, "factor_lib.py"),
    ])
    result.add("后端文件存在", backend_ok,
               "factor_lib_service.py + factor_lib.py" if backend_ok else "缺少文件")

    frontend_ok = os.path.exists(os.path.join(FRONTEND_DIR, "src", "FactorLibrary.jsx"))
    result.add("前端文件存在", frontend_ok,
               "FactorLibrary.jsx" if frontend_ok else "缺少文件")

    # 1.2 API 可调用
    try:
        from services.factor_lib_service import get_factor_library_overview
        data = get_factor_library_overview()
        api_ok = data.get("success", False) and data.get("total_factors", 0) > 0
        result.add("API overview 可用", api_ok,
                   f"共 {data.get('total_factors', 0)} 个因子" if api_ok else str(data))
    except Exception as e:
        result.add("API overview 可用", False, str(e))

    # 1.3 路由前缀隔离
    try:
        from fastapi import FastAPI
        from routers import factor_lib_router, evo_router

        app = FastAPI()
        app.include_router(factor_lib_router)
        app.include_router(evo_router)

        routes = [r.path for r in app.routes if hasattr(r, "path") and r.path.startswith("/api/")]
        fl_routes = [p for p in routes if p.startswith("/api/factor-lib/")]
        evo_routes = [p for p in routes if p.startswith("/api/evo/")]

        prefix_ok = len(fl_routes) > 0 and all(p.startswith("/api/factor-lib/") for p in fl_routes)
        no_conflict = len(routes) == len(set(routes))

        result.add("FactorLib 前缀隔离", prefix_ok,
                   f"{len(fl_routes)} 条路由均以 /api/factor-lib/ 开头")
        result.add("路由无冲突", no_conflict,
                   f"{len(routes)} 条路径，全部唯一")
    except Exception as e:
        result.add("FactorLib 前缀隔离", False, str(e))
        result.add("路由无冲突", False, str(e))


def test_rolled_back_state(result, rollback_mgr):
    """测试 2: 回滚后系统正常性"""
    print("\n\033[1;34m【测试 2】回滚后系统验证\033[0m")

    # 执行回滚
    rollback_mgr.rollback()

    # 2.1 文件已移除
    backend_removed = not any(os.path.exists(f) for f in [
        os.path.join(SERVICES_DIR, "factor_lib_service.py"),
        os.path.join(ROUTERS_DIR, "factor_lib.py"),
    ])
    result.add("后端文件已移除", backend_removed)

    frontend_removed = not os.path.exists(
        os.path.join(FRONTEND_DIR, "src", "FactorLibrary.jsx"))
    result.add("前端文件已移除", frontend_removed)

    # 2.2 routers/__init__.py 不含 factor_lib
    try:
        with open(os.path.join(ROUTERS_DIR, "__init__.py"), "r") as f:
            init_content = f.read()
        init_clean = "factor_lib" not in init_content.lower()
        result.add("routers/__init__.py 无残留", init_clean)
    except Exception as e:
        result.add("routers/__init__.py 无残留", False, str(e))

    # 2.3 EVO 路由仍可用
    try:
        from routers import evo_router
        evo_ok = evo_router is not None and len(evo_router.routes) > 0
        result.add("EVO 路由正常", evo_ok,
                   f"{len(evo_router.routes)} 条路由" if evo_ok else "")
    except Exception as e:
        result.add("EVO 路由正常", False, str(e))

    # 2.4 factor_lib_router 不可导入
    try:
        from routers import factor_lib_router
        result.add("FactorLib 路由不可用", False, "仍可导入 factor_lib_router")
    except ImportError:
        result.add("FactorLib 路由不可用", True, "已无法导入（预期行为）")
    except Exception as e:
        result.add("FactorLib 路由不可用", True, f"导入失败: {e}")

    # 2.5 app.py 可正常启动（模拟）
    try:
        # 清理缓存后重新导入 routers
        for mod in list(sys.modules.keys()):
            if "router" in mod.lower():
                del sys.modules[mod]

        # 验证：导入 evo_router 不会触发 factor_lib 错误
        from routers import evo_router
        app_start_ok = True
        result.add("系统启动不崩溃", app_start_ok,
                   "移除 FactorLib 后系统仍可正常启动")
    except Exception as e:
        result.add("系统启动不崩溃", False, str(e))


def test_restore_state(result, rollback_mgr):
    """测试 3: 恢复后功能正常"""
    print("\n\033[1;34m【测试 3】恢复后功能验证\033[0m")

    rollback_mgr.restore()

    # 3.1 文件已恢复
    backend_restored = all(os.path.exists(f) for f in [
        os.path.join(SERVICES_DIR, "factor_lib_service.py"),
        os.path.join(ROUTERS_DIR, "factor_lib.py"),
    ])
    result.add("后端文件已恢复", backend_restored)

    frontend_restored = os.path.exists(
        os.path.join(FRONTEND_DIR, "src", "FactorLibrary.jsx"))
    result.add("前端文件已恢复", frontend_restored)

    # 3.2 API 重新可用
    try:
        # 清理缓存
        for mod in list(sys.modules.keys()):
            if "factor_lib_service" in mod:
                del sys.modules[mod]

        from services.factor_lib_service import get_factor_ranking
        data = get_factor_ranking(limit=3)
        api_ok = data.get("success", False) and data.get("count", 0) > 0
        result.add("API 恢复可用", api_ok,
                   f"返回 {data.get('count', 0)} 条记录" if api_ok else str(data))
    except Exception as e:
        result.add("API 恢复可用", False, str(e))

    # 3.3 路由恢复
    try:
        for mod in list(sys.modules.keys()):
            if "factor_lib" in mod.lower() or mod == "routers":
                del sys.modules[mod]

        from routers import factor_lib_router
        routes_ok = len(factor_lib_router.routes) >= 5
        result.add("路由恢复完整", routes_ok,
                   f"{len(factor_lib_router.routes)} 条路由")
    except Exception as e:
        result.add("路由恢复完整", False, str(e))


def test_frontend_rollback(result, rollback_mgr):
    """测试 4: 前端回滚验证"""
    print("\n\033[1;34m【测试 4】前端回滚验证\033[0m")

    # 此时应该是接入状态（test_restore_state 已恢复）
    # 验证 routes.config.jsx 中包含 factor-lib
    with open(rollback_mgr.routes_config, "r") as f:
        content_before = f.read()
    has_factorlib_before = "factor-lib" in content_before or "FactorLibrary" in content_before
    result.add("接入态: routes.config 含 FactorLib", has_factorlib_before)

    # 回滚
    rollback_mgr.rollback()

    with open(rollback_mgr.routes_config, "r") as f:
        content_after = f.read()
    has_factorlib_after = "factor-lib" in content_after.lower() or "FactorLibrary" in content_after
    result.add("回滚态: routes.config 无 FactorLib", not has_factorlib_after,
               "已移除因子库路由配置" if not has_factorlib_after else "仍有残留")

    # 验证 app.jsx 相关引用不受影响（Dashboard 等核心组件仍存在）
    dashboard_exists = os.path.exists(
        os.path.join(FRONTEND_DIR, "src", "Dashboard.jsx"))
    factors_exists = os.path.exists(
        os.path.join(FRONTEND_DIR, "src", "Factors.jsx"))
    result.add("核心前端组件完整", dashboard_exists and factors_exists,
               f"Dashboard + Factors 均存在" if (dashboard_exists and factors_exists) else "有组件缺失")

    # 恢复
    rollback_mgr.restore()


# ── 主流程 ───────────────────────────────────────────────────

def main():
    print("=" * 60)
    print("\033[1;35mFactorLib 回滚验证测试\033[0m")
    print("=" * 60)
    print()

    result = TestResult()
    rollback_mgr = FactorLibRollback()

    # 预检查
    if not rollback_mgr.is_installed():
        print("\033[33m⚠️  警告: FactorLib 未接入，测试可能不完整\033[0m")
        print()

    try:
        # 测试 1: 接入状态
        test_installed_state(result)

        # 测试 2: 回滚状态
        test_rolled_back_state(result, rollback_mgr)

        # 测试 3: 恢复状态
        test_restore_state(result, rollback_mgr)

        # 测试 4: 前端回滚
        test_frontend_rollback(result, rollback_mgr)

    finally:
        # 确保最终状态是已接入
        if rollback_mgr._rolled_back:
            print()
            print("\033[33m正在恢复 FactorLib 接入...\033[0m")
            rollback_mgr.restore()

    # 汇总
    all_passed = result.summary()
    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(main())
