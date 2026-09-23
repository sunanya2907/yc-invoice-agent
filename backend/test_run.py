import os
import glob
import io
import json
import time
from typing import List
import pymupdf
from PIL import Image
from pydantic import BaseModel
from google import genai
from google.genai import types
from dotenv import load_dotenv
import gspread

# Load API key
load_dotenv()
client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

# 1. Catalog Schema (for Construction Materials / Price Catalogs)
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

def pdf_to_images(pdf_path: str):
    print(f"Reading {pdf_path}...")
    images = []
    doc = pymupdf.open(pdf_path)
    for page in doc:
        pix = page.get_pixmap(matrix=pymupdf.Matrix(2.0, 2.0))
        img = Image.open(io.BytesIO(pix.tobytes("png")))
        images.append(img)
    return images

def extract(pdf_path: str):
    images = pdf_to_images(pdf_path)
    prompt = "You are an expert AI extraction agent. Extract all catalog items, categories, specifications, indicative prices, and units from this document."
    
    # Retry loop to handle 503 high-demand traffic spikes
    for attempt in range(5):
        try:
            print(f"Sending to Gemini API (Attempt {attempt + 1}/5)...")
            response = client.models.generate_content(
                model='gemini-3.8-flash',
                contents=images + [prompt],
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=CatalogData,
                    temperature=0.1
                )
            )
            return response.text
        except Exception as e:
            if "503" in str(e):
                print("Google's servers are busy (503). Waiting 5 seconds and retrying...")
                time.sleep(5)
            else:
                raise e

    print("Failed to connect after 5 attempts.")
    return "{}"

def push_to_sheets(json_str: str):
    print("Connecting to Google Sheets...")
    gc = gspread.service_account(filename="credentials.json")
    sheet = gc.open("Automated Invoices").sheet1
    
    data = json.loads(json_str)
    title = data.get("document_title", "Catalog")
    date = data.get("catalog_date", "")
    market = data.get("primary_reference_market", "")
    
    items = data.get("items", [])
    if not items:
        print("No items found to push.")
        return

    # Append each extracted catalog item to Google Sheets
    for item in items:
        row = [
            title,
            date,
            market,
            item.get("category", ""),
            item.get("material_specification", ""),
            item.get("indicative_price", ""),
            item.get("unit", "")
        ]
        sheet.append_row(row)
    print(f"Successfully pushed {len(items)} rows to Google Sheets!")

if __name__ == "__main__":
    files = glob.glob("invoices/*.pdf")
    if not files:
        print("Put a PDF inside the 'invoices' folder first!")
    else:
        json_result = extract(files[0])
        print("\n--- EXTRACTED DATA (GEMINI) ---")
        print(json_result)
        push_to_sheets(json_result)