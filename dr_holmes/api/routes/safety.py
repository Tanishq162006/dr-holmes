"""Budget + safety status endpoints for the frontend pill."""
from fastapi import APIRouter

from dr_holmes.safety import budget


router = APIRouter(prefix="/api/safety", tags=["safety"])


@router.get("/budget")
async def get_budget():
    """Snapshot of session + per-case spend. Frontend polls this."""
    return budget.snapshot()
