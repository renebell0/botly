# bot.py

import os
import logging
from threading import Thread
from flask import Flask
import signal

# --- Selenium Imports ---
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
# ------------------------

from bs4 import BeautifulSoup
from urllib.parse import urljoin, quote_plus
import requests

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Updater,
    CommandHandler,
    CallbackContext,
    CallbackQueryHandler,
    MessageHandler,
    Filters,
)

# --- CONFIGURACIÓN DEL SERVIDOR WEB (PARA RENDER) ---
app = Flask(__name__)

@app.route('/')
def index():
    return "Bot is alive!"

def run_flask():
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)

# --- CONFIGURACIÓN DEL BOT ---
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
BASE_URL = "https://annas-archive.org"

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO
)
logger = logging.getLogger(__name__)


# --- LÓGICA DE SCRAPING CON SELENIUM (SOLUCIÓN EXPERTA) ---

def setup_selenium_driver():
    """Configura el driver de Selenium para ejecutarse en el entorno de Render."""
    chrome_options = webdriver.ChromeOptions()
    # Estas opciones son cruciales para correr en un servidor sin interfaz gráfica
    chrome_options.add_argument("--headless")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--window-size=1920,1080")
    
    # Render instala chromium en esta ruta
    service = Service(executable_path="/usr/bin/chromedriver")
    driver = webdriver.Chrome(service=service, options=chrome_options)
    return driver

def buscar_libros(query: str, page: int = 1):
    """
    Busca libros usando un navegador real (Selenium) para manejar JavaScript.
    """
    driver = None
    try:
        driver = setup_selenium_driver()
        safe_query = quote_plus(query)
        search_url = f"{BASE_URL}/search?q={safe_query}&page={page}&sort=relevant"
        logger.info(f"Navigating to URL with Selenium: {search_url}")
        
        driver.get(search_url)

        # Espera explícita: Esperamos un máximo de 20 segundos a que al menos
        # un elemento de resultado sea visible. Esta es la clave.
        WebDriverWait(driver, 20).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "a[href^='/md5/']"))
        )

        # Una vez que la página está cargada, obtenemos el HTML y lo pasamos a BeautifulSoup
        soup = BeautifulSoup(driver.page_source, 'lxml')
        
        result_links = soup.select("a[href^='/md5/']")
        
        libros = []
        for link in result_links:
            titulo_div = link.find('div', class_='text-lg')
            autor_div = link.find('div', class_='italic')
            if titulo_div and autor_div:
                titulo = titulo_div.get_text(strip=True)
                autor = autor_div.get_text(strip=True)
                md5_hash = link['href'].split('/md5/')[1]
                libros.append({"titulo": titulo, "autor": autor, "md5": md5_hash})

        has_next_page = soup.find('a', string='Next') is not None
        logger.info(f"Found {len(libros)} books on page {page} for query '{query}'.")
        return {"libros": libros, "has_next_page": has_next_page}

    except Exception as e:
        logger.error(f"An unexpected error occurred during scraping: {e}", exc_info=True)
        return None
    finally:
        if driver:
            driver.quit() # Es crucial cerrar el navegador para liberar recursos

# La función para obtener detalles no necesita Selenium, `requests` es suficiente y más rápido.
def obtener_detalles_libro(md5: str):
    detail_url = f"{BASE_URL}/md5/{md5}"
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
        response = requests.get(detail_url, headers=headers, timeout=20)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'lxml')
        titulo_tag = soup.find('h1')
        titulo = titulo_tag.get_text(strip=True) if titulo_tag else "Título no encontrado"
        cover_url = ""
        img_tag = soup.find('img', class_='w-full')
        if img_tag and img_tag.get('src'): cover_url = urljoin(BASE_URL, img_tag['src'])
        description = "No hay descripción disponible."
        description_div = soup.find('div', class_='js-md5-search-result-description')
        if description_div: description = description_div.get_text(strip=True)
        download_links = []
        download_buttons = soup.find_all('a', class_='js-download-link')
        for button in download_buttons:
            link = button.get('href')
            if link and 'downloads.annas-archive.org' in link:
                format_text = button.get_text(strip=True).split('(')[0].strip()
                download_links.append({"format": format_text, "url": link})
        return {"titulo": titulo, "cover_url": cover_url, "description": description, "download_links": download_links}
    except Exception as e:
        logger.error(f"Error en obtener_detalles_libro: {e}")
        return None

# --- MANEJADORES DEL BOT (Sin cambios) ---
def start_command(update: Update, context: CallbackContext) -> None:
    mensaje = (
        "¡Buenas! ¡Soy tu bot de Ebooks! ¡Encantado de conocerte! 🙋‍♀️\n\n"
        "Puedo buscar Ebooks por título, autor o serie, simplemente pregúntame lo que quieras buscar.\n\n"
        "**Ejemplos de peticiones:**\n"
        "• `Harry Potter`\n"
        "• `El alquimista Paulo Coelho`\n"
        "• `autor: Stephen King`\n"
        "• `título: El código da Vinci`\n"
        "• `serie: Canción de hielo y fuego`"
    )
    update.message.reply_text(mensaje, parse_mode='Markdown')

def handle_search(update: Update, context: CallbackContext, page: int = 1, query_str: str = None) -> None:
    if query_str:
        query = query_str
        msg = context.bot.edit_message_text(chat_id=update.effective_chat.id, message_id=update.effective_message.message_id, text=f"🔎 Buscando \"{query}\", página {page}...")
    else:
        query = update.message.text
        msg = update.message.reply_text(f"🔎 Buscando \"{query}\"...")
    search_results = buscar_libros(query, page)
    if search_results is None or not search_results["libros"]:
        msg.edit_text(f"🚫 No se encontraron resultados para \"{query}\".")
        return
    keyboard = []
    for libro in search_results["libros"]:
        short_code = libro["md5"][-6:]
        texto_boton = f"{libro['titulo']} /d_{short_code}"
        keyboard.append([InlineKeyboardButton(texto_boton, callback_data=f"detail_{libro['md5']}")])
    nav_buttons = []
    if page > 1: nav_buttons.append(InlineKeyboardButton("⬅️ Anterior", callback_data=f"page_{page-1}_{query}"))
    if search_results["has_next_page"]: nav_buttons.append(InlineKeyboardButton("Siguiente ➡️", callback_data=f"page_{page+1}_{query}"))
    if nav_buttons: keyboard.append(nav_buttons)
    reply_markup = InlineKeyboardMarkup(keyboard)
    msg.edit_text("Ahí van algunos libros que coinciden con tu búsqueda:", reply_markup=reply_markup)

def callback_router(update: Update, context: CallbackContext) -> None:
    query = update.callback_query
    query.answer()
    data = query.data
    if data.startswith("page_"):
        _, page, query_str = data.split("_", 2)
        handle_search(query, context, page=int(page), query_str=query_str)
    elif data.startswith("detail_"):
        md5 = data.split("_", 1)[1]
        query.edit_message_text(text="⏳ Obteniendo detalles del libro...")
        details = obtener_detalles_libro(md5)
        if not details:
            query.edit_message_text("❌ No se pudieron obtener los detalles de este libro.")
            return
        caption = f"**{details.get('titulo', 'Título no encontrado')}**\n\n{details['description']}"
        download_keyboard = []
        for link in details["download_links"]:
            download_keyboard.append([InlineKeyboardButton(f"Descargar {link['format']}", url=link['url'])])
        if not download_keyboard:
            caption += "\n\n❌ Lo siento, no encontré enlaces de descarga válidos para este libro."
            reply_markup = None
        else:
            reply_markup = InlineKeyboardMarkup(download_keyboard)
        context.bot.delete_message(chat_id=query.message.chat_id, message_id=query.message.message_id)
        if details["cover_url"]:
            context.bot.send_photo(chat_id=query.message.chat_id, photo=details["cover_url"], caption=caption, parse_mode='Markdown', reply_markup=reply_markup)
        else:
            context.bot.send_message(chat_id=query.message.chat_id, text=caption, parse_mode='Markdown', reply_markup=reply_markup)

def main() -> None:
    """Función principal que inicia el bot Y el servidor web."""
    if not TELEGRAM_TOKEN:
        logger.error("¡No se encontró el TELEGRAM_TOKEN!")
        return
    
    flask_thread = Thread(target=run_flask)
    flask_thread.start()
        
    updater = Updater(TELEGRAM_TOKEN)
    dispatcher = updater.dispatcher
    
    def shutdown(signum, frame):
        logger.info("Señal de apagado recibida. Deteniendo el bot...")
        updater.stop()

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)
    
    dispatcher.add_handler(CommandHandler("start", start_command))
    dispatcher.add_handler(MessageHandler(Filters.text & ~Filters.command, handle_search))
    dispatcher.add_handler(CallbackQueryHandler(callback_router))

    updater.start_polling()
    logger.info("Bot iniciado y listo para recibir comandos.")
    updater.idle()

if __name__ == '__main__':
    main()
