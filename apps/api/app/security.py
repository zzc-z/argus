"""HTTP 安全响应头。

## 为什么后端只设这一组，不设完整 CSP

OWASP REST Security Cheat Sheet 把头分成两类：一类只对 **HTML 文档**生效，
对不返回 HTML 的 API "may provide little or no security benefits"；另一类对
**任何**被浏览器消费的响应都成立。本文件只放第二类。

真正管 XSS 的那份 CSP（``script-src`` / ``style-src`` / ``connect-src``，
后者决定 fetch 与 SSE 能不能发出去）归前端，见 apps/web/next.config.js——
CSP 由浏览器对**发起请求的那个文档**执行，设在 JSON 响应上没有意义
（W3C CSP §3.5 Policy applicability 明确 CSP 不施加于 application/json）。

依据（2026-10-15 实查）：
- OWASP REST Security Cheat Sheet「Security Headers」
  https://cheatsheetseries.owasp.org/cheatsheets/REST_Security_Cheat_Sheet.html
- MDN Strict-Transport-Security / X-Content-Type-Options / Permissions-Policy
"""

from collections.abc import Mapping

from starlette.types import ASGIApp, Message, Receive, Scope, Send

# Permissions-Policy 取 OWASP cheat sheet 的推荐 deny-list。
# 逐条对着 apps/web 核过：本项目只用 navigator.clipboard（error-404 的
# TraceIdBar），而 clipboard 不在清单里；camera / microphone / geolocation /
# fullscreen / usb 全仓无引用。MDN 标注该头 Firefox 与 Safari 不支持
# （"not Baseline"），Chromium 系才认——属纵深防御，不是主力防线。
_PERMISSIONS_POLICY = ", ".join(
    f"{feature}=()"
    for feature in (
        "accelerometer",
        "ambient-light-sensor",
        "autoplay",
        "battery",
        "camera",
        "display-capture",
        "encrypted-media",
        "execution-while-not-rendered",
        "execution-while-out-of-viewport",
        "fullscreen",
        "geolocation",
        "gyroscope",
        "keyboard-map",
        "magnetometer",
        "microphone",
        "midi",
        "payment",
        "picture-in-picture",
        "publickey-credentials-get",
        "screen-wake-lock",
        "sync-xhr",
        "usb",
        "web-share",
        "xr-spatial-tracking",
    )
)

# frame-ancestors 'none' 挡住点击劫持（含 OWASP 点名的拖拽式攻击）。
# 这条 CSP 指令管的是「本响应能否被嵌进 iframe」，与响应体是不是 HTML 无关，
# 所以对 JSON API 依然成立——OWASP 把它列为 API 响应的推荐项。
# 同时发 X-Frame-Options: DENY 兜住不认 CSP 的老浏览器；两者值一致（都不许嵌），
# 现代浏览器按 CSP 规范忽略 XFO，不会出现互相打架。
_CSP = "frame-ancestors 'none'"

# Referrer-Policy 用 no-referrer：OWASP 给 API 响应的推荐值，理由是
# 「Non-HTML responses should not trigger additional requests」。
# OAuth 回调不依赖 Referer（靠 state 参数 + cookie），收紧不影响登录。
_REFERRER_POLICY = "no-referrer"

# nosniff 阻止 MIME 嗅探。MDN：响应若声明非 HTML 类型，浏览器不得改按 HTML
# 渲染——这正是把用户内容（研报正文）塞进 JSON 响应时的经典 XSS 载体。
_NOSNIFF = "nosniff"

_FRAME_OPTIONS = "DENY"

# HSTS：MDN 明确「浏览器在 HTTP 下会忽略该头」，所以它对本地 http 开发毫无
# 作用，却会在有人用 HTTPS 跑开发时把整个域名钉死。故只在 app_env=prod 下发。
_HSTS = "max-age=31536000; includeSubDomains"


def build_security_headers(*, enable_hsts: bool) -> dict[str, str]:
    """构造要附加到每个响应上的头。

    ``enable_hsts`` 由调用方按 ``app_env`` 决定——判断放在 main.py，
    这里只管组装，不读配置（app/config.py 是唯一读环境变量的地方）。
    """
    headers = {
        "content-security-policy": _CSP,
        "x-content-type-options": _NOSNIFF,
        "x-frame-options": _FRAME_OPTIONS,
        "referrer-policy": _REFERRER_POLICY,
        "permissions-policy": _PERMISSIONS_POLICY,
    }
    if enable_hsts:
        headers["strict-transport-security"] = _HSTS
    return headers


class SecurityHeadersMiddleware:
    """给每个响应补上安全头。

    写成裸 ASGI 而不是 ``BaseHTTPMiddleware``：后者会把 ``StreamingResponse``
    包进自己的任务里，与 SSE 流式响应有已知的缓冲 / 中断问题（见
    ``app/gateway/research.py`` 的 ``text/event-stream``，那边逐块 yield 依赖
    数据立刻出栈）。本中间件只在 ``http.response.start`` 消息上补头，
    响应体一个字节都不碰。

    已存在的同名头不覆盖——让路由自己说了算（目前没有，但 SSE 路由就明确
    自设了 Cache-Control，不该被这里改掉）。
    """

    def __init__(self, app: ASGIApp, headers: Mapping[str, str]) -> None:
        self._app = app
        # 预先编码：每个请求都要补，不能每次重算。
        self._raw = tuple((key.lower().encode(), value.encode()) for key, value in headers.items())

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        # lifespan / websocket 不走这里，直接放行。
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return

        async def send_with_security_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                self._inject(message)
            await send(message)

        await self._app(scope, receive, send_with_security_headers)

    def _inject(self, message: Message) -> None:
        existing = message.setdefault("headers", [])
        present = {key.lower() for key, _ in existing}
        existing.extend((key, value) for key, value in self._raw if key not in present)
