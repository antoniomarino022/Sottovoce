import asyncio
from datetime import datetime, timezone
import unittest
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage
from sqlmodel import Session, SQLModel, create_engine, select
from sqlmodel.pool import StaticPool

from config.database import get_session
from main import app
from src.models import (
    CoinTransaction,
    Confession,
    ModerationStatus,
    Report,
    User,
    UserStatus,
)
from src.models.enums import TriageCategory, TxType
from src.services.redis_service import check_rate_limit, get_cache, set_cache
import src.models  # noqa: F401

# In-memory SQLite engine for tests
sqlite_engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)


def get_test_session():
    with Session(sqlite_engine) as session:
        yield session


class TestFeaturesAndRedis(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        SQLModel.metadata.create_all(sqlite_engine)
        app.dependency_overrides[get_session] = get_test_session
        cls.client = TestClient(app, raise_server_exceptions=True)

    @classmethod
    def tearDownClass(cls):
        app.dependency_overrides.pop(get_session, None)
        SQLModel.metadata.drop_all(sqlite_engine)

    def setUp(self):
        with Session(sqlite_engine) as session:
            # Create test users with coins
            self.user1 = User(
                telegram_id=10101,
                user_key="key_user_one",
                referral_code="REF101",
                terms_accepted_at=datetime.now(timezone.utc),
                status=UserStatus.ACTIVE,
                coins_balance=100,
            )
            self.user2 = User(
                telegram_id=20202,
                user_key="key_user_two",
                referral_code="REF202",
                terms_accepted_at=datetime.now(timezone.utc),
                status=UserStatus.ACTIVE,
                coins_balance=100,
            )
            self.user3 = User(
                telegram_id=30303,
                user_key="key_user_three",
                referral_code="REF303",
                terms_accepted_at=datetime.now(timezone.utc),
                status=UserStatus.ACTIVE,
                coins_balance=10,  # Low balance for testing
            )
            session.add(self.user1)
            session.add(self.user2)
            session.add(self.user3)
            session.commit()
            session.refresh(self.user1)
            session.refresh(self.user2)
            session.refresh(self.user3)
            self.u1_id = self.user1.id
            self.u2_id = self.user2.id
            self.u3_id = self.user3.id

            # Create test confession
            self.confession = Confession(
                author_id=self.user1.id,
                content="Ho finto che la connessione saltasse durante una call noiosa.",
                mod_status=ModerationStatus.APPROVED,
                ai_roast="La Corte ti condanna a un corso obbligatorio di bon ton digitale.",
            )
            session.add(self.confession)
            session.commit()
            session.refresh(self.confession)
            self.cid = self.confession.id

    def tearDown(self):
        with Session(sqlite_engine) as session:
            for t in session.exec(select(CoinTransaction)).all():
                session.delete(t)
            for r in session.exec(select(Report)).all():
                session.delete(r)
            for c in session.exec(select(Confession)).all():
                session.delete(c)
            for u in session.exec(select(User)).all():
                session.delete(u)
            session.commit()

    def test_reporting_and_auto_moderation(self):
        """Test user reporting, duplicate prevention, and auto-moderation threshold."""
        client1 = TestClient(app, cookies={"hotmic_session": "key_user_one"})
        client2 = TestClient(app, cookies={"hotmic_session": "key_user_two"})
        client3 = TestClient(app, cookies={"hotmic_session": "key_user_three"})

        # 1. User 2 reports confession
        res1 = client2.post(
            f"/confessions/{self.cid}/reports",
            json={"reason": "abuse", "details": "Non fa ridere"},
        )
        self.assertEqual(res1.status_code, 201)
        self.assertEqual(res1.json()["confession_id"], self.cid)

        # 2. Duplicate report by User 2 is rejected
        res_dup = client2.post(
            f"/confessions/{self.cid}/reports",
            json={"reason": "abuse"},
        )
        self.assertEqual(res_dup.status_code, 400)

        # 3. User 1 reports confession (count = 2)
        res2 = client1.post(
            f"/confessions/{self.cid}/reports",
            json={"reason": "violence"},
        )
        self.assertEqual(res2.status_code, 201)

        with Session(sqlite_engine) as session:
            db_conf = session.get(Confession, self.cid)
            self.assertEqual(db_conf.reports_count, 2)
            self.assertEqual(db_conf.mod_status, ModerationStatus.APPROVED)

        # 4. User 3 reports confession (count = 3 -> reaches threshold!)
        res3 = client3.post(
            f"/confessions/{self.cid}/reports",
            json={"reason": "hate_speech"},
        )
        self.assertEqual(res3.status_code, 201)

        # Confession should now be auto-moderated to crisis_held
        with Session(sqlite_engine) as session:
            db_conf = session.get(Confession, self.cid)
            self.assertEqual(db_conf.reports_count, 3)
            self.assertEqual(db_conf.mod_status, ModerationStatus.CRISIS_HELD)

    def test_coins_deduction_for_powers(self):
        """Test that invoking defense and prosecution deducts coins and records transactions."""
        client = TestClient(app, cookies={"hotmic_session": "key_user_one"})

        with patch("src.agents.nodes.creative_llm") as mock_creative:
            mock_creative.ainvoke = AsyncMock(
                side_effect=[
                    AIMessage(content="Difesa: La disconnessione è un diritto umano!"),
                    AIMessage(content="Accusa: Chiude le call senza salutare!"),
                ]
            )

            # User 1 has 100 coins -> calls defense (-20 coins)
            res_def = client.post(f"/confessions/{self.cid}/defense")
            self.assertEqual(res_def.status_code, 200)

            with Session(sqlite_engine) as session:
                u1 = session.get(User, self.u1_id)
                self.assertEqual(u1.coins_balance, 80)
                txs = session.exec(select(CoinTransaction).where(CoinTransaction.user_id == self.u1_id)).all()
                self.assertEqual(len(txs), 1)
                self.assertEqual(txs[0].amount, -20)
                self.assertEqual(txs[0].balance_after, 80)
                self.assertEqual(txs[0].tx_type, TxType.BUY_AI_LAWYER)

            # User 1 calls prosecution (-20 coins)
            res_pros = client.post(f"/confessions/{self.cid}/prosecution")
            self.assertEqual(res_pros.status_code, 200)

            with Session(sqlite_engine) as session:
                u1 = session.get(User, self.u1_id)
                self.assertEqual(u1.coins_balance, 60)

        # Test user with insufficient coins (User 3 has only 10 coins)
        client_poor = TestClient(app, cookies={"hotmic_session": "key_user_three"})
        with patch("src.agents.nodes.creative_llm") as mock_creative:
            mock_creative.ainvoke = AsyncMock(return_value=AIMessage(content="Test"))
            res_fail = client_poor.post(f"/confessions/{self.cid}/defense")
            self.assertEqual(res_fail.status_code, 400)
            self.assertIn("insufficiente", res_fail.json()["detail"].lower())

    def test_redis_cache_and_rate_limit(self):
        """Test Redis/in-memory cache helper and sliding window rate limiting."""
        async def run_test():
            # Test Cache
            await set_cache("test:key", {"message": "hello"}, ttl_seconds=5)
            cached = await get_cache("test:key")
            self.assertIsNotNone(cached)
            self.assertEqual(cached["message"], "hello")

            # Test Rate Limiting
            key = "unit_test_action"
            # 3 requests allowed in 10-second window
            self.assertTrue(await check_rate_limit(key, max_requests=3, window_seconds=10))
            self.assertTrue(await check_rate_limit(key, max_requests=3, window_seconds=10))
            self.assertTrue(await check_rate_limit(key, max_requests=3, window_seconds=10))
            # 4th request exceeds limit
            self.assertFalse(await check_rate_limit(key, max_requests=3, window_seconds=10))

        asyncio.run(run_test())

    def test_telegram_webhook_route(self):
        """Verify the Telegram webhook route accepts update payloads."""
        mock_update = {
            "update_id": 999999,
            "message": {
                "message_id": 1,
                "date": 1700000000,
                "chat": {"id": 12345, "type": "private"},
                "from": {"id": 12345, "is_bot": False, "first_name": "Test"},
                "text": "/start",
            },
        }
        with patch("src.routers.telegram.dp.feed_update", new_callable=AsyncMock) as mock_feed:
            mock_feed.return_value = None
            res = self.client.post("/telegram/webhook", json=mock_update)
            self.assertEqual(res.status_code, 200)
            self.assertTrue(res.json().get("ok"))
