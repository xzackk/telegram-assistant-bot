import os
import html
import logging
import threading
from typing import Optional

import httpx
from google import genai
from openai import OpenAI
from http.server import HTTPServer, BaseHTTPRequestHandler
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
)

logger = logging.getLogger(__name__)

logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("telegram").setLevel(logging.WARNING)
logging.getLogger("telegram.ext").setLevel(logging.WARNING)
logging.getLogger("google_genai").setLevel(logging.WARNING)
logging.getLogger("openai").setLevel(logging.WARNING)

TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
GEMINI_KEY = os.environ["GEMINI_KEY"]
GROQ_KEY = os.environ["GROQ_KEY"]
OPENROUTER_KEY = os.environ["OPENROUTER_KEY"]

gemini_client = genai.Client(api_key=GEMINI_KEY)
groq_client = OpenAI(api_key=GROQ_KEY, base_url="https://api.groq.com/openai/v1")
openrouter_client = OpenAI(
    api_key=OPENROUTER_KEY,
    base_url="https://openrouter.ai/api/v1",
)

user_state = {}

CITY_COORDS = {
    "sofia": {
        "name": "Sofia",
        "lat": 42.6977,
        "lon": 23.3219,
        "tz": "Europe/Sofia",
    },
    "pernik": {
        "name": "Pernik",
        "lat": 42.6056,
        "lon": 23.0378,
        "tz": "Europe/Sofia",
    },
    "amsterdam": {
        "name": "Amsterdam",
        "lat": 52.3676,
        "lon": 4.9041,
        "tz": "Europe/Amsterdam",
    },
    "larnaca": {
        "name": "Larnaca",
        "lat": 34.9229,
        "lon": 33.6232,
        "tz": "Asia/Nicosia",
    },
}


class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")

    def log_message(self, format, *args):
        pass


def run_health_server():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), HealthHandler)
    server.serve_forever()


def safe_html(text: str) -> str:
    return html.escape(text or "No response.")


def get_user_state(user_id: int) -> dict:
    if user_id not in user_state:
        user_state[user_id] = {
            "mode": "menu",
            "provider": "gemini",
        }
    return user_state[user_id]


def main_menu() -> InlineKeyboardMarkup:
    keyboard = [
        [InlineKeyboardButton("🤖 Ask AI", callback_data="menu_ai")],
        [InlineKeyboardButton("🌦 Weather", callback_data="menu_weather")],
        [InlineKeyboardButton("⚙️ Settings", callback_data="menu_settings")],
        [InlineKeyboardButton("ℹ️ Help", callback_data="menu_help")],
    ]
    return InlineKeyboardMarkup(keyboard)


def ai_menu() -> InlineKeyboardMarkup:
    keyboard = [
        [
            InlineKeyboardButton("✨ Gemini", callback_data="set_ai_gemini"),
            InlineKeyboardButton("⚡ Groq", callback_data="set_ai_groq"),
        ],
        [
            InlineKeyboardButton("🆓 Free AI", callback_data="set_ai_freeai"),
            InlineKeyboardButton("🌐 Ask All", callback_data="set_mode_ask_all"),
        ],
        [InlineKeyboardButton("🔙 Back", callback_data="back_main")],
    ]
    return InlineKeyboardMarkup(keyboard)


def weather_menu() -> InlineKeyboardMarkup:
    keyboard = [
        [
            InlineKeyboardButton("Sofia", callback_data="weather_sofia"),
            InlineKeyboardButton("Pernik", callback_data="weather_pernik"),
        ],
        [
            InlineKeyboardButton("Amsterdam", callback_data="weather_amsterdam"),
            InlineKeyboardButton("Larnaca", callback_data="weather_larnaca"),
        ],
        [InlineKeyboardButton("🔙 Back", callback_data="back_main")],
    ]
    return InlineKeyboardMarkup(keyboard)


def settings_menu(current_provider: str) -> InlineKeyboardMarkup:
    pretty_name = {
        "gemini": "Gemini",
        "groq": "Groq",
        "freeai": "Free AI",
    }.get(current_provider, "Gemini")

    keyboard = [
        [InlineKeyboardButton(f"Current AI: {pretty_name}", callback_data="noop")],
        [InlineKeyboardButton("Change AI", callback_data="menu_ai")],
        [InlineKeyboardButton("Reset Mode", callback_data="reset_mode")],
        [InlineKeyboardButton("🔙 Back", callback_data="back_main")],
    ]
    return InlineKeyboardMarkup(keyboard)


def weather_code_to_text(code: Optional[int]) -> str:
    mapping = {
        0: "Clear sky",
        1: "Mainly clear",
        2: "Partly cloudy",
        3: "Overcast",
        45: "Fog",
        48: "Depositing rime fog",
        51: "Light drizzle",
        53: "Moderate drizzle",
        55: "Dense drizzle",
        56: "Light freezing drizzle",
        57: "Dense freezing drizzle",
        61: "Slight rain",
        63: "Moderate rain",
        65: "Heavy rain",
        66: "Light freezing rain",
        67: "Heavy freezing rain",
        71: "Slight snow fall",
        73: "Moderate snow fall",
        75: "Heavy snow fall",
        77: "Snow grains",
        80: "Slight rain showers",
        81: "Moderate rain showers",
        82: "Violent rain showers",
        85: "Slight snow showers",
        86: "Heavy snow showers",
        95: "Thunderstorm",
        96: "Thunderstorm with slight hail",
        99: "Thunderstorm with heavy hail",
    }

    if code is None:
        return "Unknown conditions"

    return mapping.get(code, "Unknown conditions")


async def ask_gemini(question: str) -> str:
    response = gemini_client.models.generate_content(
        model="gemini-2.5-flash",
        contents=question,
    )
    return response.text or "No response."


async def ask_groq(question: str) -> str:
    response = groq_client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{"role": "user", "content": question}],
    )
    return response.choices[0].message.content or "No response."


async def ask_freeai(question: str) -> str:
    response = openrouter_client.chat.completions.create(
        model="openrouter/free",
        messages=[{"role": "user", "content": question}],
    )
    return response.choices[0].message.content or "No response."


def friendly_error_message(e: Exception) -> str:
    text = str(e).lower()

    if "429" in text or "rate" in text:
        return "Temporarily rate-limited. Please try again in a bit."
    if "401" in text or "invalid" in text:
        return "Invalid API key."
    if "402" in text or "balance" in text:
        return "Insufficient balance."
    return "Something went wrong. Please try again."


async def get_weather_for_city(city_key: str) -> str:
    city = CITY_COORDS[city_key]

    params = {
        "latitude": city["lat"],
        "longitude": city["lon"],
        "current": "temperature_2m,weather_code,precipitation,rain",
        "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_sum,rain_sum,showers_sum,precipitation_probability_max",
        "timezone": city["tz"],
        "forecast_days": 1,
    }

    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.get("https://api.open-meteo.com/v1/forecast", params=params)
        response.raise_for_status()
        data = response.json()

    current = data.get("current", {})
    daily = data.get("daily", {})

    current_temp = current.get("temperature_2m", "N/A")
    current_weather_code = current.get("weather_code")
    current_weather_text = weather_code_to_text(current_weather_code)
    current_rain = current.get("rain", 0)
    current_precipitation = current.get("precipitation", 0)

    temp_max = daily.get("temperature_2m_max", ["N/A"])[0]
    temp_min = daily.get("temperature_2m_min", ["N/A"])[0]
    day_weather_code = daily.get("weather_code", [None])[0]
    day_weather_text = weather_code_to_text(day_weather_code)
    rain_sum = daily.get("rain_sum", [0])[0]
    precipitation_sum = daily.get("precipitation_sum", [0])[0]
    showers_sum = daily.get("showers_sum", [0])[0]
    precipitation_probability = daily.get("precipitation_probability_max", ["N/A"])[0]

    will_rain = "Yes" if (
        (isinstance(rain_sum, (int, float)) and rain_sum > 0)
        or (isinstance(precipitation_sum, (int, float)) and precipitation_sum > 0)
        or (isinstance(showers_sum, (int, float)) and showers_sum > 0)
    ) else "No"

    umbrella_tip = "Take an umbrella ☔" if will_rain == "Yes" else "No umbrella needed 😎"

    lines = [
        f"🌦 Weather for {city['name']}",
        "",
        f"Current: {current_temp}°C, {current_weather_text}",
        f"Today: {temp_min}°C to {temp_max}°C, {day_weather_text}",
        f"Will it rain today? {will_rain}",
        f"Max rain chance today: {precipitation_probability}%",
        f"Expected rain today: {rain_sum} mm",
        f"Expected total precipitation today: {precipitation_sum} mm",
        f"Current rain: {current_rain} mm",
        f"Current precipitation: {current_precipitation} mm",
        "",
        umbrella_tip,
    ]
    return "\n".join(lines)


async def send_text(context, chat_id: int, text: str, reply_markup=None):
    await context.bot.send_message(
        chat_id=chat_id,
        text=safe_html(text),
        parse_mode="HTML",
        reply_markup=reply_markup,
    )


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message is None:
        return

    if update.effective_user is None:
        return

    user = get_user_state(update.effective_user.id)
    user["mode"] = "menu"

    welcome_text = (
        "Welcome! 👋\n\n"
        "I'm your Telegram assistant.\n"
        "Choose an option below."
    )
    await update.message.reply_text(welcome_text, reply_markup=main_menu())


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message is None or update.message.text is None:
        return

    if update.effective_chat is None or update.effective_user is None:
        return

    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    text = update.message.text.strip()

    user = get_user_state(user_id)
    mode = user.get("mode", "menu")
    provider = user.get("provider", "gemini")

    if mode == "ai_chat":
        await send_text(context, chat_id, "Thinking... ⏳")

        try:
            if provider == "gemini":
                answer = await ask_gemini(text)
                await send_text(context, chat_id, f"✨ Gemini\n\n{answer}")

            elif provider == "groq":
                answer = await ask_groq(text)
                await send_text(context, chat_id, f"⚡ Groq\n\n{answer}")

            elif provider == "freeai":
                answer = await ask_freeai(text)
                await send_text(context, chat_id, f"🆓 Free AI\n\n{answer}")

            else:
                await send_text(context, chat_id, "No AI provider selected.")
        except Exception as e:
            logger.exception("AI error")
            await send_text(context, chat_id, friendly_error_message(e))

        return

    if mode == "ask_all":
        await send_text(context, chat_id, "Asking all available AIs... ⏳")

        for title, func in [
            ("✨ Gemini", ask_gemini),
            ("⚡ Groq", ask_groq),
            ("🆓 Free AI", ask_freeai),
        ]:
            try:
                answer = await func(text)
                await send_text(context, chat_id, f"{title}\n\n{answer}")
            except Exception as e:
                logger.exception("%s error", title)
                await send_text(context, chat_id, f"{title}\n\n{friendly_error_message(e)}")

        return

    await send_text(
        context,
        chat_id,
        "Please choose an option from the menu first.",
        reply_markup=main_menu(),
    )


async def handle_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query is None:
        return

    await query.answer()

    if update.effective_chat is None or update.effective_user is None:
        return

    if query.data is None:
        return

    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    data = query.data
    user = get_user_state(user_id)

    if data == "noop":
        return

    if data == "back_main":
        user["mode"] = "menu"
        await query.edit_message_text("Main menu", reply_markup=main_menu())
        return

    if data == "menu_ai":
        await query.edit_message_text(
            "Choose your AI provider.",
            reply_markup=ai_menu(),
        )
        return

    if data == "menu_weather":
        await query.edit_message_text(
            "Choose a city.",
            reply_markup=weather_menu(),
        )
        return

    if data == "menu_settings":
        await query.edit_message_text(
            "Settings",
            reply_markup=settings_menu(user["provider"]),
        )
        return

    if data == "menu_help":
        help_text = (
            "How to use me:\n\n"
            "• Tap Ask AI and choose a provider.\n"
            "• Then send your message normally.\n"
            "• Tap Weather to get a forecast for a city.\n"
            "• Use Settings to view your current AI mode."
        )
        await query.edit_message_text(
            help_text,
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("🔙 Back", callback_data="back_main")]]
            ),
        )
        return

    if data == "reset_mode":
        user["mode"] = "menu"
        await query.edit_message_text(
            "Mode reset. Back to main menu.",
            reply_markup=main_menu(),
        )
        return

    if data == "set_ai_gemini":
        user["provider"] = "gemini"
        user["mode"] = "ai_chat"
        await query.edit_message_text(
            "✨ Gemini selected.\n\nSend me your question.",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("🔙 Back", callback_data="back_main")]]
            ),
        )
        return

    if data == "set_ai_groq":
        user["provider"] = "groq"
        user["mode"] = "ai_chat"
        await query.edit_message_text(
            "⚡ Groq selected.\n\nSend me your question.",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("🔙 Back", callback_data="back_main")]]
            ),
        )
        return

    if data == "set_ai_freeai":
        user["provider"] = "freeai"
        user["mode"] = "ai_chat"
        await query.edit_message_text(
            "🆓 Free AI selected.\n\nSend me your question.",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("🔙 Back", callback_data="back_main")]]
            ),
        )
        return

    if data == "set_mode_ask_all":
        user["mode"] = "ask_all"
        await query.edit_message_text(
            "🌐 Ask All selected.\n\nSend me your question.",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("🔙 Back", callback_data="back_main")]]
            ),
        )
        return

    if data.startswith("weather_"):
        city_key = data.split("_", 1)[1]

        try:
            await query.edit_message_text("Loading weather... ⏳", reply_markup=weather_menu())
            weather_text = await get_weather_for_city(city_key)

            await context.bot.send_message(
                chat_id=chat_id,
                text=safe_html(weather_text),
                parse_mode="HTML",
                reply_markup=weather_menu(),
            )
        except Exception:
            logger.exception("Weather error")
            await context.bot.send_message(
                chat_id=chat_id,
                text=safe_html("Could not load weather right now. Please try again."),
                parse_mode="HTML",
                reply_markup=weather_menu(),
            )
        return


def main():
    threading.Thread(target=run_health_server, daemon=True).start()

    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(CallbackQueryHandler(handle_button))

    logger.info("Bot is online!")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()