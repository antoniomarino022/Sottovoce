import logging
from typing import Optional, Tuple

from fastapi import HTTPException, status
from sqlmodel import Session, select

from src.models import Confession, Report
from src.models.enums import ModerationStatus, TriageCategory
from src.services.redis_service import invalidate_feed_cache

logger = logging.getLogger("hotmic.report_service")

# Threshold of reports required to automatically hide content pending review
REPORT_AUTO_MOD_THRESHOLD = 3


async def create_report_service(
    session: Session,
    confession_id: int,
    reporter_id: int,
    reason: TriageCategory,
    details: Optional[str] = None,
) -> Tuple[Report, bool]:
    """
    Register a user report on a confession.
    Increments report count and automatically sets mod_status to crisis_held if threshold is reached.
    """
    try:
        confession = session.get(Confession, confession_id)
        if not confession or confession.deleted_at is not None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Confession not found",
            )

        # Check for duplicate reports by the same user
        existing_report = session.exec(
            select(Report).where(
                Report.confession_id == confession_id,
                Report.reporter_id == reporter_id,
            )
        ).first()

        if existing_report:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Hai già inviato una segnalazione per questa confessione",
            )

        # Create report record
        report = Report(
            confession_id=confession_id,
            reporter_id=reporter_id,
            reason=reason,
            resolved=False,
        )

        confession.reports_count += 1

        was_hidden = False
        if confession.reports_count >= REPORT_AUTO_MOD_THRESHOLD:
            confession.mod_status = ModerationStatus.CRISIS_HELD
            was_hidden = True
            logger.warning(
                "Confession %s reached %s reports; auto-moderated to crisis_held.",
                confession_id,
                confession.reports_count,
            )

        session.add(report)
        session.add(confession)
        session.commit()
        session.refresh(report)
        session.refresh(confession)

        await invalidate_feed_cache()
        return report, was_hidden

    except HTTPException:
        raise
    except Exception as exc:
        session.rollback()
        logger.error("Failed to submit report for confession %s: %s", confession_id, exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to submit report: {str(exc)}",
        )
