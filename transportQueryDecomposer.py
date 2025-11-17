import re
import sqlglot
from sqlglot import exp

MODES = ["train", "bus", "flight"]

TRANSPORT_TABLE = {
    "train": "train",
    "bus": "bus",
    "flight": "flight"
}

PACKAGES_TABLE = {
    "train": "train_packages",
    "bus": "bus_packages",
    "flight": "flight_packages"
}

ID_COL = {             
    "train": "train_id",
    "bus": "bus_id",
    "flight": "flight_id"
}


def transportOnlyQueryDecomposer(query):
    ast = sqlglot.parse_one(query)

    # ================
    # STEP 1 — Extract WHERE (AND-only)
    # ================
    where_expr = ast.args.get("where")
    conditions = []
    detected_mode = None

    if where_expr:
        raw = where_expr.sql()
        raw = re.sub(r"(?i)^\s*where\s+", "", raw).strip()

        raw_conditions = re.split(r"(?i)\s+AND\s+", raw)

        for cond in raw_conditions:
            c = cond.strip()

            m = re.search(
                r"(?i)\btransport(?:_packages)?\s*\.\s*mode\s*=\s*['\"]?(train|bus|flight)['\"]?",
                c
            )
            if m:
                detected_mode = m.group(1).lower()
                continue

            conditions.append(c)

    modes_to_use = [detected_mode] if detected_mode else MODES

    # ================
    # STEP 2 — SELECT analysis
    # ================
    select_exprs = ast.args.get("expressions", []) or []

    # generic SELECT *
    has_global_star = any(
        isinstance(expr, exp.Star) and expr.args.get("table") is None
        for expr in select_exprs
    )

    outputs = []

    # ================
    # STEP 3 — BUILD PER-MODE QUERIES
    # ================
    for mode in modes_to_use:
        local_trans = TRANSPORT_TABLE[mode]
        local_pack  = PACKAGES_TABLE[mode]
        local_id    = ID_COL[mode]
        
        # ==============
        # SELECT clause
        # ==============
        select_parts = []
        mode_added = False

        if has_global_star:
            select_parts.append(f"{local_trans}.*")
            select_parts.append(f"'{mode}' AS mode")
            mode_added = True

        else:
            for expr in select_exprs:

                table_expr = expr.args.get("table") if isinstance(expr, exp.Star) else None
                table_name = table_expr.name.lower() if table_expr else None

                # ---------------------------------
                # transport.*
                # ---------------------------------
                if isinstance(expr, exp.Star) and table_name == "transport":
                    select_parts.append(f"{local_trans}.*")
                    if not mode_added:
                        select_parts.append(f"'{mode}' AS mode")
                        mode_added = True
                    continue

                # ---------------------------------
                # transport_packages.*
                # ---------------------------------
                if isinstance(expr, exp.Star) and table_name == "transport_packages":
                    select_parts.append(f"{local_pack}.*")
                    if not mode_added:
                        select_parts.append(f"'{mode}' AS mode")
                        mode_added = True
                    continue

                # ---------------------------------
                # Column mapping
                # ---------------------------------
                if isinstance(expr, exp.Column):
                    tbl = expr.table.lower() if expr.table else None
                    col = expr.name.lower()

                    # transport.mode or transport_packages.mode
                    if tbl in ("transport", "transport_packages") and col == "mode":
                        if not mode_added:
                            select_parts.append(f"'{mode}' AS mode")
                            mode_added = True
                        continue

                    # transport.transport_id
                    if tbl == "transport" and col == "transport_id":
                        select_parts.append(f"{local_trans}.{local_id}")
                        continue

                    # transport_packages.transport_id
                    if tbl == "transport_packages" and col == "transport_id":
                        select_parts.append(f"{local_pack}.{local_id}")
                        continue

                    # transport.other_column
                    if tbl == "transport":
                        select_parts.append(f"{local_trans}.{expr.name}")
                        continue

                    # transport_packages.other_column
                    if tbl == "transport_packages":
                        select_parts.append(f"{local_pack}.{expr.name}")
                        continue

                    # Otherwise keep as-is
                    select_parts.append(expr.sql())
                    continue

                # Non-column expression
                select_parts.append(expr.sql())

        # If mode not added yet (rare), add it now:
        if not mode_added:
            select_parts.append(f"'{mode}' AS mode")

        select_clause = "SELECT " + ", ".join(select_parts) + " "

        # ==============
        # FROM clause
        # ==============
        base_table = None
        for t in ast.find_all(exp.Table):
            name = t.name.lower()
            if name in ("transport", "transport_packages"):
                base_table = name
                break
        # if base_table is None:
        #     base_table = "transport"

        if base_table == "transport":
            from_parts = [local_trans]
        else:
            from_parts = [local_pack]

        # ==============
        # JOIN rewriting
        # ==============
        for j in ast.find_all(exp.Join):
            right_global = j.this.name.lower()   # table being joined
            on_sql = j.args["on"].sql()

            # Rewrite ON: transport.*
            on_sql = re.sub(
                r"(?i)\btransport\s*\.\s*transport_id\b",
                f"{local_trans}.{local_id}",
                on_sql
            )
            on_sql = re.sub(
                r"(?i)\btransport\s*\.\s*([a-zA-Z0-9_]+)\b",
                lambda m: f"{local_trans}.{m.group(1)}",
                on_sql
            )

            # Rewrite ON: transport_packages.*
            on_sql = re.sub(
                r"(?i)\btransport_packages\s*\.\s*transport_id\b",
                f"{local_pack}.{local_id}",
                on_sql
            )
            on_sql = re.sub(
                r"(?i)\btransport_packages\s*\.\s*([a-zA-Z0-9_]+)\b",
                lambda m: f"{local_pack}.{m.group(1)}",
                on_sql
            )

            # map join table
            if right_global == "transport":
                join_table = local_trans
            elif right_global == "transport_packages":
                join_table = local_pack
            else:
                join_table = right_global

            from_parts.append(f"JOIN {join_table} ON {on_sql}")

        from_clause = "FROM " + " ".join(from_parts) + " "

        # ==============
        # WHERE rewriting
        # ==============
        if conditions:
            rewritten = []
            for c in conditions:
                c2 = re.sub(
                    r"(?i)\btransport\s*\.\s*transport_id\b",
                    f"{local_trans}.{local_id}",
                    c
                )
                c2 = re.sub(
                    r"(?i)\btransport\s*\.\s*([a-zA-Z0-9_]+)\b",
                    lambda m: f"{local_trans}.{m.group(1)}",
                    c2
                )
                c2 = re.sub(
                    r"(?i)\btransport_packages\s*\.\s*transport_id\b",
                    f"{local_pack}.{local_id}",
                    c2
                )
                c2 = re.sub(
                    r"(?i)\btransport_packages\s*\.\s*([a-zA-Z0-9_]+)\b",
                    lambda m: f"{local_pack}.{m.group(1)}",
                    c2
                )
                rewritten.append(c2)

            where_clause = "WHERE " + " AND ".join(rewritten) + " "
        else:
            where_clause = ""

        # ==============
        # Final SQL
        # ==============
        sql = (select_clause + from_clause + where_clause).strip()
        if not sql.endswith(";"):
            sql += ";"

        outputs.append(sql)
    # print(outputs)
    return outputs


sql_queries = [
# "SELECT transport.mode, transport.transport_id, transport.source, transport.destination, transport.avg_price, transport_packages.package_id, transport_packages.package_name, transport_packages.package_price, transport_packages.mode FROM transport JOIN transport_packages ON transport_packages.transport_id = transport.transport_id WHERE transport.mode = 'train' AND transport.avg_price < 5000 AND transport.destination = 'Goa' AND transport_packages.package_price >= 2000 AND transport_packages.package_name = 'Summer Special';"
# "SELECT transport.mode, transport.transport_id, transport.source, transport.destination, transport.avg_price, transport_packages.package_id, transport_packages.package_name, transport_packages.package_price, transport_packages.mode FROM transport JOIN transport_packages ON transport_packages.transport_id = transport.transport_id WHERE transport.avg_price < 5000 AND transport.destination = 'Goa' AND transport_packages.package_price >= 2000 AND transport_packages.package_name = 'Summer Special';"
# "SELECT *  FROM transport WHERE transport.avg_price < 2500 AND transport.source = 'Delhi';"
# "SELECT transport.avg_price, transport_packages.package_name  FROM transport JOIN transport_packages ON transport_packages.transport_id = transport.transport_id WHERE transport_packages.mode = 'bus' AND transport.avg_price < 4000;"
# "SELECT transport.mode, transport_packages.mode, transport.destination FROM transport JOIN transport_packages ON transport_packages.transport_id = transport.transport_id WHERE transport.destination = 'Chennai';"
# "SELECT transport.transport_id, transport_packages.transport_id, transport.avg_price FROM transport JOIN transport_packages ON transport_packages.transport_id = transport.transport_id WHERE transport.transport_id > 50 AND transport_packages.transport_id > 100 AND transport.avg_price BETWEEN 2000 AND 6000;"
"SELECT transport.price, transport_packages.package_name  FROM transport_packages JOIN transport ON transport_packages.transport_id = transport.transport_id WHERE transport_packages.mode = 'bus' AND transport.price < 4000;"
]


# for query in sql_queries:
#     match = re.search(
#         r"FROM\s+(.*?)(?=WHERE|GROUP BY|ORDER BY|LIMIT|;|$)",
#         query,
#         re.IGNORECASE | re.DOTALL
#     )
#     tables_block = match.group(1) if match else ""

#     has_hotel = bool(re.search(r"\b(hotels|rooms|reviews)\b", tables_block, re.IGNORECASE))
#     has_transport = bool(re.search(r"\b(transport|transport_packages)\b", tables_block, re.IGNORECASE))

#     if has_transport:
#         transportOnlyQueryDecomposer(query)