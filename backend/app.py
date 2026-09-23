import os
import io
import json
import time
from typing import List
from flask import Flask, request, jsonify
from flask_cors import CORS
import pymupdf
from PIL import Image
from pydantic import BaseModel
from google import genai
from google.genai import types
from dotenv import load_dotenv
import gspread

load_dotenv()

app = Flask(__name__)

# Allow requests from your Netlify domain and local testing
CORS(app, resources={r"/*": {"origins": [
    "http://127.0.0.1:5000", 
    "http://localhost:5000",
    "https://invoice-agent-ai.netlify.app"
]}})

client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

class CatalogItem(BaseModel):
    category: str
    material_specification: str
    indicative_price: str
    unit: str

class CatalogData(BaseModel):
    document_title: str
    primary_reference_market: str
    catalog_date: str
    items: List[CatalogItem]

def pdf_bytes_to_images(pdf_bytes: bytes):
    images = []
    doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    for page in doc:
        pix = page.get_pixmap(matrix=pymupdf.Matrix(2.0, 2.0))
        img = Image.open(io.BytesIO(pix.tobytes("png")))
        images.append(img)
    return images

def extract_from_images(images):
    prompt = (
        "You are an expert AI extraction agent. Extract all catalog items, "
        "categories, specifications, indicative prices, and units from this document."
    )
    for attempt in range(5):
        try:
            response = client.models.generate_content(
                model='gemini-3.8-flash',
                contents=images + [prompt],
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=CatalogData,
                    temperature=0.1
                )
            )
            return json.loads(response.text)
        except Exception as e:
            if "503" in str(e):
                time.sleep(5)
            else:
                raise e
    raise RuntimeError("API busy after 5 retry attempts.")

@app.route("/upload", methods=["POST"])
def upload():
    if "file" not in request.files:
        return jsonify({"error": "No file uploaded"}), 400
    
    file = request.files["file"]
    if file.filename == "":
        return jsonify({"error": "Empty filename"}), 400

    try:
        pdf_bytes = file.read()
        images = pdf_bytes_to_images(pdf_bytes)
        extracted_data = extract_from_images(images)
        return jsonify({"success": True, "data": extracted_data})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/sync", methods=["POST"])
def sync_to_sheets():
    payload = request.get_json()
    if not payload or "data" not in payload:
        return jsonify({"error": "No data provided"}), 400

    data = payload["data"]
    title = data.get("document_title", "Document")
    date = data.get("catalog_date", "")
    market = data.get("primary_reference_market", "")
    items = data.get("items", [])

    try:
        gc = gspread.service_account(filename="credentials.json")
        sheet = gc.open("Automated Invoices").sheet1

        rows_to_append = []
        for item in items:
            rows_to_append.append([
                title,
                date,
                market,
                item.get("category", ""),
                item.get("material_specification", ""),
                item.get("indicative_price", ""),
                item.get("unit", "")
            ])

        if rows_to_append:
            sheet.append_rows(rows_to_append)

        return jsonify({"success": True, "inserted_count": len(rows_to_append)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    # Render requires binding to 0.0.0.0 for production
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))

@app.route('/health', methods=['GET'])
def health_check():
    return "OK", 200