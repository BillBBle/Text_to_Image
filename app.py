import os
from flask import Flask, request, jsonify, send_from_directory, render_template, url_for
from dotenv import load_dotenv
from datetime import datetime
from PIL import Image, ImageDraw
import requests
from werkzeug.utils import secure_filename
import uuid
from google import genai
from google.genai import types as genai_types

IMAGEN_MODEL = os.getenv("IMAGEN_MODEL", "imagen-3.0-generate-002")

# Load environment variables
load_dotenv()

app = Flask(__name__)
os.makedirs("output", exist_ok=True)

UPLOAD_DIR = os.path.join("static", "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

app.config["MAX_CONTENT_LENGTH"] = 10 * 1024 * 1024
ALLOWED_EXTS = {"png", "jpg", "jpeg", "webp", "gif"}

def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTS

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/preview/<filename>")
def preview_page(filename):
    print("📦 preview filename =", filename)
    return render_template("preview.html", filename=filename)

@app.route("/upload", methods=["GET"])
def upload_page():
    return render_template("upload.html")

@app.route("/upload-image", methods=["POST"])
def upload_image():
    file = request.files.get("file")
    if not file:
        return jsonify({"error": "No file provided"}), 400

    ext = os.path.splitext(file.filename)[1]
    out_name = f"{uuid.uuid4().hex}{ext}"
    save_path = os.path.join("static/uploads", out_name)
    file.save(save_path)

    return jsonify({
        "redirect_url": url_for("preview_page", filename=out_name)
    })

@app.route("/uploads/<path:filename>")
def serve_upload(filename):
    return send_from_directory(UPLOAD_DIR, filename)

# ======== 关键改造：/generate 使用 Google Imagen 3 ========
# 映射：width/height -> (aspectRatio, imageSize)
# Imagen 仅支持 aspectRatio: "1:1","3:4","4:3","9:16","16:9"
# imageSize: "1K" 或 "2K"（标准/Ultra 模型支持）
def pick_aspect_ratio(width: int, height: int) -> str:
    # 计算最接近的支持比例
    target = width / height if height else 1.0
    ratios = {
        "1:1": 1.0,
        "3:4": 3/4,
        "4:3": 4/3,
        "9:16": 9/16,
        "16:9": 16/9,
    }
    best = min(ratios.items(), key=lambda kv: abs(kv[1] - target))
    return best[0]

def pick_image_size(width: int, height: int) -> str:
    # 简单规则：最长边 <= 1024 用 1K，否则 2K
    longest = max(width, height)
    return "1K" if longest <= 1024 else "2K"

# 你可以在这里统一切换模型版本（Imagen 3 / 4）
IMAGEN_MODEL = os.getenv("IMAGEN_MODEL", "imagen-3.0-generate-002")

# 复用一个全局客户端（使用 ADC 或服务账号）

# 延迟创建 Google GenAI 客户端（本地用 API Key；线上可走 ADC）
VTX_PROJECT = os.getenv("GOOGLE_CLOUD_PROJECT") or "<你的GCP_PROJECT_ID>"
VTX_LOCATION = os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1")

_genai_client = None
def get_genai_client():
    global _genai_client
    if _genai_client is None:
        _genai_client = genai.Client(
            vertexai=True,           # ← 强制走 Vertex
            project=VTX_PROJECT,
            location=VTX_LOCATION,
        )
    return _genai_client

@app.route("/generate", methods=["POST"])
def generate():
    data = request.get_json()
    prompt = data.get("prompt", "").strip()
    width = int(data.get("width", 512))
    height = int(data.get("height", 512))

    if not prompt:
        return jsonify({"error": "Prompt is required"}), 400

    # 规范化到 Imagen 支持的参数
    aspect_ratio = pick_aspect_ratio(width, height)
    image_size = pick_image_size(width, height)

    # 可选：前端也可以单独传 aspectRatio / imageSize，后端以它们为准
    if "aspectRatio" in data:
        ar = str(data["aspectRatio"])
        if ar in {"1:1","3:4","4:3","9:16","16:9"}:
            aspect_ratio = ar
    if "imageSize" in data:
        sz = str(data["imageSize"]).upper()
        if sz in {"1K","2K"}:
            image_size = sz

    client = get_genai_client()
    if not client:
        return jsonify({"error": "GenAI client not initialized. Set GOOGLE_API_KEY or ADC."}), 500

    try:
        resp = client.models.generate_images(
            model=IMAGEN_MODEL,
            prompt=prompt,
            config=genai_types.GenerateImagesConfig(
                number_of_images=1,
                image_size=image_size,
                aspect_ratio=aspect_ratio,
            ),
        )

        if not resp.generated_images:
            return jsonify({"error": "No image generated", "details": str(resp)}), 500

        # ↓ 正确处理返回的字节
        img_bytes = resp.generated_images[0].image
        filename = f"{datetime.now().strftime('%Y%m%d-%H%M%S')}.png"
        filepath = os.path.join("output", filename)
        with open(filepath, "wb") as f:
            # 有的版本是字段 .image_bytes；做个兼容
            f.write(getattr(img_bytes, "image_bytes", img_bytes))

        return jsonify({
            "image_url": f"/output/{filename}",
            "aspect_ratio": aspect_ratio,
            "image_size": image_size,
            "model": IMAGEN_MODEL
        })
    except Exception as e:
        app.logger.exception("Generate failed")
        return jsonify({"error": "Image generation failed", "details": str(e)}), 500
# ====================== 关键改造结束 ======================

@app.route("/generate-prompt", methods=["POST"])
def generate_prompt():
    data = request.get_json()
    idea = data.get("idea", "").strip()
    style = data.get("style", "cartoon")
    emotion = data.get("emotion", "happy")
    background = data.get("background", "forest")
    model = data.get("model", "llama3")

    if not idea:
        return jsonify({"error": "Idea is required"}), 400

    prompt_text = (
        f"Act as a text-to-image prompt generator. Based on the idea: '{idea}', "
        f"generate 3 short English prompts that match the style '{style}', emotion '{emotion}', and background '{background}'. "
        f"Each prompt should be a single sentence, no more than 20 words. "
        f"Only return the prompts in plain list format. Do not include explanation or descriptions."
    )

    try:
        response = requests.post(
            "http://localhost:11434/api/generate",
            json={
                "model": model,
                "prompt": prompt_text,
                "stream": False
            }
        )
        result = response.json()
        refined_prompt = result.get("response", "").strip()

        if refined_prompt:
            return jsonify({"prompt": refined_prompt})
        else:
            return jsonify({"error": "No prompt generated", "details": result}), 500
    except Exception as e:
        return jsonify({"error": "Exception occurred", "details": str(e)}), 500

@app.route("/output/<filename>")
def serve_image(filename):
    return send_from_directory("output", filename)

@app.route("/resize", methods=["POST"])
def resize_image():
    data = request.get_json()
    image_url = data.get("image_url")
    width = int(data.get("width", 512))
    height = int(data.get("height", 512))

    try:
        if image_url.startswith("/"):
            image_url = image_url.lstrip("/")
        local_path = os.path.join("static", image_url) if not image_url.startswith("output") else image_url

        print("📁 File path:", local_path)

        with open(local_path, "rb") as f:
            img = Image.open(f)
            resized = img.resize((width, height))

        filename = f"resized_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
        output_path = os.path.join("static", "resized", filename)
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        resized.save(output_path)

        return jsonify({ "resized_url": f"/static/resized/{filename}" })

    except Exception as e:
        print("❌ Resize Error:", str(e))
        return jsonify({ "error": str(e) }), 500

@app.route("/reshape", methods=["POST"])
def reshape_image():
    data = request.get_json()
    image_url = data.get("image_url")
    shape = data.get("shape", "circle")

    try:
        if image_url.startswith("/"):
            image_url = image_url.lstrip("/")
        local_path = image_url if image_url.startswith("output") else os.path.join("static", image_url)

        img = Image.open(local_path).convert("RGBA")
        width, height = img.size

        mask = Image.new("L", (width, height), 0)
        draw = ImageDraw.Draw(mask)

        if shape == "circle":
            draw.ellipse((0, 0, width, height), fill=255)
        elif shape == "rounded":
            radius = int(min(width, height) * 0.2)
            draw.rounded_rectangle((0, 0, width, height), radius=radius, fill=255)
        elif shape == "square":
            draw.rectangle((0, 0, width, height), fill=255)
        else:
            return jsonify({ "error": "Unsupported shape" }), 400

        img.putalpha(mask)

        filename = f"reshaped_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
        output_path = os.path.join("static", "reshaped", filename)
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        img.save(output_path)

        return jsonify({ "reshaped_url": f"/{output_path}" })

    except Exception as e:
        return jsonify({ "error": str(e) }), 500

if __name__ == "__main__":
    app.run(port=5001, debug=True)
