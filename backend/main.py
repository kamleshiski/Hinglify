"""
Hinglish Subtitle Converter — Flask Backend
Main application entry point with API routes.
"""

import os
import sys
import logging
import traceback
import asyncio
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, request, jsonify
from flask_cors import CORS

# Load environment variables from .env
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# Import our modules
from converter import convert_srt

# ─── App Setup ────────────────────────────────────────────────────────────────

app = Flask(__name__)
# Add proper CORS so the Vercel frontend can talk to the Render backend.
CORS(app, origins=["https://hinglify.vercel.app", "http://localhost:3000"])

# ─── Constants ────────────────────────────────────────────────────────────────

MAX_FILE_SIZE = 5 * 1024 * 1024  # 5MB

# ─── API Routes ───────────────────────────────────────────────────────────────

@app.route('/health', methods=['GET'])
def health():
    return jsonify({"status": "ok"}), 200

@app.route("/api/convert", methods=["POST"])
def convert_file():
    try:
        if 'file' not in request.files:
            return jsonify({"error": "Please upload an .srt file."}), 400
        
        file = request.files['file']
        if not file.filename or not file.filename.lower().endswith(".srt"):
            return jsonify({"error": "Please upload an .srt file."}), 400

        raw_bytes = file.read()

        if len(raw_bytes) > MAX_FILE_SIZE:
            return jsonify({"error": "This file seems too large for an SRT — double-check it's the right file."}), 400

        try:
            content = raw_bytes.decode("utf-8")
        except UnicodeDecodeError:
            content = raw_bytes.decode("latin-1")

        if not content.strip():
            return jsonify({"error": "This SRT file appears to be empty."}), 400

        try:
            # Run the async conversion pipeline using asyncio.run
            result = asyncio.run(convert_srt(content=content))
        except ValueError as e:
            return jsonify({"error": "This file couldn't be read as a valid SRT. Try opening it in a text editor to check the formatting."}), 400
        except RuntimeError as e:
            return jsonify({"error": "Something went wrong during conversion. Please try again."}), 502

        return jsonify({
            "srt_content": result["srt_content"],
            "preview": result["preview"],
            "warnings": result["warnings"],
            "has_unconverted": result["has_unconverted"],
            "stats": result["stats"],
            "original_filename": file.filename,
        })

    except Exception as e:
        print(f"ERROR: {str(e)}")
        print(traceback.format_exc())
        return jsonify({"error": "Conversion failed. Please try again."}), 500

# ─── Main Entry Point ────────────────────────────────────────────────────────

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
