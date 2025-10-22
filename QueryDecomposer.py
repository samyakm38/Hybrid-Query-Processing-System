import re
from typing import Dict, Tuple, Set, List, Optional

# ---Transport Only-----
def transportOnlyQueryDecomposer(global_query: str) -> List[str]:
    query = re.sub(r"\s+", " ", global_query.strip())

    has_transport = bool(re.search(r"\btransport\b", query, re.IGNORECASE))
    has_packages = bool(re.search(r"\btransport_packages\b", query, re.IGNORECASE))

    where_match = re.search(r"\bWHERE\s+(.*?)(ORDER BY|GROUP BY|LIMIT|;|$)", query, re.IGNORECASE | re.DOTALL)
    where_clause = where_match.group(1).strip() if where_match else ""
    rest_part = query[where_match.end(1):] if where_match else ""

    select_match = re.search(r"SELECT\s+(.*?)\s+FROM\s+", query, re.IGNORECASE | re.DOTALL)
    select_part = select_match.group(1).strip() if select_match else "*"

    from_part_match = re.search(r"FROM\s+(.*?)\s*(WHERE|ORDER BY|GROUP BY|LIMIT|;|$)", query, re.IGNORECASE | re.DOTALL)
    from_part = from_part_match.group(1).strip() if from_part_match else ""

    modes = re.findall(r"\bmode\s*=\s*['\"]?(\w+)['\"]?", where_clause, re.IGNORECASE)
    modes = [m.lower() for m in modes]
    if not modes:
        modes = ["flight", "train", "bus"]

    where_no_mode = re.sub(r"\b\w*\.?mode\s*=\s*['\"]?\w+['\"]?\s*(AND|OR)?", "", where_clause, flags=re.IGNORECASE)
    where_no_mode = re.sub(r"\s*(AND|OR)\s*$", "", where_no_mode.strip(), flags=re.IGNORECASE)

    local_queries = []

    for mode in modes:
        if has_transport and not has_packages:
            local_query = f"SELECT {select_part} FROM {mode}"
            if where_no_mode:
                local_query += f" WHERE {where_no_mode}"
            local_query += f" {rest_part}"

        elif has_packages and not has_transport:
            local_query = f"SELECT {select_part} FROM transport_packages"
            if where_no_mode:
                local_query += f" WHERE {where_no_mode}"
            else:
                local_query += " WHERE 1=1"
            local_query += f" AND transport_packages.mode = '{mode}' {rest_part}"

        else:
            local_query = f"""
            SELECT {select_part}
            FROM transport_packages
            JOIN {mode} ON transport_packages.transport_id = {mode}.transport_id
            """
            if where_no_mode:
                local_query += f" WHERE {where_no_mode}"
                local_query += f" AND transport_packages.mode = '{mode}'"
            else:
                local_query += f" WHERE transport_packages.mode = '{mode}'"
            local_query += f" {rest_part}"

        local_queries.append(re.sub(r"\s+", " ", local_query.strip()))
    for query in local_queries:
        print("-----Local Schema Query--------------")
        print(query)
    return local_queries


# --Hotel Only----
def get_required_tables(query: str, column_mapping: Dict[str, Tuple[str, str]]) -> Set[str]:
    tokens = re.findall(r"\b\w+\b", query)
    required_tables: Set[str] = set()

    for token in tokens:
        if token.lower() in column_mapping:
            required_tables.add(column_mapping[token.lower()][0])

    return required_tables

def build_local_from_clause(required_tables: Set[str]) -> str:
    clause = "hotels_basic hb"

    if "hotel_facilities" in required_tables:
        clause += " LEFT JOIN hotel_facilities hf ON hb.hotel_id = hf.hotel_id"
    if "hotel_contact" in required_tables:
        clause += " LEFT JOIN hotel_contact hc ON hb.hotel_id = hc.hotel_id"
    if "rooms" in required_tables:
        clause += " JOIN rooms r ON hb.hotel_id = r.hotel_id"
    if "reviews" in required_tables:
        clause += " JOIN reviews rv ON hb.hotel_id = rv.hotel_id"

    return clause

def replace_from_clause(global_query: str, new_from_clause: str) -> str:
    pattern = r"FROM\s+.*?(?=\s+(WHERE|GROUP BY|ORDER BY|LIMIT|;|$))"
    return re.sub(pattern, f"FROM {new_from_clause}", global_query, flags=re.IGNORECASE | re.DOTALL)


def replace_columns_with_aliases(query: str, column_mapping: Dict[str, Tuple[str, str]], local_table_alias: Dict[str, str]) -> str:
    for global_col, (local_table, local_col) in column_mapping.items():
        alias = local_table_alias.get(local_table)
        if not alias:
            continue  
        query = re.sub(rf"\b\w+\.{global_col}\b", f"{alias}.{local_col}", query, flags=re.IGNORECASE)
        query = re.sub(rf"(?<!\.)\b{global_col}\b", f"{alias}.{local_col}", query, flags=re.IGNORECASE)

    return query


def hotelOnlyQueryDecomposer(query: str) -> None:
    column_mapping = {
        # hotels_basic
        "hotel_id": ("hotels_basic", "hotel_id"),
        "name": ("hotels_basic", "name"),
        "city": ("hotels_basic", "city"),
        "state": ("hotels_basic", "state"),
        "address": ("hotels_basic", "address"),

        # hotel_facilities
        "star_rating": ("hotel_facilities", "star_rating"),
        "has_wifi": ("hotel_facilities", "has_wifi"),
        "has_parking": ("hotel_facilities", "has_parking"),
        "has_breakfast": ("hotel_facilities", "has_breakfast"),
        "has_swimming_pool": ("hotel_facilities", "has_swimming_pool"),

        # hotel_contact
        "owner_name": ("hotel_contact", "email_id"),
        "email_id": ("hotel_contact", "email_id"),
        "phone_no": ("hotel_contact", "phone_no"),

        # rooms (unchanged)
        "room_id": ("rooms", "room_id"),
        "room_type": ("rooms", "room_type"),
        "price_per_night": ("rooms", "price_per_night"),

        # reviews (unchanged)
        "review_id": ("reviews", "review_id"),
        "reviewer_name": ("reviews", "reviewer_name"),
        "review_text": ("reviews", "review_text"),
        "rating": ("reviews", "rating"),
    }

    tables = get_required_tables(query, column_mapping)
    # print(tables)
    local_table_alias = {
        "hotels_basic": "hb",
        "hotel_facilities": "hf",
        "hotel_contact": "hc",
        "rooms": "r",
        "reviews": "rv",
    }

    new_from_clause = build_local_from_clause(tables)
    rewritten = replace_from_clause(query, new_from_clause)

    print("-----Local Schema Query--------------")
    print(replace_columns_with_aliases(rewritten, column_mapping, local_table_alias))


  
# ---Hotel+Transport Joined----

def hotelAndTransportJoinedQueryDecomposer(global_query:str):
    """
    Splits a cross-database SQL query into two per-database global queries
    (e.g., hoteldb and transportdb), and extracts the join keys.
    """

    # --- 1️⃣ Column-to-table-to-db mapping ---
    column_mapping = {
        # Hotel DB
        "hotel_id": ("hotels", "hotel_id", "hoteldb"),
        "name": ("hotels", "name", "hoteldb"),
        "city": ("hotels", "city", "hoteldb"),
        "state": ("hotels", "state", "hoteldb"),
        "address": ("hotels", "address", "hoteldb"),
        "avg_rating": ("hotels", "avg_rating", "hoteldb"),
        "has_wifi": ("hotels", "has_wifi", "hoteldb"),
        "has_parking": ("hotels", "has_parking", "hoteldb"),
        "has_breakfast": ("hotels", "has_breakfast", "hoteldb"),
        "has_swimming_pool": ("hotels", "has_swimming_pool", "hoteldb"),
        "email_id": ("hotels", "email_id", "hoteldb"),
        "phone_no": ("hotels", "phone_no", "hoteldb"),

        "room_id": ("rooms", "room_id", "hoteldb"),
        "room_type": ("rooms", "room_type", "hoteldb"),
        "price_per_night": ("rooms", "price_per_night", "hoteldb"),

        "review_id": ("reviews", "review_id", "hoteldb"),
        "reviewer_name": ("reviews", "reviewer_name", "hoteldb"),
        "review_text": ("reviews", "review_text", "hoteldb"),
        "rating": ("reviews", "rating", "hoteldb"),

        # Transport DB
        "transport_id": ("transport", "transport_id", "transportdb"),
        "mode": ("transport", "mode", "transportdb"),
        "operator_name": ("transport", "operator_name", "transportdb"),
        "source": ("transport", "source", "transportdb"),
        "destination": ("transport", "destination", "transportdb"),
        "approx_duration": ("transport", "approx_duration", "transportdb"),
        "avg_price": ("transport", "avg_price", "transportdb"),

        "package_id": ("transport_packages", "package_id", "transportdb"),
        "package_name": ("transport_packages", "package_name", "transportdb"),
        "package_price": ("transport_packages", "package_price", "transportdb"),
        "hotel_id": ("transport_packages", "hotel_id", "transportdb"),  # shared key
    }

    table_to_db = {
        "hotels": "hoteldb",
        "rooms": "hoteldb",
        "reviews": "hoteldb",
        "transport": "transportdb",
        "transport_packages": "transportdb"
    }

    select_match = re.search(r"SELECT\s+(.*?)\s+FROM", global_query, re.IGNORECASE | re.DOTALL)
    from_match = re.search(r"FROM\s+(.*?)(WHERE|GROUP BY|ORDER BY|;|$)", global_query, re.IGNORECASE | re.DOTALL)
    where_match = re.search(r"WHERE\s+(.*?)(GROUP BY|ORDER BY|;|$)", global_query, re.IGNORECASE | re.DOTALL)

    select_part = select_match.group(1).strip() if select_match else ""
    from_part = from_match.group(1).strip() if from_match else ""
    where_part = where_match.group(1).strip() if where_match else ""
    # print(from_part)
    # print(where_part)

    all_cols = re.findall(r"\b\w+\.\w+\b", global_query)
    db_columns = {"hoteldb": set(), "transportdb": set()}

    for c in all_cols:
        table, col = c.split(".")
        if table in table_to_db:
            db = table_to_db[table]
            db_columns[db].add(f"{table}.{col}")
    # print(db_columns)

    join_relations = []
    join_conds = re.findall(
        r"JOIN\s+(\w+)\s+ON\s+(.*?)(?=\s+JOIN|\s+WHERE|\s+GROUP BY|\s+ORDER BY|;|$)",
        from_part,
        re.IGNORECASE | re.DOTALL
    )
    # print(join_conds)
    for right_table, cond in join_conds:
        cond_cols = re.findall(r"(\w+)\.(\w+)", cond)
        if len(cond_cols) == 2:
            (left_table, left_col), (right_table2, right_col) = cond_cols
            left_db = table_to_db.get(left_table)
            right_db = table_to_db.get(right_table2)
            join_relations.append({
                "left_table": left_table,
                "left_col": left_col,
                "right_table": right_table2,
                "right_col": right_col,
                "dbs_involved": list({left_db, right_db})
            })

    all_cols = re.findall(r"\b\w+\.\w+\b", global_query)
    db_columns = {"hoteldb": set(), "transportdb": set()}

    for c in all_cols:
        table, column = c.split(".")
        db = table_to_db.get(table)
        if db:
            db_columns[db].add(c)

    where_hoteldb, where_transportdb = [], []
    if where_part:
        for cond in re.split(r"\s+AND\s+", where_part, flags=re.IGNORECASE):
            cols = re.findall(r"(\w+)\.(\w+)", cond)
            dbs = {table_to_db[c[0]] for c in cols if c[0] in table_to_db}
            if len(dbs) == 1:
                db = list(dbs)[0]
                if db == "hoteldb":
                    where_hoteldb.append(cond.strip())
                elif db == "transportdb":
                    where_transportdb.append(cond.strip())

    def build_from_clause(db_name):
        tables = {column.split(".")[0] for column in db_columns[db_name]}
        joins = [j for j in join_relations if len(set(j["dbs_involved"])) == 1 and j["dbs_involved"][0] == db_name]
        base_table = list(tables)[0] if tables else ""
        from_clause = base_table
        for j in joins:
            from_clause += f" JOIN {j['right_table']} ON {j['left_table']}.{j['left_col']} = {j['right_table']}.{j['right_col']}"
        return from_clause

    from_hoteldb = build_from_clause("hoteldb")
    from_transportdb = build_from_clause("transportdb")

    hotel_query = f"SELECT DISTINCT {', '.join(db_columns['hoteldb'])} FROM {from_hoteldb}"
    if where_hoteldb:
        hotel_query += " WHERE " + " AND ".join(where_hoteldb)

    transport_query = f"SELECT DISTINCT {', '.join(db_columns['transportdb'])} FROM {from_transportdb}"
    if where_transportdb:
        transport_query += " WHERE " + " AND ".join(where_transportdb)

    print("-----Local Schema Query--------------")
    print("Hotel DB Query:", hotel_query)
    print("-----Local Schema Query--------------")
    print("Transport DB Query:", transport_query)
