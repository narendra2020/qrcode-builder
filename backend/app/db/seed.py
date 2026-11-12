"""
Idempotent seeding of plan rows. Limits come from settings on first
insert only — afterwards admins own them (PUT /api/qr/admin/plans/{code}).

Usage:
    python -m app.db.seed
"""
from app.core.config import settings
from app.db.session import SessionLocal
from app.models.models import Plan


def seed_plans(db) -> None:
    free_n = settings.QR_FREE_MONTHLY_UPDATES
    pro_n = settings.QR_PRO_MONTHLY_UPDATES
    pro_updates = "Unlimited catalogue updates" if pro_n is None else f"{pro_n} catalogue updates per month"
    limit = settings.SPLIT_BILL_FREE_MONTHLY
    plans = [
        Plan(code=settings.FREE_PLAN_CODE, name="Free", display_order=0,
             description="Everything you need to run your digital store.",
             monthly_catalogue_updates=free_n, price_rupees=0,
             features=["AI menu & catalogue import", "Branded QR code", "WhatsApp enquiries & cart",
                       f"{free_n} catalogue updates per month", f"{limit} Split Bills per month"]),
        Plan(code=settings.SPLIT_PLAN_CODE, name="Split Bill", display_order=1,
             description="For restaurants and cafés that want customers to split the bill.",
             monthly_catalogue_updates=free_n,
             price_rupees=settings.QR_SPLIT_BILL_PRICE_RUPEES or None,
             features=["Everything in Free", "Unlimited Split Bills", f"{free_n} catalogue updates per month"]),
        Plan(code=settings.PAID_PLAN_CODE, name="Pro", display_order=2,
             description="For stores that change their menu or stock often.",
             monthly_catalogue_updates=pro_n,
             price_rupees=settings.QR_STORE_PRO_PRICE_RUPEES or None,
             features=["Everything in Free", pro_updates, f"{limit} Split Bills per month", "Priority support"]),
        Plan(code=settings.PRO_SPLIT_PLAN_CODE, name="Pro + Split Bill", display_order=3,
             description="Everything in Pro, plus unlimited Split Bills.",
             monthly_catalogue_updates=pro_n,
             price_rupees=settings.QR_PRO_SPLIT_PRICE_RUPEES or None,
             features=["Everything in Pro", pro_updates, "Unlimited Split Bills", "Priority support"]),
    ]
    for plan in plans:
        if not db.get(Plan, plan.code):
            db.add(plan)
            print(f"[qr-seed] created plan: {plan.code}")
    db.commit()


if __name__ == "__main__":
    session = SessionLocal()
    try:
        seed_plans(session)
    finally:
        session.close()
