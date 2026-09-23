import os
import json
from typing import List
from flask import Flask, request, jsonify
from flask_cors import CORS
from pydantic import BaseModel
from google import genai
from google.genai import types
from dotenv import load_dotenv
import gspread

load_dotenv()

app = Flask(__name__)

# Allow requests from your Netlify domain and local
# CORS(app, resources={r"/*": {"origins": [
#     "http://127.0.0.1:5000",
#     "http://localhost:5000",
#     "https://invoice-agent-ai.netlify.app"
# ]}})

# Temporarily allow all origins for debugging
CORS(app, resources={r"/*": {"origins": "*"}})

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

@app.route("/upload", methods=["POST"])
def upload():
    if "file" not in request.files:
        return jsonify({"error": "No file uploaded"}), 400
    
    file = request.files["file"]
    if file.filename == "":
        return jsonify({"error": "Empty filename"}), 400

    try:
        # 1. Read the entire PDF directly into memory
        pdf_bytes = file.read()
        
        # 2. Package the raw PDF bytes as a single document part
        pdf_part = types.Part.from_bytes(
            data=pdf_bytes,
            mime_type='application/pdf'
        )
        
        prompt = (
            "You are an expert AI extraction agent. Extract all catalog items, "
            "categories, specifications, indicative prices, and units from this document."
        )
        
        # 3. Send one single request to Gemini 3.8 Flash
        response = client.models.generate_content(
            model='gemini-3.8-flash',
            contents=[pdf_part, prompt],
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=CatalogData,
                temperature=0.1
            )
        )
        
        extracted_data = json.loads(response.text)
        return jsonify({"success": True, "data": extracted_data})
        
    except Exception as e:
        print(f"Extraction Error: {e}")
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

@app.route('/health', methods=['GET'])
def health_check():
    return "OK", 200

if __name__ == "__main__":
    # Render requires binding to 0.0.0.0 for production
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))