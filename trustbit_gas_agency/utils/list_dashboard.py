import frappe
from frappe.utils import add_days, flt, nowdate

from trustbit_gas_agency.trustbit_gas_agency.report.credit_sales.credit_sales import credit_type
from trustbit_gas_agency.utils.stock_utils import _get_cylinder_items, _get_locations, _get_stock

LIMIT = 10

# The branch conditions below narrow a list to one branch: Sales Invoices by
# their Gas Agency Location, everything else by the branch's warehouses.
PURCHASE_INVOICE_IN_BRANCH = """
    EXISTS (
        SELECT 1 FROM `tabPurchase Invoice Item` i
        LEFT JOIN `tabPurchase Receipt Item` pri ON pri.name = i.pr_detail
        WHERE i.parent = d.name
        AND COALESCE(NULLIF(i.warehouse, ''), pri.warehouse) IN %(warehouses)s
    )
"""

# (doctype, date field, party field, branch condition)
PURCHASE_DOCTYPES = [
    ("Purchase Order", "transaction_date", "supplier",
     "EXISTS (SELECT 1 FROM `tabPurchase Order Item` i WHERE i.parent = d.name AND i.warehouse IN %(warehouses)s)"),
    ("Purchase Receipt", "posting_date", "supplier",
     "EXISTS (SELECT 1 FROM `tabPurchase Receipt Item` i WHERE i.parent = d.name AND i.warehouse IN %(warehouses)s)"),
    ("Purchase Invoice", "posting_date", "supplier", PURCHASE_INVOICE_IN_BRANCH),
]
SALES_DOCTYPES = [
    ("Sales Order", "transaction_date", "customer",
     "EXISTS (SELECT 1 FROM `tabSales Order Item` i WHERE i.parent = d.name AND i.warehouse IN %(warehouses)s)"),
    ("Sales Invoice", "posting_date", "customer", "d.gas_agency_location = %(location)s"),
]
PAYMENT_IN_BRANCH = {
    "Receive": """
        EXISTS (
            SELECT 1 FROM `tabPayment Entry Reference` r
            INNER JOIN `tabSales Invoice` si ON si.name = r.reference_name
            WHERE r.parent = pe.name AND r.reference_doctype = 'Sales Invoice'
            AND si.gas_agency_location = %(location)s
        )
    """,
    "Pay": """
        EXISTS (
            SELECT 1 FROM `tabPayment Entry Reference` r
            INNER JOIN `tabPurchase Invoice Item` i ON i.parent = r.reference_name
            LEFT JOIN `tabPurchase Receipt Item` pri ON pri.name = i.pr_detail
            WHERE r.parent = pe.name AND r.reference_doctype = 'Purchase Invoice'
            AND COALESCE(NULLIF(i.warehouse, ''), pri.warehouse) IN %(warehouses)s
        )
    """,
}


@frappe.whitelist()
def get_list_dashboard_data(company=None, location=None, from_date=None, to_date=None):
    """
    Recent documents for the Dashboard List View page, 10 per section and
    filtered like Dashboard Stats: by company (none = all companies), branch
    (none = the whole company) and dates. Pending invoices and low stock are
    as of now.
    """
    # The data below is read without permission checks, so apply the page's
    # access (its roles plus any added in Role Permission for Page and Report)
    if not frappe.get_cached_doc("Page", "dashboard-list-view").is_permitted():
        raise frappe.PermissionError

    f = frappe._dict(
        company=company or None,
        location=location or None,
        from_date=from_date or add_days(nowdate(), -30),
        to_date=to_date or nowdate(),
    )
    locations = _get_locations(f.location, f.company)
    if f.location:
        # A branch outside the chosen company matches nothing
        f.warehouses = tuple(
            w for loc in locations for w in (loc.warehouse, loc.default_target_warehouse) if w
        ) or ("",)
    cylinders = _get_cylinder_items()

    return {
        "company_options": frappe.get_all("Company", pluck="name", order_by="name asc"),
        "location_options": [loc.name for loc in _get_locations(company=f.company)],
        "branch_warehouses": list(f.warehouses or []),
        "cylinder_items": list(cylinders.filled) + list(cylinders.empty),
        "purchases": _recent_documents(f, PURCHASE_DOCTYPES),
        "sales": _show_credit_types(_recent_documents(f, SALES_DOCTYPES)),
        "supplier_payments": _recent_payments(f, "Pay"),
        "customer_payments": _recent_payments(f, "Receive"),
        "credit_sales": _credit_sales(f),
        "cylinder_movements": _cylinder_movements(f, cylinders),
        "low_stock": _low_stock(locations, cylinders),
        "exchange_errors": _exchange_errors(f, locations),
    }


def _recent_documents(f, doctypes):
    """The latest documents of these doctypes in the dates, newest first; cancelled ones are left out."""
    rows = []
    for doctype, date_field, party_field, branch_condition in doctypes:
        conditions = ["d.docstatus < 2", f"d.{date_field} BETWEEN %(from_date)s AND %(to_date)s"]
        if f.company:
            conditions.append("d.company = %(company)s")
        if f.location:
            conditions.append(branch_condition)
        rows += frappe.db.sql(
            f"""
            SELECT %(doctype)s AS doctype, d.name, d.{date_field} AS date, d.{party_field} AS party,
                d.base_grand_total AS amount, d.status, d.creation
            FROM `tab{doctype}` d
            WHERE {" AND ".join(conditions)}
            ORDER BY d.{date_field} DESC, d.creation DESC
            LIMIT {LIMIT}
            """,
            {**f, "doctype": doctype},
            as_dict=True,
        )
    rows.sort(key=lambda r: (r.date, r.creation), reverse=True)
    return rows[:LIMIT]


def _show_credit_types(rows):
    """
    Sales Invoices still owing money or empties show their credit type as
    their status, as in the Sales Invoice list.
    """
    names = [row.name for row in rows if row.doctype == "Sales Invoice"]
    if not names:
        return rows

    owing = {
        d.name: d
        for d in frappe.get_all(
            "Sales Invoice",
            filters={"name": ["in", names], "docstatus": 1, "is_return": 0},
            fields=["name", "outstanding_amount", "pending_empties"],
        )
        if flt(d.outstanding_amount) > 0 or flt(d.pending_empties) > 0
    }
    for row in rows:
        if row.doctype == "Sales Invoice" and row.name in owing:
            d = owing[row.name]
            row.status = credit_type(d.outstanding_amount, d.pending_empties)
    return rows


def _recent_payments(f, payment_type):
    """The latest submitted payments of this type; for a branch, those allocated to its invoices."""
    conditions = [
        "pe.docstatus = 1",
        "pe.payment_type = %(payment_type)s",
        "pe.posting_date BETWEEN %(from_date)s AND %(to_date)s",
    ]
    if f.company:
        conditions.append("pe.company = %(company)s")
    if f.location:
        conditions.append(PAYMENT_IN_BRANCH[payment_type])
    return frappe.db.sql(
        f"""
        SELECT pe.name, pe.posting_date AS date, pe.party, pe.mode_of_payment,
            pe.base_paid_amount AS amount
        FROM `tabPayment Entry` pe
        WHERE {" AND ".join(conditions)}
        ORDER BY pe.posting_date DESC, pe.creation DESC
        LIMIT {LIMIT}
        """,
        {**f, "payment_type": payment_type},
        as_dict=True,
    )


def _credit_sales(f):
    """Customer invoices still owing money or empties, as of now, newest first, with their credit type."""
    conditions = ["docstatus = 1", "is_return = 0", "(outstanding_amount > 0 OR pending_empties > 0)"]
    if f.company:
        conditions.append("company = %(company)s")
    if f.location:
        conditions.append("gas_agency_location = %(location)s")
    rows = frappe.db.sql(
        f"""
        SELECT name, posting_date AS date, due_date, customer AS party,
            outstanding_amount, pending_empties
        FROM `tabSales Invoice`
        WHERE {" AND ".join(conditions)}
        ORDER BY posting_date DESC, creation DESC
        LIMIT {LIMIT}
        """,
        f,
        as_dict=True,
    )
    for row in rows:
        row.credit_type = credit_type(row.outstanding_amount, row.pending_empties)
    return rows


def _cylinder_movements(f, cylinders):
    """The latest stock movements of filled and empty cylinders in the dates."""
    items = tuple(cylinders.filled) + tuple(cylinders.empty)
    if not items:
        return []

    conditions = [
        "is_cancelled = 0",
        "item_code IN %(items)s",
        "posting_date BETWEEN %(from_date)s AND %(to_date)s",
    ]
    if f.company:
        conditions.append("company = %(company)s")
    if f.location:
        conditions.append("warehouse IN %(warehouses)s")
    rows = frappe.db.sql(
        f"""
        SELECT posting_date AS date, voucher_type, voucher_no, item_code, warehouse,
            actual_qty, qty_after_transaction
        FROM `tabStock Ledger Entry`
        WHERE {" AND ".join(conditions)}
        ORDER BY posting_date DESC, posting_time DESC, creation DESC
        LIMIT {LIMIT}
        """,
        {**f, "items": items},
        as_dict=True,
    )
    for row in rows:
        row.kind = "Filled" if row.item_code in cylinders.filled else "Empty"
    return rows


def _low_stock(locations, cylinders):
    """Branches whose filled cylinders in hand are below their minimum, biggest shortfall first."""
    rows = []
    for loc in locations:
        if not loc.min_filled_qty:
            continue
        warehouses = tuple(w for w in (loc.warehouse, loc.default_target_warehouse) if w)
        stock = _get_stock(warehouses, cylinders)
        if stock.filled_qty < loc.min_filled_qty:
            rows.append(frappe._dict(
                location=loc.name,
                company=loc.company,
                filled_qty=stock.filled_qty,
                empty_qty=stock.empty_qty,
                min_filled_qty=loc.min_filled_qty,
                shortfall=loc.min_filled_qty - stock.filled_qty,
            ))
    rows.sort(key=lambda r: r.shortfall, reverse=True)
    return rows[:LIMIT]


def _exchange_errors(f, locations):
    """Cylinder exchanges that failed in the dates, newest first."""
    filters = {"status": "Error", "exchange_date": ["between", [f.from_date, f.to_date]]}
    if f.location or f.company:
        names = [loc.name for loc in locations]
        if not names:
            return []
        filters["location"] = ["in", names]
    return frappe.get_all(
        "Cylinder Exchange Log",
        filters=filters,
        fields=["name", "exchange_date", "source_doctype", "source_name", "location",
                "filled_item", "qty", "error_message"],
        order_by="creation desc",
        limit_page_length=LIMIT,
    )
