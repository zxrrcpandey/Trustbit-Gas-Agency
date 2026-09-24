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

    # Invoice-level aggregates (no item join, so grand_total is counted once).
    # Counts are of sales only; amounts net credit notes out.
    sales_data = frappe.db.sql(
        """
        SELECT
            si.gas_agency_location as location,
            SUM(CASE WHEN si.is_return = 0 THEN 1 ELSE 0 END) as total_invoices,
            SUM(si.grand_total) as total_revenue
        FROM `tabSales Invoice` si
        WHERE {conditions}
        AND si.gas_agency_location IS NOT NULL
        AND si.gas_agency_location != ''
        GROUP BY si.gas_agency_location
        ORDER BY si.gas_agency_location
        """.format(conditions=conditions),
        values,
        as_dict=True,
    )

    # Item-level qty aggregated separately, in stock UOM so rows sold in
    # different UOMs add up and match the exchange figures
    qty_data = frappe.db.sql(
        """
        SELECT
            si.gas_agency_location as location,
            SUM(sii.stock_qty) as total_qty
        FROM `tabSales Invoice` si
        INNER JOIN `tabSales Invoice Item` sii ON sii.parent = si.name
        WHERE {conditions}
        AND si.gas_agency_location IS NOT NULL
        AND si.gas_agency_location != ''
        GROUP BY si.gas_agency_location
        """.format(conditions=conditions),
        values,
        as_dict=True,
    )
    qty_map = {d.location: flt(d.total_qty) for d in qty_data}

    # Exchange data — the company filter applies via the location master
    exchange_conditions = "cxl.status = 'Completed'"
    exchange_values = {}

    if filters and filters.get("from_date"):
        exchange_conditions += " AND cxl.exchange_date >= %(from_date)s"
        exchange_values["from_date"] = filters["from_date"]

    if filters and filters.get("to_date"):
        exchange_conditions += " AND cxl.exchange_date <= %(to_date)s"
        exchange_values["to_date"] = filters["to_date"]

    if filters and filters.get("location"):
        exchange_conditions += " AND cxl.location = %(location)s"
        exchange_values["location"] = filters["location"]

    if filters and filters.get("company"):
        exchange_conditions += " AND loc.company = %(company)s"
        exchange_values["company"] = filters["company"]

    # Return give-backs are logged with negative qty/KG: count receipts only,
    # and let the KG total net the returns out
    exchange_data = frappe.db.sql(
        """
        SELECT
            cxl.location,
            SUM(CASE WHEN cxl.qty > 0 THEN 1 ELSE 0 END) as total_exchanges,
            SUM(cxl.weight_kg) as total_kg_exchanged
        FROM `tabCylinder Exchange Log` cxl
        LEFT JOIN `tabGas Agency Location` loc ON loc.name = cxl.location
        WHERE {conditions}
        AND cxl.location IS NOT NULL
        AND cxl.location != ''
        GROUP BY cxl.location
        ORDER BY cxl.location
        """.format(conditions=exchange_conditions),
        exchange_values,
        as_dict=True,
    )

    sales_map = {d.location: d for d in sales_data}
    exchange_map = {d.location: d for d in exchange_data}

    # Merge over the union so exchange-only locations are not dropped
    data = []
    for location in sorted(set(sales_map) | set(exchange_map)):
        sales = sales_map.get(location, {})
        exchange = exchange_map.get(location, {})
        data.append({
            "location": location,
            "total_invoices": sales.get("total_invoices") or 0,
            "total_qty": flt(qty_map.get(location, 0)),
            "total_revenue": flt(sales.get("total_revenue")),
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
