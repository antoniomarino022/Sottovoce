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
                coins_balance=5,  # Low balance (< 10 escalation cost) for testing
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
            for c in session.exec(select(Confession)).all():
                session.delete(c)
            for u in session.exec(select(User)).all():
                session.delete(u)
            session.commit()

    def test_coins_deduction_for_powers(self):
        """Test that invoking defense and prosecution deducts coins and records transactions."""
        client = TestClient(app, cookies={"sottovoce_session": "key_user_one"})

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

        # Test user with insufficient coins (User 3 has only 5 coins, joining costs 10)
        client_poor = TestClient(app, cookies={"sottovoce_session": "key_user_three"})
        with patch("src.agents.nodes.creative_llm") as mock_creative:
            mock_creative.ainvoke = AsyncMock(return_value=AIMessage(content="Test"))
            res_fail = client_poor.post(f"/confessions/{self.cid}/defense")
            self.assertEqual(res_fail.status_code, 400)
            self.assertIn("insufficiente", res_fail.json()["detail"].lower())

    def test_court_escalation_five_prosecutors(self):
        """Test 5 users accusing a confession: 1st pays 20 + AI, 2nd-4th pay 10 + 0 AI, 5th pays 10 + Aggravated AI + badge."""
        extra_keys = []
        with Session(sqlite_engine) as session:
            for idx in (4, 5, 6):
                key = f"key_user_{idx}"
                extra_keys.append(key)
                session.add(
                    User(
                        telegram_id=40000 + idx,
                        user_key=key,
                        referral_code=f"REF40{idx}",
                        terms_accepted_at=datetime.now(timezone.utc),
                        status=UserStatus.ACTIVE,
                        coins_balance=50,
                    )
                )
            session.commit()

        prosecutor_keys = ["key_user_one", "key_user_two", *extra_keys]

        with patch("src.agents.nodes.creative_llm") as mock_creative:
            mock_creative.ainvoke = AsyncMock(
                side_effect=[
                    AIMessage(content="Chiedo 100 ore di lavori socialmente inutili!"),
                    AIMessage(content="Cinque cittadini chiedono l'esilio perpetuo su Marte!"),
                ]
            )

            # 1° accusatore: paga 20 monete e sblocca la 1ª Requisitoria AI
            c1 = TestClient(app, cookies={"sottovoce_session": prosecutor_keys[0]})
            r1 = c1.post(f"/confessions/{self.cid}/prosecution")
            self.assertEqual(r1.status_code, 200)
            self.assertEqual(r1.json()["prosecution_count"], 1)
            self.assertTrue(r1.json()["user_prosecuted"])
            self.assertEqual(mock_creative.ainvoke.call_count, 1)

            # Doppio click dello stesso utente bloccato senza addebiti
            r_dup = c1.post(f"/confessions/{self.cid}/prosecution")
            self.assertEqual(r_dup.status_code, 400)

            # 2°, 3°, 4° accusatore: pagano 10 monete ciascuno, ZERO chiamate AI
            for expected_cnt, key in enumerate(prosecutor_keys[1:4], start=2):
                c = TestClient(app, cookies={"sottovoce_session": key})
                resp = c.post(f"/confessions/{self.cid}/prosecution")
                self.assertEqual(resp.status_code, 200)
                self.assertEqual(resp.json()["prosecution_count"], expected_cnt)
            self.assertEqual(mock_creative.ainvoke.call_count, 1)

            # Verifica saldo 2° utente (100 - 10 = 90)
            with Session(sqlite_engine) as session:
                u2 = session.get(User, self.u2_id)
                self.assertEqual(u2.coins_balance, 90)

            # 5° accusatore: paga 10 monete, scatta l'Escalation AI Aggravata + badge Condannato!
            c5 = TestClient(app, cookies={"sottovoce_session": prosecutor_keys[4]})
            r5 = c5.post(f"/confessions/{self.cid}/prosecution")
            self.assertEqual(r5.status_code, 200)
            body5 = r5.json()
            self.assertEqual(body5["prosecution_count"], 5)
            self.assertIn("Marte", body5["ai_prosecution"])
            self.assertEqual(body5["shame_stamp"], "certified_clown")
            self.assertEqual(mock_creative.ainvoke.call_count, 2)

            # Cosa vedono tutti gli altri utenti nel feed HTML
            viewer = TestClient(app, cookies={"sottovoce_session": "key_user_three"})
            feed_html = viewer.get("/").text
            self.assertIn("Condannato (5)", feed_html)
            self.assertIn("Requisitoria Aggravata", feed_html)
            self.assertIn("5 accusatori", feed_html)
            self.assertIn("Rincara Accusa (10 🪙)", feed_html)

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
