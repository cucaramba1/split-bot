"""aiogram: тонкий слой над Service."""
from __future__ import annotations

import logging

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.types import (BotCommand, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message)

from splitbot.config import NAMES, QUEUES, Settings
from splitbot.service import Reply, Service

log = logging.getLogger("splitbot.bot")

FAIL = "Не разобрал, напиши текстом"
HELP = ("Кидай трату голосом или текстом: «кофе 120к на троих», «чипсы 30к мне с Полиной».\n"
        "Очереди: «заправил байк», «купил воду».\n\n"
        "/balance: кто кому сколько должен\n/queue: чей ход (байк, вода) и кнопка «выполнил»\n"
        "/undo: удалить свою последнюю запись")

COMMANDS = [
    BotCommand(command="balance", description="Кто кому сколько должен"),
    BotCommand(command="queue", description="Чей ход: байк и вода"),
    BotCommand(command="undo", description="Удалить свою последнюю запись"),
    BotCommand(command="help", description="Как пользоваться"),
]


def _names_kb(prefix: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=n, callback_data=f"{prefix}:{n}") for n in NAMES]])


async def _answer(m: Message, r: Reply | None) -> Message | None:
    if r is None:
        return None
    return await m.answer(r.text, reply_markup=r.kb)


def build_router(s: Settings, svc: Service) -> Router:
    r = Router()

    if s.chat_id is None:
        @r.message(Command("join"))
        async def join_setup(m: Message):
            log.warning("CHAT_ID не задан, id этого чата: %s", m.chat.id)
            await m.answer(f"Id этого чата: {m.chat.id}. Впиши его в .env как CHAT_ID и перезапусти бота.")
        return r

    r.message.filter(F.chat.id == s.chat_id)
    r.callback_query.filter(F.message.chat.id == s.chat_id)

    def me(m: Message | CallbackQuery) -> str | None:
        return svc.db.member_name(m.from_user.id) if m.from_user else None

    @r.message(Command("join"))
    async def join(m: Message):
        if len(svc.db.members()) >= len(NAMES) and me(m) is None:
            return
        await m.answer("Кто ты?", reply_markup=_names_kb("jn"))

    @r.callback_query(F.data.startswith("jn:"))
    async def join_pick(c: CallbackQuery):
        rep = svc.join(c.from_user.id, c.data.split(":", 1)[1])
        await c.answer(rep.text if rep else "Регистрация закрыта", show_alert=True)

    @r.message(Command("help"))
    async def help_(m: Message):
        if me(m):
            await m.answer(HELP)

    @r.message(Command("balance"))
    async def balance(m: Message):
        if me(m):
            await _answer(m, svc.balance())

    @r.message(Command("queue"))
    async def queue(m: Message):
        if me(m):
            await _answer(m, svc.queue_status())

    @r.callback_query(F.data.startswith("qv:"))
    async def queue_view(c: CallbackQuery):
        rep = svc.queue_view(c.data[3:]) if me(c) else None
        if rep is None:
            return await c.answer()
        try:
            await c.message.edit_text(rep.text, reply_markup=rep.kb)
        except TelegramBadRequest as e:  # повторный тап: текст тот же
            log.info("очередь не обновить: %s", e)
        await c.answer()

    @r.callback_query(F.data.startswith("qd:"))
    async def queue_done(c: CallbackQuery):
        parts = c.data.split(":", 2)
        if len(parts) != 3:
            return await c.answer()
        await _finish(c, svc.queue_done(c.from_user.id, parts[1], parts[2]))

    @r.message(Command("queue_set"))
    async def queue_set(m: Message):
        if me(m):
            kb = InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text=title, callback_data=f"qs:{q}") for q, title in QUEUES.items()]])
            await m.answer("Какая очередь?", reply_markup=kb)

    @r.callback_query(F.data.startswith("qs:"))
    async def queue_pick(c: CallbackQuery):
        if not me(c):
            return await c.answer()
        q = c.data.split(":", 1)[1]
        if q not in QUEUES:
            return await c.answer()
        await c.message.edit_text(f"{QUEUES[q]}: чей ход следующий?", reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text=n, callback_data=f"qn:{q}:{n}") for n in NAMES]]))
        await c.answer()

    @r.callback_query(F.data.startswith("qn:"))
    async def queue_name(c: CallbackQuery):
        if not me(c):
            return await c.answer()
        _, q, name = c.data.split(":", 2)
        if q not in QUEUES or name not in NAMES:
            return await c.answer()
        rep = svc.queue_set(q, name)
        await c.message.edit_text(rep.text)
        await c.answer()

    @r.message(Command("undo"))
    async def undo(m: Message):
        await _answer(m, svc.undo_ask(m.from_user.id))

    async def _finish(c: CallbackQuery, result: str) -> None:
        """Успех снимает кнопки и дописывает итог к карточке, отказ только всплывает."""
        ok = result.startswith(("✅", "❌", "↩️"))
        if ok:
            try:
                await c.message.edit_text(f"{c.message.text}\n\n{result}", reply_markup=None)
            except TelegramBadRequest as e:
                log.warning("карточку не отредактировать: %s", e)
        await c.answer(None if ok else result, show_alert=not ok)

    @r.callback_query(F.data.startswith("ok:"))
    async def ok(c: CallbackQuery):
        await _finish(c, svc.confirm(c.from_user.id, int(c.data[3:])))

    @r.callback_query(F.data.startswith("no:"))
    async def no(c: CallbackQuery):
        await _finish(c, svc.cancel(c.from_user.id, int(c.data[3:])))

    @r.callback_query(F.data.startswith("ud:"))
    async def ud(c: CallbackQuery):
        await _finish(c, svc.undo(c.from_user.id, int(c.data[3:])))

    @r.callback_query(F.data.in_({"pm:open", "pm:back"}))
    async def pay_menu(c: CallbackQuery):
        if not me(c):
            return await c.answer()
        rep = svc.pay_menu() if c.data == "pm:open" else svc.balance()
        if rep is None:
            return await c.answer("Все долги закрыты", show_alert=True)
        try:
            await c.message.edit_reply_markup(reply_markup=rep.kb)  # текст остаётся, меняются только кнопки
        except TelegramBadRequest as e:
            log.info("кнопки не обновить: %s", e)
        await c.answer()

    @r.callback_query(F.data.startswith("pd:"))
    async def pd(c: CallbackQuery):
        """Тап по переводу открывает выбор суммы, ничего не записывая."""
        rep = svc.pay_amount_menu(c.from_user.id, int(c.data[3:])) if me(c) else None
        if rep is None:
            return await c.answer("Уже отмечено или это не твой перевод", show_alert=True)
        try:
            await c.message.edit_reply_markup(reply_markup=rep.kb)
        except TelegramBadRequest as e:
            log.info("кнопки не обновить: %s", e)
        await c.answer(rep.text)

    @r.callback_query(F.data == "pm:other")
    async def pay_other(c: CallbackQuery):
        await c.answer("Напиши или надиктуй в чат, например: «отдал Антону 25к»", show_alert=True)

    async def _paid_done(c: CallbackQuery, res: str, undo_id: int) -> None:
        if not res.startswith("✅"):
            return await c.answer(res, show_alert=True)
        undo_kb = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="↩️ Не оплачено", callback_data=f"up:{undo_id}")]])
        await c.message.answer(res, reply_markup=undo_kb)  # ошибочный тап можно снять
        rep = svc.pay_menu()  # остаток пересчитан: показываем актуальный список или убираем кнопки
        try:
            await c.message.edit_reply_markup(reply_markup=rep.kb if rep else None)
        except TelegramBadRequest as e:
            log.warning("кнопки не обновить: %s", e)
        await c.answer()

    @r.callback_query(F.data.startswith("pf:"))
    async def pay_full(c: CallbackQuery):
        item = int(c.data[3:])
        await _paid_done(c, svc.paid(c.from_user.id, item), item)

    @r.callback_query(F.data.startswith("ph:"))
    async def pay_half(c: CallbackQuery):
        res, new_id = svc.pay_half(c.from_user.id, int(c.data[3:]))
        await _paid_done(c, res, new_id or 0)

    @r.callback_query(F.data.startswith("up:"))
    async def up(c: CallbackQuery):
        res = svc.unpaid(c.from_user.id, int(c.data[3:]))
        if res.startswith("↩️"):
            try:
                await c.message.edit_text(f"{c.message.text}\n\n{res}", reply_markup=None)
            except TelegramBadRequest as e:
                log.warning("сообщение не отредактировать: %s", e)
            await c.answer()
        else:
            await c.answer(res, show_alert=True)

    async def _card(m: Message, text: str, placeholder: Message | None = None) -> None:
        try:
            res = await svc.handle_text(m.from_user.id, text)
        except Exception:
            log.exception("разбор упал")
            await (placeholder.edit_text(FAIL) if placeholder else m.answer(FAIL))
            return
        if res is None:
            if placeholder:
                await placeholder.delete()
            return
        rep, did = res
        if placeholder:
            msg = await placeholder.edit_text(rep.text, reply_markup=rep.kb)
        else:
            msg = await m.answer(rep.text, reply_markup=rep.kb)
        svc.db.set_card(did, msg.message_id)

    @r.message(F.voice)
    async def voice(m: Message):
        if not me(m):
            return
        ph = await m.answer("⏳ Слушаю…")
        path = s.data_dir / "voice" / f"{m.chat.id}_{m.message_id}.ogg"
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            await m.bot.download(m.voice, destination=path)
            text = await svc.transcribe_fn(path)
        except Exception:
            log.exception("голос не расшифрован")
            await ph.edit_text(FAIL)
            return
        finally:
            path.unlink(missing_ok=True)
        await _card(m, text, ph)

    @r.message(F.text & ~F.text.startswith("/"))
    async def text(m: Message):
        if me(m):
            await _card(m, m.text)

    return r
