import json
import math
import os
from collections.abc import Iterator
from contextlib import asynccontextmanager

from fastapi import (
    Depends,
    FastAPI,
    Header,
    HTTPException,
    Path,
    Query,
    Request,
    Response,
)
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import EmailStr
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.db import setup_database
from app.models import Payment, Tariff
from app.schemas import (
    MAX_ID,
    BankWebhook,
    HealthOut,
    PaymentCreate,
    PaymentOut,
    PaymentStatus,
    TariffOut,
)
from app.security import verify_bank_signature


def get_session() -> Iterator[Session]:
    # The session factory is initialized in the application lifespan.
    with app.state.session_factory() as session:
        yield session


@asynccontextmanager
async def lifespan(application: FastAPI):
    secret = os.getenv("WEBHOOK_SECRET")
    if not secret:
        raise RuntimeError("Set WEBHOOK_SECRET before starting the application")
    application.state.webhook_secret = secret
    database_url = os.getenv("DATABASE_URL", "sqlite:///./payments.db")
    engine, application.state.session_factory = setup_database(database_url)
    try:
        yield
    finally:
        engine.dispose()


app = FastAPI(title="Квитто Payments API", lifespan=lifespan)


@app.exception_handler(RequestValidationError)
def validation_error_response(_request: Request, exc: RequestValidationError):
    # Invalid input must not cause another error while rendering the standard 422 body.
    errors = jsonable_encoder(exc.errors(), custom_encoder={
        float: lambda value: value if math.isfinite(value) else str(value),
        bytes: lambda value: value.decode("utf-8", errors="replace"),
    })
    return Response(
        content=json.dumps({"detail": errors}, ensure_ascii=True, allow_nan=False),
        status_code=422,
        media_type="application/json",
    )


@app.get("/health", response_model=HealthOut)
def health(session: Session = Depends(get_session)):
    try:
        # SQLite can execute SELECT 1 even when application tables are missing.
        session.execute(select(Tariff.id).limit(1))
        session.execute(select(Payment.id).limit(1))
    except SQLAlchemyError:
        session.rollback()
        raise HTTPException(status_code=503, detail="database unavailable")
    return {"status": "ok"}


@app.get("/tariffs", response_model=list[TariffOut])
def list_tariffs(session: Session = Depends(get_session)):
    return session.scalars(select(Tariff).order_by(Tariff.id)).all()


@app.post("/payments", response_model=PaymentOut, status_code=201)
def create_payment(
    data: PaymentCreate,
    response: Response,
    idempotency_key: str | None = Header(default=None, min_length=1, max_length=255),
    session: Session = Depends(get_session),
):
    if idempotency_key is not None:
        existing = session.scalar(select(Payment).where(Payment.idempotency_key == idempotency_key))
        if existing is not None:
            response.status_code = 200
            return existing

    tariff = session.get(Tariff, data.tariff_id)
    if tariff is None:
        raise HTTPException(status_code=404, detail="tariff not found")

    discount = tariff.price // 10 if data.promo_code is not None else 0
    amount = tariff.price - discount
    schedule = None
    if data.installment_months is not None:
        each, remainder = divmod(amount, data.installment_months)
        schedule = [each + (index < remainder) for index in range(data.installment_months)]

    payment = Payment(
        tariff_id=tariff.id,
        email=str(data.email),
        method=data.method.value,
        installment_months=data.installment_months,
        amount=amount,
        discount=discount,
        schedule=schedule,
        idempotency_key=idempotency_key,
    )
    session.add(payment)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        if idempotency_key is None:
            raise
        existing = session.scalar(select(Payment).where(Payment.idempotency_key == idempotency_key))
        if existing is None:
            raise
        response.status_code = 200
        return existing
    session.refresh(payment)
    return payment


@app.get("/payments", response_model=list[PaymentOut])
def list_payments(
    email: EmailStr | None = Query(default=None),
    status: PaymentStatus | None = Query(default=None),
    session: Session = Depends(get_session),
):
    query = select(Payment).order_by(Payment.id)
    if email is not None:
        query = query.where(Payment.email == str(email))
    if status is not None:
        query = query.where(Payment.status == status.value)
    return session.scalars(query).all()


@app.get("/payments/{payment_id}", response_model=PaymentOut)
def get_payment(
    payment_id: int = Path(gt=0, le=MAX_ID), session: Session = Depends(get_session)
):
    payment = session.get(Payment, payment_id)
    if payment is None:
        raise HTTPException(status_code=404, detail="payment not found")
    return payment


ALLOWED_TRANSITIONS = {
    "pending": {"succeeded", "failed"},
    "succeeded": {"refunded"},
}


def transition_payment_status(payment: Payment, target: str, session: Session) -> bool:
    if target not in ALLOWED_TRANSITIONS.get(payment.status, set()):
        return False
    # Another request may have changed the status after our read.
    result = session.execute(
        update(Payment)
        .where(Payment.id == payment.id, Payment.status == payment.status)
        .values(status=target)
        .execution_options(synchronize_session=False)
    )
    if result.rowcount == 0:
        session.rollback()
        return False
    session.commit()
    return True


@app.post("/payments/{payment_id}/refund", response_model=PaymentOut)
def refund_payment(
    payment_id: int = Path(gt=0, le=MAX_ID), session: Session = Depends(get_session)
):
    payment = session.get(Payment, payment_id)
    if payment is None:
        raise HTTPException(status_code=404, detail="payment not found")
    if not transition_payment_status(payment, "refunded", session):
        return JSONResponse(status_code=409, content={"error": "invalid_transition"})
    session.refresh(payment)
    return payment


@app.post("/webhooks/bank", dependencies=[Depends(verify_bank_signature)])
def bank_webhook(data: BankWebhook, response: Response, session: Session = Depends(get_session)):
    payment = session.get(Payment, data.payment_id)
    if payment is None:
        raise HTTPException(status_code=404, detail="payment not found")
    if not transition_payment_status(payment, data.status.value, session):
        response.status_code = 409
        return {"error": "invalid_transition"}
    return {"result": "ok"}
