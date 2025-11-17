from matplotlib.pylab import less
from hotelQueryDecomposer import hotelOnlyQueryDecomposer
from transportQueryDecomposer import transportOnlyQueryDecomposer
from joinedQueryDecomposer import hotelAndTransportJoinedQueryDecomposer
import json
import re
import google.genai as genai
from google.genai import types
import os
from dotenv import load_dotenv
import csv
import pandas as pd
import requests
import time
from google.genai.errors import ServerError


HOTEL_API_URL = "http://127.0.0.1:8000/query"
TRANSPORT_API_URL = "https://nonderogatively-cephalometric-zoie.ngrok-free.dev/query"

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
    complete_address TEXT,
    star_rating REAL,
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
    source TEXT,
    destination TEXT,
    duration TEXT,
    price REAL
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
Generate **all necessary SQL queries** strictly over the GLOBAL SCHEMA to gather the raw data required to answer the user's question. 
These must be provided as an **array of strings**. If only one SQL query is needed, the array must contain one string.

========================
STRICT SQL FORMAT RULES
========================

1. **Use ONLY this SQL structure (MANDATORY):**

   SELECT <column_list> FROM <table_name> [JOIN <table_name> ON <col>=<col>] [JOIN <table_name> ON <col>=<col>] WHERE <condition_1> AND <condition_2> AND ... AND <condition_n>;
   
2. **Every column referenced in SELECT, JOIN, and WHERE must be written using the form `table.col`.**

3. If the user question logically requires an **OR**, then:
   - You MUST split it into **multiple independent SQL queries**.
   - Each query MUST obey the fixed structure and contain **only AND** inside WHERE.
   Example:
     (A OR B OR (C AND D))  →  3 separate queries:
       - A
       - B
       - C AND D

4. **Each SQL query must be a complete standalone query.**

5. **NO nested queries, NO subqueries.**

6. **NO table aliases.**  
   Every table must use its full name exactly as shown in the GLOBAL SCHEMA.

7. Allowed operators: =, >, <, >=, <=, LIKE.  
   (No IN, NOT IN, BETWEEN, EXISTS, LIMIT, ORDER BY, GROUP BY.)

8. Only select the **minimum columns needed** to answer the question.

9. JOINs are allowed **but only in the explicit fixed structure**.

========================
LLM SYNTHESIS STEP RULES
========================

After generating the SQL queries:
- Generate a single **LLM Query** explaining how to combine the results from all queries,
  especially because OR-conditions may result in separate SQL queries.
- The LLM Query must explain:
  - how to union or merge the multiple results,
  - how to deduplicate if needed,
  - how to use reasoning or general knowledge to form the final answer.

========================
INPUTS
========================

GLOBAL DATABASE SCHEMA:
{DB_SCHEMA}

USER QUESTION:
"{user_question}"

========================
OUTPUT FORMAT (MANDATORY)
========================

{{
  "sql_queries": [
      "SQL Query 1",
      "SQL Query 2",
      ...
  ],
  "llm_query": "Natural-language instructions for synthesizing the final answer."
}}
"""

# response = client.models.generate_content(
#     model="gemini-2.5-flash",
#     contents=prompt,
#     config=types.GenerateContentConfig(
#         response_mime_type="application/json", 
#         thinking_config=types.ThinkingConfig(thinking_budget=0) 
#     ),
# )

def call_with_retry(prompt, retries=3, delay=3):
    for attempt in range(1, retries + 1):
        try:
            response = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    thinking_config=types.ThinkingConfig(thinking_budget=0)
                ),
            )
            return response  # success → exit function

        except ServerError as e:
            # Check if it's a 503
            if "503" in str(e) or "overloaded" in str(e):
                print(f"Model overloaded (attempt {attempt}/{retries}). Retrying in {delay}s...")
                time.sleep(delay)
            else:
                # Some other server error → re-raise
                raise e

        except Exception as e:
            # Non-server error, no point retrying
            raise e

    # If all retries fail
    raise RuntimeError(f"Failed after {retries} attempts.")

response = call_with_retry(prompt)

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
        
    # print("\n--- Generated LLM Query ---")
    # if llm_query:
        # print(llm_query)
    # else:
        # print("No LLM synthesis query was generated.")
    
except json.JSONDecodeError:
    print("Error: Could not parse response as JSON. Check the Gemini output format.")
except AttributeError as e:
        print(f"Error accessing keys: {e}. Check if 'sql_queries' or 'llm_query' keys are missing or not arrays/strings.")


os.makedirs("results", exist_ok=True)
os.makedirs("temp", exist_ok=True)

# Overwrite main result files at start
open("results/hotel_results.csv", "w").close()
open("results/transport_results.csv", "w").close()
open("results/joined_results.csv", "w").close()

joined_counter = 0

def write_temp_csv(filepath, rows):
    """
    Overwrites (creates new) a temp CSV containing raw query results.
    """
    if isinstance(rows, dict) and "data" in rows:
        rows = rows["data"]

    if not rows:
        return

    with open(filepath, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)

def inner_join(left_rows, right_rows, join_condition):
    """
    Performs an inner join between left_rows and right_rows.
    If one side is empty, returns the non-empty side.
    If both are empty, returns [].
    If join keys are missing, returns concatenated rows (safe fallback).
    """

    # Empty cases
    if not left_rows and not right_rows:
        return []
    if not left_rows:
        return right_rows
    if not right_rows:
        return left_rows

    # Normal join path
    if not join_condition:
        # No join key — safest behavior: return both sets appended
        return left_rows + right_rows

    cond = join_condition[0]  # single condition like "hotels.city = transport.destination"

    try:
        left_col = cond.split("=")[0].strip()     # "hotels.city"
        right_col = cond.split("=")[1].strip()    # "transport.destination"

        _, left_key = left_col.split(".")
        _, right_key = right_col.split(".")

        df_left = pd.DataFrame(left_rows)
        df_right = pd.DataFrame(right_rows)

        # Check join keys exist
        if left_key not in df_left.columns or right_key not in df_right.columns:
            # Fallback: return combined rows if no join possible
            return left_rows + right_rows

        # Perform actual inner join
        df_joined = df_left.merge(df_right, left_on=left_key, right_on=right_key, how="inner")
        return df_joined.to_dict(orient="records")

    except Exception as e:
        # Any unexpected failure → do NOT crash the pipeline.
        print(f"[WARN] Join error: {e}. Falling back to concatenation.")
        return left_rows + right_rows
# def execute_sql(api_url, sql):
#     response = requests.get(api_url, params={"sql": sql})
#     response.raise_for_status()
#     # print(response.json())
#     return response.json()   # return list of rows (dicts)

def execute_sql(api_url, sql):
    response = requests.get(api_url, params={"sql": sql})
    response.raise_for_status()
    payload = response.json()

    # Always extract .data
    if isinstance(payload, dict) and "data" in payload:
        return payload["data"]

    # Rare case: payload already list
    if isinstance(payload, list):
        return payload

    # Otherwise convert single row into list-of-dicts
    return [payload]

def append_results_csv(filepath, rows):
    if not rows:
        return

    # rows might be list-of-dicts OR {"data": [...]}
    if isinstance(rows, dict) and "data" in rows:
        rows = rows["data"]

    if not rows:
        return

    # --------- COMPUTE UNION OF FIELDNAMES ---------
    # This handles train_id, bus_id, flight_id, etc.
    all_keys = set()
    for row in rows:
        all_keys.update(row.keys())

    file_exists = os.path.exists(filepath)

    # If file exists already, merge its header too
    if file_exists:
        with open(filepath, "r", newline="") as f:
            reader = csv.DictReader(f)
            old_keys = reader.fieldnames or []
            all_keys.update(old_keys)

    all_keys = list(all_keys)   # final header

    # --------- WRITE/APPEND ---------
    rows_to_write = []
    for row in rows:
        # ensure every key exists
        fixed = {k: row.get(k, "") for k in all_keys}
        rows_to_write.append(fixed)

    with open(filepath, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=all_keys)

        # if file is new → write header
        if not file_exists:
            writer.writeheader()

        writer.writerows(rows_to_write)


for query in sql_queries:

    # ========== CLASSIFY QUERY ==========
    match = re.search(
        r"FROM\s+(.*?)(?=WHERE|GROUP BY|ORDER BY|LIMIT|;|$)",
        query,
        re.IGNORECASE | re.DOTALL
    )
    tables_block = match.group(1) if match else ""

    has_hotel = bool(re.search(r"\b(hotels|rooms|reviews)\b", tables_block, re.IGNORECASE))
    has_transport = bool(re.search(r"\b(transport|transport_packages)\b", tables_block, re.IGNORECASE))


    # ========== CASE 1: JOINED QUERY ==========
    if has_hotel and has_transport:
        joined_counter += 1
        # print(f"[JOINED] Decomposing: {query}")

        parts = hotelAndTransportJoinedQueryDecomposer(query)

        hotel_sql = parts["hotel_global_query"]
        transport_sql = parts["transport_global_query"]
        join_cond = parts["join_condition"]
        hotel_sql = hotelOnlyQueryDecomposer(hotel_sql)
        transport_sqls = transportOnlyQueryDecomposer(transport_sql)
        # print(transport_sqls)
        # Execute both
        hotel_rows = execute_sql(HOTEL_API_URL, hotel_sql)
        all_transport_rows = []
        for t_sql in transport_sqls:
            rows = execute_sql(TRANSPORT_API_URL, t_sql)
            all_transport_rows.extend(rows)
        # Local join
        # print(hotel_rows) 
        # print(all_transport_rows)
        joined_rows = inner_join(hotel_rows, all_transport_rows, join_cond)

        # Append joined results to main file
        append_results_csv("results/joined_results.csv", joined_rows)

        continue


    # ========== CASE 2: HOTEL-ONLY ==========
    if has_hotel:
        # print(f"[HOTEL] Decomposing: {query}")

        hotel_sql = hotelOnlyQueryDecomposer(query)
        # print(hotel_sql)
        rows = execute_sql(HOTEL_API_URL, hotel_sql)
        # Append to hotel results
        append_results_csv("results/hotel_results.csv", rows)

        continue


    # ========== CASE 3: TRANSPORT-ONLY ==========
    if has_transport:
        # print(f"[TRANSPORT] Decomposing: {query}")

        transport_sqls = transportOnlyQueryDecomposer(query)

        all_rows = []
        for sql in transport_sqls:
            # print(sql)
            rows = execute_sql(TRANSPORT_API_URL, sql)
            all_rows.extend(rows)

        # Append all transport rows to CSV
        append_results_csv("results/transport_results.csv", all_rows)

        continue


    # ========== Should never reach here ==========
    print("ERROR: Query did not match any category:", query)
    

# Find all hotels in Delhi that offer transport packages where the transport originates from Mumbai and costs less than 4000 rupees.





def load_rows(path, n=5):
    # Missing file → empty list
    if not os.path.exists(path):
        return {"rows": []}

    # Empty file → empty list
    if os.path.getsize(path) == 0:
        return {"rows": []}

    rows = []
    with open(path, newline="") as f:
        reader = csv.reader(f)
        for row in reader:
            if not row:  # skip empty lines
                continue
            rows.append(row)
            if len(rows) >= n:
                break  # stop after n rows
    
    return {"rows": rows}

hotel_sample = load_rows("results/hotel_results.csv", 10)
transport_sample = load_rows("results/transport_results.csv", 10)
# print(transport_sample)
joined_sample = load_rows("results/joined_results.csv", 10)
final_payload = {
    "user_question": user_question,
    "sql_queries_generated": sql_queries,  # from first LLM
    "llm_synthesis_instructions": llm_query,  # from first LLM
    "results": {
        "hotels": hotel_sample,
        "transport": transport_sample,
        "joined": joined_sample
    }
}

final_prompt = f"""
You are an analytical AI assistant.

The following data was retrieved from multiple SQL queries and decompositions.
You have been provided **only a sample** of the full results. 
You do NOT know the total number of rows in any dataset.

Use all visible data, but acknowledge uncertainty when necessary. 

=================================
USER QUESTION
=================================
{final_payload["user_question"]}

=================================
SQL QUERIES USED
=================================
{json.dumps(final_payload["sql_queries_generated"], indent=2)}

=================================
RAW DATA (SAMPLED)
=================================

--- HOTELS DATA (sample only) ---
{json.dumps(final_payload["results"]["hotels"]["rows"], indent=2)}

--- TRANSPORT DATA (sample only) ---
{json.dumps(final_payload["results"]["transport"]["rows"], indent=2)}

--- JOINED DATA (sample only) ---
{json.dumps(final_payload["results"]["joined"]["rows"], indent=2)}

=================================
GUIDANCE
=================================
Use the synthesis logic provided earlier by the LLM:
{final_payload["llm_synthesis_instructions"]}

But ALSO:
- Use your own reasoning and general knowledge.
- Produce a clean and direct final answer for the user.
"""


# - Use ONLY the provided sample rows.
# - If the sample is insufficient or incomplete, clearly state the limitation.
# - Don't comment on the data being wrong, it's just a sample.

response_final = client.models.generate_content(
    model="gemini-2.5-flash",
    contents=final_prompt,
    config=types.GenerateContentConfig(
        response_mime_type="text/plain",
        thinking_config=types.ThinkingConfig(thinking_budget=0)
    ),
)

response=call_with_retry(final_prompt)

print("\n\n===== FINAL ANSWER =====\n")
print(response_final.text)


# Find all hotels in delhi and suggest me places to visit in delhi.
# Find all trains that cost less than 5000 or flights that cost less than 10000 and suggest places to visit in December in India.
# Find all hotels in Delhi that offer transport packages from Pune, and and suggest good veg food to eat in Delhi.
# Find hotels in Jodhpur which have a star rating of at least 3 and have a swimming pool, also suggest things to do in Jodhpur.
# Find transport packages from Goa to Jaipur, and suggest a 3 day itinerary for Jaipur.
