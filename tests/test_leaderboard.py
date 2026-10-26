from datetime import datetime, timezone
import unittest

from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine, select
from sqlmodel.pool import StaticPool

from config.database import get_session
from config.settings import settings
from main import app
from src.models import (
    CoinTransaction,
    Confession,
    ModerationStatus,
    User,
    UserStatus,
)
from src.models.enums import PostStyle, ShameBadge, TxType
from src.routers.deps import get_current_user, get_optional_current_user
import src.models  # noqa: F401

# In-memory SQLite engine for leaderboard tests
sqlite_engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)


def get_test_session():
    with Session(sqlite_engine) as session:
        yield session


class TestWeeklyLeaderboard(unittest.TestCase):
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
            session.exec(select(CoinTransaction)).all()
            for tx in session.exec(select(CoinTransaction)).all():
                session.delete(tx)
            for c in session.exec(select(Confession)).all():
                session.delete(c)
            for u in session.exec(select(User)).all():
                session.delete(u)
            session.commit()

            # Create test users
            now = datetime.now(timezone.utc)
            self.user1 = User(
                user_key="k1" * 32,
                status=UserStatus.ACTIVE,
                coins_balance=50,
                referral_code="REF1",
                terms_accepted_at=now,
            )
            self.user2 = User(
                user_key="k2" * 32,
                status=UserStatus.ACTIVE,
                coins_balance=50,
                referral_code="REF2",
                terms_accepted_at=now,
            )
            self.user3 = User(
                user_key="k3" * 32,
                status=UserStatus.ACTIVE,
                coins_balance=50,
                referral_code="REF3",
                terms_accepted_at=now,
            )
            session.add_all([self.user1, self.user2, self.user3])
            session.commit()
            session.refresh(self.user1)
            session.refresh(self.user2)
            session.refresh(self.user3)

            self.u1_id = self.user1.id
            self.u2_id = self.user2.id
            self.u3_id = self.user3.id

            # Create test confessions with varied reactions and shares
            self.c1 = Confession(
                author_id=self.u1_id,
                content="Segreto 1 più votato",
                mod_status=ModerationStatus.APPROVED,
                severity=1,
                visual_style=PostStyle.STANDARD,
                shame_stamp=ShameBadge.NONE,
                count_skull=10,
                count_disagio=10,
                count_popcorn=5,
                count_clown=5,  # Total reactions = 30
                shares_count=2,
            )
            self.c2 = Confession(
                author_id=self.u2_id,
                content="Segreto 2 secondo per voti",
                mod_status=ModerationStatus.APPROVED,
                severity=1,
                visual_style=PostStyle.STANDARD,
                shame_stamp=ShameBadge.NONE,
                count_skull=5,
                count_disagio=5,
                count_popcorn=5,
                count_clown=5,  # Total reactions = 20
                shares_count=15,  # Most shared!
            )
            self.c3 = Confession(
                author_id=self.u3_id,
                content="Segreto 3 terzo per voti",
                mod_status=ModerationStatus.APPROVED,
                severity=1,
                visual_style=PostStyle.STANDARD,
                shame_stamp=ShameBadge.NONE,
                count_skull=2,
                count_disagio=3,
                count_popcorn=2,
                count_clown=3,  # Total reactions = 10
                shares_count=8,  # Second most shared!
            )
            session.add_all([self.c1, self.c2, self.c3])
            session.commit()
            session.refresh(self.c1)
            session.refresh(self.c2)
            session.refresh(self.c3)

            self.c1_id = self.c1.id
            self.c2_id = self.c2.id
            self.c3_id = self.c3.id

    def test_share_confession_endpoint(self):
        """Test POST /confessions/{id}/share increments share counter."""
        res = self.client.post(f"/confessions/{self.c1_id}/share")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["status"], "success")
        self.assertEqual(data["shares_count"], 3)  # 2 + 1 = 3

        # Non-existent confession gives 404
        res404 = self.client.post("/confessions/999999/share")
        self.assertEqual(res404.status_code, 404)

    def test_api_leaderboard_rankings(self):
        """Test GET /api/leaderboard returns ordered top secrets."""
        res = self.client.get("/api/leaderboard")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn("secrets", data)

        # Check top secrets ordering by reactions: c1 (30), c2 (20), c3 (10)
        secrets = data["secrets"]
        self.assertGreaterEqual(len(secrets), 3)
        self.assertEqual(secrets[0]["id"], self.c1_id)
        self.assertEqual(secrets[0]["rank"], 1)
        self.assertEqual(secrets[0]["reward_coins"], 200)

        self.assertEqual(secrets[1]["id"], self.c2_id)
        self.assertEqual(secrets[1]["rank"], 2)
        self.assertEqual(secrets[1]["reward_coins"], 150)

        self.assertEqual(secrets[2]["id"], self.c3_id)
        self.assertEqual(secrets[2]["rank"], 3)
        self.assertEqual(secrets[2]["reward_coins"], 100)

    def test_leaderboard_html_page_and_htmx(self):
        """Test GET /leaderboard page rendering and HTMX list swapping."""
        # Authenticate user with a fresh user reference having id
        mock_user = User(
            id=self.u1_id,
            user_key="k1" * 32,
            status=UserStatus.ACTIVE,
            coins_balance=50,
            referral_code="REF1",
            terms_accepted_at=datetime.now(timezone.utc),
        )
        app.dependency_overrides[get_optional_current_user] = lambda: mock_user
        app.dependency_overrides[get_current_user] = lambda: mock_user

        # Full page
        res = self.client.get("/leaderboard")
        self.assertEqual(res.status_code, 200)
        self.assertIn("Classifiche", res.text)

        # HTMX partial list request
        res_htmx = self.client.get(
            "/leaderboard",
            headers={"HX-Request": "true", "HX-Target": "leaderboard-list"},
        )
        self.assertEqual(res_htmx.status_code, 200)
        self.assertIn("voti totali", res_htmx.text)

    def test_award_weekly_podium_rewards(self):
        """Test POST /api/leaderboard/award distributes coins and assigns weekly podium ranks."""
        headers = {}
        cron_sec = settings.CRON_SECRET.get_secret_value().strip()
        if cron_sec:
            headers["Authorization"] = f"Bearer {cron_sec}"

        res = self.client.post("/api/leaderboard/award", headers=headers)
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["status"], "success")

        with Session(sqlite_engine) as session:
            # Check user1:
            # - Won 1st place in reactions: +200 coins
            # - Initial balance: 50
            # - Total balance: 50 + 200 = 250
            u1 = session.get(User, self.u1_id)
            self.assertEqual(u1.coins_balance, 250)

            # Check user2:
            # - Won 2nd place in reactions: +150 coins
            # - Initial balance: 50
            # - Total balance: 50 + 150 = 200
            u2 = session.get(User, self.u2_id)
            self.assertEqual(u2.coins_balance, 200)

            # Check user3:
            # - Won 3rd place in reactions: +100 coins
            # - Initial balance: 50
            # - Total balance: 50 + 100 = 150
            u3 = session.get(User, self.u3_id)
            self.assertEqual(u3.coins_balance, 150)

            # Check transactions logged
            txs = session.exec(select(CoinTransaction).where(CoinTransaction.tx_type == TxType.WEEKLY_PODIUM)).all()
            self.assertEqual(len(txs), 3)  # 3 for reactions podium

            # Check confession weekly_rank set
            c1_db = session.get(Confession, self.c1_id)
            self.assertEqual(c1_db.weekly_rank, 1)

            c2_db = session.get(Confession, self.c2_id)
            self.assertEqual(c2_db.weekly_rank, 2)

            c3_db = session.get(Confession, self.c3_id)
            self.assertEqual(c3_db.weekly_rank, 3)


if __name__ == "__main__":
    unittest.main()
