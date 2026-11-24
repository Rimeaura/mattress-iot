"""备用的iot路由，使用http模式获取数据流转推送

由于不具备公网，只能使用amqp模式，该http模式用作未来扩展
"""

import hashlib
from typing import Optional

from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/iot", tags=["iot"])

# 这里填你在华为云 IoT 控制台创建订阅时设置的 Token（3-32位字母/数字）
SUBSCRIBE_TOKEN = "aaaaaa"

# 推送数据体 —— 根据实际订阅的数据类型调整字段
class IotPushPayload(BaseModel):
    resource: Optional[str] = None
    event: Optional[str] = None
    device_id: Optional[str] = None
    payload: Optional[dict] = None
    # TODO: 根据华为云「数据流转」文档补充完整字段

# 签名校验（完全照搬文档的 Java 示例逻辑）
def verify_signature(nonce: str, timestamp: str, signature: str) -> bool:
    items = sorted([SUBSCRIBE_TOKEN, nonce, timestamp])
    raw = "".join(items)
    computed = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    return computed == signature

@router.post("/callback")
async def iot_callback(request: Request):
    # 读取鉴权头
    nonce      = request.headers.get("nonce", "")
    timestamp  = request.headers.get("timestamp", "")
    signature  = request.headers.get("signature", "")

    # 校验签名（HTTP/HTTPS 模式都走 Token 鉴权）
    if not verify_signature(nonce, timestamp, signature):
        raise HTTPException(status_code=403, detail="signature mismatch")

    # 读取推送体（Pydantic 自动校验）
    body = await request.json()
    payload = IotPushPayload(**body)

    # 关键：收到后立即返回 200，别阻塞 IoT 平台
    # 后续业务逻辑放异步任务/队列里慢慢处理
    print(f"[IoT Push] device={payload.device_id}, event={payload.event}")

    return {"code": 0, "message": "ok"}
