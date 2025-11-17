import re
import sqlglot
from sqlglot import expressions as exp

# sql_queries=[
#   "SELECT * FROM transport WHERE source = 'Delhi' AND destination = 'Shimla' ORDER BY avg_price ASC;",
# "SELECT transport_packages.package_name, transport.destination FROM transport_packages JOIN transport ON transport_packages.transport_id = transport.transport_id WHERE transport.destination = 'Shimla'; "]
# "SELECT * FROM transport;"]
# # "SELECT * FROM transport WHERE transport.mode='train';"]

# for query in (sql_queries):
#   table_pattern = re.search(r"FROM\s+(.*?)(?:\s+(WHERE|GROUP BY|ORDER BY|LIMIT)\b|;|$)", query, re.IGNORECASE)
#   table_part = table_pattern.group(1).strip() if table_pattern else None
#   if not re.search(r"\b(hotels|rooms|reviews)\b", table_part, re.IGNORECASE): qd.transportOnlyQueryDecomposer(query)
#   elif not bool(re.search(r"\btransport\b",table_part, re.IGNORECASE) or re.search(r"\btransport_packages\b",table_part, re.IGNORECASE)): qd.hotelOnlyQueryDecomposer(query)
#   else: qd.hotelAndTransportJoinedQueryDecomposer(query)

# "SELECT * FROM hotels JOIN transport ON hotels.city = transport.destination WHERE hotels.has_parking = true AND transport.avg_price < 5000 AND hotels.city = 'Goa';"]
# "SELECT hotels.name, transport.avg_price FROM hotels JOIN transport ON hotels.city = transport.destination WHERE hotels.has_parking = true AND transport.avg_price < 5000 AND hotels.city = 'Goa';"]
# sql_queries = [
#     # 1
#     "SELECT hotels.name, transport.avg_price FROM hotels JOIN transport ON hotels.city = transport.destination WHERE hotels.star_rating > 3 AND transport.avg_price < 4000;",

#     # 2
#     "SELECT transport.source, hotels.name FROM transport JOIN hotels ON transport.destination = hotels.city WHERE hotels.has_wifi = true AND transport.avg_price < 3000;",

#     # 3
#     "SELECT hotels.name, transport_packages.package_price, transport.avg_price FROM hotels JOIN transport_packages ON transport_packages.hotel_id = hotels.hotel_id JOIN transport ON transport.transport_id = transport_packages.transport_id WHERE hotels.star_rating >= 4 AND transport.avg_price < 5000;",

#     # 4
#     "SELECT transport.destination, transport_packages.package_name, hotels.city FROM transport JOIN transport_packages ON transport_packages.transport_id = transport.transport_id JOIN hotels ON hotels.hotel_id = transport_packages.hotel_id WHERE hotels.has_parking = true AND transport.avg_price < 3500;",

#     # 5
#     "SELECT hotels.name, rooms.price_per_night, transport.mode FROM hotels JOIN rooms ON rooms.hotel_id = hotels.hotel_id JOIN transport ON transport.destination = hotels.city WHERE hotels.city = 'Goa' AND transport.avg_price < 3000;",

#     # 6
#     "SELECT hotels.name, reviews.rating, transport.mode FROM hotels JOIN reviews ON reviews.hotel_id = hotels.hotel_id JOIN transport ON transport.destination = hotels.city WHERE reviews.rating >= 4 AND transport.avg_price < 5000;",

#     # 9
#     "SELECT hotels.name, rooms.room_type, reviews.rating, transport.mode FROM hotels JOIN rooms ON rooms.hotel_id = hotels.hotel_id JOIN reviews ON reviews.hotel_id = hotels.hotel_id JOIN transport ON transport.destination = hotels.city WHERE reviews.rating >= 4 AND transport.avg_price < 4000;",

#     # 10
#     "SELECT hotels.name, reviews.review_text, rooms.price_per_night, transport.mode FROM hotels JOIN reviews ON reviews.hotel_id = hotels.hotel_id JOIN rooms ON rooms.hotel_id = hotels.hotel_id JOIN transport ON transport.destination = hotels.city WHERE hotels.has_parking = true AND transport.avg_price < 2500;",

#     # 15
#     "SELECT transport.destination, transport_packages.package_price, hotels.name, rooms.room_type FROM transport JOIN transport_packages ON transport_packages.transport_id = transport.transport_id JOIN hotels ON hotels.hotel_id = transport_packages.hotel_id JOIN rooms ON rooms.hotel_id = hotels.hotel_id WHERE rooms.price_per_night < 2000;",

#     # 16
#     "SELECT transport.mode, transport_packages.package_name, hotels.name, reviews.rating FROM transport JOIN transport_packages ON transport_packages.transport_id = transport.transport_id JOIN hotels ON hotels.hotel_id = transport_packages.hotel_id JOIN reviews ON reviews.hotel_id = hotels.hotel_id WHERE reviews.rating >= 3;",

#     # 17
#     "SELECT rooms.room_type, hotels.name, transport.mode FROM rooms JOIN hotels ON hotels.hotel_id = rooms.hotel_id JOIN transport ON transport.destination = hotels.city WHERE rooms.price_per_night < 3000 AND transport.avg_price < 5000;",

#     # 18
#     "SELECT reviews.review_text, reviews.rating, hotels.name, transport.mode FROM reviews JOIN hotels ON hotels.hotel_id = reviews.hotel_id JOIN transport ON transport.source = hotels.city WHERE reviews.rating > 2;",

#     # 21
#     "SELECT transport.source, hotels.name, rooms.room_type FROM transport JOIN hotels ON hotels.city = transport.destination JOIN rooms ON rooms.hotel_id = hotels.hotel_id WHERE rooms.price_per_night < 2500;",

#     # 22 (SELECT *)
#     "SELECT * FROM hotels JOIN transport ON hotels.city = transport.destination WHERE hotels.has_wifi = true AND transport.avg_price < 5000;",

#     # 23 (hotels.*, transport column)
#     "SELECT hotels.*, transport.avg_price FROM hotels JOIN transport ON hotels.city = transport.destination WHERE hotels.city = 'Goa';",

#     # 24 (transport.*, hotels column)
#     "SELECT transport.*, hotels.name FROM transport JOIN hotels ON hotels.city = transport.destination WHERE hotels.star_rating >= 3;"
# ]


HOTEL_TABLES = {"hotels", "rooms", "reviews"}
TRANSPORT_TABLES = {"transport", "transport_packages"}


def hotelAndTransportJoinedQueryDecomposer(query):
    ast = sqlglot.parse_one(query)

    # 1) collect only columns that appear in the SELECT clause
    select_exprs = []
    star_present = any(isinstance(expr, exp.Star) for expr in (ast.args.get("expressions") or []))

    # If SELECT * → we keep '*' for BOTH queries
    if star_present:
        hotel_select_cols = ["*"]
        transport_select_cols = ["*"]
    else:
        for expr in ast.args.get("expressions", []) or []:
            if isinstance(expr, exp.Column):
                select_exprs.append(expr)
            else:
                select_exprs.extend(expr.find_all(exp.Column))

        hotel_select_cols = []
        transport_select_cols = []

        for col in select_exprs:
            table = col.table.lower() if col.table else None
            if table in HOTEL_TABLES:
                hotel_select_cols.append(col.sql())
            elif table in TRANSPORT_TABLES:
                transport_select_cols.append(col.sql())

        # dedupe while preserving order
        hotel_select_cols = list(dict.fromkeys(hotel_select_cols))
        transport_select_cols = list(dict.fromkeys(transport_select_cols))
    # print(hotel_select_cols)
    # print(transport_select_cols)
    # 2) extract join condition and join keys
    joins = list(ast.find_all(exp.Join))
    if not joins:
        raise ValueError("Not a joined hotel-transport query")

    hotel_joins = []      # hotel-only joins
    transport_joins = []  # transport-only joins
    cross_joins = []      # hotel <-> transport joins (usually 1)

    for j in joins:
        join_on = j.args["on"]
        left_expr = join_on.args["this"]
        right_expr = join_on.args["expression"]

        left_table = left_expr.table.lower() if left_expr.table else None
        right_table = right_expr.table.lower() if right_expr.table else None

        if left_table in HOTEL_TABLES and right_table in HOTEL_TABLES:
            hotel_joins.append(j)
        elif left_table in TRANSPORT_TABLES and right_table in TRANSPORT_TABLES:
            transport_joins.append(j)
        else:
            # Cross DB join (main join)
            cross_joins.append(j)

    # Use ALL cross joins to extract join keys
    if not star_present:
        join_keys = []
        for cj in cross_joins:
            jc = cj.args["on"]

            left_expr = jc.args["this"]
            right_expr = jc.args["expression"]

            left_join_col = left_expr.sql()           # e.g. hotels.city
            right_join_col = right_expr.sql()         # e.g. transport.destination

            left_table = left_expr.table.lower()
            right_table = right_expr.table.lower()

            join_keys.append((left_join_col, right_join_col))

            # ---- Add left join key to correct DB ----
            if left_table in HOTEL_TABLES:
                if left_join_col not in hotel_select_cols:
                    hotel_select_cols.append(left_join_col)
            elif left_table in TRANSPORT_TABLES:
                if left_join_col not in transport_select_cols:
                    transport_select_cols.append(left_join_col)

            # ---- Add right join key to correct DB ----
            if right_table in HOTEL_TABLES:
                if right_join_col not in hotel_select_cols:
                    hotel_select_cols.append(right_join_col)
            elif right_table in TRANSPORT_TABLES:
                if right_join_col not in transport_select_cols:
                    transport_select_cols.append(right_join_col)
    # print(hotel_select_cols)
    # print(transport_select_cols)
    # ...existing code...
    # print(hotel_select_cols)
    # print(transport_select_cols)

    # ==========================================
    #  Build correct FROM block for each DB
    # ==========================================

    # 1) Identify base table
    from_expr = ast.args.get("from")
    base_table_expr = list(from_expr.find_all(exp.Table))[0]
    base_table_name = base_table_expr.name.lower()
    # print("Base table:", base_table_name)
    # Determine hotel base table
    if base_table_name in HOTEL_TABLES:
        hotel_base = base_table_expr.sql()
    else:
        # Find transport→hotel cross-db join
        # left or right can belong to hotel
        for cj in cross_joins:
            jc = cj.args["on"]
            left_col = jc.args["this"]
            right_col = jc.args["expression"]
            left_table = left_col.table.lower()
            right_table = right_col.table.lower()
            if left_table in HOTEL_TABLES:
                hotel_base = left_table
            elif right_table in HOTEL_TABLES:
                hotel_base = right_table

    # Determine transport base table
    if base_table_name in TRANSPORT_TABLES:
        transport_base = base_table_expr.sql()
    else:
        for cj in cross_joins:
            # print("Cross join:", cj.sql())
            jc = cj.args["on"]
            left_col = jc.args["this"]
            right_col = jc.args["expression"]
            left_table = left_col.table.lower()
            right_table = right_col.table.lower()
            if left_table in TRANSPORT_TABLES:
                transport_base = left_table
            elif right_table in TRANSPORT_TABLES:
                transport_base = right_table

    hotel_from_parts = [f"{hotel_base}"]
    # print("Hotel base table:", hotel_base)
    for j in hotel_joins:
        hotel_from_parts.append(f"JOIN {j.this.sql()} ON {j.args['on'].sql()}")

    # TRANSPORT FROM BLOCK
    transport_from_parts = [f"{transport_base}"]
    # print("Transport base table:", transport_base)
    for j in transport_joins:
        transport_from_parts.append(f"JOIN {j.this.sql()} ON {j.args['on'].sql()}")

    hotel_query = "SELECT " + ", ".join(hotel_select_cols) + " "

    if hotel_from_parts:
        hotel_query += "FROM " + " ".join(hotel_from_parts) + " "

    # WHERE splitting (your existing logic)
    hotel_where = []
    transport_where = []

    if "WHERE" in query:
        where_text = query.split("WHERE", 1)[1].strip()
        raw_preds = [p.strip() for p in where_text.split("AND")]

        for pred in raw_preds:
            lower_pred = pred.lower()
            # print(pred)
            # predicate belongs to hotel db?
            if any(tbl + "." in lower_pred for tbl in HOTEL_TABLES):
                hotel_where.append(pred)

            # predicate belongs to transport db?
            elif any(tbl + "." in lower_pred for tbl in TRANSPORT_TABLES):
                transport_where.append(pred)
    
    if hotel_where:
        hotel_query += "WHERE " + " AND ".join(hotel_where)
    # print(hotel_where)
    # print(transport_where)
    # ==========================================
    # 5) Build TRANSPORT query
    # ==========================================
    transport_query = "SELECT " + ", ".join(transport_select_cols) + " "

    # FROM + JOIN (single clean space)
    if transport_from_parts:
        transport_query += "FROM " + " ".join(transport_from_parts) + " "

    # WHERE
    if transport_where:
        transport_query += "WHERE " + " AND ".join(transport_where)

    if not hotel_query.strip().endswith(";"):
        hotel_query = hotel_query.strip() + ";"

    if not transport_query.strip().endswith(";"):
        transport_query = transport_query.strip() + ";"
    # print(hotel_query.strip())
    # print(transport_query.strip())
    # print("\n")

    return {
        "hotel_global_query": hotel_query.strip(),
        "transport_global_query": transport_query.strip(),
        "join_condition": [cj.args['on'].sql() for cj in cross_joins]
    }

# for query in sql_queries:
#     match = re.search(
#         r"FROM\s+(.*?)(?=WHERE|GROUP BY|ORDER BY|LIMIT|;|$)",
#         query,
#         re.IGNORECASE | re.DOTALL
#     )
#     tables_block = match.group(1) if match else ""

#     has_hotel = bool(re.search(r"\b(hotels|rooms|reviews)\b", tables_block, re.IGNORECASE))
#     has_transport = bool(re.search(r"\b(transport|transport_packages)\b", tables_block, re.IGNORECASE))

#     if has_transport and has_hotel:
#         hotelAndTransportJoinedQueryDecomposer(query)
    