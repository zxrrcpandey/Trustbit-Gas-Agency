import frappe
from frappe.utils import add_days, cint, flt, getdate, nowdate


@frappe.whitelist()
def get_dashboard_data(location=None, from_date=None, to_date=None, company=None):
    """
    Get dashboard data for the Gas Agency Dashboard page: per location, the
    period's purchases, sales, collections and empties movement, what is
    still to pay and to collect, and the stock in hand; plus a daily sales
    trend and the recent exchange logs.
    """
    # The data below is read without permission checks, so apply the Gas
    # Agency Dashboard page's access (its roles plus any added in Role
    # Permission for Page and Report) to the API itself
    if not frappe.get_cached_doc("Page", "gas-agency-dashboard").is_permitted():
        raise frappe.PermissionError

    if not from_date:
        from_date = add_days(nowdate(), -30)
    if not to_date:
        to_date = nowdate()

    # No company means all companies
    locations = _get_locations(location, company)
    cylinders = _get_cylinder_items()

    return {
        # Dropdown choices: every company, and the active locations of the
        # chosen company (of all companies when none is chosen)
        "company_options": frappe.get_all("Company", pluck="name", order_by="name asc"),
        "location_options": [loc.name for loc in _get_locations(company=company)],
        "locations": [
            _get_location_summary(loc, cylinders, from_date, to_date) for loc in locations
        ],
        "daily_sales": _get_daily_sales(locations, from_date, to_date),
        "exchange_logs": _get_recent_exchange_logs(locations, from_date, to_date),
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
        fields=[
            "name", "location_name", "warehouse", "default_target_warehouse",
            "company", "min_filled_qty",
        ],
        order_by="location_name asc",
    )


def _get_cylinder_items():
    """Filled and empty cylinder items from the active exchange rules, with their KG."""
    rules = frappe.get_all(
        "Cylinder Exchange Rule",
        filters={"is_active": 1},
        fields=["filled_item", "empty_item", "filled_weight_kg", "empty_weight_kg"],
    )
    return frappe._dict(
        filled={r.filled_item: flt(r.filled_weight_kg) for r in rules},
        empty={r.empty_item: flt(r.empty_weight_kg) for r in rules},
    )


def _get_location_summary(loc, cylinders, from_date, to_date):
    """Every dashboard figure for one location."""
    warehouses = tuple(w for w in (loc.warehouse, loc.default_target_warehouse) if w)

    summary = frappe._dict(location=loc.name, min_filled_qty=cint(loc.min_filled_qty))
    summary.update(_get_stock(warehouses, cylinders))
    summary.update(_get_purchases(warehouses, cylinders, from_date, to_date))
    summary.update(_get_sales(loc.name, cylinders, from_date, to_date))
    summary.update(_get_empties_movement(loc.name, warehouses, cylinders, from_date, to_date))
    summary.pending_purchase = _get_pending_purchase(warehouses)
    summary.pending_sales = _get_pending_sales(loc.name)
    summary.collected = _get_collected(loc.name, from_date, to_date)
    summary.low_stock = bool(summary.min_filled_qty) and summary.filled_qty < summary.min_filled_qty
    return summary


def _get_stock(warehouses, cylinders):
    """Filled and empty cylinders in hand at the location's warehouses, in qty and KG."""
    stock = frappe._dict(filled_qty=0, empty_qty=0, filled_kg=0, empty_kg=0)
    items = list(cylinders.filled) + list(cylinders.empty)
    if not warehouses or not items:
        return stock

    bins = frappe.get_all(
        "Bin",
        filters={"warehouse": ["in", warehouses], "item_code": ["in", items]},
        fields=["item_code", "actual_qty"],
    )
    for b in bins:
        if b.item_code in cylinders.filled:
            stock.filled_qty += flt(b.actual_qty)
            stock.filled_kg += flt(b.actual_qty) * cylinders.filled[b.item_code]
        else:
            stock.empty_qty += flt(b.actual_qty)
            stock.empty_kg += flt(b.actual_qty) * cylinders.empty[b.item_code]
    return stock


def _get_purchases(warehouses, cylinders, from_date, to_date):
    """
    What came in from suppliers in the period: filled cylinders received, and
    the value of everything received (at valuation, so excluding GST). Read
    from the stock ledger so a Purchase Receipt and a Purchase Invoice with
    Update Stock each count once; purchase returns net out.
    """
    if not warehouses:
        return {"purchase_qty": 0, "purchase_amount": 0}

    rows = frappe.db.sql(
        """
        SELECT item_code, SUM(actual_qty) AS qty, SUM(stock_value_difference) AS amount
        FROM `tabStock Ledger Entry`
        WHERE is_cancelled = 0
        AND voucher_type IN ('Purchase Receipt', 'Purchase Invoice')
        AND warehouse IN %(warehouses)s
        AND posting_date BETWEEN %(from_date)s AND %(to_date)s
        GROUP BY item_code
        """,
        {"warehouses": warehouses, "from_date": from_date, "to_date": to_date},
        as_dict=True,
    )
    return {
        "purchase_qty": sum(flt(r.qty) for r in rows if r.item_code in cylinders.filled),
        "purchase_amount": sum(flt(r.amount) for r in rows),
    }


def _get_pending_purchase(warehouses):
    """
    Unpaid supplier bills for goods that went into the location's warehouses,
    whether billed with Update Stock or against a Purchase Receipt.
    """
    if not warehouses:
        return 0

    return flt(
        frappe.db.sql(
            """
            SELECT COALESCE(SUM(pi.outstanding_amount), 0)
            FROM `tabPurchase Invoice` pi
            WHERE pi.docstatus = 1
            AND pi.outstanding_amount != 0
            AND EXISTS (
                SELECT 1
                FROM `tabPurchase Invoice Item` pii
                LEFT JOIN `tabPurchase Receipt Item` pri ON pri.name = pii.pr_detail
                WHERE pii.parent = pi.name
                AND COALESCE(NULLIF(pii.warehouse, ''), pri.warehouse) IN %(warehouses)s
            )
            """,
            {"warehouses": warehouses},
        )[0][0]
    )


def _get_sales(location, cylinders, from_date, to_date):
    """
    Sales in the period on invoices tagged with the location: filled
    cylinders sold with their KG, and the amount excluding GST. Credit notes
    carry negative quantities and amounts, so returns net out.
    """
    params = {"location": location, "from_date": from_date, "to_date": to_date}
    amount = frappe.db.sql(
        """
        SELECT COALESCE(SUM(base_net_total), 0)
        FROM `tabSales Invoice`
        WHERE docstatus = 1
        AND gas_agency_location = %(location)s
        AND posting_date BETWEEN %(from_date)s AND %(to_date)s
        """,
        params,
    )[0][0]

    rows = frappe.db.sql(
        """
        SELECT sii.item_code, SUM(sii.stock_qty) AS qty
        FROM `tabSales Invoice Item` sii
        INNER JOIN `tabSales Invoice` si ON si.name = sii.parent
        WHERE si.docstatus = 1
        AND si.gas_agency_location = %(location)s
        AND si.posting_date BETWEEN %(from_date)s AND %(to_date)s
        GROUP BY sii.item_code
        """,
        params,
        as_dict=True,
    )
    filled_rows = [r for r in rows if r.item_code in cylinders.filled]
    return {
        "sales_amount": flt(amount),
        "sales_qty": sum(flt(r.qty) for r in filled_rows),
        "sales_kg": sum(flt(r.qty) * cylinders.filled[r.item_code] for r in filled_rows),
    }


def _get_pending_sales(location):
    """Unpaid amounts on the location's invoices (credit notes reduce it)."""
    return flt(
        frappe.db.sql(
            """
            SELECT COALESCE(SUM(outstanding_amount), 0)
            FROM `tabSales Invoice`
            WHERE docstatus = 1 AND gas_agency_location = %s
            """,
            location,
        )[0][0]
    )


def _get_collected(location, from_date, to_date):
    """
    Money received in the period for the location's invoices: payments taken
    at the counter on POS invoices, plus Payment Entries allocated to them.
    """
    params = {"location": location, "from_date": from_date, "to_date": to_date}
    at_counter = frappe.db.sql(
        """
        SELECT COALESCE(SUM(base_paid_amount - base_change_amount), 0)
        FROM `tabSales Invoice`
        WHERE docstatus = 1 AND is_pos = 1
        AND gas_agency_location = %(location)s
        AND posting_date BETWEEN %(from_date)s AND %(to_date)s
        """,
        params,
    )[0][0]

    by_payment_entry = frappe.db.sql(
        """
        SELECT COALESCE(SUM(per.allocated_amount), 0)
        FROM `tabPayment Entry Reference` per
        INNER JOIN `tabPayment Entry` pe ON pe.name = per.parent
        INNER JOIN `tabSales Invoice` si ON si.name = per.reference_name
        WHERE pe.docstatus = 1 AND pe.payment_type = 'Receive'
        AND per.reference_doctype = 'Sales Invoice'
        AND si.gas_agency_location = %(location)s
        AND pe.posting_date BETWEEN %(from_date)s AND %(to_date)s
        """,
        params,
    )[0][0]
    return flt(at_counter) + flt(by_payment_entry)


def _get_empties_movement(location, warehouses, cylinders, from_date, to_date):
    """
    Empties taken in from customers in the period (the exchange logs, net of
    those given back on returns), and empties that otherwise left the
    location's warehouses, e.g. sent back to the plant.
    """
    empties_in = frappe.db.sql(
        """
        SELECT COALESCE(SUM(qty), 0)
        FROM `tabCylinder Exchange Log`
        WHERE status = 'Completed' AND location = %s
        AND exchange_date BETWEEN %s AND %s
        """,
        (location, from_date, to_date),
    )[0][0]

    empties_out = 0
    if warehouses and cylinders.empty:
        empties_out = frappe.db.sql(
            """
            SELECT COALESCE(-SUM(sle.actual_qty), 0)
            FROM `tabStock Ledger Entry` sle
            WHERE sle.is_cancelled = 0 AND sle.actual_qty < 0
            AND sle.item_code IN %(items)s
            AND sle.warehouse IN %(warehouses)s
            AND sle.posting_date BETWEEN %(from_date)s AND %(to_date)s
            AND NOT EXISTS (
                SELECT 1 FROM `tabCylinder Exchange Log` cxl
                WHERE cxl.stock_entry = sle.voucher_no
            )
            """,
            {
                "items": tuple(cylinders.empty),
                "warehouses": warehouses,
                "from_date": from_date,
                "to_date": to_date,
            },
        )[0][0]

    return {"empties_in": flt(empties_in), "empties_out": flt(empties_out)}


def _get_daily_sales(locations, from_date, to_date):
    """Sales amount (excluding GST) for each day of the period across the shown locations."""
    if not locations:
        return []

    rows = frappe.db.sql(
        """
        SELECT posting_date, SUM(base_net_total) AS amount
        FROM `tabSales Invoice`
        WHERE docstatus = 1
        AND gas_agency_location IN %(locations)s
        AND posting_date BETWEEN %(from_date)s AND %(to_date)s
        GROUP BY posting_date
        """,
        {
            "locations": tuple(loc.name for loc in locations),
            "from_date": from_date,
            "to_date": to_date,
        },
        as_dict=True,
    )
    by_date = {getdate(r.posting_date): flt(r.amount) for r in rows}

    days = []
    day, last_day = getdate(from_date), getdate(to_date)
    while day <= last_day:
        days.append({"date": str(day), "amount": by_date.get(day, 0)})
        day = add_days(day, 1)
    return days


def _get_recent_exchange_logs(locations, from_date=None, to_date=None):
    """Get recent cylinder exchange logs — all statuses, so failures stay visible.

    Scoped to the same resolved location set as the other dashboard panels,
    so the company filter applies here too. Logs without a location cannot be
    attributed to any company, so they are always shown rather than buried.
    """
    filters = {}
    if from_date and to_date:
        filters["exchange_date"] = ["between", [from_date, to_date]]

    return frappe.get_all(
        "Cylinder Exchange Log",
        filters=filters,
        or_filters=[
            ["location", "in", [loc.name for loc in locations]],
            ["location", "is", "not set"],
        ],
        fields=[
            "name", "source_doctype", "source_name", "location",
            "filled_item", "empty_item", "qty", "weight_kg",
            "exchange_date", "status", "stock_entry", "error_message",
        ],
        order_by="creation desc",
        limit_page_length=20,
    )
