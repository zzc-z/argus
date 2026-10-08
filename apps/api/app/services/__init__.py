"""业务编排层。

职责：把「数据访问」（models的 @classmethod）与「外部 IO」（OAuth调GitHub API）
串成一段业务流程，路由只负责 HTTP 解析和响应。

依赖方向单向：gateway → services → models。禁止反向依赖。
"""

from app.services.auth import get_or_create_user

__all__ = ["get_or_create_user"]
