import frappe
from frappe import _
from frappe.utils import flt


def execute(filters=None):
    filters = frappe._dict(filters or {})
    return get_columns(), get_data(filters)


def get_columns():
    return [
        {
            "fieldname": "invoice",
            "label": _("Invoice"),
            "fieldtype": "Link",
            "options": "Sales Invoice",
            "width": 170,
        },
        {
            "fieldname": "posting_date",
            "label": _("Date"),
            "fieldtype": "Date",
            "width": 100,
        },
        {
            "fieldname": "customer",
            "label": _("Customer"),
            "fieldtype": "Link",
            "options": "Customer",
            "width": 180,
        },
        {
            "fieldname": "location",
            "label": _("Location"),
            "fieldtype": "Link",
            "options": "Gas Agency Location",
            "width": 150,
        },
        {
            "fieldname": "broker",
            "label": _("Broker"),
            "fieldtype": "Link",
            "options": "Broker",
            "width": 130,
        },
        {
            "fieldname": "grand_total",
            "label": _("Invoice Total"),
            "fieldtype": "Currency",
            "width": 130,
        },
        {
            "fieldname": "outstanding_amount",
            "label": _("Amount Pending"),
            "fieldtype": "Currency",
            "width": 140,
        },
        {
            "fieldname": "pending_empties",
            "label": _("Empties Pending"),
            "fieldtype": "Float",
            "width": 130,
        },
        {
            "fieldname": "credit_type",
            "label": _("Credit Type"),
            "fieldtype": "Data",
            "width": 140,
        },
    ]


def get_data(filters):
    conditions = [["docstatus", "=", 1], ["is_return", "=", 0]]
    for field, value in (
        ("company", filters.company),
        ("customer", filters.customer),
        ("gas_agency_location", filters.location),
        ("broker", filters.broker),
    ):
        if value:
            conditions.append([field, "=", value])
    if filters.from_date:
        conditions.append(["posting_date", ">=", filters.from_date])
    if filters.to_date:
        conditions.append(["posting_date", "<=", filters.to_date])

    invoices = frappe.get_list(
        "Sales Invoice",
        filters=conditions,
        or_filters=[["outstanding_amount", ">", 0], ["pending_empties", ">", 0]],
        fields=[
            "name as invoice",
            "posting_date",
            "customer",
            "gas_agency_location as location",
            "broker",
            "grand_total",
            "outstanding_amount",
            "pending_empties",
        ],
        order_by="posting_date, name",
    )

    data = []
    for row in invoices:
        row.credit_type = credit_type(row.outstanding_amount, row.pending_empties)
        if not filters.credit_type or row.credit_type == filters.credit_type:
            data.append(row)
    return data


def credit_type(outstanding_amount, pending_empties):
    """Amount Pending, Cylinder Pending or Both Pending, from what's still owed."""
    # Kept untranslated: the Credit Type filter compares against these
    amount_pending = flt(outstanding_amount) > 0
    cylinder_pending = flt(pending_empties) > 0
    if amount_pending and cylinder_pending:
        return "Both Pending"
    return "Amount Pending" if amount_pending else "Cylinder Pending"
