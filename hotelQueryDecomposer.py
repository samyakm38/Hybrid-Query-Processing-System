import re
import sqlglot
from sqlglot import expressions as exp

# -----------------------------------------------------------
# GLOBAL → LOCAL COLUMN MAP FOR HOTELS
# -----------------------------------------------------------
HOTEL_COLUMN_MAP = {
    "hotels.name": "hotels_basic.name",
    "hotels.city": "hotels_basic.city",
    "hotels.state": "hotels_basic.state",
    "hotels.complete_address": "hotels_basic.complete_address",
    "hotels.hotel_id": "hotels_basic.hotel_id",

    "hotels.star_rating": "hotel_facilities.star_rating",
    "hotels.has_wifi": "hotel_facilities.has_wifi",
    "hotels.has_parking": "hotel_facilities.has_parking",
    "hotels.has_breakfast": "hotel_facilities.has_breakfast",
    "hotels.has_swimming_pool": "hotel_facilities.has_swimming_pool",

    "hotels.email_id": "hotel_contact.email_id",
    "hotels.phone_no": "hotel_contact.phone_no",
}

HOTEL_TABLES = {"hotels", "rooms", "reviews"}


# -----------------------------------------------------------
# Helper — rewrite hotels.* columns
# -----------------------------------------------------------
def rewrite_hotel_column(col: exp.Column):
    if not col.table:
        return col.sql()

    key = f"{col.table.lower()}.{col.name.lower()}"
    return HOTEL_COLUMN_MAP.get(key, col.sql())


# -----------------------------------------------------------
# MAIN FUNCTION
# -----------------------------------------------------------
def hotelOnlyQueryDecomposer(query: str):
    ast = sqlglot.parse_one(query)

    # ===========================================================
    # STEP 0 — detect if hotels table appears at all
    # ===========================================================
    tables = {t.name.lower() for t in ast.find_all(exp.Table)}
    uses_hotels = "hotels" in tables

    # If no hotels table → leave query unchanged (rooms-only or reviews-only)
    if not uses_hotels:
        # Ensure semicolon consistency
        q = query.strip()
        return q if q.endswith(";") else q + ";"

    # ===========================================================
    # STEP 1 — rewrite SELECT clause
    # ===========================================================
    select_exprs = ast.args.get("expressions", [])
    select_list = []

    # --------------------------------------------------------
    # CASE 1 — SELECT *
    # --------------------------------------------------------
    # If ANY select expression is a Star → keep SELECT * as-is
    if any(isinstance(expr, exp.Star) for expr in select_exprs):
        select_clause = "SELECT * "
    else:
        # --------------------------------------------------------
        # CASE 2 — Rewrite SELECT expressions (no SELECT *)
        # --------------------------------------------------------
        for expr in select_exprs:

            # hotels.* → expand into 3 hotel tables
            if (
                isinstance(expr, exp.Column)
                and expr.name == "*"
                and expr.table
                and expr.table.lower() == "hotels"
            ):
                select_list.extend([
                    "hotels_basic.*",
                    "hotel_facilities.*",
                    "hotel_contact.*"
                ])
                continue

            # Normal column: hotels.col or rooms.col or reviews.col
            if isinstance(expr, exp.Column):
                select_list.append(rewrite_hotel_column(expr))
                continue

            # Complex expression (function, arithmetic, etc.)
            rewritten = expr.sql()
            for col in expr.find_all(exp.Column):
                rewritten = rewritten.replace(col.sql(), rewrite_hotel_column(col))
            select_list.append(rewritten)

        # Build SELECT clause
        select_clause = "SELECT " + ", ".join(select_list) + " "
    # for col in select_list:
    #     print(col)
    # ===========================================================
    # STEP 2 — FROM + JOIN reconstruction
    # ===========================================================
    # Hotels becomes the base table ALWAYS
    from_parts = [
    "hotels_basic",
    "LEFT JOIN hotel_facilities ON hotel_facilities.hotel_id = hotels_basic.hotel_id",
    "LEFT JOIN hotel_contact ON hotel_contact.hotel_id = hotels_basic.hotel_id",
    ]

    # Collect joins in the order they appear
    for j in ast.find_all(exp.Join):
        # print (j)
        on_expr = j.args["on"]
        on_sql = on_expr.sql()

        # Rewrite hotels.* using mapping
        for gcol, lcol in HOTEL_COLUMN_MAP.items():
            on_sql = on_sql.replace(gcol, lcol)

        # Table introduced by this JOIN
        right_table = j.this.name.lower()

        # Tables referenced in ON clause
        tables_in_on = {
            col.table.lower()
            for col in on_expr.find_all(exp.Column)
            if col.table  # skip None
        }
        # print(tables_in_on)
        # -------------------------------------------------
        # CASE 1 — JOIN introduces HOTELS → must reverse
        # -------------------------------------------------
        if right_table == "hotels":
            # remove 'hotels' to find the child table (rooms/reviews)
            other_tables = tables_in_on - {"hotels"}
            # print("yes")
            # print(other_tables)
            if not other_tables:
                continue   # malformed join

            other = other_tables.pop()  # e.g., "rooms" or "reviews"
            from_parts.append(f"JOIN {other} ON {on_sql}")
            continue

        # -------------------------------------------------
        # CASE 2 — Normal child-table JOIN (rooms/reviews)
        # -------------------------------------------------
        if right_table in ("rooms", "reviews"):
            from_parts.append(f"JOIN {right_table} ON {on_sql}")
            continue
        
    # print(from_parts)
    from_clause = "FROM " + " ".join(from_parts) + " "

    # ===========================================================
    # STEP 3 — WHERE clause rewrite (simple AND-only logic)
    # ===========================================================
    where_clause = ""
    where_expr = ast.args.get("where")

    if where_expr:
        # Get WHERE string without "WHERE"
        where_str = where_expr.sql()[6:].strip()

        # Split into individual conditions
        conditions = [c.strip() for c in where_str.split("AND")]

        rewritten_conditions = []
        for cond in conditions:
            new_cond = cond
            # Rewrite hotels.column → local schema tables
            for gcol, lcol in HOTEL_COLUMN_MAP.items():
                new_cond = new_cond.replace(gcol, lcol)
            rewritten_conditions.append(new_cond)

        where_clause = "WHERE " + " AND ".join(rewritten_conditions) + " "

    # ===========================================================
    # FINAL QUERY
    # ===========================================================
    final_sql = (select_clause + from_clause + where_clause).strip()

    if not final_sql.endswith(";"):
        final_sql += ";"
    # print(final_sql)
    return final_sql


sql_queries = [
# "SELECT hotels.name, hotels.city, hotels.star_rating, hotels.has_wifi, hotels.phone_no, rooms.room_type, rooms.price_per_night, reviews.rating, reviews.review_text FROM hotels JOIN rooms ON rooms.hotel_id = hotels.hotel_id JOIN reviews ON reviews.hotel_id = hotels.hotel_id WHERE hotels.city = 'Goa' AND hotels.star_rating >= 4 AND hotels.has_wifi = true AND rooms.price_per_night < 2500 AND reviews.rating >= 3;"]
# "SELECT * FROM hotels WHERE hotels.star_rating > 3;"]
# "SELECT hotels.*, hotels.city FROM hotels WHERE hotels.has_wifi = true AND hotels.has_parking = true;"]
# "SELECT rooms.room_type, hotels.name FROM rooms JOIN hotels ON rooms.hotel_id = hotels.hotel_id WHERE rooms.price_per_night < 1500;"]
"SELECT hotels.hotel_id, hotels.name, hotels.city FROM hotels WHERE hotels.city = 'Delhi';"]
# "SELECT hotels.name, reviews.rating FROM hotels JOIN reviews ON reviews.hotel_id = hotels.hotel_id WHERE reviews.rating >= 4 AND hotels.city = 'Delhi';"]



# for query in sql_queries:
#     match = re.search(
#         r"FROM\s+(.*?)(?=WHERE|GROUP BY|ORDER BY|LIMIT|;|$)",
#         query,
#         re.IGNORECASE | re.DOTALL
#     )
#     tables_block = match.group(1) if match else ""

#     has_hotel = bool(re.search(r"\b(hotels|rooms|reviews)\b", tables_block, re.IGNORECASE))
#     has_transport = bool(re.search(r"\b(transport|transport_packages)\b", tables_block, re.IGNORECASE))

#     if has_hotel:
#         hotelOnlyQueryDecomposer(query)