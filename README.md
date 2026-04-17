# Project Insight
### Empowering Analytical Agency through LLM-Driven SQL Generation

A Conversational Business Intelligence system for the FMCG sector, leveraging LLMs to translate natural language questions into executable SQL.

## Stack
- **LLM:** Google Gemini 2.5 Flash
- **Query Engine:** DuckDB
- **Storage:** Apache Parquet
- **Interface:** Streamlit
- **Language:** Python 3.x

## Setup
1. Clone the repo
2. Create a virtual environment: `python -m venv .venv && source .venv/bin/activate`
3. Install dependencies: `pip install -r requirements.txt`
4. Copy `.env.example` to `.env` and add your API keys
5. Run: `streamlit run app.py`
