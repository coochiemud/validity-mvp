# analyzer.py
from openai import OpenAI
import json
import os
import re
import time
from dotenv import load_dotenv
from prompts import build_prompt
from failure_library import REASONING_FAILURES, ALLOWED_FAILURE_TYPES

load_dotenv()

class ValidityAnalyzer:
    def __init__(self):
        # Try Streamlit secrets first, fall back to environment variable
        try:
            import streamlit as st
            api_key = st.secrets.get("OPENAI_API_KEY")
            model_name = st.secrets.get("MODEL_NAME", "gpt-4o")
        except:
            api_key = os.getenv("OPENAI_API_KEY")
            model_name = os.getenv("MODEL_NAME", "gpt-4o")
        
        self.client = OpenAI(api_key=api_key)
        self.model = model_name
        
        # Production limits
        self.MAX_FAILURES_RETURNED = 10
        self.MAX_SYNTHESIS_ITEMS = 5
    
    def _normalize_text(self, text: str) -> str:
        """Clean up input text"""
        text = text.replace("\x00", "")
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()
    
    def _clean_json_response(self, text: str) -> str:
        """Remove markdown code fences and clean response"""
        cleaned = text.strip()
        
        if cleaned.startswith("```json"):
            cleaned = cleaned[7:]
        elif cleaned.startswith("```"):
            cleaned = cleaned[3:]
        
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3]
        
        return cleaned.strip()
    
    def _repair_json(self, bad_json: str) -> str:
        """Attempt to repair invalid JSON using OpenAI (one attempt only)"""
        repair_prompt = f"""The following is invalid JSON. Fix it and return ONLY valid JSON matching the original structure.

Rules:
- Return ONLY the JSON object
- No commentary
- No markdown code fences
- Fix any syntax errors (trailing commas, quotes, etc)

INVALID JSON:
{bad_json}

Return the corrected JSON:"""
        
        response = self.client.chat.completions.create(
            model=self.model,
