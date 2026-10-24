from datetime import datetime, timezone
import unittest

from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine, select
from sqlmodel.pool import StaticPool

from config.database import get_session
from main import app
from src.models import CoinTransaction, User, UserStatus
from src.models.enums import TxType
from src.routers.deps import get_current_user, get_optional_current_user
import src.models  # noqa: F401

sqlite_engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)


def get_test_session():
    with Session(sqlite_engine) as session:
        yield session


class TestAdsgramRewards(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        SQLModel.metadata.create_all(sqlite_engine)
        app.dependency_overrides[get_session] = get_test_session
        cls.client = TestClient(app, raise_server_exceptions=True)

    @classmethod
    def tearDownClass(cls):
        app.dependency_overrides.pop(get_session, None)
        app.dependency_overrides.pop(get_current_user, None)
        app.dependency_overrides.pop(get_optional_current_user, None)
        SQLModel.metadata.drop_all(sqlite_engine)

    def setUp(self):
        with Session(sqlite_engine) as session:
            for tx in session.exec(select(CoinTransaction)).all():
                session.delete(tx)
            for u in session.exec(select(User)).all():
                session.delete(u)
            session.commit()

            self.user = User(
                user_key="ad_key" * 16,
                status=UserStatus.ACTIVE,
                coins_balance=50,
                referral_code="ADREF1",
                terms_accepted_at=datetime.now(timezone.utc),
            )
            session.add(self.user)
            session.commit()
            session.refresh(self.user)
            self.user_id = self.user.id

    def test_claim_ad_reward_success(self):
        """Test authenticated user claims +20 coins for viewing an ad."""
        app.dependency_overrides[get_current_user] = lambda: self.user

        res = self.client.post("/ads/reward")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["status"], "success")
        self.assertEqual(data["reward"], 20)
        self.assertEqual(data["coins_balance"], 70)
        self.assertEqual(data["ads_watched_count"], 1)

        # Verify DB updates
        with Session(sqlite_engine) as session:
            db_user = session.get(User, self.user_id)
            self.assertEqual(db_user.coins_balance, 70)
            self.assertEqual(db_user.ads_watched_count, 1)
            self.assertIsNotNone(db_user.last_ad_watched_at)

            # Check transaction record
            tx = session.exec(
                select(CoinTransaction).where(CoinTransaction.user_id == self.user_id)
            ).first()
            self.assertIsNotNone(tx)
            self.assertEqual(tx.amount, 20)
            self.assertEqual(tx.balance_after, 70)
            self.assertEqual(tx.tx_type, TxType.AD_REWARD)

    def test_ad_reward_cooldown_anti_spam(self):
        """Test rapid consecutive claims are blocked by cooldown (429)."""
        app.dependency_overrides[get_current_user] = lambda: self.user

        # First claim succeeds
        res1 = self.client.post("/ads/reward")
        self.assertEqual(res1.status_code, 200)

        # Immediate second claim triggers 429
        # Update user object with current state from DB
        with Session(sqlite_engine) as session:
            updated_user = session.get(User, self.user_id)
        app.dependency_overrides[get_current_user] = lambda: updated_user

        res2 = self.client.post("/ads/reward")
        self.assertEqual(res2.status_code, 429)
        self.assertIn("Attendi ancora", res2.json()["detail"])

    def test_ad_status_endpoint(self):
        """Test GET /ads/status returns correct eligibility info."""
        app.dependency_overrides[get_current_user] = lambda: self.user

        res = self.client.get("/ads/status")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data["can_watch"])
        self.assertEqual(data["cooldown_remaining"], 0)
        self.assertEqual(data["coins_balance"], 50)
        self.assertEqual(data["ads_watched_count"], 0)


if __name__ == "__main__":
    unittest.main()
