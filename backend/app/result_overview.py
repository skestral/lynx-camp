"""Bounded result pages and complete rollups, independent of the legacy list cap."""
from .db import utc_now
from .schemas import ResultFilters, ResultOverviewQuery


PARK = "COALESCE(NULLIF(t.park_name, ''), 'Unassigned park')"
JOINS = "FROM results r JOIN targets t ON t.id = r.target_id JOIN watches w ON w.id = r.watch_id"
METRICS = """
    COUNT(*) AS match_count,
    COALESCE(SUM(CASE WHEN active = 1 AND status IN ('available', 'opened') THEN 1 ELSE 0 END), 0) AS active_count,
    COUNT(DISTINCT campground_id) AS campground_count,
    COUNT(DISTINCT park_name) AS park_count,
    COUNT(DISTINCT json_array(campground_id, campsite_id)) AS site_count,
    COUNT(DISTINCT json_array(arrival_date, departure_date)) AS stay_count,
    MIN(arrival_date) AS first_arrival, MAX(departure_date) AS last_departure,
    MAX(last_seen_at) AS last_seen_at, MAX(discovered_at) AS newest_at
"""
GROUPS = {
    "park": ("park_name", "park_name"),
    "campground": ("park_name, campground_id", "park_name, campground_id, MAX(target_name) AS campground_name"),
    "stay": ("arrival_date, departure_date", "arrival_date, departure_date"),
}


def _where(filters: ResultFilters):
    clauses, params = [], []
    if filters.view == "active":
        clauses.append("r.active = 1 AND r.status IN ('available', 'opened')")
    elif filters.view != "all":
        clauses.append("r.status = ?")
        params.append(filters.view)
    if filters.park_name is not None:
        clauses.append(f"{PARK} = ?")
        params.append(filters.park_name)
    if filters.campground_id is not None:
        clauses.append("r.campground_id = ?")
        params.append(filters.campground_id)
    if filters.campground_ids:
        clauses.append(f"r.campground_id IN ({','.join('?' for _ in filters.campground_ids)})")
        params.extend(filters.campground_ids)
    if filters.arrival is not None:
        clauses.append("r.arrival_date <= ? AND r.departure_date >= ?")
        params.extend([filters.arrival.isoformat(), filters.departure.isoformat()])
    if filters.exact_arrival is not None:
        clauses.append("r.arrival_date = ? AND r.departure_date = ?")
        params.extend([filters.exact_arrival.isoformat(), filters.exact_departure.isoformat()])
    if filters.max_result_id is not None:
        clauses.append("r.id <= ?")
        params.append(filters.max_result_id)
    search = filters.search.strip().casefold()
    if search:
        columns = [PARK, "t.name", "r.campground_name", "r.site", "r.loop", "r.campsite_type",
                   "w.name", "r.arrival_date", "r.departure_date"]
        # INSTR gives literal substring matching; '%' and '_' are not wildcards.
        clauses.append("(" + " OR ".join(f"INSTR(CASEFOLD(COALESCE({column}, '')), ?) > 0" for column in columns) + ")")
        params.extend([search] * len(columns))
    return " AND ".join(clauses) or "1 = 1", params


def read_overview(store, options: ResultOverviewQuery) -> dict:
    with store.connect() as conn:
        conn.create_function("CASEFOLD", 1, str.casefold, deterministic=True)
        conn.execute("BEGIN")
        boundary = options.max_result_id
        if boundary is None:
            boundary = conn.execute("SELECT COALESCE(MAX(id), 0) FROM results").fetchone()[0]
        where, params = _where(options.model_copy(update={"max_result_id": boundary}))
        cte = f"""WITH matched AS (
            SELECT r.*, w.name AS watch_name, t.name AS target_name, {PARK} AS park_name, t.state_code
            {JOINS} WHERE {where}
        )"""
        summary = dict(conn.execute(f"{cte} SELECT {METRICS} FROM matched", params).fetchone())
        if options.group_by == "items":
            order = {"arrival": "arrival_date, departure_date, site COLLATE NOCASE, id",
                     "park": "park_name COLLATE NOCASE, target_name COLLATE NOCASE, arrival_date, id",
                     "newest": "discovered_at DESC, id DESC"}[options.sort]
            rows = conn.execute(f"{cte} SELECT * FROM matched ORDER BY {order} LIMIT ? OFFSET ?",
                                [*params, options.limit, options.offset]).fetchall()
            total = summary["match_count"]
            groups, results = [], [dict(row) for row in rows]
        else:
            keys, columns = GROUPS[options.group_by]
            total = conn.execute(f"{cte} SELECT COUNT(*) FROM (SELECT 1 FROM matched GROUP BY {keys})", params).fetchone()[0]
            order = {"arrival": f"first_arrival, {keys}", "park": keys,
                     "newest": f"newest_at DESC, {keys}"}[options.sort]
            rows = conn.execute(f"""{cte} SELECT {columns}, {METRICS} FROM matched
                GROUP BY {keys} ORDER BY {order} LIMIT ? OFFSET ?""", [*params, options.limit, options.offset]).fetchall()
            groups, results = [dict(row) for row in rows], []
        return {"summary": summary, "groups": groups, "results": results, "total_groups": total,
                "offset": options.offset, "limit": options.limit, "has_more": options.offset + options.limit < total,
                "snapshot_max_id": boundary}


def dismiss_scope(store, filters: ResultFilters) -> int:
    where, params = _where(filters)
    with store.connect() as conn:
        conn.create_function("CASEFOLD", 1, str.casefold, deterministic=True)
        cursor = conn.execute(f"""UPDATE results
            SET status = 'dismissed', active = 0, notification_pending = 0, auto_missing = 0,
                dismissed_at = COALESCE(dismissed_at, ?)
            WHERE id IN (SELECT r.id {JOINS} WHERE {where}
                AND r.active = 1 AND r.status IN ('available', 'opened'))""", [utc_now(), *params])
        return cursor.rowcount
