import frappe
from frappe.utils import nowdate, add_days, flt


def update_dashboard_cache():
    """Daily scheduled task to update dashboard cache (placeholder for future optimization)."""
    pass


@frappe.whitelist()
def get_dashboard_data(location=None, from_date=None, to_date=None, company=None):
    """
    Get dashboard data for Gas Agency Dashboard page.
    Returns stock summary, sales summary, revenue, and recent exchange logs.
    """
    if not from_date:
        from_date = add_days(nowdate(), -30)
    if not to_date:
        to_date = nowdate()

    filters = {}
    if company:
        filters["company"] = company

    locations = _get_locations(location, company)

    return {
        "stock_summary": _get_stock_summary(locations),
        "sales_summary": _get_sales_summary(locations, from_date, to_date),
        "revenue_summary": _get_revenue_summary(locations, from_date, to_date),
        "exchange_logs": _get_recent_exchange_logs(location),
    }


def _get_locations(location=None, company=None):
    """Get list of Gas Agency Locations."""
    filters = {"is_active": 1}
    if location:
        filters["name"] = location
    if company:
        filters["company"] = company

    return frappe.get_all(
        "Gas Agency Location",
        filters=filters,
        fields=["name", "location_name", "warehouse", "default_target_warehouse", "company"],
        order_by="location_name asc",
    )


def _get_stock_summary(locations):
    """Get location-wise stock of filled and empty cylinders."""
    if not locations:
        return []

    # Get all exchange rules to identify filled/empty items
    rules = frappe.get_all(
        "Cylinder Exchange Rule",
        filters={"is_active": 1},
        fields=["filled_item", "empty_item", "filled_weight_kg", "empty_weight_kg"],
        order_by="creation asc",
    )

    filled_items = {r.filled_item for r in rules}
    empty_items = {r.empty_item for r in rules}

    # Build weight lookup
    filled_weight = {r.filled_item: flt(r.filled_weight_kg) for r in rules}
    empty_weight = {r.empty_item: flt(r.empty_weight_kg) for r in rules}

    summary = []
    for loc in locations:
        warehouses = [loc.warehouse]
        if loc.default_target_warehouse:
            warehouses.append(loc.default_target_warehouse)

        bins = frappe.get_all(
            "Bin",
            filters={
                "warehouse": ["in", warehouses],
                "item_code": ["in", list(filled_items | empty_items)],
            },
            fields=["item_code", "actual_qty", "warehouse"],
            order_by="item_code asc",
        )

        filled_qty = 0
        empty_qty = 0
        filled_kg = 0
        empty_kg = 0

        for b in bins:
            if b.item_code in filled_items:
                filled_qty += flt(b.actual_qty)
                filled_kg += flt(b.actual_qty) * filled_weight.get(b.item_code, 0)
            elif b.item_code in empty_items:
                empty_qty += flt(b.actual_qty)
                empty_kg += flt(b.actual_qty) * empty_weight.get(b.item_code, 0)

        summary.append({
            "location": loc.name,
            "filled_qty": filled_qty,
            "empty_qty": empty_qty,
            "filled_kg": filled_kg,
            "empty_kg": empty_kg,
        })

    return summary


def _get_sales_summary(locations, from_date, to_date):
    """Get location-wise sales count."""
    if not locations:
        return []

    summary = []
    for loc in locations:
        count = frappe.db.count(
            "Sales Invoice",
            filters={
                "gas_agency_location": loc.name,
                "posting_date": ["between", [from_date, to_date]],
                "docstatus": 1,
            },
        )
        summary.append({
            "location": loc.name,
            "sales_count": count,
        })

    return summary


def _get_revenue_summary(locations, from_date, to_date):
    """Get location-wise revenue."""
    if not locations:
        return []

    summary = []
    for loc in locations:
        result = frappe.db.sql(
            """
            SELECT COALESCE(SUM(grand_total), 0) as total_revenue
            FROM `tabSales Invoice`
            WHERE gas_agency_location = %s
            AND posting_date BETWEEN %s AND %s
            AND docstatus = 1
            """,
            (loc.name, from_date, to_date),
            as_dict=True,
        )
        summary.append({
            "location": loc.name,
            "total_revenue": flt(result[0].total_revenue) if result else 0,
        })

    return summary


def _get_recent_exchange_logs(location=None):
    """Get recent cylinder exchange logs."""
    filters = {"status": "Completed"}
    if location:
        filters["location"] = location

    return frappe.get_all(
        "Cylinder Exchange Log",
        filters=filters,
        fields=[
            "name", "source_doctype", "source_name", "location",
            "filled_item", "empty_item", "qty", "weight_kg",
            "exchange_date", "status", "stock_entry",
        ],
        order_by="creation desc",
        limit_page_length=20,
    )
