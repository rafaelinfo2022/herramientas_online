import os
import sys
import uuid
from flask import Flask, render_template, request, send_from_directory, redirect, url_for, flash, send_file, session
from werkzeug.utils import secure_filename
from PIL import Image, ImageEnhance, ImageFilter
from pdf2docx import Converter
import qrcode
from docx2pdf import convert
from pdf2image import convert_from_path
import re
from collections import Counter
import string
import random
from rembg import remove
import fitz  # PyMuPDF
import tabula
import pytesseract
from pdf2image import convert_from_path
import pandas as pd
import numpy as np
from PyPDF2 import PdfReader, PdfWriter
import subprocess
from werkzeug.exceptions import RequestEntityTooLarge
import atexit
import tempfile
import shutil
from rembg import remove, new_session
from werkzeug.security import generate_password_hash, check_password_hash
import yt_dlp
import time
from datetime import datetime
import json
from dotenv import load_dotenv
from PyPDF2 import PdfMerger


load_dotenv()  # Carga las variables desde el archivo .env

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY")
app.config['MAX_CONTENT_LENGTH'] = 1024 * 1024 * 1024 * 16  # 16 GB (Prácticamente ilimitado para local)

# Ruta correcta de tu instalación de Tesseract OCR
pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

# 🔐 Configuración de administrador
ADMIN_USER = os.getenv("ADMIN_USER")
ADMIN_PASS_HASH = os.getenv("ADMIN_PASS_HASH")



@app.errorhandler(413)
def request_entity_too_large(error):
    flash("El archivo es demasiado grande. El límite es de 16 GB.", "error")
    return redirect(request.url)

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
UPLOAD_FOLDER = os.path.join(BASE_DIR, "static", "uploads")
GENERATED_FOLDER = os.path.join(BASE_DIR, "static", "generated")

os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(GENERATED_FOLDER, exist_ok=True)

app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
app.config["GENERATED_FOLDER"] = GENERATED_FOLDER



# Ruta a FFmpeg (nombres corregidos)
FFMPEG_PATH = r"C:\ffmpeg-8.0-full_build\bin\ffmpeg.exe"  # Corregido: "ffmpeg" no "ffimpeg"
FFPROBE_PATH = r"C:\ffmpeg-8.0-full_build\bin\ffprobe.exe"  # Corregido: "ffprobe" no "fiprobe"

POTRACE_PATH = r"C:\potrace-1.16.win64\potrace.exe"
MKBMP_PATH = r"C:\potrace-1.16.win64\mkbitmap.exe"

AUTOTRACE_EXE = os.path.join(BASE_DIR, "autotrace.exe")  

BG_MODEL = new_session("u2net") 
STATS_FILE = "analytics.json"

def save_stats(data):
    with open(STATS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)


def check_ffmpeg():
    """Verificar si FFmpeg está disponible en el sistema"""
    try:
        # Intentar encontrar ffmpeg en el PATH
        ffmpeg_path = shutil.which("ffmpeg")
        if ffmpeg_path:
            print(f"FFmpeg encontrado en: {ffmpeg_path}")
            return ffmpeg_path
        
        # Verificar si existe en la ruta configurada
        if os.path.exists(FFMPEG_PATH):
            print(f"FFmpeg encontrado en ruta configurada: {FFMPEG_PATH}")
            return FFMPEG_PATH
            
        print("FFmpeg no encontrado")
        return None
    except Exception as e:
        print(f"Error buscando FFmpeg: {e}")
        return None

# Llamar esta función al inicio
FFMPEG_AVAILABLE = check_ffmpeg()


# --------- RUTAS GENERALES ---------
@app.route("/admin_login", methods=["GET", "POST"])
def admin_login():

    if request.method == "POST":
        usuario = request.form.get("usuario")
        password = request.form.get("password")

        # Verificar usuario
        if usuario != ADMIN_USER:
            flash("Usuario incorrecto", "error")
            return redirect("/admin_login")

        # Verificar password con HASH
        if not check_password_hash(ADMIN_PASS_HASH, password):
            flash("Contraseña incorrecta", "error")
            return redirect("/admin_login")

        # Guardar sesión
        session["admin_logged"] = True
        flash("Inicio de sesión exitoso", "success")
        return redirect("/admin_feedback")

    return render_template("login_admin.html")

@app.route("/admin_feedback")
def admin_feedback():

    if not session.get("admin_logged"):
        flash("Acceso restringido. Iniciá sesión.", "error")
        return redirect("/admin_login")

    # Cargar comentarios
    comentarios = []
    if os.path.exists("feedback/comentarios.json"):
        with open("feedback/comentarios.json", "r", encoding="utf-8") as f:
            for linea in f:
                comentarios.append(json.loads(linea.strip()))

    # Cargar estadísticas
    stats = load_stats()

    # Ranking herramientas
    ranking = sorted(stats["tools"].items(), key=lambda x: x[1], reverse=True)

    # Últimos periodos
    daily = sorted(stats["daily"].items())[-7:]        # últimos 7 días
    weekly = sorted(stats["weekly"].items())[-6:]      # últimas semanas
    monthly = sorted(stats["monthly"].items())[-6:]    # últimos 6 meses

    return render_template(
        "admin_feedback.html",
        comentarios=comentarios,
        stats=stats,
        ranking=ranking,
        daily=daily,
        weekly=weekly,
        monthly=monthly
    )

@app.route("/admin_logout")
def admin_logout():
    session.pop("admin_logged", None)
    flash("Sesión cerrada", "success")
    return redirect("/admin_login")

@app.route("/contacto", methods=["GET", "POST"])
def contacto():

    if request.method == "POST":
        nombre = request.form.get("nombre")
        email = request.form.get("email")
        mensaje = request.form.get("mensaje")
        fecha = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        data = {
            "id": str(uuid.uuid4()),
            "nombre": nombre,
            "email": email,
            "mensaje": mensaje,
            "fecha": fecha,
            "leido": False
        }

        # Guarda en JSON
        if not os.path.exists("feedback"):
            os.makedirs("feedback")

        with open("feedback/comentarios.json", "a", encoding="utf-8") as f:
            f.write(json.dumps(data, ensure_ascii=False) + "\n")

        flash("Tu mensaje fue enviado correctamente. ¡Gracias por contactarnos!", "success")
        return redirect("/contacto")

    return render_template("contacto.html")

@app.route("/feedback")
def feedback_redirect():
    return redirect("/contacto")

@app.route("/marcar_leido/<msg_id>")
def marcar_leido(msg_id):

    if not session.get("admin_logged"):
        return redirect("/admin_login")

    mensajes = []

    if os.path.exists("feedback/comentarios.json"):
        with open("feedback/comentarios.json", "r", encoding="utf-8") as f:
            for linea in f:
                mensaje = json.loads(linea.strip())
                if mensaje["id"] == msg_id:
                    mensaje["leido"] = True
                mensajes.append(mensaje)

    # reescribir el archivo completo
    with open("feedback/comentarios.json", "w", encoding="utf-8") as f:
        for m in mensajes:
            f.write(json.dumps(m, ensure_ascii=False) + "\n")

    flash("Mensaje marcado como leído", "success")
    return redirect("/admin_feedback")

@app.route("/eliminar/<msg_id>")
def eliminar_mensaje(msg_id):

    if not session.get("admin_logged"):
        return redirect("/admin_login")

    mensajes = []

    if os.path.exists("feedback/comentarios.json"):
        with open("feedback/comentarios.json", "r", encoding="utf-8") as f:
            for linea in f:
                mensaje = json.loads(linea.strip())
                if mensaje["id"] != msg_id:
                    mensajes.append(mensaje)

    # Reescribir sin ese mensaje
    with open("feedback/comentarios.json", "w", encoding="utf-8") as f:
        for m in mensajes:
            f.write(json.dumps(m, ensure_ascii=False) + "\n")

    flash("Mensaje eliminado", "success")
    return redirect("/admin_feedback")

@app.route("/admin/stats")
def admin_stats():
    stats = load_stats()

    # Ranking herramientas
    ranking = sorted(
        stats["tools"].items(),
        key=lambda x: x[1],
        reverse=True
    )

    return render_template("admin_stats.html",
                           stats=stats,
                           ranking=ranking)



import json, os
from datetime import datetime
from flask import request

# Nombre del archivo donde guardamos las estadísticas
STATS_FILE = "analytics.json"

def load_stats():
    if not os.path.exists(STATS_FILE):
        return {
            "total_visits": 0,
            "daily": {},
            "weekly": {},
            "monthly": {},
            "yearly": {},
            "tools": {},
            "history": []
        }
    with open(STATS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_stats(data):
    with open(STATS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

@app.after_request
def add_header(r):
    r.headers["Cache-Control"] = "public, max-age=86400"
    return r

# ==========================
#    Sintemap
# ==========================
@app.route('/sitemap.xml')
def sitemap():
    return send_from_directory('static', 'sitemap.xml')

# ==========================
#    Robots
# ==========================
@app.route('/robots.txt')
def robots_txt():
    return send_from_directory('static', 'robots.txt')


# ==========================
#    Legalidad
# ==========================
@app.route("/politica-privacidad")
def politica_privacidad():
    return render_template("politica_privacidad.html")


@app.route("/terminos-condiciones")
def terminos_condiciones():
    return render_template("terminos_condiciones.html")


@app.route("/politica-cookies")
def politica_cookies():
    return render_template("politica_cookies.html")

# ==========================
#    Sobre Nosotros
# ==========================
@app.route("/sobre-nosotros")
def sobre_nosotros():
    return render_template("sobre_nosotros.html")


# ==========================
#    🏠 INDEX + CONTADOR
# ==========================
@app.route("/")
def index():

    # =============================
    # 1. Cargar estadísticas
    # =============================
    stats = load_stats()
    now = datetime.now()

    # Formatos
    day = now.strftime("%Y-%m-%d")
    week = now.strftime("%Y-W%U")
    month = now.strftime("%Y-%m")
    year = now.strftime("%Y")

    # =============================
    # 2. Contadores principales
    # =============================
    stats["total_visits"] += 1

    stats["daily"][day] = stats["daily"].get(day, 0) + 1
    stats["weekly"][week] = stats["weekly"].get(week, 0) + 1
    stats["monthly"][month] = stats["monthly"].get(month, 0) + 1
    stats["yearly"][year] = stats["yearly"].get(year, 0) + 1

    # =============================
    # 3. Historial (últimas 50)
    # =============================
    stats["history"].append({
        "date": now.strftime("%Y-%m-%d %H:%M:%S"),
        "ip": request.remote_addr,
        "agent": request.headers.get("User-Agent")
    })

    # Solo guardamos las últimas 50 visitas
    stats["history"] = stats["history"][-50:]

    # Guardamos el archivo
    save_stats(stats)

    # =============================
    # 4. Lista de herramientas
    # =============================
    tools = [
        {"name": "Convertir imagen a JPG", "endpoint": "image_to_jpg"},
        {"name": "Convertir Imagen a PNG", "endpoint": "image_to_png"},
        {"name": "Convertir Imagen a Ícono", "endpoint": "image_to_icon"},
        {"name": "Quitar Fondo de Imagen", "endpoint": "remove_background"},
        {"name": "Comprimir imagen", "endpoint": "compress_image"},
        {"name": "Redimensionar Imagen", "endpoint": "resize_image"},
        {"name": "Convertir PDF a Word", "endpoint": "pdf_to_word"},
        {"name": "Convertir Word a PDF", "endpoint": "word_to_pdf"},
        {"name": "PDF a Imágenes", "endpoint": "pdf_to_images"},
        {"name": "Unir PDFs", "endpoint": "merge_pdfs"},
        {"name": "PDF a Excel (OCR)", "endpoint": "pdf_ocr_excel"},
        {"name": "Dividir PDF", "endpoint": "pdf_split"},
        {"name": "Comprimir PDF", "endpoint": "pdf_compress"},
        {"name": "Generador de QR", "endpoint": "qr_generator"},
        {"name": "Contador de Palabras", "endpoint": "word_counter"},
        {"name": "Generador de Contraseñas", "endpoint": "password_generator"},
        {"name": "Compresor de Video", "endpoint": "video_compress"},
        {"name": "Convertir Video a MP4", "endpoint": "video_to_mp4"},
        {"name": "Convertidor de Audio", "endpoint": "audio_converter"},
        {"name": "Eliminador de Voz (IA)", "endpoint": "vocal_remover"},
        {"name": "Descargador Universal (YouTube/Redes)", "endpoint": "video_downloader"},
    ]

    return render_template("index.html", tools=tools)


# =============================
# Registro de herramientas
# =============================
def register_tool(tool_name):
    stats = load_stats()
    stats["tools"][tool_name] = stats["tools"].get(tool_name, 0) + 1
    save_stats(stats)


@app.route("/download/<path:filename>")
def download_file(filename):
    return send_from_directory(app.config["GENERATED_FOLDER"], filename, as_attachment=True)

@app.route("/download_image_to_pdf/<folder>/<filename>")
def download_image_to_pdf(folder, filename):
    directory = os.path.join("uploads", folder)
    return send_from_directory(directory, filename, as_attachment=True)


# --------- 1) CONVERTIR IMAGEN A JPG ---------
@app.route("/image-to-jpg", methods=["GET", "POST"])
def image_to_jpg():
    register_tool("image_to_jpg")
    if request.method == "POST":
        file = request.files.get("file")
        if not file or file.filename == "":
            flash("Por favor seleccioná una imagen.", "error")
            return redirect(request.url)

        filename = secure_filename(file.filename)
        input_path = os.path.join(app.config["UPLOAD_FOLDER"], filename)
        file.save(input_path)

        try:
            img = Image.open(input_path).convert("RGB")
            out_name = f"{uuid.uuid4().hex}.jpg"
            output_path = os.path.join(app.config["GENERATED_FOLDER"], out_name)
            img.save(output_path, "JPEG")

            flash("Imagen convertida correctamente.", "success")
            return render_template("image_to_jpg.html", download_file=out_name)
        except Exception as e:
            print(e)
            flash("Error al procesar la imagen.", "error")
            return redirect(request.url)

    return render_template("image_to_jpg.html")


# --------- 2) COMPRIMIR IMAGEN ---------
@app.route("/compress-image", methods=["GET", "POST"])
def compress_image():
    register_tool("compress_image")
    if request.method == "POST":
        file = request.files.get("file")
        quality = request.form.get("quality", "60")

        if not file or file.filename == "":
            flash("Por favor seleccioná una imagen.", "error")
            return redirect(request.url)

        try:
            quality = int(quality)
            quality = max(5, min(quality, 95))  # límite de 5 a 95
        except ValueError:
            quality = 60

        filename = secure_filename(file.filename)
        input_path = os.path.join(app.config["UPLOAD_FOLDER"], filename)
        file.save(input_path)

        try:
            img = Image.open(input_path)
            out_ext = img.format.lower() if img.format else "jpg"
            out_name = f"{uuid.uuid4().hex}.{out_ext}"
            output_path = os.path.join(app.config["GENERATED_FOLDER"], out_name)

            img.save(output_path, optimize=True, quality=quality)

            flash(f"Imagen comprimida (calidad {quality}).", "success")
            return render_template("compress_image.html", download_file=out_name)
        except Exception as e:
            print(e)
            flash("Error al comprimir la imagen.", "error")
            return redirect(request.url)

    return render_template("compress_image.html")


# --------- 3) CONVERTIR PDF A WORD ---------
@app.route("/pdf-to-word", methods=["GET", "POST"])
def pdf_to_word():
    register_tool("pdf-to-word")
    if request.method == "POST":
        file = request.files.get("file")
        if not file or file.filename == "":
            flash("Por favor seleccioná un archivo PDF.", "error")
            return redirect(request.url)

        filename = secure_filename(file.filename)
        input_path = os.path.join(app.config["UPLOAD_FOLDER"], filename)
        file.save(input_path)

        if not filename.lower().endswith(".pdf"):
            flash("El archivo debe ser un PDF.", "error")
            return redirect(request.url)

        try:
            out_name = f"{uuid.uuid4().hex}.docx"
            output_path = os.path.join(app.config["GENERATED_FOLDER"], out_name)

            cv = Converter(input_path)
            cv.convert(output_path, start=0, end=None)
            cv.close()

            flash("PDF convertido correctamente a Word.", "success")
            return render_template("pdf_to_word.html", download_file=out_name)
        except Exception as e:
            print(e)
            flash("Error al convertir el PDF. Verificá que el archivo no esté dañado.", "error")
            return redirect(request.url)

    return render_template("pdf_to_word.html")


# --------- 4) UNIR PDFs ---------
@app.route("/merge-pdfs", methods=["GET", "POST"])
def merge_pdfs():
    register_tool("merge-pdfs")
    if request.method == "POST":
        files = request.files.getlist("files")
        pdf_paths = []

        if not files or len(files) == 0 or files[0].filename == "":
            flash("Seleccioná al menos dos PDFs.", "error")
            return redirect(request.url)

        for f in files:
            if f and f.filename.lower().endswith(".pdf"):
                filename = secure_filename(f.filename)
                path = os.path.join(app.config["UPLOAD_FOLDER"], filename)
                f.save(path)
                pdf_paths.append(path)

        if len(pdf_paths) < 2:
            flash("Necesitás al menos dos PDFs válidos.", "error")
            return redirect(request.url)

        try:
            merger = PdfMerger()
            for path in pdf_paths:
                merger.append(path)

            out_name = f"{uuid.uuid4().hex}_merged.pdf"
            output_path = os.path.join(app.config["GENERATED_FOLDER"], out_name)
            merger.write(output_path)
            merger.close()

            flash("PDFs unidos correctamente.", "success")
            return render_template("merge_pdfs.html", download_file=out_name)
        except Exception as e:
            print(e)
            flash("Error al unir los PDFs.", "error")
            return redirect(request.url)

    return render_template("merge_pdfs.html")


# --------- 5) GENERADOR DE CÓDIGO QR ---------
@app.route("/qr-generator", methods=["GET", "POST"])
def qr_generator():
    register_tool("qr-generator")
    if request.method == "POST":
        text = request.form.get("text", "").strip()
        if not text:
            flash("Ingresá un texto o URL para generar el QR.", "error")
            return redirect(request.url)

        try:
            img = qrcode.make(text)
            out_name = f"{uuid.uuid4().hex}.png"
            output_path = os.path.join(app.config["GENERATED_FOLDER"], out_name)
            img.save(output_path)

            flash("Código QR generado correctamente.", "success")
            return render_template("qr_generator.html", image_file=out_name)
        except Exception as e:
            print(e)
            flash("Error al generar el QR.", "error")
            return redirect(request.url)

    return render_template("qr_generator.html")


# --------- 6) CONVERTIR WORD A PDF ---------

@app.route("/word-to-pdf", methods=["GET", "POST"])
def word_to_pdf():
    register_tool("word-to-pdf")
    if request.method == "POST":
        file = request.files.get("file")

        if not file or file.filename == "":
            flash("Por favor seleccioná un archivo .docx", "error")
            return redirect(request.url)

        filename = secure_filename(file.filename)
        if not filename.lower().endswith(".docx"):
            flash("El archivo debe ser un documento .docx", "error")
            return redirect(request.url)

        input_path = os.path.join(app.config["UPLOAD_FOLDER"], filename)
        file.save(input_path)

        try:
            out_name = f"{uuid.uuid4().hex}.pdf"
            output_path = os.path.join(app.config["GENERATED_FOLDER"], out_name)

            # Conversión (Word → PDF)
            convert(input_path, output_path)

            flash("Documento convertido correctamente.", "success")
            return render_template("word_to_pdf.html", download_file=out_name)

        except Exception as e:
            print(e)
            flash("Error al convertir el archivo. Verificá que el .docx no esté dañado.", "error")
            return redirect(request.url)

    return render_template("word_to_pdf.html")


# --------- 7) PDF A IMÁGENES ---------
@app.route("/pdf-to-images", methods=["GET", "POST"])
def pdf_to_images():
    register_tool("pdf-to-images")
    if request.method == "POST":
        file = request.files.get("file")

        if not file or file.filename == "":
            flash("Por favor seleccioná un PDF.", "error")
            return redirect(request.url)

        filename = secure_filename(file.filename)

        if not filename.lower().endswith(".pdf"):
            flash("El archivo debe ser un PDF válido.", "error")
            return redirect(request.url)

        input_path = os.path.join(app.config["UPLOAD_FOLDER"], filename)
        file.save(input_path)

        try:
            out_images = []
            poppler_path = r"C:\poppler\Library\bin"  # ← CAMBIAR si lo instalaste en otra ruta

            pages = convert_from_path(input_path, dpi=200, poppler_path=poppler_path)

            for i, page in enumerate(pages):
                out_name = f"{uuid.uuid4().hex}_page_{i+1}.jpg"
                output_path = os.path.join(app.config["GENERATED_FOLDER"], out_name)
                page.save(output_path, "JPEG")
                out_images.append(out_name)

            flash("PDF convertido correctamente en imágenes.", "success")
            return render_template("pdf_to_images.html", images=out_images)

        except Exception as e:
            print(e)
            flash("Error al convertir el PDF. Verificá que el archivo no esté dañado.", "error")
            return redirect(request.url)

    return render_template("pdf_to_images.html")


# --------- 8) CONTADOR DE PALABRAS ---------
@app.route("/word-counter", methods=["GET", "POST"])
def word_counter():
    register_tool("word-counter")
    text = ""
    result = None
    error = None

    try:
        if request.method == "POST":
            text = request.form.get("text", "").strip()

            # Validaciones
            if not text:
                flash("❌ Ingresá algún texto para analizar.", "error")
                return render_template("word_counter.html", text=text, result=None)
            
            if len(text) > 10000:  # Límite de caracteres
                flash("⚠️ El texto es demasiado largo (máximo 10,000 caracteres).", "warning")
                return render_template("word_counter.html", text=text, result=None)

            # Procesamiento mejorado
            words = len(re.findall(r'\b\w+\b', text))  # Mejor detección de palabras
            characters = len(text)
            characters_no_spaces = len(text.replace(" ", ""))
            lines = len([line for line in text.split('\n') if line.strip()]) or 1
            paragraphs = len([p for p in text.split('\n\n') if p.strip()])
            
            # Estadísticas adicionales
            sentences = len(re.findall(r'[.!?]+', text))
            avg_word_length = round(characters_no_spaces / words, 2) if words > 0 else 0
            avg_words_per_sentence = round(words / sentences, 2) if sentences > 0 else 0
            
            # Palabras únicas
            words_list = re.findall(r'\b\w+\b', text.lower())
            unique_words = len(set(words_list))
            
            # Palabra más común
            word_freq = Counter(words_list)
            most_common_word = word_freq.most_common(1)[0] if word_freq else ("", 0)

            result = {
                "words": words,
                "characters": characters,
                "characters_no_spaces": characters_no_spaces,
                "lines": lines,
                "paragraphs": paragraphs,
                "sentences": sentences,
                "unique_words": unique_words,
                "avg_word_length": avg_word_length,
                "avg_words_per_sentence": avg_words_per_sentence,
                "most_common_word": most_common_word[0],
                "most_common_word_count": most_common_word[1],
                "reading_time": round(words / 200, 1),  # Tiempo lectura aprox (200 palabras/min)
                "speaking_time": round(words / 150, 1)   # Tiempo habla aprox (150 palabras/min)
            }

    except Exception as e:
        error = f"Error procesando el texto: {str(e)}"
        flash("❌ Ocurrió un error al procesar el texto.", "error")
        # Log the error for debugging
        print(f"Error en word_counter: {e}")

    return render_template("word_counter.html", 
                         text=text, 
                         result=result, 
                         error=error)

# --------- 9) GENERADOR DE CONTRASEÑAS ---------

@app.route("/password-generator", methods=["GET", "POST"])
def password_generator():
    register_tool("password-generator")
    generated_password = None

    if request.method == "POST":
        length = request.form.get("length", 12)
        use_upper = "upper" in request.form
        use_numbers = "numbers" in request.form
        use_symbols = "symbols" in request.form

        try:
            length = int(length)
            length = max(4, min(length, 50))  # límites 4 a 50
        except:
            length = 12

        # Caracteres posibles
        chars = string.ascii_lowercase

        if use_upper:
            chars += string.ascii_uppercase
        if use_numbers:
            chars += string.digits
        if use_symbols:
            chars += "!@#$%^&*()-_=+[]{};:,.?/"

        # Generar contraseña
        if chars:
            generated_password = ''.join(random.choice(chars) for _ in range(length))

    return render_template("password_generator.html", password=generated_password)

# --------- 10) CONVERTIR IMAGEN A PNG ---------

@app.route("/image-to-png", methods=["GET", "POST"])
def image_to_png():
    register_tool("image-to-png")
    if request.method == "POST":
        file = request.files.get("file")

        if not file or file.filename == "":
            flash("Seleccioná una imagen para convertir.", "error")
            return redirect(request.url)

        filename = secure_filename(file.filename)
        input_path = os.path.join(app.config["UPLOAD_FOLDER"], filename)
        file.save(input_path)

        try:
            img = Image.open(input_path)

            # Convertir a PNG siempre en modo RGB o RGBA
            if img.mode in ("P", "RGBA", "RGB"):
                pass
            else:
                img = img.convert("RGB")

            out_name = f"{uuid.uuid4().hex}.png"
            output_path = os.path.join(app.config["GENERATED_FOLDER"], out_name)
            img.save(output_path, "PNG")

            flash("Imagen convertida correctamente a PNG.", "success")
            return render_template("image_to_png.html", download_file=out_name)

        except Exception as e:
            print(e)
            flash("Error al convertir la imagen.", "error")
            return redirect(request.url)

    return render_template("image_to_png.html")

# --------- 11) CONVERTIR IMAGEN A ÍCONO (.ICO) ---------

@app.route("/image-to-icon", methods=["GET", "POST"])
def image_to_icon():
    register_tool("image-to-icon")
    if request.method == "POST":
        file = request.files.get("file")
        size = request.form.get("size", "256")

        if not file or file.filename == "":
            flash("Seleccioná una imagen para convertir.", "error")
            return redirect(request.url)

        # Validar tamaño
        try:
            size = int(size)
            if size not in [16, 32, 48, 64, 128, 256, 512]:
                size = 256
        except:
            size = 256

        filename = secure_filename(file.filename)
        input_path = os.path.join(app.config["UPLOAD_FOLDER"], filename)
        file.save(input_path)

        try:
            img = Image.open(input_path)

            # Convertir siempre a RGBA (íconos lo requieren)
            img = img.convert("RGBA")

            # Redimensionar a tamaño seleccionado
            img = img.resize((size, size))

            out_name = f"{uuid.uuid4().hex}.ico"
            output_path = os.path.join(app.config["GENERATED_FOLDER"], out_name)

            img.save(output_path, format="ICO")

            flash("Ícono generado correctamente.", "success")
            return render_template("image_to_icon.html", download_file=out_name)

        except Exception as e:
            print(e)
            flash("Error al convertir la imagen a ícono.", "error")
            return redirect(request.url)

    return render_template("image_to_icon.html")


# --------- 12) QUITAR FONDO DE IMAGEN ---------
@app.route("/remove-background", methods=["GET", "POST"])
def remove_background():
    register_tool("remove-background")
    if request.method == "POST":

        file = request.files.get("file")
        if not file or file.filename == "":
            flash("Seleccioná una imagen para procesar.", "error")
            return redirect(request.url)

        try:
            # Guardar entrada
            filename = secure_filename(file.filename)
            input_path = os.path.join(app.config["UPLOAD_FOLDER"], filename)
            file.save(input_path)

            # Leer bytes
            with open(input_path, "rb") as i:
                input_data = i.read()

            # 🔥 IA de eliminación con modelo ya cargado (rápido)
            output_data = remove(input_data, session=BG_MODEL)

            # Nombre de salida
            out_name = f"{uuid.uuid4().hex}_nofondo.png"
            output_path = os.path.join(app.config["GENERATED_FOLDER"], out_name)

            # Guardar imagen final
            with open(output_path, "wb") as o:
                o.write(output_data)

            # Limpieza automática del archivo original
            try:
                os.remove(input_path)
            except:
                pass

            flash("Fondo eliminado correctamente.", "success")
            return render_template("remove_background.html", download_file=out_name)

        except Exception as e:
            print("❌ ERROR en Quitar Fondo:", e)
            flash("Ocurrió un error al procesar la imagen. Probá con otra.", "error")
            return redirect(request.url)

    return render_template("remove_background.html")


# --------- 13) PDF A EXCEL (CON OCR DEFINITIVO) ---------

@app.route("/pdf-ocr-excel", methods=["GET", "POST"])
def pdf_ocr_excel():
    register_tool("pdf-ocr-excel")
    if request.method == "POST":
        file = request.files.get("file")

        if not file or file.filename == "":
            flash("Subí un archivo PDF.", "error")
            return redirect(request.url)

        filename = secure_filename(file.filename)
        if not filename.lower().endswith(".pdf"):
            flash("El archivo debe ser un PDF válido.", "error")
            return redirect(request.url)

        input_path = os.path.join(app.config["UPLOAD_FOLDER"], filename)
        file.save(input_path)

        try:
            # Convertir PDF a imágenes
            pages = convert_from_path(input_path, dpi=300, poppler_path=r"C:/poppler/Library/bin")

            dataframes = []
            for page in pages:
                # OCR
                ocr_text = pytesseract.image_to_string(page)

                # Convertir a tabla simple por líneas
                rows = [line.strip().split() for line in ocr_text.split("\n") if line.strip()]

                if rows:
                    df = pd.DataFrame(rows)
                    dataframes.append(df)

            if not dataframes:
                flash("No se pudo extraer ninguna tabla del PDF.", "error")
                return redirect(request.url)

            # Guardar a Excel
            out_name = f"{uuid.uuid4().hex}_ocr.xlsx"
            output_path = os.path.join(app.config["GENERATED_FOLDER"], out_name)

            with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
                for i, df in enumerate(dataframes):
                    df.to_excel(writer, sheet_name=f"Pagina_{i+1}", index=False)

            flash("PDF convertido a Excel con OCR exitosamente.", "success")
            return render_template("pdf_ocr_excel.html", download_file=out_name)

        except Exception as e:
            print("ERROR:", e)
            flash("Error al procesar el PDF con OCR.", "error")
            return redirect(request.url)

    return render_template("pdf_ocr_excel.html")


# --------- 14) DIVIDIR PDF: TODO EN UNO ---------

pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

@app.route("/pdf-split", methods=["GET", "POST"])
def pdf_split():
    register_tool("pdf-split")
    if request.method == "POST":
        file = request.files.get("file")
        mode = request.form.get("mode", "all")
        pages_input = request.form.get("pages", "")

        if not file or file.filename == "":
            flash("Subí un archivo PDF.", "error")
            return redirect(request.url)

        filename = secure_filename(file.filename)
        if not filename.lower().endswith(".pdf"):
            flash("El archivo debe ser un PDF.", "error")
            return redirect(request.url)

        input_path = os.path.join(app.config["UPLOAD_FOLDER"], filename)
        file.save(input_path)

        try:
            reader = PdfReader(input_path)
            total_pages = len(reader.pages)
            generated_files = []

            # --- MODO 1: TODAS LAS PÁGINAS ---
            if mode == "all":
                for i in range(total_pages):
                    writer = PdfWriter()
                    writer.add_page(reader.pages[i])

                    out_name = f"{uuid.uuid4().hex}_page_{i+1}.pdf"
                    output_path = os.path.join(app.config["GENERATED_FOLDER"], out_name)

                    with open(output_path, "wb") as out_pdf:
                        writer.write(out_pdf)

                    generated_files.append(out_name)

            # --- MODO 2: PÁGINAS ESPECÍFICAS ---
            else:
                raw = pages_input.replace(" ", "")

                # Soportar:
                # 1,3,9
                # 1-3, 5, 7-10
                pattern = r'(\d+-\d+|\d+)'
                matches = re.findall(pattern, raw)

                pages_to_extract = []

                for m in matches:
                    if "-" in m:
                        start, end = m.split("-")
                        start = int(start)
                        end = int(end)
                        pages_to_extract.extend(range(start, end + 1))
                    else:
                        pages_to_extract.append(int(m))

                # Eliminar repetidos y valores inválidos
                pages_to_extract = sorted(set([
                    p for p in pages_to_extract if 1 <= p <= total_pages
                ]))

                if not pages_to_extract:
                    flash("No se ingresaron páginas válidas.", "error")
                    return redirect(request.url)

                # Crear un PDF por cada página seleccionada
                for p in pages_to_extract:
                    writer = PdfWriter()
                    writer.add_page(reader.pages[p - 1])

                    out_name = f"{uuid.uuid4().hex}_page_{p}.pdf"
                    output_path = os.path.join(app.config["GENERATED_FOLDER"], out_name)

                    with open(output_path, "wb") as out_pdf:
                        writer.write(out_pdf)

                    generated_files.append(out_name)

            flash("PDF dividido correctamente.", "success")
            return render_template("pdf_split.html", files=generated_files)

        except Exception as e:
            print("ERROR:", e)
            flash("Error al dividir el PDF.", "error")
            return redirect(request.url)

    return render_template("pdf_split.html", files=None)


# --------- 15) COMPRESOR DE PDF ---------
GS_PATH = r"C:\Program Files\gs\gs10.06.0\bin\gswin64c.exe"


@app.route("/pdf-compress", methods=["GET", "POST"])
def pdf_compress():
    register_tool("pdf-compress")
    if request.method == "POST":
        file = request.files.get("file")
        quality = request.form.get("quality", "medium")

        if not file or file.filename == "":
            flash("Subí un archivo PDF.", "error")
            return redirect(request.url)

        filename = secure_filename(file.filename)
        if not filename.lower().endswith(".pdf"):
            flash("Debe ser un archivo PDF.", "error")
            return redirect(request.url)

        input_path = os.path.join(app.config["UPLOAD_FOLDER"], filename)
        file.save(input_path)

        out_name = f"{uuid.uuid4().hex}_compressed.pdf"
        output_path = os.path.join(app.config["GENERATED_FOLDER"], out_name)

        # Calidad de compresión
        QUALITY_MAP = {
            "low": "/screen",       # Más comprimido, menor calidad
            "medium": "/ebook",     # Equilibrado
            "high": "/printer"      # Mejor calidad, menos compresión
        }

        gs_quality = QUALITY_MAP.get(quality, "/ebook")

        try:
            # Ejecutar Ghostscript
            gs_cmd = [
                GS_PATH,
                "-sDEVICE=pdfwrite",
                "-dCompatibilityLevel=1.4",
                f"-dPDFSETTINGS={gs_quality}",
                "-dNOPAUSE",
                "-dQUIET",
                "-dBATCH",
                f"-sOutputFile={output_path}",
                input_path
            ]

            subprocess.run(gs_cmd, check=True)

            flash("PDF comprimido correctamente.", "success")
            return render_template("pdf_compress.html", download_file=out_name)

        except Exception as e:
            print("ERROR COMPRESS:", e)
            flash("Error al comprimir el PDF. Verificá la instalación de Ghostscript.", "error")
            return redirect(request.url)

    return render_template("pdf_compress.html")


# --------- 16) COMPRESOR DE VIDEO (VERSIÓN PRO MAX) ---------
def get_video_duration(path):
    register_tool("video-compress")
    cmd = [
        FFPROBE_PATH,
        "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        path
    ]
    result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        return float(result.stdout.strip())
    except:
        return None

@app.route("/video-compress", methods=["GET", "POST"])
def video_compress():
    register_tool("video-compress")
    if request.method == "POST":
        file = request.files.get("file")
        preset = request.form.get("preset")

        if not file or file.filename == "":
            flash("Subí un archivo de video válido.", "error")
            return redirect(request.url)

        filename = secure_filename(file.filename)
        ext = filename.lower().split(".")[-1]
        if ext not in ["mp4", "mov", "avi", "mkv", "webm"]:
            flash("Formato inválido.", "error")
            return redirect(request.url)

        # Guardar video
        input_path = os.path.join(app.config["UPLOAD_FOLDER"], filename)
        file.save(input_path)

        output_name = f"{uuid.uuid4().hex}_compressed.mp4"
        
        output_path = os.path.join(app.config["GENERATED_FOLDER"], output_name)

        # Duración del video
        duration = get_video_duration(input_path)
        if duration is None:
            flash("No se pudo leer la duración del video.", "error")
            return redirect(request.url)

        # BASE FFmpeg
        cmd = [FFMPEG_PATH, "-i", input_path, "-preset", "medium"]

        # 🎯 PRESETS PRO
        if preset == "low":
            cmd += ["-vcodec", "libx264", "-crf", "32", "-b:v", "800k", "-maxrate", "800k",
                    "-vf", "scale=640:-1", "-b:a", "96k"]

        elif preset == "medium":
            cmd += ["-vcodec", "libx264", "-crf", "28", "-b:v", "1500k", "-maxrate", "1500k",
                    "-vf", "scale=720:-1", "-b:a", "96k"]

        elif preset == "high":
            cmd += ["-vcodec", "libx264", "-crf", "23", "-b:v", "2500k", "-maxrate", "2500k",
                    "-vf", "scale=1080:-1", "-b:a", "128k"]

        # 🟦 WHATSAPP (16 MB)
        elif preset == "whatsapp":
            target_size_mb = 16
            target_bitrate = (target_size_mb * 8192) / duration
            target_bitrate = max(target_bitrate, 300)  # evitar 0

            cmd += [
                "-vcodec", "libx264",
                "-b:v", f"{int(target_bitrate)}k",
                "-maxrate", f"{int(target_bitrate)}k",
                "-bufsize", "3000k",
                "-vf", "scale=720:-1",
                "-b:a", "64k"
            ]

        # 🟪 INSTAGRAM REELS
        elif preset == "reels":
            cmd += [
                "-vcodec", "libx264",
                "-b:v", "4500k",
                "-maxrate", "5000k",
                "-vf", "scale=1080:1920",
                "-b:a", "128k"
            ]

        # 🟡 TIKTOK
        elif preset == "tiktok":
            cmd += [
                "-vcodec", "libx264",
                "-b:v", "2500k",
                "-maxrate", "3000k",
                "-vf", "scale=720:-1",
                "-b:a", "96k"
            ]

        # 🔴 TAMAÑO OBJETIVO
        elif preset == "target":
            target_mb = int(request.form.get("target_size"))
            target_bitrate = (target_mb * 8192) / duration
            target_bitrate = max(target_bitrate, 300)

            cmd += [
                "-vcodec", "libx264",
                "-b:v", f"{int(target_bitrate)}k",
                "-maxrate", f"{int(target_bitrate)}k",
                "-bufsize", "3000k",
                "-vf", "scale=720:-1",
                "-b:a", "96k"
            ]

        # SALIDA
        cmd.append(output_path)

        try:
            subprocess.run(cmd, check=True)
            flash("Video comprimido correctamente.", "success")
            return render_template("video_compress.html", download_file=output_name)
        except Exception as e:
            print("ERROR:", e)
            flash("Error al comprimir el video.", "error")
            return redirect(request.url)

    return render_template("video_compress.html")


# --------- 17) CONVERTIR VIDEO A MP4 ---------
def get_video_duration(path):
    register_tool("video-to-mp4")
    """Devuelve la duración del video en segundos"""
    result = subprocess.run(
        [FFPROBE_PATH, "-v", "error", "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1", path],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )

    return float(result.stdout.strip())


@app.route("/video-to-mp4", methods=["GET", "POST"])
def video_to_mp4():
    register_tool("video-to-mp4")
    download_url = None

    if request.method == "POST":
        if "file" not in request.files:
            flash("No se subió ningún archivo.", "error")
            return redirect(request.url)

        file = request.files["file"]
        if file.filename == "":
            flash("Seleccioná un archivo válido.", "error")
            return redirect(request.url)

        # Guardar archivo temporal
        input_filename = secure_filename(file.filename)
        input_path = os.path.join(app.config["UPLOAD_FOLDER"], input_filename)
        file.save(input_path)

        # Archivo MP4 convertido → SIEMPRE a GENERATED_FOLDER ✔️
        output_filename = input_filename.rsplit(".", 1)[0] + "_convertido.mp4"
        output_path = os.path.join(app.config["GENERATED_FOLDER"], output_filename)

        # Comando FFmpeg — solo convertir a MP4
        cmd = [
            FFMPEG_PATH, "-y",
            "-i", input_path,
            "-vcodec", "libx264",
            "-acodec", "aac",
            "-preset", "medium",
            "-movflags", "+faststart",
            output_path
        ]

        try:
            subprocess.run(cmd, check=True)
            flash("El video fue convertido correctamente.", "success")
            download_url = url_for("download_file", filename=output_filename)

        except Exception as e:
            flash("Error al convertir el video.", "error")
            print("FFMPEG ERROR:", e)

        return render_template("video_to_mp4.html", download_url=download_url)

    return render_template("video_to_mp4.html", download_url=None)


@app.errorhandler(RequestEntityTooLarge)
def too_large(e):
    register_tool("video-to-mp4")
    flash("El video supera el tamaño máximo permitido (1GB).", "error")
    return redirect(request.url)

# ------------ 18) AUDIO CONVERTER (FFMPEG)  ------------
@app.route("/audio_converter", methods=["GET", "POST"])
def audio_converter():
    register_tool("audio-converter")
    if request.method == "POST":
        try:
            if "audio_file" not in request.files:
                flash("No se subió ningún archivo.", "error")
                return redirect(request.url)

            file = request.files["audio_file"]

            if file.filename == "":
                flash("Seleccioná un archivo válido.", "error")
                return redirect(request.url)

            # Guardar archivo temporal
            filename = secure_filename(file.filename)
            input_path = os.path.join(app.config["UPLOAD_FOLDER"], filename)
            file.save(input_path)

            # Opciones del formulario
            output_format = request.form.get("format", "mp3")
            bitrate = request.form.get("bitrate", "192k")  # Default 192k

            # Nombre de salida único
            out_name = f"{uuid.uuid4().hex}_converted.{output_format}"
            output_path = os.path.join(app.config["GENERATED_FOLDER"], out_name)

            # Ruta FFmpeg (Idealmente usar variable de entorno, pero mantenemos compatibilidad por ahora)
            ffmpeg_path = r"C:\ffmpeg-8.0-full_build\bin\ffmpeg.exe"

            # Construir comando
            cmd = [ffmpeg_path, "-y", "-i", input_path, "-vn"]

            # Configuración por formato
            if output_format == "mp3":
                cmd.extend(["-acodec", "libmp3lame", "-b:a", bitrate])
            elif output_format == "aac":
                cmd.extend(["-acodec", "aac", "-b:a", bitrate])
            elif output_format == "wav":
                cmd.extend(["-acodec", "pcm_s16le"]) # WAV no usa bitrate comprimido
            elif output_format == "ogg":
                cmd.extend(["-acodec", "libvorbis", "-b:a", bitrate])
            elif output_format == "m4a":
                cmd.extend(["-acodec", "aac", "-b:a", bitrate])
            elif output_format == "flac":
                cmd.extend(["-acodec", "flac"])

            cmd.append(output_path)

            # Verificar si el archivo tiene streams de audio
            try:
                probe_cmd = [
                    FFPROBE_PATH,
                    "-v", "error",
                    "-select_streams", "a",
                    "-show_entries", "stream=index",
                    "-of", "csv=p=0",
                    input_path
                ]
                probe_result = subprocess.run(probe_cmd, capture_output=True, text=True)
                if not probe_result.stdout.strip():
                    flash("El archivo seleccionado no contiene ninguna pista de audio.", "error")
                    return redirect(request.url)
            except Exception as e:
                print(f"Error verificando audio: {e}")
                # Si falla la verificación, intentamos convertir igual por si acaso

            # Ejecutar conversión
            result = subprocess.run(cmd, capture_output=True, text=True)

            if result.returncode != 0:
                error_msg = result.stderr
                print(f"FFmpeg Error: {error_msg}")
                # Mostrar error técnico simplificado si es otro tipo de fallo
                if "does not contain any stream" in error_msg:
                     flash("El archivo no contiene datos de audio válidos.", "error")
                else:
                     flash(f"Error en la conversión: {error_msg[-100:]}", "error")
                return redirect(request.url)

            # Limpiar archivo de entrada
            try:
                os.remove(input_path)
            except:
                pass

            flash("Conversión completada con éxito.", "success")
            
            # En lugar de descargar directo, mostramos la página con el botón de descarga (mejor UX)
            # O podemos descargar directo si el usuario prefiere. 
            # Para mantener consistencia con otros módulos, renderizamos template con download_file
            return render_template("audio_converter.html", download_file=out_name)

        except Exception as e:
            print(f"Error: {str(e)}")
            flash(f"Ocurrió un error inesperado: {str(e)}", "error")
            return redirect(request.url)

    return render_template("audio_converter.html")

# ================================
# 19) ELIMINADOR DE VOZ (VOCAL REMOVER) - VERSIÓN MEJORADA
# ================================
@app.route("/vocal_remover", methods=["GET", "POST"])
def vocal_remover():
    register_tool("vocal-remover")
    if request.method == "POST":
        try:
            if "audio_file" not in request.files:
                flash("No se subió ningún archivo.", "error")
                return redirect(request.url)

            file = request.files["audio_file"]
            if file.filename == "":
                flash("Seleccioná un archivo válido.", "error")
                return redirect(request.url)

            # Validar tipo de archivo
            allowed_extensions = {'.wav', '.mp3', '.flac', '.aiff', '.aac', '.m4a'}
            file_ext = os.path.splitext(file.filename)[1].lower()
            if file_ext not in allowed_extensions:
                flash(f"Formato no soportado. Usá: {', '.join(allowed_extensions)}", "error")
                return redirect(request.url)

            # Guardar archivo
            filename = secure_filename(file.filename)
            unique_id = uuid.uuid4().hex
            input_filename = f"{unique_id}_{filename}"
            input_path = os.path.join(app.config["UPLOAD_FOLDER"], input_filename)
            file.save(input_path)

            # Verificar que el archivo se guardó correctamente
            if not os.path.exists(input_path) or os.path.getsize(input_path) == 0:
                flash("Error al guardar el archivo.", "error")
                return redirect(request.url)

            # Crear carpeta de salida
            output_dir = os.path.join(app.config["GENERATED_FOLDER"], unique_id)
            os.makedirs(output_dir, exist_ok=True)

            # Configurar entorno para FFmpeg
            ffmpeg_dir = os.path.dirname(FFMPEG_PATH)
            current_env = os.environ.copy()
            if ffmpeg_dir not in current_env["PATH"]:
                current_env["PATH"] = ffmpeg_dir + os.pathsep + current_env["PATH"]

            # Comando Demucs mejorado
            wrapper_path = os.path.join(BASE_DIR, "run_demucs_wrapper.py")
            
            cmd = [
                sys.executable, wrapper_path,
                "--two-stems=vocals",
                "-n", "htdemucs",
                "-o", output_dir,
                "--mp3",  # Convertir a MP3 para ahorrar espacio
                input_path
            ]

            # Ejecutar con timeout
            try:
                result = subprocess.run(
                    cmd, 
                    capture_output=True, 
                    text=True, 
                    env=current_env,
                    timeout=3600  # 1 hora timeout (CPU puede ser lento)
                )
            except subprocess.TimeoutExpired:
                flash("El proceso tardó demasiado tiempo. Intentá con un archivo más corto.", "error")
                # Limpieza
                if os.path.exists(input_path):
                    os.remove(input_path)
                if os.path.exists(output_dir):
                    shutil.rmtree(output_dir)
                return redirect(request.url)

            # Logging mejorado
            log_file = os.path.join(BASE_DIR, "debug_demucs.txt")
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(f"Timestamp: {uuid.uuid4()}\n")
                f.write(f"Input file: {input_filename}\n")
                f.write(f"Command: {' '.join(cmd)}\n")
                f.write(f"Return Code: {result.returncode}\n")
                f.write(f"Stdout: {result.stdout}\n")
                f.write(f"Stderr: {result.stderr}\n")
                f.write("-" * 50 + "\n")

            if result.returncode != 0:
                error_msg = "Error al procesar el audio."
                if "CUDA out of memory" in result.stderr:
                    error_msg += " Memoria de GPU insuficiente. Intentá con un archivo más corto."
                elif "No such file or directory" in result.stderr:
                    error_msg += " Archivo no encontrado."
                
                flash(f"{error_msg} Revisá debug_demucs.txt para más detalles.", "error")
                return redirect(request.url)

            # Buscar archivos resultantes
            track_name = os.path.splitext(input_filename)[0]
            result_folder = os.path.join(output_dir, "htdemucs", track_name)

            if not os.path.exists(result_folder):
                flash("No se pudieron generar los archivos separados.", "error")
                return redirect(request.url)

            # Archivos generados
            vocals_path = os.path.join(result_folder, "vocals.mp3")
            accompaniment_path = os.path.join(result_folder, "no_vocals.mp3")

            new_vocals_name = f"{unique_id}_vocals.mp3"
            new_acc_name = f"{unique_id}_instrumental.mp3"
            final_vocals_path = os.path.join(app.config["GENERATED_FOLDER"], new_vocals_name)
            final_acc_path = os.path.join(app.config["GENERATED_FOLDER"], new_acc_name)

            # Mover archivos
            files_generated = False
            if os.path.exists(vocals_path):
                shutil.move(vocals_path, final_vocals_path)
                files_generated = True
            
            if os.path.exists(accompaniment_path):
                shutil.move(accompaniment_path, final_acc_path)
                files_generated = True

            if not files_generated:
                flash("No se pudieron generar los archivos separados.", "error")
                return redirect(request.url)

            # Limpieza
            try:
                if os.path.exists(input_path):
                    os.remove(input_path)
                if os.path.exists(output_dir):
                    shutil.rmtree(output_dir)
            except Exception as cleanup_error:
                print(f"Error en limpieza: {cleanup_error}")

            flash("¡Separación completada con éxito! Descargá los archivos a continuación.", "success")
            return render_template("vocal_remover.html", 
                                 vocals_file=new_vocals_name, 
                                 accompaniment_file=new_acc_name)

        except Exception as e:
            print(f"Error: {e}")
            flash(f"Error inesperado: {str(e)}", "error")
            # Limpieza en caso de error
            try:
                if 'input_path' in locals() and os.path.exists(input_path):
                    os.remove(input_path)
                if 'output_dir' in locals() and os.path.exists(output_dir):
                    shutil.rmtree(output_dir)
            except:
                pass
            return redirect(request.url)

    return render_template("vocal_remover.html")

# ================================
# 20) DESCARGADOR DE VIDEO/AUDIO (YT-DLP) - CORREGIDO
# ================================
@app.route("/video_downloader", methods=["GET", "POST"])
def video_downloader():
    register_tool("video-downloader")
    if request.method == "POST":
        url = request.form.get("url", "").strip()
        fmt = request.form.get("format", "video")

        if not url:
            flash("Por favor, ingresá una URL válida.", "error")
            return redirect(url_for('video_downloader'))

        unique_id = uuid.uuid4().hex
        temp_dir = None
        downloaded_path = None
        
        try:
            # Crear directorio temporal manualmente para mejor control
            temp_dir = tempfile.mkdtemp()
            
            # CONFIGURACIÓN MEJORADA
            if fmt == "video":
                if FFMPEG_AVAILABLE:
                    opts = {
                        "format": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
                        "outtmpl": os.path.join(temp_dir, f"{unique_id}_%(title)s.%(ext)s"),
                        "merge_output_format": "mp4",
                        "ffmpeg_location": FFMPEG_AVAILABLE,
                    }
                else:
                    opts = {
                        "format": "best[ext=mp4]/best",
                        "outtmpl": os.path.join(temp_dir, f"{unique_id}_%(title)s.%(ext)s"),
                    }
            else:
                if FFMPEG_AVAILABLE:
                    opts = {
                        "format": "bestaudio/best",
                        "outtmpl": os.path.join(temp_dir, f"{unique_id}_%(title)s.%(ext)s"),
                        "ffmpeg_location": FFMPEG_AVAILABLE,
                        "postprocessors": [
                            {
                                "key": "FFmpegExtractAudio",
                                "preferredcodec": "mp3",
                                "preferredquality": "192",
                            }
                        ]
                    }
                else:
                    opts = {
                        "format": "bestaudio[ext=m4a]/bestaudio/best",
                        "outtmpl": os.path.join(temp_dir, f"{unique_id}_%(title)s.%(ext)s"),
                    }

            # CONFIGURACIÓN COMÚN
            opts.update({
                "noplaylist": True,
                "quiet": True,
                "no_warnings": True,
                "ignoreerrors": False,
                "restrictfilenames": True,
            })

            # DESCARGA
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=True)

                if info is None:
                    flash("No se pudo obtener la información del video. Probá con otra URL.", "error")
                    return redirect(url_for("video_downloader"))

                # Obtener el archivo descargado
                downloaded_path = ydl.prepare_filename(info)
                
                if fmt == "audio" and FFMPEG_AVAILABLE:
                    base, _ = os.path.splitext(downloaded_path)
                    downloaded_path = base + ".mp3"

            # Verificar que el archivo existe
            if not os.path.exists(downloaded_path):
                # Buscar cualquier archivo que comience con el unique_id
                for file in os.listdir(temp_dir):
                    if file.startswith(unique_id):
                        downloaded_path = os.path.join(temp_dir, file)
                        break
                else:
                    flash("Ocurrió un problema al generar el archivo de salida.", "error")
                    return redirect(url_for("video_downloader"))

            # Obtener nombre seguro para el archivo
            original_title = info.get('title', 'video')
            safe_title = "".join(c for c in original_title if c.isalnum() or c in (' ', '-', '_')).rstrip()
            
            if fmt == "video":
                download_name = f"{safe_title}.mp4"
            else:
                download_name = f"{safe_title}.mp3"

            # **SOLUCIÓN: Copiar el archivo a un lugar seguro antes de enviar**
            safe_copy_path = os.path.join(app.config["GENERATED_FOLDER"], f"{unique_id}_{download_name}")
            shutil.copy2(downloaded_path, safe_copy_path)

            # **LIMPIAR ARCHIVO TEMPORAL INMEDIATAMENTE**
            try:
                if os.path.exists(downloaded_path):
                    os.remove(downloaded_path)
            except Exception as e:
                print(f"⚠️  No se pudo eliminar archivo temporal: {e}")

            # Enviar desde la copia segura
            response = send_file(
                safe_copy_path, 
                as_attachment=True, 
                download_name=download_name,
                mimetype='application/octet-stream'
            )

            # **LIMPIAR LA COPIA SEGURA DESPUÉS DE ENVIAR**
            @response.call_on_close
            def cleanup():
                try:
                    if os.path.exists(safe_copy_path):
                        os.remove(safe_copy_path)
                    if temp_dir and os.path.exists(temp_dir):
                        shutil.rmtree(temp_dir, ignore_errors=True)
                except Exception as e:
                    print(f"⚠️  Error en limpieza: {e}")

            return response

        except Exception as e:
            print("[VIDEO_DOWNLOADER] ERROR:", e)
            
            # **LIMPIAR EN CASO DE ERROR**
            try:
                if downloaded_path and os.path.exists(downloaded_path):
                    os.remove(downloaded_path)
                if temp_dir and os.path.exists(temp_dir):
                    shutil.rmtree(temp_dir, ignore_errors=True)
            except Exception as cleanup_error:
                print(f"⚠️  Error limpiando en excepción: {cleanup_error}")

            # Mensajes de error específicos
            error_msg = str(e).lower()
            if "ffmpeg" in error_msg and "not installed" in error_msg:
                flash("Error: FFmpeg no está disponible. Se necesitan codecs adicionales para procesar este video.", "error")
            elif "unable to download webpage" in error_msg:
                flash("No se pudo acceder a la URL. Verificá que sea válida y pública.", "error")
            elif "private" in error_msg:
                flash("El video es privado o no está disponible.", "error")
            elif "copyright" in error_msg:
                flash("El contenido está protegido por derechos de autor.", "error")
            else:
                flash("Ocurrió un error al procesar la descarga. Probá con otra URL.", "error")
            
            return redirect(url_for('video_downloader'))

    return render_template("video_downloader.html")


# --------- 21) REDIMENSIONAR IMAGEN ---------
@app.route("/resize-image", methods=["GET", "POST"])
def resize_image():
    register_tool("resize-image")
    if request.method == "POST":
        file = request.files.get("file")
        width = int(request.form.get("width"))
        height = int(request.form.get("height"))

        if not file or file.filename == "":
            flash("Subí una imagen válida.", "error")
            return redirect(request.url)

        filename = secure_filename(file.filename)
        input_path = os.path.join(app.config["UPLOAD_FOLDER"], filename)
        file.save(input_path)

        try:
            img = Image.open(input_path)
            resized = img.resize((width, height))

            out_name = f"{uuid.uuid4().hex}_resized.png"
            output_path = os.path.join(app.config["GENERATED_FOLDER"], out_name)
            resized.save(output_path)

            flash("Imagen redimensionada con éxito.", "success")
            return render_template("resize_image.html", download_file=out_name)

        except Exception as e:
            print(e)
            flash("Error al procesar la imagen.", "error")
            return redirect(request.url)

    return render_template("resize_image.html")


# --------- 22) REDIMENSIONAR IMAGEN ---------
@app.route("/image_to_pdf", methods=["GET", "POST"])
def image_to_pdf():
    register_tool("image-to-pdf")
    if request.method == "POST":
        images = request.files.getlist("images")

        # Validación
        if not images or len(images) == 0:
            return render_template("image_to_pdf.html", download_file=None)

        # Carpeta temporal por ID único
        unique_id = str(uuid.uuid4())
        upload_path = os.path.join("uploads", unique_id)
        os.makedirs(upload_path, exist_ok=True)

        pil_images = []
        pdf_filename = f"output_{unique_id}.pdf"
        pdf_path = os.path.join(upload_path, pdf_filename)

        for img in images:
            filename = secure_filename(img.filename)
            img_path = os.path.join(upload_path, filename)
            img.save(img_path)

            # Convertir imagen a RGB (obligatorio para PDF)
            pil_img = Image.open(img_path).convert("RGB")
            pil_images.append(pil_img)

        # Crear PDF final
        if len(pil_images) == 1:
            pil_images[0].save(pdf_path)
        else:
            pil_images[0].save(pdf_path, save_all=True, append_images=pil_images[1:])

        # Devolver archivo para la template
        return render_template(
            "image_to_pdf.html",
            download_file=pdf_filename,
            folder=unique_id
        )

    # Método GET → NO hay archivo todavía
    return render_template("image_to_pdf.html", download_file=None)


# ============================
# 23) IMAGEN → TEXTO (OCR)
# ============================
def ocr_image_ordered(path):
    register_tool("image-to-text")
    try:
        img = Image.open(path)

        # --- Mejoras importantes ---
        img = img.convert("L")  # B/N
        img = ImageEnhance.Contrast(img).enhance(2)  # Más contraste
        img = img.filter(ImageFilter.SHARPEN)  # Más nitidez

        # --- OCR con layout real ---
        text = pytesseract.image_to_string(img, lang="spa+eng", config="--psm 6")

        return text.strip()

    except Exception as e:
        return f"Error al procesar la imagen: {str(e)}"


@app.route("/image_to_text", methods=["GET", "POST"])
def image_to_text():
    register_tool("image-to-text")
    extracted_text = None
    error_message = None

    if request.method == "POST":
        try:
            file = request.files.get("file")

            if not file:
                error_message = "No se subió ninguna imagen."
            else:
                filename = secure_filename(file.filename)
                temp_path = os.path.join("uploads", filename)
                file.save(temp_path)

                extracted_text = ocr_image_ordered(temp_path)

        except Exception as e:
            error_message = f"Error al procesar la imagen: {str(e)}"

    return render_template(
        "image_to_text.html",
        extracted_text=extracted_text,
        error_message=error_message
    )


if __name__ == "__main__":
    app.run(debug=True)
