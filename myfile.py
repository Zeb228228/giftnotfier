import logging
import asyncio
import nest_asyncio
import requests
import datetime
import json
import os
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, ContextTypes,
    CallbackQueryHandler, MessageHandler, filters, ConversationHandler
)

# Применяем патч для поддержки вложенных event loop (например, в Jupyter)
nest_asyncio.apply()

# Данные бота и канала
BOT_TOKEN = "7773092319:AAFwirYylj1qOYcUxDlCJCczG5C0bBWZPMo"  # Токен вашего бота
GIFT_URL = f"https://api.telegram.org/bot{BOT_TOKEN}/getAvailableGifts"
ADMIN_CHAT_ID = 531669581

# Числовой ID канала для проверки подписки (с префиксом -100)
CHANNEL_ID = -1002350477905
# Ссылка на канал (для кнопки "Подписаться")
CHANNEL_URL = "https://t.me/giftgemble"

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

USERS_FILE = "users.json"


def load_users() -> set:
    if os.path.exists(USERS_FILE):
        try:
            with open(USERS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                return set(data)
        except Exception as e:
            logger.error("Ошибка загрузки пользователей: %s", e)
    return set()


def save_users(users: set) -> None:
    try:
        with open(USERS_FILE, "w", encoding="utf-8") as f:
            json.dump(list(users), f)
    except Exception as e:
        logger.error("Ошибка сохранения пользователей: %s", e)


# Загружаем пользователей при старте
users = load_users()

# Состояния для диалогов
CONTACT_MESSAGE = 1
ADMIN_REPLY = 2

# Опции периодичности уведомлений (в секундах)
FREQUENCY_OPTIONS = {
    "Только при наличии новых подарков": None,
    "Каждый день": 86400,
    "Каждые 6 часов": 21600,
    "Каждый час": 3600,
    "Каждые 10 минут": 600,
    "Каждые 5 минут": 300,
    "Каждую минуту": 60
}


# ====================================================================
# Функция проверки подписки
# ====================================================================
async def ensure_subscription(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    user_id = update.effective_user.id
    try:
        member = await context.bot.get_chat_member(CHANNEL_ID, user_id)
        logger.info("Проверка подписки для пользователя %s: статус %s", user_id, member.status)
        if member.status not in ["left", "kicked"]:
            return True
        else:
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("Подписаться", url=CHANNEL_URL)],
                [InlineKeyboardButton("Проверить подписку", callback_data="check_subscription")]
            ])
            if update.message:
                await update.message.reply_text(
                    "Для использования бота необходимо подписаться на канал.",
                    reply_markup=keyboard
                )
            elif update.callback_query:
                await update.callback_query.message.reply_text(
                    "Для использования бота необходимо подписаться на канал.",
                    reply_markup=keyboard
                )
            return False
    except Exception as e:
        logger.error("Ошибка проверки подписки: %s", e)
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("Подписаться", url=CHANNEL_URL)],
            [InlineKeyboardButton("Проверить подписку", callback_data="check_subscription")]
        ])
        if update.message:
            await update.message.reply_text(
                "Произошла ошибка при проверке подписки. Проверьте, что бот является администратором канала.",
                reply_markup=keyboard
            )
        elif update.callback_query:
            await update.callback_query.message.reply_text(
                "Произошла ошибка при проверке подписки. Проверьте, что бот является администратором канала.",
                reply_markup=keyboard
            )
        return False


async def check_subscription_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.callback_query.answer()
    if await ensure_subscription(update, context):
        text = "Вы успешно подписаны на канал!"
    else:
        text = "Вы всё ещё не подписаны. Пожалуйста, подпишитесь на канал."
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("↩️ Вернуться в меню", callback_data="back_to_menu")]
    ])
    await update.callback_query.edit_message_text(text=text, reply_markup=keyboard)


# ====================================================================
# Основное меню и функционал бота
# ====================================================================
def get_main_menu_text(is_active: bool, frequency_label: str) -> str:
    if not is_active:
        return (
            "Привет! Я бот-оповещатель, информирующий вас о выпуске новых подарков.\n\n"
            "<b>Нажмите кнопку ▶️ СТАРТ ниже, чтобы начать поиск подарков.</b>\n\n"
            "Статус: поиск неактивен 🔴\n"
            f"Текущие настройки напоминаний: <i>{frequency_label}</i>\n\n"
            "<code>Version: 3.0</code>"
        )
    else:
        return (
            "Привет! Я бот-оповещатель, информирующий вас о выпуске новых подарков.\n\n"
            "<b>Нажмите кнопку ⏹ СТОП ниже, чтобы остановить поиск подарков.</b>\n\n"
            "Статус: поиск активен 🟢\n"
            f"Текущие настройки напоминаний: <i>{frequency_label}</i>\n\n"
            "<code>Version: 3.0</code>"
        )


def get_main_menu_keyboard(is_active: bool) -> InlineKeyboardMarkup:
    toggle_text = "▶️ СТАРТ" if not is_active else "⏹ СТОП"
    toggle_button = InlineKeyboardButton(toggle_text, callback_data="toggle_start")
    how_button = InlineKeyboardButton("❓ Как работает бот?", callback_data="how_it_works")
    settings_button = InlineKeyboardButton("⚙️ Настройки", callback_data="settings")
    contact_button = InlineKeyboardButton("💬 Связаться с админом", callback_data="contact_admin")
    return InlineKeyboardMarkup([[toggle_button], [how_button, settings_button], [contact_button]])


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # Добавляем пользователя в постоянное хранилище, если его там нет
    user_id = update.effective_user.id
    if user_id not in users:
        users.add(user_id)
        save_users(users)
    if not await ensure_subscription(update, context):
        return
    context.chat_data.setdefault("monitoring_active", False)
    context.chat_data.setdefault("notification_frequency", None)
    context.chat_data.setdefault("notification_frequency_label", "только при наличии новых подарков")
    text = get_main_menu_text(context.chat_data["monitoring_active"],
                              context.chat_data["notification_frequency_label"])
    keyboard = get_main_menu_keyboard(context.chat_data["monitoring_active"])
    await update.message.reply_text(text, reply_markup=keyboard, parse_mode="HTML")


async def monitor_gifts(chat_id: int, context: ContextTypes.DEFAULT_TYPE) -> None:
    previous_gift_ids = set()
    first_run = True
    while context.chat_data.get("monitoring_active", False):
        try:
            response = requests.get(GIFT_URL)
            if response.status_code == 200:
                data = response.json()
                if data.get("ok"):
                    gifts = data.get("result", {}).get("gifts", [])
                    current_gift_ids = {gift.get("id") for gift in gifts if gift.get("id")}
                    if first_run:
                        previous_gift_ids = current_gift_ids
                        first_run = False
                    else:
                        new_gifts = current_gift_ids - previous_gift_ids
                        if new_gifts:
                            context.chat_data["last_gift_found"] = datetime.datetime.now()
                            for _ in range(3):
                                await context.bot.send_message(chat_id=chat_id, text="Подарки найдены!!!")
                        previous_gift_ids = current_gift_ids
                else:
                    logger.error("Ошибка API: %s", data)
            else:
                logger.error("Ошибка подключения: статус %s", response.status_code)
        except Exception as e:
            logger.exception("Ошибка при мониторинге подарков: %s", e)
        await asyncio.sleep(0.5)
    logger.info("Мониторинг подарков остановлен для чата %s", chat_id)


async def periodic_notification(chat_id: int, context: ContextTypes.DEFAULT_TYPE, period: int) -> None:
    while context.chat_data.get("monitoring_active", False) and context.chat_data.get(
            "notification_frequency") == period:
        await asyncio.sleep(period)
        last_found = context.chat_data.get("last_gift_found")
        now = datetime.datetime.now()
        if not last_found or (now - last_found).total_seconds() >= period:
            await context.bot.send_message(chat_id=chat_id, text="Новых подарков не найдено. Продолжаю поиск...")
    logger.info("Периодические уведомления остановлены для чата %s", chat_id)


async def toggle_start_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await ensure_subscription(update, context):
        return
    query = update.callback_query
    await query.answer()
    chat_id = query.message.chat_id
    monitoring_active = context.chat_data.get("monitoring_active", False)
    if not monitoring_active:
        context.chat_data["monitoring_active"] = True
        context.chat_data["last_gift_found"] = None
        context.chat_data["gift_task"] = asyncio.create_task(monitor_gifts(chat_id, context))
        freq = context.chat_data.get("notification_frequency")
        if freq:
            context.chat_data["notification_task"] = asyncio.create_task(periodic_notification(chat_id, context, freq))
    else:
        context.chat_data["monitoring_active"] = False
        if "gift_task" in context.chat_data:
            context.chat_data["gift_task"].cancel()
        if "notification_task" in context.chat_data:
            context.chat_data["notification_task"].cancel()
    text = get_main_menu_text(
        context.chat_data.get("monitoring_active", False),
        context.chat_data.get("notification_frequency_label", "только при наличии новых подарков")
    )
    keyboard = get_main_menu_keyboard(context.chat_data.get("monitoring_active", False))
    await query.edit_message_text(text=text, reply_markup=keyboard, parse_mode="HTML")


async def settings_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await ensure_subscription(update, context):
        return
    query = update.callback_query
    await query.answer()
    keyboard = []
    for label, seconds in FREQUENCY_OPTIONS.items():
        callback_data = f"set_freq_{seconds}" if seconds is not None else "set_freq_default"
        keyboard.append([InlineKeyboardButton(label, callback_data=callback_data)])
    keyboard.append([InlineKeyboardButton("↩️ Вернуться в меню", callback_data="back_to_menu")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    text = "Выберите периодичность уведомлений:"
    await query.edit_message_text(text=text, reply_markup=reply_markup)


async def set_frequency_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await ensure_subscription(update, context):
        return
    query = update.callback_query
    await query.answer()
    data = query.data
    if data == "set_freq_default":
        context.chat_data["notification_frequency"] = None
        context.chat_data["notification_frequency_label"] = "только при наличии новых подарков"
        if "notification_task" in context.chat_data:
            context.chat_data["notification_task"].cancel()
    else:
        try:
            seconds = int(data.split("_")[-1])
            context.chat_data["notification_frequency"] = seconds
            for label, sec in FREQUENCY_OPTIONS.items():
                if sec == seconds:
                    context.chat_data["notification_frequency_label"] = label
                    break
            chat_id = query.message.chat_id
            if context.chat_data.get("monitoring_active", False):
                if "notification_task" in context.chat_data:
                    context.chat_data["notification_task"].cancel()
                context.chat_data["notification_task"] = asyncio.create_task(
                    periodic_notification(chat_id, context, seconds))
        except Exception as e:
            logger.exception("Ошибка при установке периодичности: %s", e)
    keyboard = get_main_menu_keyboard(context.chat_data.get("monitoring_active", False))
    text = get_main_menu_text(
        context.chat_data.get("monitoring_active", False),
        context.chat_data.get("notification_frequency_label", "только при наличии новых подарков")
    )
    await query.edit_message_text(text=text, reply_markup=keyboard, parse_mode="HTML")


async def how_it_works_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await ensure_subscription(update, context):
        return
    query = update.callback_query
    await query.answer()
    explanation = (
        "<b>Как пользоваться ботом?</b>\n"
        "• Нажмите кнопку ▶️ СТАРТ для запуска поиска подарков.\n"
        "• В разделе <i>⚙️ Настройки</i> выберите нужный интервал уведомлений.\n"
        "• Если возникнут вопросы — используйте кнопку <i>💬 Связаться с админом</i>.\n\n"
        "<b>Принцип работы:</b>\n"
        "Бот каждые 0.5 секунды опрашивает API для обнаружения новых подарков. Если новые подарки находятся, он отправляет уведомление три раза. "
        "При отсутствии обновлений, в зависимости от настроек, бот периодически сообщает, что поиск продолжается. "
        "Все процессы работают асинхронно, что гарантирует стабильную работу 24/7."
    )
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("↩️ Вернуться в меню", callback_data="back_to_menu")]
    ])
    await query.edit_message_text(text=explanation, reply_markup=keyboard, parse_mode="HTML")


async def back_to_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await ensure_subscription(update, context):
        return
    query = update.callback_query
    await query.answer()
    text = get_main_menu_text(
        context.chat_data.get("monitoring_active", False),
        context.chat_data.get("notification_frequency_label", "только при наличии новых подарков")
    )
    keyboard = get_main_menu_keyboard(context.chat_data.get("monitoring_active", False))
    await query.edit_message_text(text=text, reply_markup=keyboard, parse_mode="HTML")


# ====================================================================
# Функционал связи с админом
# ====================================================================
async def contact_admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not await ensure_subscription(update, context):
        return ConversationHandler.END
    query = update.callback_query
    await query.answer()
    await query.message.reply_text("Напишите, что хотите отправить администратору. Можно прикрепить изображение.")
    return CONTACT_MESSAGE


async def retry_contact_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not await ensure_subscription(update, context):
        return ConversationHandler.END
    query = update.callback_query
    await query.answer()
    await query.message.reply_text(
        "Попробуйте отправить сообщение для администратора ещё раз. Можно прикрепить изображение.")
    return CONTACT_MESSAGE


async def admin_message_received(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.effective_user
    user_chat_id = update.effective_chat.id
    now = datetime.datetime.now().strftime("%d.%m.%Y %H:%M:%S")
    header = f"Отправлено от: {user.username or user.full_name} (ID: {user_chat_id})\nВ: {now}\n\n"
    user_text = update.message.text if update.message.text else ""
    final_text = header + user_text
    try:
        if update.message.photo:
            photo = update.message.photo[-1]
            sent_msg = await context.bot.send_photo(
                chat_id=ADMIN_CHAT_ID,
                photo=photo.file_id,
                caption=final_text,
            )
        else:
            sent_msg = await context.bot.send_message(
                chat_id=ADMIN_CHAT_ID,
                text=final_text,
            )
        reply_button = InlineKeyboardMarkup([
            [InlineKeyboardButton("Ответить", callback_data=f"reply_{user_chat_id}")]
        ])
        await context.bot.edit_message_reply_markup(
            chat_id=ADMIN_CHAT_ID,
            message_id=sent_msg.message_id,
            reply_markup=reply_button
        )
        user_keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("↩️ Вернуться в меню", callback_data="back_to_menu")]
        ])
        await update.message.reply_text(
            "Ваше сообщение успешно отправлено администратору.",
            reply_markup=user_keyboard
        )
        return ConversationHandler.END
    except Exception as e:
        logger.exception("Ошибка отправки сообщения админу: %s", e)
        error_keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔄 Попробовать снова", callback_data="retry_contact")],
            [InlineKeyboardButton("↩️ Вернуться в меню", callback_data="back_to_menu")]
        ])
        await update.message.reply_text(
            "Ошибка отправки сообщения. Попробуйте ещё раз или вернитесь в меню.",
            reply_markup=error_keyboard
        )
        return ConversationHandler.END


async def cancel_contact(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("Отмена отправки сообщения.")
    return ConversationHandler.END


async def admin_reply_start_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.effective_user.id != ADMIN_CHAT_ID:
        await update.callback_query.answer("У вас нет прав для этого действия.", show_alert=True)
        return ConversationHandler.END
    await update.callback_query.answer()
    try:
        data = update.callback_query.data  # формат "reply_{user_id}"
        target_user_id = int(data.split("_")[1])
        context.user_data["reply_target"] = target_user_id
        await update.callback_query.message.reply_text("Введите ваш ответ для пользователя:")
        return ADMIN_REPLY
    except Exception as e:
        logger.exception("Ошибка при начале ответа: %s", e)
        await update.callback_query.message.reply_text("Ошибка при попытке ответа. Попробуйте снова.")
        return ConversationHandler.END


async def admin_reply_received(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    target_user_id = context.user_data.get("reply_target")
    if not target_user_id:
        await update.message.reply_text("Целевой пользователь не найден.")
        return ConversationHandler.END
    try:
        admin_reply = update.message.text or "Ответ администратора"
        final_reply = "Вы получили ответ от администратора:\n\n" + admin_reply
        if update.message.photo:
            photo = update.message.photo[-1]
            await context.bot.send_photo(
                chat_id=target_user_id,
                photo=photo.file_id,
                caption=final_reply
            )
        else:
            await context.bot.send_message(
                chat_id=target_user_id,
                text=final_reply
            )
        await update.message.reply_text("Ваш ответ успешно отправлен пользователю.")
        return ConversationHandler.END
    except Exception as e:
        logger.exception("Ошибка отправки ответа пользователю: %s", e)
        await update.message.reply_text("Ошибка отправки ответа пользователю.")
        return ConversationHandler.END


# ====================================================================
# Функция /announce – рассылка сообщений всем пользователям (только для админа)
# ====================================================================
async def announce_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user.id != ADMIN_CHAT_ID:
        await update.message.reply_text("Доступ запрещён!")
        return
    args = context.args
    if not args:
        await update.message.reply_text("Используйте: /announce <текст объявления>")
        return
    announcement = " ".join(args)
    sent_count = 0
    # Загружаем список пользователей из файла (на случай, если глобальная переменная не актуальна)
    user_ids = load_users()
    for user_id in user_ids:
        try:
            await context.bot.send_message(chat_id=user_id, text=announcement)
            sent_count += 1
        except Exception as e:
            logger.error("Не удалось отправить сообщение пользователю %s: %s", user_id, e)
    await update.message.reply_text(f"Объявление отправлено {sent_count} пользователям.")


# ====================================================================
# Регистрация обработчиков и запуск приложения
# ====================================================================
def main() -> None:
    application = ApplicationBuilder().token(BOT_TOKEN).build()

    # Основная команда /start для пользователей
    application.add_handler(CommandHandler("start", start_command))
    # Команда /announce для рассылки (только для админа)
    application.add_handler(CommandHandler("announce", announce_command))

    # Обработчик для проверки подписки (по кнопке "Проверить подписку")
    application.add_handler(CallbackQueryHandler(check_subscription_callback, pattern="^check_subscription$"))
    # Обработчик переключения поиска подарков
    application.add_handler(CallbackQueryHandler(toggle_start_callback, pattern="^toggle_start$"))
    # Обработчики для раздела "Как работает бот?" и "Настройки"
    application.add_handler(CallbackQueryHandler(how_it_works_callback, pattern="^how_it_works$"))
    application.add_handler(CallbackQueryHandler(settings_callback, pattern="^settings$"))
    application.add_handler(CallbackQueryHandler(back_to_menu_callback, pattern="^back_to_menu$"))
    application.add_handler(CallbackQueryHandler(set_frequency_callback, pattern="^set_freq_"))

    # ConversationHandler для отправки сообщения от пользователя админу
    user_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(contact_admin_callback, pattern="^contact_admin$")],
        states={
            CONTACT_MESSAGE: [MessageHandler(filters.TEXT | filters.PHOTO, admin_message_received)]
        },
        fallbacks=[CommandHandler("cancel", cancel_contact)]
    )
    application.add_handler(user_conv)

    # ConversationHandler для ответа администратора пользователю
    admin_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(admin_reply_start_callback, pattern="^reply_")],
        states={
            ADMIN_REPLY: [MessageHandler(filters.TEXT | filters.PHOTO, admin_reply_received)]
        },
        fallbacks=[CommandHandler("cancel", admin_reply_received)]
    )
    application.add_handler(admin_conv)

    application.run_polling()


if __name__ == '__main__':
    main()
