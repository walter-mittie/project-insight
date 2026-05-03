import os
from google import genai
from dotenv import load_dotenv

load_dotenv()
api_key = os.getenv("GEMINI_API_KEY")

client = genai.Client(api_key=api_key)

response = client.models.generate_content(
    model='gemini-2.5-flash',
    contents="""How good is your capability to translate natural language questions to SQL queries for a duckdb schema with 4 tables -  500 rows, 250 rows, 43,000 rows and 2,200,000 rows?"""
)

print(response.text)