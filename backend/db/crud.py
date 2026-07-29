"""Transactional database operations for users, crops, diagnoses and follow-ups."""

import datetime
import json
import uuid

from sqlalchemy import and_, delete, func, insert, select, update
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.exc import IntegrityError

from . import models


KST = datetime.timezone(datetime.timedelta(hours=9))


class DuplicateEmailError(ValueError):
    """Raised when a normalized email already belongs to another account."""


def kst_today_start_utc():
    """Return today's KST midnight as an aware UTC datetime."""
    now_kst = datetime.datetime.now(KST)
    midnight_kst = now_kst.replace(hour=0, minute=0, second=0, microsecond=0)
    return midnight_kst.astimezone(datetime.timezone.utc)


def _one_mapping(result):
    row = result.mappings().first()
    return dict(row) if row else None


_USER_COLUMNS = (
    models.users.c.id,
    models.users.c.public_id,
    models.users.c.created_at,
    models.users.c.email,
    models.users.c.password_hash,
    models.users.c.role,
    models.users.c.certification,
    models.users.c.purpose,
    models.users.c.daily_limit,
    models.users.c.token_version,
)


# --- users -------------------------------------------------------------


def create_user(email, password_hash, certification, purpose):
    """Insert a normalized user and return that transaction's user snapshot.

    Returning the INSERT snapshot is security-sensitive. Re-reading after
    commit would let a concurrent managed-admin promotion turn a signup
    response into a valid administrator token.
    """
    values = {
        "public_id": str(uuid.uuid4()),
        "email": email.strip().lower(),
        "password_hash": password_hash,
        "certification": certification,
        "purpose": purpose,
    }
    try:
        with models.get_engine().begin() as connection:
            return _one_mapping(
                connection.execute(
                    insert(models.users).values(**values).returning(*_USER_COLUMNS)
                )
            )
    except IntegrityError as exc:
        raise DuplicateEmailError from exc


def get_user_by_email(email):
    normalized = (email or "").strip().lower()
    with models.get_engine().connect() as connection:
        return _one_mapping(
            connection.execute(
                select(*_USER_COLUMNS).where(
                    func.lower(models.users.c.email) == normalized
                )
            )
        )


def get_user_by_id(user_id):
    with models.get_engine().connect() as connection:
        return _one_mapping(
            connection.execute(
                select(*_USER_COLUMNS).where(models.users.c.id == user_id)
            )
        )


def get_user_by_public_id(public_id):
    with models.get_engine().connect() as connection:
        return _one_mapping(
            connection.execute(
                select(*_USER_COLUMNS).where(models.users.c.public_id == public_id)
            )
        )


def update_user_profile(user_id, certification, purpose):
    with models.get_engine().begin() as connection:
        connection.execute(
            update(models.users)
            .where(models.users.c.id == user_id)
            .values(certification=certification, purpose=purpose)
        )


def _dialect_insert(connection, table):
    if connection.dialect.name == "postgresql":
        return postgresql_insert(table)
    return sqlite_insert(table)


def apply_managed_admin_config(email, password_hash, config_version):
    """Atomically apply a monotonic singleton administrator configuration.

    Old Cloud Run revisions may start after a newer revision. A lower stored
    version is therefore a complete no-op, and an equal version is read-only.
    Only a strictly newer version may rotate credentials or change the admin.
    """
    if (
        isinstance(config_version, bool)
        or not isinstance(config_version, int)
        or not 1 <= config_version <= 9_223_372_036_854_775_807
    ):
        raise ValueError("config_version must be a positive signed 64-bit integer")

    normalized = email.strip().lower()
    if not normalized:
        raise ValueError("email is required")

    with models.get_engine().begin() as connection:
        # This first write serializes the empty-state bootstrap too. PostgreSQL
        # then locks the singleton row; SQLite holds its write lock.
        initialize_state = (
            _dialect_insert(connection, models.managed_admin_state)
            .values(id=1, config_version=0)
            .on_conflict_do_nothing(index_elements=[models.managed_admin_state.c.id])
        )
        connection.execute(initialize_state)

        state = (
            connection.execute(
                select(
                    models.managed_admin_state.c.admin_user_id,
                    models.managed_admin_state.c.config_version,
                )
                .where(models.managed_admin_state.c.id == 1)
                .with_for_update()
            )
            .mappings()
            .one()
        )
        stored_version = int(state["config_version"])
        if config_version < stored_version:
            return {"status": "stale", "stored_version": stored_version}
        if config_version == stored_version:
            current_user = None
            if state["admin_user_id"] is not None:
                current_user = _one_mapping(
                    connection.execute(
                        select(*_USER_COLUMNS).where(
                            models.users.c.id == state["admin_user_id"]
                        )
                    )
                )
            return {
                "status": "current",
                "stored_version": stored_version,
                "user": current_user,
            }

        candidate = {
            "public_id": str(uuid.uuid4()),
            "email": normalized,
            "password_hash": password_hash,
            "role": "admin",
            "daily_limit": None,
        }
        insert_candidate = (
            _dialect_insert(connection, models.users)
            .values(**candidate)
            .on_conflict_do_nothing()
            .returning(models.users.c.id)
        )
        inserted_user_id = connection.execute(insert_candidate).scalar_one_or_none()

        if inserted_user_id is None:
            target = _one_mapping(
                connection.execute(
                    select(models.users.c.id)
                    .where(func.lower(models.users.c.email) == normalized)
                    .with_for_update()
                )
            )
            if target is None:
                raise RuntimeError(
                    "Managed admin email conflicted with an unrelated unique value."
                )
            target_user_id = target["id"]
            connection.execute(
                update(models.users)
                .where(models.users.c.id == target_user_id)
                .values(
                    email=normalized,
                    password_hash=password_hash,
                    role="admin",
                    daily_limit=None,
                    token_version=models.users.c.token_version + 1,
                )
            )
        else:
            target_user_id = inserted_user_id

        # This service has one environment-managed administrator. Revoking and
        # demoting every prior admin prevents an ADMIN_ID rotation from leaving
        # a valid privileged token behind. Former admins receive the safe
        # default quota if they previously had the admin-only unlimited value.
        connection.execute(
            update(models.users)
            .where(
                models.users.c.role == "admin",
                models.users.c.id != target_user_id,
            )
            .values(
                role="user",
                daily_limit=func.coalesce(models.users.c.daily_limit, 3),
                token_version=models.users.c.token_version + 1,
            )
        )
        connection.execute(
            update(models.managed_admin_state)
            .where(models.managed_admin_state.c.id == 1)
            .values(
                admin_user_id=target_user_id,
                config_version=config_version,
                updated_at=func.now(),
            )
        )

        return {
            "status": "applied",
            "stored_version": config_version,
            "user": _one_mapping(
                connection.execute(
                    select(*_USER_COLUMNS).where(models.users.c.id == target_user_id)
                )
            ),
        }


def set_daily_limit(public_id, daily_limit):
    """Update an account by public UUID. Returns False when it does not exist."""
    with models.get_engine().begin() as connection:
        result = connection.execute(
            update(models.users)
            .where(models.users.c.public_id == public_id)
            .values(daily_limit=daily_limit)
        )
        return result.rowcount > 0


def admin_list_users(today_start_utc):
    used_today = (
        select(func.count())
        .select_from(models.diagnoses)
        .where(
            models.diagnoses.c.user_id == models.users.c.id,
            models.diagnoses.c.created_at >= today_start_utc,
        )
        .correlate(models.users)
        .scalar_subquery()
    )
    total_count = (
        select(func.count())
        .select_from(models.diagnoses)
        .where(models.diagnoses.c.user_id == models.users.c.id)
        .correlate(models.users)
        .scalar_subquery()
    )
    last_diagnosis = (
        select(func.max(models.diagnoses.c.created_at))
        .where(models.diagnoses.c.user_id == models.users.c.id)
        .correlate(models.users)
        .scalar_subquery()
    )

    statement = select(
        models.users.c.public_id.label("id"),
        models.users.c.created_at,
        models.users.c.email,
        models.users.c.role,
        models.users.c.certification,
        models.users.c.purpose,
        models.users.c.daily_limit,
        used_today.label("used_today"),
        total_count.label("total_count"),
        last_diagnosis.label("last_diagnosis_at"),
    ).order_by(models.users.c.created_at, models.users.c.id)

    with models.get_engine().connect() as connection:
        return [dict(row) for row in connection.execute(statement).mappings()]


# --- crops -------------------------------------------------------------

_CROP_COLUMNS = (
    models.crops.c.id,
    models.crops.c.user_id,
    models.crops.c.created_at,
    models.crops.c.name,
    models.crops.c.emoji,
    models.crops.c.color,
    models.crops.c.growing_environment,
    models.crops.c.purpose_override,
    models.crops.c.harvest_date,
)


def create_crop(
    user_id,
    name,
    emoji,
    color,
    growing_environment,
    purpose_override,
    harvest_date,
):
    values = {
        "user_id": user_id,
        "name": name,
        "emoji": emoji,
        "color": color,
        "growing_environment": growing_environment,
        "purpose_override": purpose_override,
        "harvest_date": harvest_date,
    }
    with models.get_engine().begin() as connection:
        result = connection.execute(insert(models.crops).values(**values))
        crop_id = result.inserted_primary_key[0]
        return _one_mapping(
            connection.execute(
                select(*_CROP_COLUMNS).where(models.crops.c.id == crop_id)
            )
        )


def get_crops(user_id):
    with models.get_engine().connect() as connection:
        rows = connection.execute(
            select(*_CROP_COLUMNS)
            .where(models.crops.c.user_id == user_id)
            .order_by(models.crops.c.id)
        ).mappings()
        return [dict(row) for row in rows]


def get_crop(user_id, crop_id):
    with models.get_engine().connect() as connection:
        return _one_mapping(
            connection.execute(
                select(*_CROP_COLUMNS).where(
                    models.crops.c.id == crop_id,
                    models.crops.c.user_id == user_id,
                )
            )
        )


def update_crop(
    user_id,
    crop_id,
    growing_environment=None,
    purpose_override=...,
    harvest_date=None,
):
    values = {}
    if growing_environment is not None:
        values["growing_environment"] = growing_environment
    if purpose_override is not ...:
        values["purpose_override"] = purpose_override
    if harvest_date is not None:
        values["harvest_date"] = harvest_date
    if not values:
        return get_crop(user_id, crop_id) is not None

    with models.get_engine().begin() as connection:
        result = connection.execute(
            update(models.crops)
            .where(
                models.crops.c.id == crop_id,
                models.crops.c.user_id == user_id,
            )
            .values(**values)
        )
        return result.rowcount > 0


def delete_crop(user_id, crop_id):
    with models.get_engine().begin() as connection:
        result = connection.execute(
            delete(models.crops).where(
                models.crops.c.id == crop_id,
                models.crops.c.user_id == user_id,
            )
        )
        return result.rowcount > 0


# --- diagnoses ---------------------------------------------------------


def save_diagnosis(
    crop_id,
    class_id,
    confidence,
    status,
    result,
    follow_up_target_date=None,
    user_id=None,
    follow_up_status=None,
):
    with models.get_engine().begin() as connection:
        inserted = connection.execute(
            insert(models.diagnoses).values(
                user_id=user_id,
                crop_id=crop_id,
                class_id=class_id,
                confidence=confidence,
                status=status,
                result_json=json.dumps(result, ensure_ascii=False),
                follow_up_status=follow_up_status,
            )
        )
        diagnosis_id = inserted.inserted_primary_key[0]

        if follow_up_target_date:
            connection.execute(
                insert(models.follow_up_reminders).values(
                    diagnosis_id=diagnosis_id,
                    target_date=follow_up_target_date,
                )
            )
        return diagnosis_id


def get_history(user_id):
    join = models.diagnoses.outerjoin(
        models.crops,
        and_(
            models.crops.c.id == models.diagnoses.c.crop_id,
            models.crops.c.user_id == models.diagnoses.c.user_id,
        ),
    )
    statement = (
        select(
            models.diagnoses.c.id,
            models.diagnoses.c.created_at,
            models.diagnoses.c.status,
            models.diagnoses.c.confidence,
            models.diagnoses.c.result_json,
            models.diagnoses.c.follow_up_status,
            models.crops.c.name.label("crop_name"),
            models.crops.c.emoji.label("crop_emoji"),
            models.crops.c.color.label("crop_color"),
        )
        .select_from(join)
        .where(models.diagnoses.c.user_id == user_id)
        .order_by(models.diagnoses.c.created_at.desc(), models.diagnoses.c.id.desc())
    )
    with models.get_engine().connect() as connection:
        return [dict(row) for row in connection.execute(statement).mappings()]


def get_diagnosis(user_id, diagnosis_id):
    statement = select(
        models.diagnoses.c.id,
        models.diagnoses.c.created_at,
        models.diagnoses.c.user_id,
        models.diagnoses.c.crop_id,
        models.diagnoses.c.class_id,
        models.diagnoses.c.confidence,
        models.diagnoses.c.status,
        models.diagnoses.c.result_json,
        models.diagnoses.c.follow_up_status,
    ).where(
        models.diagnoses.c.id == diagnosis_id,
        models.diagnoses.c.user_id == user_id,
    )
    with models.get_engine().connect() as connection:
        return _one_mapping(connection.execute(statement))


def set_follow_up_status(user_id, diagnosis_id, status):
    with models.get_engine().begin() as connection:
        result = connection.execute(
            update(models.diagnoses)
            .where(
                models.diagnoses.c.id == diagnosis_id,
                models.diagnoses.c.user_id == user_id,
            )
            .values(follow_up_status=status)
        )
        return result.rowcount > 0


def count_diagnoses_since(user_id, since_utc):
    with models.get_engine().connect() as connection:
        return connection.execute(
            select(func.count())
            .select_from(models.diagnoses)
            .where(
                models.diagnoses.c.user_id == user_id,
                models.diagnoses.c.created_at >= since_utc,
            )
        ).scalar_one()


# --- follow-up reminders -----------------------------------------------


def get_due_follow_ups(today=None):
    today = today or datetime.date.today().isoformat()
    statement = select(
        models.follow_up_reminders.c.id,
        models.follow_up_reminders.c.diagnosis_id,
        models.follow_up_reminders.c.target_date,
        models.follow_up_reminders.c.sent,
    ).where(
        models.follow_up_reminders.c.sent == 0,
        models.follow_up_reminders.c.target_date <= today,
    )
    with models.get_engine().connect() as connection:
        return [dict(row) for row in connection.execute(statement).mappings()]


def mark_follow_up_sent(reminder_id):
    with models.get_engine().begin() as connection:
        connection.execute(
            update(models.follow_up_reminders)
            .where(models.follow_up_reminders.c.id == reminder_id)
            .values(sent=1)
        )
