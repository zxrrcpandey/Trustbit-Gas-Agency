import frappe
from frappe import _
from frappe.utils import flt


def execute(filters=None):
    columns = get_columns()
    data = get_data(filters)
    chart = get_chart(data)
    return columns, data, None, chart


def get_columns():
    return [
        {
            "fieldname": "location",
            "label": _("Location"),
            "fieldtype": "Link",
            "options": "Gas Agency Location",
            "width": 200,
        },
        {
            "fieldname": "total_invoices",
            "label": _("Total Invoices"),
            "fieldtype": "Int",
            "width": 130,
        },
        {
            "fieldname": "total_qty",
            "label": _("Total Qty Sold"),
            "fieldtype": "Float",
            "width": 130,
        },
        {
            "fieldname": "total_revenue",
            "label": _("Total Revenue"),
            "fieldtype": "Currency",
            "width": 150,
        },
        {
            "fieldname": "total_exchanges",
            "label": _("Total Exchanges"),
            "fieldtype": "Int",
            "width": 130,
        },
        {
            "fieldname": "total_kg_exchanged",
            "label": _("Total KG Exchanged"),
            "fieldtype": "Float",
            "width": 150,
            "precision": 3,
        },
    ]


def get_data(filters):
    conditions = "si.docstatus = 1"
    values = {}

    if filters and filters.get("from_date"):
        conditions += " AND si.posting_date >= %(from_date)s"
        values["from_date"] = filters["from_date"]

    if filters and filters.get("to_date"):
        conditions += " AND si.posting_date <= %(to_date)s"
        values["to_date"] = filters["to_date"]

    if filters and filters.get("company"):
        conditions += " AND si.company = %(company)s"
        values["company"] = filters["company"]

    if filters and filters.get("location"):
        conditions += " AND si.gas_agency_location = %(location)s"
        values["location"] = filters["location"]

    # Sales data
    sales_data = frappe.db.sql(
        """
        SELECT
            si.gas_agency_location as location,
            COUNT(DISTINCT si.name) as total_invoices,
            SUM(sii.qty) as total_qty,
            SUM(si.grand_total) as total_revenue
        FROM `tabSales Invoice` si
        LEFT JOIN `tabSales Invoice Item` sii ON sii.parent = si.name
        WHERE {conditions}
        AND si.gas_agency_location IS NOT NULL
        AND si.gas_agency_location != ''
        GROUP BY si.gas_agency_location
        ORDER BY si.gas_agency_location
        """.format(conditions=conditions),
        values,
        as_dict=True,
    )

    # Exchange data
    exchange_conditions = "status = 'Completed'"
    exchange_values = {}

    if filters and filters.get("from_date"):
        exchange_conditions += " AND exchange_date >= %(from_date)s"
        exchange_values["from_date"] = filters["from_date"]

    if filters and filters.get("to_date"):
        exchange_conditions += " AND exchange_date <= %(to_date)s"
        exchange_values["to_date"] = filters["to_date"]

    if filters and filters.get("location"):
        exchange_conditions += " AND location = %(location)s"
        exchange_values["location"] = filters["location"]

    exchange_data = frappe.db.sql(
        """
        SELECT
            location,
            COUNT(*) as total_exchanges,
            SUM(weight_kg) as total_kg_exchanged
        FROM `tabCylinder Exchange Log`
        WHERE {conditions}
        AND location IS NOT NULL
        AND location != ''
        GROUP BY location
        ORDER BY location
        """.format(conditions=exchange_conditions),
        exchange_values,
        as_dict=True,
    )

    exchange_map = {d.location: d for d in exchange_data}

    # Merge
    data = []
    for row in sales_data:
        exchange = exchange_map.get(row.location, {})
        data.append({
            "location": row.location,
            "total_invoices": row.total_invoices or 0,
            "total_qty": flt(row.total_qty),
            "total_revenue": flt(row.total_revenue),
            "total_exchanges": exchange.get("total_exchanges", 0),
            "total_kg_exchanged": flt(exchange.get("total_kg_exchanged", 0)),
        })

    return data


def get_chart(data):
    if not data:
        return None

    labels = [d["location"] for d in data]
    revenue = [d["total_revenue"] for d in data]

    return {
        "data": {
            "labels": labels,
            "datasets": [{"name": _("Revenue"), "values": revenue}],
        },
        "type": "bar",
        "colors": ["#9C27B0"],
    }
