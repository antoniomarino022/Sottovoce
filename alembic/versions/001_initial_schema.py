"""001_initial_schema

Revision ID: 001_initial_schema
Revises: 
Create Date: 2026-10-24 16:15:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '001_initial_schema'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Cleanly drop any old empty tables with UUIDs
    op.execute("DROP TABLE IF EXISTS coin_transactions, reactions, reports, confessions, users, poll_votes CASCADE;")

    # 2. Ensure PostgreSQL ENUM types exist
    op.execute("""
    DO $$ BEGIN
        CREATE TYPE user_status AS ENUM ('active', 'shadowbanned', 'suspended', 'banned');
    EXCEPTION WHEN duplicate_object THEN null; END $$;

    DO $$ BEGIN
        CREATE TYPE moderation_status AS ENUM ('pending_ai', 'approved', 'crisis_held', 'under_review', 'rejected');
    EXCEPTION WHEN duplicate_object THEN null; END $$;

    DO $$ BEGIN
        CREATE TYPE triage_category AS ENUM ('ok', 'self_harm', 'violence', 'abuse', 'doxxing', 'hate_speech', 'illegal', 'spam');
    EXCEPTION WHEN duplicate_object THEN null; END $$;

    DO $$ BEGIN
        CREATE TYPE reaction_type AS ENUM ('skull', 'disagio', 'popcorn', 'clown');
    EXCEPTION WHEN duplicate_object THEN null; END $$;

    DO $$ BEGIN
        CREATE TYPE post_style AS ENUM ('standard', 'neon_cyber', 'gold_glitch');
    EXCEPTION WHEN duplicate_object THEN null; END $$;

    DO $$ BEGIN
        CREATE TYPE shame_badge AS ENUM ('none', 'certified_clown', 'walking_red_flag', 'touch_grass');
    EXCEPTION WHEN duplicate_object THEN null; END $$;

    DO $$ BEGIN
        CREATE TYPE tx_type AS ENUM ('stars_purchase', 'referral_bonus', 'weekly_podium', 'buy_highlight', 'buy_pin_boost', 'buy_ai_lawyer', 'buy_ai_prosecutor', 'buy_shame_stamp', 'ad_reward');
    EXCEPTION WHEN duplicate_object THEN null; END $$;
    """)

    # 3. Create 'users' table
    op.execute("""
    CREATE TABLE users (
        id SERIAL PRIMARY KEY,
        user_key CHAR(64) UNIQUE NOT NULL,
        status user_status NOT NULL DEFAULT 'active',
        ban_reason TEXT,
        banned_until TIMESTAMPTZ,
        coins_balance INTEGER NOT NULL DEFAULT 50 CHECK (coins_balance >= 0),
        referral_code VARCHAR(16) UNIQUE NOT NULL,
        referred_by_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
        referral_qualified_at TIMESTAMPTZ,
        trust_score INTEGER NOT NULL DEFAULT 100,
        last_post_at TIMESTAMPTZ,
        last_ad_watched_at TIMESTAMPTZ,
        ads_watched_count INTEGER NOT NULL DEFAULT 0,
        terms_accepted_at TIMESTAMPTZ NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now()
    );
    CREATE INDEX idx_users_referred_by ON users (referred_by_id) WHERE referred_by_id IS NOT NULL;
    """)

    # 4. Create 'confessions' table
    op.execute("""
    CREATE TABLE confessions (
        id SERIAL PRIMARY KEY,
        author_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        content TEXT NOT NULL,
        ai_roast TEXT,
        mod_status moderation_status NOT NULL DEFAULT 'pending_ai',
        severity SMALLINT NOT NULL DEFAULT 0,
        ai_defense TEXT,
        ai_prosecution TEXT,
        visual_style post_style NOT NULL DEFAULT 'standard',
        shame_stamp shame_badge NOT NULL DEFAULT 'none',
        pinned_until TIMESTAMPTZ,
        weekly_rank SMALLINT CHECK (weekly_rank IN (1, 2, 3)),
        count_skull INTEGER NOT NULL DEFAULT 0 CHECK (count_skull >= 0),
        count_disagio INTEGER NOT NULL DEFAULT 0 CHECK (count_disagio >= 0),
        count_popcorn INTEGER NOT NULL DEFAULT 0 CHECK (count_popcorn >= 0),
        count_clown INTEGER NOT NULL DEFAULT 0 CHECK (count_clown >= 0),
        total_reactions INTEGER GENERATED ALWAYS AS (count_skull + count_disagio + count_popcorn + count_clown) STORED,
        reports_count INTEGER NOT NULL DEFAULT 0 CHECK (reports_count >= 0),
        shares_count INTEGER NOT NULL DEFAULT 0 CHECK (shares_count >= 0),
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        deleted_at TIMESTAMPTZ
    );
    CREATE INDEX idx_public_feed ON confessions (pinned_until DESC NULLS LAST, created_at DESC) WHERE mod_status = 'approved' AND deleted_at IS NULL;
    CREATE INDEX idx_leaderboard ON confessions (created_at DESC, total_reactions DESC) WHERE mod_status = 'approved' AND deleted_at IS NULL;
    CREATE INDEX idx_shares_leaderboard ON confessions (created_at DESC, shares_count DESC) WHERE mod_status = 'approved' AND deleted_at IS NULL;
    CREATE INDEX idx_confessions_author ON confessions (author_id, created_at DESC);
    """)

    # 5. Create 'reactions' table
    op.execute("""
    CREATE TABLE reactions (
        id SERIAL PRIMARY KEY,
        confession_id INTEGER NOT NULL REFERENCES confessions(id) ON DELETE CASCADE,
        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        type reaction_type NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        CONSTRAINT uq_reactions_confession_user UNIQUE (confession_id, user_id)
    );
    CREATE INDEX idx_reactions_confession ON reactions (confession_id);
    """)

    # 6. Create 'reports' table
    op.execute("""
    CREATE TABLE reports (
        id SERIAL PRIMARY KEY,
        confession_id INTEGER NOT NULL REFERENCES confessions(id) ON DELETE CASCADE,
        reporter_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        reason triage_category NOT NULL,
        resolved BOOLEAN NOT NULL DEFAULT false,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        CONSTRAINT uq_reports_confession_reporter UNIQUE (confession_id, reporter_id)
    );
    CREATE INDEX idx_reports_unresolved ON reports (confession_id) WHERE resolved = false;
    """)

    # 7. Create 'coin_transactions' table
    op.execute("""
    CREATE TABLE coin_transactions (
        id SERIAL PRIMARY KEY,
        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
        amount INTEGER NOT NULL CHECK (amount <> 0),
        balance_after INTEGER NOT NULL CHECK (balance_after >= 0),
        tx_type tx_type NOT NULL,
        stars_paid INTEGER CHECK (stars_paid > 0),
        telegram_charge_id VARCHAR(255) UNIQUE,
        target_confession_id INTEGER REFERENCES confessions(id) ON DELETE SET NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now()
    );
    CREATE INDEX idx_wallet_history ON coin_transactions (user_id, created_at DESC);
    CREATE INDEX idx_tx_target_confession ON coin_transactions (target_confession_id) WHERE target_confession_id IS NOT NULL;
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS coin_transactions, reactions, reports, confessions, users CASCADE;")
