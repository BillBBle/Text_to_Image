import os
from flask import Flask, request, jsonify, send_from_directory, render_template
from dotenv import load_dotenv
from datetime import datetime
import requests

# Load environment variables
load_dotenv()
api_key = os.getenv("STABILITY_API_KEY")

app = Flask(__name__)
os.makedirs("output", exist_ok=True)

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/generate", methods=["POST"])
def generate():
    data = request.get_json()
    prompt = data.get("prompt", "").strip()

    if not prompt:
        return jsonify({"error": "Prompt is required"}), 400

    filename = f"{datetime.now().strftime('%Y%m%d-%H%M%S')}.png"
    filepath = os.path.join("output", filename)

    response = requests.post(
        "https://api.stability.ai/v2beta/stable-image/generate/core",
        headers={
            "authorization": f"Bearer {api_key}",
            "accept": "image/*"
        },
        files={"none": ''},
        data={
            "prompt": prompt,
            "output_format": "png",
            "aspect_ratio": "1:1"
        },
    )

    if response.status_code == 200:
        with open(filepath, "wb") as f:
            f.write(response.content)
        return jsonify({"image_url": f"/output/{filename}"})
    else:
        return jsonify({"error": "Image generation failed", "details": response.text}), 500

@app.route("/generate-prompt", methods=["POST"])
def generate_prompt():
    data = request.get_json()
    idea = data.get("idea", "").strip()
    model = data.get("model", "llama3")  # Optional: allow switching models

    if not idea:
        return jsonify({"error": "Idea is required"}), 400

    try:
        response = requests.post(
            "http://localhost:11434/api/generate",
            json={
                "model": model,
                "prompt": f"Refine this idea into a detailed image generation prompt: {idea}",
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

if __name__ == "__main__":
    app.run(debug=True)
