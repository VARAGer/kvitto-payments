import hashlib
import hmac

from fastapi import Header, HTTPException, Request


async def verify_bank_signature(request: Request, x_signature: str | None = Header(default=None)):
    body = await request.body()
    expected = hmac.new(
        request.app.state.webhook_secret.encode(), body, hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(expected.encode(), (x_signature or "").encode()):
        raise HTTPException(status_code=401, detail="invalid signature")
