# bot.py

import os
import logging
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, quote_plus

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Updater,
    CommandHandler,
    CallbackContext,
    CallbackQueryHandler,
    MessageHandler,
    Filters,
)

# --- CONFIGURACIÓN ---
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
BASE_URL = "https://annas-archive.org"
RESULTS_PER_PAGE = 10

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- LÓGICA DE SCRAPING MEJORADA ---

def buscar_libros(query: str, page: int = 1):
    """
    Busca libros en Anna's Archive con soporte para paginación.
    """
    # Codificamos la query para que sea segura en una URL
    safe_query = quote_plus(query)
    search_url = f"{BASE_URL}/search?q={safe_query}&page={page}&sort=relevant"
    
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        response = requests.get(search_url, headers=headers, timeout=20)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.text, 'lxml')
        
        resultados_html = soup.find_all('div', class_='h-[125]')
        
        libros = []
        for item in resultados_html:
            link_tag = item.find('a', href=lambda href: href and href.startswith('/md5/'))
            if not link_tag:
                continue

            md5_hash = link_tag['href'].split('/md5/')[1]
            titulo = item.find('div', class_='text-lg').get_text(strip=True)
            autor = item.find('div', class_='italic').get_text(strip=True)
            
            libros.append({
                "titulo": titulo,
                "autor": autor,
                "md5": md5_hash
            })
        
        # Comprobar si hay más resultados (si el botón "Next" existe en la página)
        has_next_page = soup.find('a', string='Next') is not None
        
        return {"libros": libros, "has_next_page": has_next_page}

    except requests.exceptions.RequestException as e:
        logger.error(f"Error al conectar con Anna's Archive: {e}")
        return None
    except Exception as e:
        logger.error(f"Error al parsear la página de resultados: {e}")
        return None

def obtener_detalles_libro(md5: str):
    """
    Obtiene portada, descripción y enlaces de descarga de la página de detalles.
    """
    detail_url = f"{BASE_URL}/md5/{md5}"
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        response = requests.get(detail_url, headers=headers, timeout=20)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'lxml')

        # Obtener título desde la página de detalles para mayor precisión
        titulo_tag = soup.find('h1')
        titulo = titulo_tag.get_text(strip=True) if titulo_tag else "Título no encontrado"

        # Obtener portada
        cover_url = ""
        img_tag = soup.find('img', class_='w-full')
        if img_tag and img_tag.get('src'):
            cover_url = urljoin(BASE_URL, img_tag['src'])

        # Obtener descripción
        description = "No hay descripción disponible."
        description_div = soup.find('div', class_='js-md5-search-result-description')
        if description_div:
            description = description_div.get_text(strip=True)

        # Obtener enlaces de descarga
        download_links = []
        # Buscamos los botones que llevan a los mirrors
        download_buttons = soup.find_all('a', class_='js-download-link')
        for button in download_buttons:
            link = button.get('href')
            if link and 'downloads.annas-archive.org' in link:
                 # El formato suele estar en el texto del botón
                format_text = button.get_text(strip=True).split('(')[0].strip()
                download_links.append({"format": format_text, "url": link})

        return {
            "titulo": titulo,
            "cover_url": cover_url,
            "description": description,
            "download_links": download_links
        }
    except Exception as e:
        logger.error(f"Error al obtener detalles del libro ({md5}): {e}")
        return None

# --- COMANDOS Y MANEJADORES ---

def start_command(update: Update, context: CallbackContext) -> None:
    """Mensaje de bienvenida mejorado."""
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
    """Maneja las búsquedas de texto y la paginación."""
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
    # Usamos los últimos 6 caracteres del hash MD5 como código corto
    for libro in search_results["libros"]:
        short_code = libro["md5"][-6:]
        texto_boton = f"{libro['titulo']} /d_{short_code}"
        keyboard.append([InlineKeyboardButton(texto_boton, callback_data=f"detail_{libro['md5']}")])

    # Lógica de paginación
    nav_buttons = []
    if page > 1:
        nav_buttons.append(InlineKeyboardButton("⬅️ Anterior", callback_data=f"page_{page-1}_{query}"))
    if search_results["has_next_page"]:
        nav_buttons.append(InlineKeyboardButton("Siguiente ➡️", callback_data=f"page_{page+1}_{query}"))
    
    if nav_buttons:
        keyboard.append(nav_buttons)

    reply_markup = InlineKeyboardMarkup(keyboard)
    msg.edit_text("Ahí van algunos libros que coinciden con tu búsqueda:", reply_markup=reply_markup)

def callback_router(update: Update, context: CallbackContext) -> None:
    """Dirige las acciones de los botones."""
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

        # Construir el mensaje con portada, descripción y botones de descarga
        caption = f"**{details.get('titulo', 'Título no encontrado')}**\n\n{details['description']}"
        
        # --- MEJORA DE DISEÑO ---
        # El bucle ya es condicional: solo crea botones para los formatos encontrados.
        download_keyboard = []
        for link in details["download_links"]:
            # Cada botón se añade en su propia fila para mayor claridad.
            download_keyboard.append(
                [InlineKeyboardButton(f"Descargar {link['format']}", url=link['url'])]
            )
        
        # Si después de revisar, no hay enlaces, informamos al usuario.
        if not download_keyboard:
            caption += "\n\n❌ Lo siento, no encontré enlaces de descarga válidos para este libro."
            reply_markup = None
        else:
            reply_markup = InlineKeyboardMarkup(download_keyboard)
        # -------------------------

        # Borramos el mensaje anterior ("Obteniendo detalles...")
        context.bot.delete_message(chat_id=query.message.chat_id, message_id=query.message.message_id)

        if details["cover_url"]:
            context.bot.send_photo(
                chat_id=query.message.chat_id,
                photo=details["cover_url"],
                caption=caption,
                parse_mode='Markdown',
                reply_markup=reply_markup
            )
        else:
            # Si no hay portada, enviar solo texto
            context.bot.send_message(
                chat_id=query.message.chat_id,
                text=caption,
                parse_mode='Markdown',
                reply_markup=reply_markup
            )

def ping(context: CallbackContext) -> None:
    """Mantiene el bot activo en Render."""
    logger.info("Ping job running to keep the bot alive.")

def main() -> None:
    """Función principal que inicia el bot."""
    if not TELEGRAM_TOKEN:
        logger.error("¡No se encontró el TELEGRAM_TOKEN!")
        return
        
    updater = Updater(TELEGRAM_TOKEN)
    dispatcher = updater.dispatcher
    
    job_queue = updater.job_queue
    job_queue.run_repeating(ping, interval=600, first=0)

    dispatcher.add_handler(CommandHandler("start", start_command))
    # Manejador para cualquier mensaje de texto que no sea un comando
    dispatcher.add_handler(MessageHandler(Filters.text & ~Filters.command, handle_search))
    dispatcher.add_handler(CallbackQueryHandler(callback_router))

    updater.start_polling()
    logger.info("Bot iniciado y listo para recibir comandos.")
    updater.idle()

if __name__ == '__main__':
    main()
