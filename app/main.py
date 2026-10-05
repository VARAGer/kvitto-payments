import os
from contextlib import asynccontextmanager
from collections.abc import Iterator

from fastapi import Depends, FastAPI, Header, HTTPException, Response
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import setup_database
from app.models import Payment, Tariff
from app.schemas import BankWebhook, PaymentCreate, PaymentOut, TariffOut


def get_session() -> Iterator[Session]:
    # The session factory is initialized in the application lifespan.
    with app.state.session_factory() as session:
        yield session


@asynccontextmanager
async def lifespan(application: FastAPI):
    database_url = os.getenv("DATABASE_URL", "sqlite:///./payments.db")
    engine, application.state.session_factory = setup_database(database_url)
    yield
    engine.dispose()


app = FastAPI(title="Квитто Payments API", lifespan=lifespan)


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


@app.get("/payments/{payment_id}", response_model=PaymentOut)
def get_payment(payment_id: int, session: Session = Depends(get_session)):
    payment = session.get(Payment, payment_id)
    if payment is None:
        raise HTTPException(status_code=404, detail="payment not found")
    return payment


ALLOWED_TRANSITIONS = {
    "pending": {"succeeded", "failed"},
    "succeeded": {"refunded"},
}


@app.post("/webhooks/bank")
def bank_webhook(data: BankWebhook, response: Response, session: Session = Depends(get_session)):
    payment = session.get(Payment, data.payment_id)
    if payment is None:
        raise HTTPException(status_code=404, detail="payment not found")
    if data.status.value not in ALLOWED_TRANSITIONS.get(payment.status, set()):
        response.status_code = 409
        return {"error": "invalid_transition"}
    payment.status = data.status.value
    session.commit()
    return {"result": "ok"}
