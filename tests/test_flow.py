import asyncio

from aiogram.methods import (
    AnswerCallbackQuery,
    DeleteMessages,
    EditMessageText,
    SendMediaGroup,
    SendMessage,
    SendPhoto,
)

from bot import texts
from bot.keyboards import CategoryCb, ModerationCb, SkipPhotosCb
from tests.conftest import ADMIN2_ID, ADMIN_ID, CHANNEL

USER_ID = 500


async def submit(env, user, category="housing", text="Сдаю комнату у кампуса, 100к", photos=()):
    await env.send(user, texts.BTN_SUBMIT)
    await env.click(user, CategoryCb(code=category).pack())
    await env.send(user, text)
    if not photos:
        await env.click(user, SkipPhotosCb().pack())
    elif len(photos) == 1:
        await env.feed(env.photo_message(user, photos[0]))
    else:
        msgs = [env.photo_message(user, p, media_group_id="album1") for p in photos]
        await asyncio.gather(*(env.feed(m) for m in msgs))


def approve_cb(ad_id):
    return ModerationCb(action="approve", ad_id=ad_id).pack()


def alerts(env):
    return [r.text for r in env.session.of(AnswerCallbackQuery) if r.show_alert]


async def test_full_flow_without_photos_and_approve(env):
    user = env.user(USER_ID, "student")
    await env.send(user, "/start")
    assert "Привет" in env.texts_to(USER_ID)[0]

    await submit(env, user)
    sent = env.texts_to(USER_ID)
    assert texts.SENT_TO_MODERATION in sent
    # превью поста
    assert any("Сдаю комнату" in t and "#жилье" in t for t in sent)

    ad = await env.db.get_ad(1)
    assert ad.status == "new" and ad.contact == "@student" and ad.photos == []

    # карточка пришла обоим админам
    for admin in (ADMIN_ID, ADMIN2_ID):
        card = env.texts_to(admin)[0]
        assert "НОВОЕ ОБЪЯВЛЕНИЕ #1" in card
        assert "@student (ID: <code>500</code>)" in card
        assert "#Жилье" in card
    assert len(await env.db.get_cards(1)) == 2

    env.clear()
    admin = env.user(ADMIN_ID, "boss")
    await env.click(admin, approve_cb(1))

    channel_posts = env.texts_to(CHANNEL)
    assert len(channel_posts) == 1
    assert channel_posts[0].endswith("#жилье")
    assert "📞 Связь: @student" in channel_posts[0]

    assert texts.USER_APPROVED in env.texts_to(USER_ID)
    edits = env.session.of(EditMessageText)
    assert len(edits) == 2  # обе карточки обновлены
    assert all("Одобрено админом @boss 🟢" in e.text for e in edits)
    assert all(e.reply_markup is None for e in edits)

    ad = await env.db.get_ad(1)
    assert ad.status == "approved" and ad.channel_message_ids


async def test_html_is_escaped(env):
    user = env.user(USER_ID)
    await submit(env, user, text="<b>жирный</b> & <script>")
    card = env.texts_to(ADMIN_ID)[0]
    assert "&lt;b&gt;жирный&lt;/b&gt; &amp; &lt;script&gt;" in card


async def test_non_admin_cannot_moderate(env):
    user = env.user(USER_ID)
    await submit(env, user)
    env.clear()

    await env.click(env.user(777, "hacker"), approve_cb(1))
    assert env.texts_to(CHANNEL) == []
    assert alerts(env) and "только администраторы" in alerts(env)[0]
    assert (await env.db.get_ad(1)).status == "new"


async def test_double_approve_publishes_once(env):
    await submit(env, env.user(USER_ID))
    env.clear()
    await env.click(env.user(ADMIN_ID, "a1"), approve_cb(1))
    await env.click(env.user(ADMIN2_ID, "a2"), approve_cb(1))
    assert len(env.texts_to(CHANNEL)) == 1
    assert any("уже обработано" in a for a in alerts(env))


async def test_reject_with_reason(env):
    await submit(env, env.user(USER_ID))
    env.clear()
    admin = env.user(ADMIN_ID, "boss")

    await env.click(admin, ModerationCb(action="reject", ad_id=1).pack())
    edit = env.session.of(EditMessageText)[-1]
    assert "Отклонено 🔴" in edit.text
    reason_buttons = [b.text for row in edit.reply_markup.inline_keyboard for b in row]
    assert {"Спам", "Не по теме", "Запрещенка"} <= set(reason_buttons)
    assert texts.USER_REJECTED.split(":")[0] not in " ".join(env.texts_to(USER_ID))

    await env.click(admin, ModerationCb(action="reason", ad_id=1, reason="spam").pack())
    assert "⚠️ Ваше объявление отклонено модератором. Причина: Спам" in env.texts_to(USER_ID)
    final = env.session.of(EditMessageText)[-1]
    assert final.reply_markup is None and "Причина: Спам" in final.text
    assert env.texts_to(CHANNEL) == []

    ad = await env.db.get_ad(1)
    assert ad.status == "rejected" and ad.reject_reason == "Спам"


async def test_reject_can_be_undone_before_reason(env):
    await submit(env, env.user(USER_ID))
    admin = env.user(ADMIN_ID, "boss")
    await env.click(admin, ModerationCb(action="reject", ad_id=1).pack())
    await env.click(admin, ModerationCb(action="back", ad_id=1).pack())
    assert (await env.db.get_ad(1)).status == "new"
    await env.click(admin, approve_cb(1))
    assert len(env.texts_to(CHANNEL)) == 1


async def test_rate_limit(env):
    user = env.user(USER_ID)
    await submit(env, user)
    env.clear()
    await env.send(user, texts.BTN_SUBMIT)
    assert "не чаще одного раза в 10 мин" in env.texts_to(USER_ID)[0]


async def test_admins_are_not_rate_limited(env):
    admin = env.user(ADMIN_ID, "boss")
    await submit(env, admin)
    await submit(env, admin)
    assert (await env.db.get_ad(2)) is not None


async def test_text_too_long(env):
    user = env.user(USER_ID)
    await env.send(user, texts.BTN_SUBMIT)
    await env.click(user, CategoryCb(code="market").pack())
    env.clear()
    await env.send(user, "x" * 801)
    assert "Слишком длинно: 801" in env.texts_to(USER_ID)[0]
    await env.send(user, "x" * 800)
    assert texts.ASK_PHOTOS in env.texts_to(USER_ID)


async def test_hidden_username_asks_contact(env):
    user = env.user(USER_ID, username=None)
    await submit(env, user, category="services")
    assert texts.ASK_CONTACT in env.texts_to(USER_ID)
    assert await env.db.get_ad(1) is None

    await env.send(user, "+7 777 123 45 67")
    ad = await env.db.get_ad(1)
    assert ad.contact == "+7 777 123 45 67"
    await env.click(env.user(ADMIN_ID), approve_cb(1))
    post = env.texts_to(CHANNEL)[0]
    assert "+7 777 123 45 67" in post and post.endswith("#услуги")


async def test_single_photo(env):
    await submit(env, env.user(USER_ID), category="market", photos=["p1"])
    ad = await env.db.get_ad(1)
    assert ad.photos == ["p1"]
    env.clear()
    await env.click(env.user(ADMIN_ID), approve_cb(1))
    [post] = [r for r in env.session.of(SendPhoto) if r.chat_id == CHANNEL]
    assert post.photo == "p1" and post.caption.endswith("#барахолка")


async def test_album_of_photos(env):
    await submit(env, env.user(USER_ID), category="other", photos=["p1", "p2", "p3"])
    ad = await env.db.get_ad(1)
    assert ad.photos == ["p1", "p2", "p3"]
    # админу пришёл альбом и одна карточка-ответ на него
    assert [r for r in env.session.of(SendMediaGroup) if r.chat_id == ADMIN_ID]
    assert len(env.texts_to(ADMIN_ID)) == 1

    env.clear()
    await env.click(env.user(ADMIN_ID), approve_cb(1))
    [post] = [r for r in env.session.of(SendMediaGroup) if r.chat_id == CHANNEL]
    assert len(post.media) == 3
    assert post.media[0].caption.endswith("#другое")


async def test_too_many_photos(env):
    await submit(env, env.user(USER_ID), photos=["p1", "p2", "p3", "p4", "p5"])
    assert texts.TOO_MANY_PHOTOS in env.texts_to(USER_ID)
    assert await env.db.get_ad(1) is None


async def test_banned_user(env):
    user = env.user(USER_ID)
    await env.send(user, "/start")
    await env.send(env.user(ADMIN_ID), f"/ban {USER_ID}")
    env.clear()
    await env.send(user, texts.BTN_SUBMIT)
    assert env.texts_to(USER_ID) == [texts.BANNED]


async def test_ban_command_ignored_for_non_admin(env):
    user = env.user(USER_ID)
    await env.send(user, "/start")
    await env.send(env.user(777), f"/ban {USER_ID}")
    assert await env.db.get_user_status(USER_ID) == "active"


async def test_delete_published_post(env):
    await submit(env, env.user(USER_ID))
    await env.click(env.user(ADMIN_ID), approve_cb(1))
    ids = (await env.db.get_ad(1)).channel_message_ids
    env.clear()
    await env.send(env.user(ADMIN_ID), "/delete 1")
    [req] = env.session.of(DeleteMessages)
    assert req.chat_id == CHANNEL and req.message_ids == ids
    assert (await env.db.get_ad(1)).status == "deleted"


async def test_cancel(env):
    user = env.user(USER_ID)
    await env.send(user, texts.BTN_SUBMIT)
    await env.send(user, texts.BTN_CANCEL)
    assert texts.CANCELLED in env.texts_to(USER_ID)
    # после отмены текст не воспринимается как описание
    env.clear()
    await env.send(user, "просто текст")
    assert env.session.of(SendMessage) == []
