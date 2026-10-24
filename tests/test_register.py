import hashlib
import hmac
import json
import time
import unittest
from unittest.mock import AsyncMock, patch
from urllib.parse import urlencode

from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage
from pydantic import SecretStr
from sqlmodel import Session, SQLModel, create_engine, select
from sqlmodel.pool import StaticPool

from config.database import get_session
from config.settings import settings
from main import app
from src.agents.state import TriageResult
from src.models import Confession, ModerationStatus, User
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


def build_webapp_init_data(telegram_id: int, bot_token: str) -> str:
    """Build a cryptographically valid Telegram Mini App initData query string."""
    user_payload = json.dumps(
        {"id": telegram_id, "first_name": "Mario", "username": "mariorossi"},
        separators=(",", ":"),
    )
    fields = {
        "auth_date": str(int(time.time())),
        "user": user_payload,
    }
    data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(fields.items()))
    secret_key = hmac.new(
        b"WebAppData",
        bot_token.encode("utf-8"),
        hashlib.sha256,
    ).digest()
    signature = hmac.new(
        secret_key,
        data_check_string.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return urlencode({**fields, "hash": signature})


class TestRegisterAndAuth(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not settings.TELEGRAM_BOT_TOKEN.get_secret_value():
            settings.TELEGRAM_BOT_TOKEN = SecretStr("123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11")
        cls.bot_token = settings.TELEGRAM_BOT_TOKEN.get_secret_value()
        SQLModel.metadata.create_all(sqlite_engine)
        app.dependency_overrides[get_session] = get_test_session
        cls.client = TestClient(app, raise_server_exceptions=True)

    @classmethod
    def tearDownClass(cls):
        app.dependency_overrides.pop(get_session, None)
        SQLModel.metadata.drop_all(sqlite_engine)

    def test_1_register_page_html(self):
        """Verifica che /register sia esclusivamente una Mini App Telegram (senza widget web o logout)."""
        response = self.client.get("/register")
        self.assertEqual(response.status_code, 200)
        html = response.text
        self.assertIn("telegram-web-app.js", html)
        self.assertNotIn("telegram-widget.js", html)
        self.assertNotIn("handleLogout", html)
        self.assertIn("Sottovoce", html)
        self.assertIn("Confessioni anonime", html)

    def test_2_tma_auth_flow(self):
        """Verifica l'autenticazione nativa Telegram Mini App tramite initData firmato."""
        init_data = build_webapp_init_data(987654321, self.bot_token)

        res = self.client.post(
            "/auth/register",
            json={
                "data": {"init_data": init_data},
                "checkbox": {"accepted": True},
            },
        )
        self.assertEqual(res.status_code, 201)
        user_data = res.json()
        self.assertEqual(user_data["coins_balance"], 50)
        self.assertIsInstance(user_data["id"], int)
        self.assertIn("user_key", user_data)
        self.assertNotIn("telegram_id", user_data)
        self.assertIn("sottovoce_session", res.cookies)

        # Utente già autenticato su /register viene reindirizzato direttamente al feed (/)
        session_cookie = res.cookies["sottovoce_session"]
        res_page = self.client.get(
            "/register",
            cookies={"sottovoce_session": session_cookie},
            follow_redirects=False,
        )
        self.assertEqual(res_page.status_code, 302)
        self.assertEqual(res_page.headers["location"], "/")

    def test_3_confession_crud_with_autoincrement_id(self):
        """Verifica creazione ed eliminazione confessione autenticandosi con header X-Telegram-Init-Data."""
        init_data = build_webapp_init_data(1122334455, self.bot_token)
        headers = {"X-Telegram-Init-Data": init_data}

        triage_mock = TriageResult(
            severity=1,
            roast_allowed=True,
            reason="Approved",
            ai_roast="La Corte approva con riserva sarcastica.",
        )
        with patch("src.agents.nodes.triage_llm") as mock_triage_llm:
            mock_runnable = AsyncMock()
            mock_runnable.ainvoke.return_value = triage_mock
            mock_triage_llm.with_structured_output.return_value = mock_runnable

            res_post = self.client.post(
                "/confessions/",
                json={"content": "Questa è una confessione anonima di prova!"},
                headers=headers,
            )

        self.assertEqual(res_post.status_code, 201)
        data = res_post.json()
        self.assertIsInstance(data["id"], int)
        self.assertIsInstance(data["author_id"], int)
        self.assertGreater(data["id"], 0)
        self.assertNotIn("category", data)

        confession_id = data["id"]
        res_del = self.client.delete(f"/confessions/{confession_id}", headers=headers)
        self.assertEqual(res_del.status_code, 200)
        self.assertEqual(res_del.json()["status"], "ok")

        res_del_again = self.client.delete(f"/confessions/{confession_id}", headers=headers)
        self.assertEqual(res_del_again.status_code, 404)

    def test_4_web_auth_endpoints_removed(self):
        """Verifica che gli endpoint dell'app web (/auth/widget e /auth/logout) siano stati rimossi."""
        res_widget = self.client.post("/auth/widget", json={})
        self.assertEqual(res_widget.status_code, 404)

        res_logout = self.client.post("/auth/logout")
        self.assertEqual(res_logout.status_code, 404)

    def test_5_confession_defense_and_prosecution_endpoints(self):
        """Verifica le chiamate separate ai due agenti Difesa e Accusa."""
        with Session(sqlite_engine) as session:
            user = session.exec(select(User)).first()
            self.assertIsNotNone(user)
            confession = Confession(
                author_id=user.id,
                content="Ho finto di aver letto i termini e condizioni.",
                mod_status=ModerationStatus.APPROVED,
                ai_roast="La Corte ti condanna alla rilettura integrale.",
            )
            session.add(confession)
            session.commit()
            session.refresh(confession)
            cid = confession.id
            cookie = user.user_key

        with patch("src.agents.nodes.creative_llm") as mock_llm:
            mock_llm.ainvoke = AsyncMock(
                side_effect=[
                    AIMessage(content="Difesa: Nessuno legge mai i termini!"),
                    AIMessage(content="Accusa: Chi non legge i termini è un pericolo pubblico!"),
                ]
            )

            res_def = self.client.post(
                f"/confessions/{cid}/defense",
                cookies={"sottovoce_session": cookie},
            )
            self.assertEqual(res_def.status_code, 200)
            self.assertIn("Nessuno legge mai i termini", res_def.json()["ai_defense"])

            res_pros = self.client.post(
                f"/confessions/{cid}/prosecution",
                cookies={"sottovoce_session": cookie},
            )
            self.assertEqual(res_pros.status_code, 200)
            self.assertIn("pericolo pubblico", res_pros.json()["ai_prosecution"])

    def test_6_feed_and_confession_pages(self):
        """Verifica il feed HTML, la pagina /confession senza tasto Esci e l'endpoint GET /confessions/."""
        with Session(sqlite_engine) as session:
            user = session.exec(select(User)).first()
            self.assertIsNotNone(user)
            cookie = user.user_key

        res_page = self.client.get("/", cookies={"sottovoce_session": cookie})
        self.assertEqual(res_page.status_code, 200)
        self.assertIn("Sottovoce", res_page.text)
        self.assertIn("feed-list", res_page.text)
        self.assertIn("Popolari", res_page.text)
        self.assertIn("Recenti", res_page.text)

        res_conf = self.client.get("/confession", cookies={"sottovoce_session": cookie})
        self.assertEqual(res_conf.status_code, 200)
        self.assertNotIn("handleLogout", res_conf.text)

        res_api = self.client.get("/confessions/", cookies={"sottovoce_session": cookie})
        self.assertEqual(res_api.status_code, 200)
        data = res_api.json()
        self.assertIsInstance(data, list)
        self.assertGreater(len(data), 0)
        self.assertIn("content", data[0])
        self.assertIn("ai_roast", data[0])
        self.assertIn("total_reactions", data[0])


if __name__ == "__main__":
    unittest.main()
