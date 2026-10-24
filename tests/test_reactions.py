from datetime import datetime, timezone
import unittest
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine, select
from sqlmodel.pool import StaticPool

from config.database import get_session
from main import app
from src.models import Confession, ModerationStatus, Reaction, User, UserStatus
from src.models.enums import ReactionType
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


class TestReactionCRUD(unittest.TestCase):
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
            # Create two test users
            self.user1 = User(
                telegram_id=1234567,
                user_key="user_key_alpha_1",
                referral_code="REF001",
                terms_accepted_at=datetime.now(timezone.utc),
                status=UserStatus.ACTIVE,
            )
            self.user2 = User(
                telegram_id=7654321,
                user_key="user_key_beta_2",
                referral_code="REF002",
                terms_accepted_at=datetime.now(timezone.utc),
                status=UserStatus.ACTIVE,
            )
            session.add(self.user1)
            session.add(self.user2)
            session.commit()
            session.refresh(self.user1)
            session.refresh(self.user2)

            # Create test confession
            self.confession = Confession(
                author_id=self.user1.id,
                content="Ho finto di sapere cos'è Kubernetes per sei mesi in riunione.",
                mod_status=ModerationStatus.APPROVED,
            )
            session.add(self.confession)
            session.commit()
            session.refresh(self.confession)
            self.confession_id = self.confession.id

    def tearDown(self):
        with Session(sqlite_engine) as session:
            for r in session.exec(select(Reaction)).all():
                session.delete(r)
            for c in session.exec(select(Confession)).all():
                session.delete(c)
            for u in session.exec(select(User)).all():
                session.delete(u)
            session.commit()

    def test_post_reaction_create(self):
        """Aggiunge una nuova reazione e verifica l'incremento del contatore."""
        client = TestClient(app, cookies={"sottovoce_session": "user_key_alpha_1"})
        response = client.post(
            f"/confessions/{self.confession_id}/reactions",
            json={"type": "skull"},
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["action"], "created")
        self.assertEqual(data["count_skull"], 1)
        self.assertEqual(data["total_reactions"], 1)
        self.assertEqual(data["reaction"]["type"], "skull")

        # Verifica stato database
        with Session(sqlite_engine) as session:
            db_conf = session.get(Confession, self.confession_id)
            self.assertIsNotNone(db_conf)
            self.assertEqual(db_conf.count_skull, 1)

    def test_post_reaction_switch(self):
        """Passa da una reazione all'altra (skull -> clown) e controlla i contatori."""
        client = TestClient(app, cookies={"sottovoce_session": "user_key_alpha_1"})
        # 1. Crea reazione 'skull'
        res1 = client.post(
            f"/confessions/{self.confession_id}/reactions",
            json={"type": "skull"},
        )
        self.assertEqual(res1.status_code, 200)
        self.assertEqual(res1.json()["action"], "created")

        # 2. Cambia reazione a 'clown'
        res2 = client.post(
            f"/confessions/{self.confession_id}/reactions",
            json={"type": "clown"},
        )
        self.assertEqual(res2.status_code, 200)
        data2 = res2.json()
        self.assertEqual(data2["action"], "updated")
        self.assertEqual(data2["count_skull"], 0)
        self.assertEqual(data2["count_clown"], 1)
        self.assertEqual(data2["total_reactions"], 1)
        self.assertEqual(data2["reaction"]["type"], "clown")

    def test_post_reaction_toggle_off(self):
        """Inviare la stessa reazione una seconda volta la rimuove (toggle)."""
        client = TestClient(app, cookies={"sottovoce_session": "user_key_alpha_1"})
        # 1. Imposta 'disagio'
        res1 = client.post(
            f"/confessions/{self.confession_id}/reactions",
            json={"type": "disagio"},
        )
        self.assertEqual(res1.status_code, 200)
        self.assertEqual(res1.json()["action"], "created")
        self.assertEqual(res1.json()["count_disagio"], 1)

        # 2. Clicca di nuovo 'disagio' -> toggle off
        res2 = client.post(
            f"/confessions/{self.confession_id}/reactions",
            json={"type": "disagio"},
        )
        self.assertEqual(res2.status_code, 200)
        data2 = res2.json()
        self.assertEqual(data2["action"], "removed")
        self.assertIsNone(data2["reaction"])
        self.assertEqual(data2["count_disagio"], 0)
        self.assertEqual(data2["total_reactions"], 0)

        # Verifica che non ci siano record in reactions
        with Session(sqlite_engine) as session:
            count = len(session.exec(select(Reaction)).all())
            self.assertEqual(count, 0)

    def test_get_reactions_summary_and_me(self):
        """Verifica GET riepilogo reazioni e GET /me."""
        client1 = TestClient(app, cookies={"sottovoce_session": "user_key_alpha_1"})
        client2 = TestClient(app, cookies={"sottovoce_session": "user_key_beta_2"})

        # Utente 1 reagisce popcorn
        client1.post(
            f"/confessions/{self.confession_id}/reactions",
            json={"type": "popcorn"},
        )
        # Utente 2 reagisce skull
        client2.post(
            f"/confessions/{self.confession_id}/reactions",
            json={"type": "skull"},
        )

        # Richiesta summary da utente 1
        summary_resp = client1.get(f"/confessions/{self.confession_id}/reactions")
        self.assertEqual(summary_resp.status_code, 200)
        summary = summary_resp.json()
        self.assertEqual(summary["count_popcorn"], 1)
        self.assertEqual(summary["count_skull"], 1)
        self.assertEqual(summary["total_reactions"], 2)
        self.assertEqual(summary["user_reaction"], "popcorn")

        # Richiesta /me da utente 1
        me_resp = client1.get(f"/confessions/{self.confession_id}/reactions/me")
        self.assertEqual(me_resp.status_code, 200)
        self.assertEqual(me_resp.json()["type"], "popcorn")

        # Richiesta summary anonima (senza cookie)
        anon_client = TestClient(app)
        anon_summary = anon_client.get(f"/confessions/{self.confession_id}/reactions")
        self.assertEqual(anon_summary.status_code, 200)
        self.assertIsNone(anon_summary.json()["user_reaction"])
        self.assertEqual(anon_summary.json()["total_reactions"], 2)

    def test_delete_reaction(self):
        """Elimina esplicitamente una reazione via DELETE."""
        client = TestClient(app, cookies={"sottovoce_session": "user_key_alpha_1"})
        client.post(
            f"/confessions/{self.confession_id}/reactions",
            json={"type": "skull"},
        )

        # DELETE reazione
        del_resp = client.delete(f"/confessions/{self.confession_id}/reactions")
        self.assertEqual(del_resp.status_code, 200)
        self.assertEqual(del_resp.json()["count_skull"], 0)
        self.assertEqual(del_resp.json()["total_reactions"], 0)

        # Secondo DELETE restituisce 404
        del_again = client.delete(f"/confessions/{self.confession_id}/reactions")
        self.assertEqual(del_again.status_code, 404)

    def test_reactions_nonexistent_confession_404(self):
        """Richieste su confessione inesistente restituiscono 404."""
        client = TestClient(app, cookies={"sottovoce_session": "user_key_alpha_1"})
        res = client.post("/confessions/99999/reactions", json={"type": "skull"})
        self.assertEqual(res.status_code, 404)

        res_get = client.get("/confessions/99999/reactions")
        self.assertEqual(res_get.status_code, 404)

        res_del = client.delete("/confessions/99999/reactions")
        self.assertEqual(res_del.status_code, 404)

    def test_unauthenticated_requests(self):
        """Richieste protette senza autenticazione restituiscono 401."""
        client = TestClient(app)
        res_post = client.post(
            f"/confessions/{self.confession_id}/reactions",
            json={"type": "skull"},
        )
        self.assertEqual(res_post.status_code, 401)

        res_me = client.get(f"/confessions/{self.confession_id}/reactions/me")
        self.assertEqual(res_me.status_code, 401)

        res_del = client.delete(f"/confessions/{self.confession_id}/reactions")
        self.assertEqual(res_del.status_code, 401)

    def test_post_reaction_htmx_form_urlencoded(self):
        """Simula il click HTMX (application/x-www-form-urlencoded da hx-vals) senza errore 422/[object Object]."""
        client = TestClient(app, cookies={"sottovoce_session": "user_key_alpha_1"})
        res = client.post(
            f"/confessions/{self.confession_id}/reactions",
            data={"type": "skull"},
            headers={
                "HX-Request": "true",
                "HX-Target": f"reaction-bar-{self.confession_id}",
            },
        )
        self.assertEqual(res.status_code, 200)
        self.assertIn(f'id="reaction-bar-{self.confession_id}"', res.text)
        self.assertIn("1 voti", res.text)

        # Verifica che payload non validi restituiscano una stringa leggibile in detail (non array di oggetti)
        bad_res = client.post(
            f"/confessions/{self.confession_id}/reactions",
            data={"type": "invalid_emoji"},
        )
        self.assertEqual(bad_res.status_code, 422)
        self.assertIsInstance(bad_res.json()["detail"], str)
