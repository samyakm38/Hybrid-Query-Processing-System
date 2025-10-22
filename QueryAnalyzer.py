import json
import re
import QueryDecomposer as qd
import google.genai as genai
from google.genai import types
import os
from dotenv import load_dotenv

load_dotenv() 
_api_key = os.getenv("GEMINI_API_KEY")
if not _api_key:
  raise RuntimeError(
    "Environment variable GEMINI_API_KEY is not set. Please set it before running this script."
  )

client = genai.Client(api_key=_api_key)

user_question = input()

DB_SCHEMA = """
Database Schema:
- Table: hotels (
    hotel_id INT,
    name TEXT,
    city TEXT,
    state TEXT,
    address TEXT,
    avg_rating REAL,
    has_wifi BOOLEAN,
    has_parking BOOLEAN,
    has_breakfast BOOLEAN,
    has_swimming_pool BOOLEAN,
    email_id TEXT,
    phone_no INT
  )
- Table: rooms (
    room_id INT PRIMARY KEY,
    hotel_id INT FOREIGN KEY REFERENCES hotels(hotel_id),
    room_type TEXT,
    price_per_night REAL
  )
- Table: reviews (
    review_id INT PRIMARY KEY,
    hotel_id INT FOREIGN KEY REFERENCES hotels(hotel_id),
    reviewer_name TEXT,
    review_text TEXT,
    rating REAL
  )
- Table: transport (
    transport_id INT PRIMARY KEY,
    mode TEXT,-- e.g., 'flight', 'train', 'bus'
    operator_name TEXT,
    source TEXT,
    destination TEXT,
    approx_duration TEXT,
    avg_price REAL
  )

- Table: transport_packages (
    package_id INT PRIMARY KEY,
    transport_id INT FOREIGN KEY REFERENCES transport(transport_id),
    hotel_id INT FOREIGN KEY REFERENCES hotels(hotel_id),
    package_name TEXT,
    package_price REAL,
    mode TEXT
  )

"""



prompt = f"""
Generate **all necessary SQL queries** to gather the raw data required to answer the user's question. These must be provided as an **array of strings**. If only one SQL query is needed, the array must contain one string.

**Instructions:**
1.  Generate **all necessary SQL queries** to gather the raw data required to answer the user's question. These must be provided as an **array of strings**. If only one SQL query is needed, the array must contain one string.
2.  IMPORTANT CONSTRAINT **Don't use alias for tables**.
3.  IMPORTANT CONSTRAINT **No nested queries**.
4.  Don't select more columns than required. 
5.  Generate a single **LLM Query** that instructs the large language model on how to combine, process, and synthesize the results from the SQL queries (which will be inserted into the LLM Query by the application) with external knowledge to form the final answer.

**Database Schema:**
{DB_SCHEMA}

**User Question:** "{user_question}"

**Output ONLY in the following JSON format:**
**Output ONLY in the following JSON format:**
{{
  "sql_queries": [
      "SQL Query 1",
      "SQL Query 2",
      // ... continue as needed
    ],
  "llm_query": "A complete natural language instruction for the final synthesis step, referencing the data from the 'sql_queries' results."
}}
"""

response = client.models.generate_content(
    model="gemini-2.5-flash",
    contents=prompt,
    config=types.GenerateContentConfig(
        response_mime_type="application/json", 
        thinking_config=types.ThinkingConfig(thinking_budget=0) 
    ),
)

try:
    decomposition = json.loads(response.text)
    
    sql_queries = decomposition.get("sql_queries", [])
    
    llm_query = decomposition.get("llm_query")

    if sql_queries:
        print("--- Generated SQL Queries ---")
        for i, query in enumerate(sql_queries, 1):
            print(f"SQL Query {i}: {query}")
    else:
        print("No SQL queries were generated.")
        
    print("\n--- Generated LLM Query ---")
    if llm_query:
        print(llm_query)
    else:
        print("No LLM synthesis query was generated.")
    
except json.JSONDecodeError:
    print("Error: Could not parse response as JSON. Check the Gemini output format.")
except AttributeError as e:
        print(f"Error accessing keys: {e}. Check if 'sql_queries' or 'llm_query' keys are missing or not arrays/strings.")



# sql_queries=[
#   # "SELECT * FROM transport WHERE source = 'Delhi' AND destination = 'Shimla' ORDER BY avg_price ASC;",
# "SELECT transport_packages.package_name, transport.destination FROM transport_packages JOIN transport ON transport_packages.transport_id = transport.transport_id WHERE transport.destination = 'Shimla'; "]
# # "SELECT * FROM transport;"]
# # "SELECT * FROM transport WHERE transport.mode='train';"]

for query in (sql_queries):
  table_pattern = re.search(r"FROM\s+(.*?)(?:\s+(WHERE|GROUP BY|ORDER BY|LIMIT)\b|;|$)", query, re.IGNORECASE)
  table_part = table_pattern.group(1).strip() if table_pattern else None
  if not re.search(r"\b(hotels|rooms|reviews)\b", table_part, re.IGNORECASE): qd.transportOnlyQueryDecomposer(query)
  elif not bool(re.search(r"\btransport\b",table_part, re.IGNORECASE) or re.search(r"\btransport_packages\b",table_part, re.IGNORECASE)): qd.hotelOnlyQueryDecomposer(query)
  else: qd.hotelAndTransportJoinedQueryDecomposer(query)





