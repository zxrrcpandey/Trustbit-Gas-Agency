import frappe
from frappe import _
from frappe.utils import flt

from trustbit_gas_agency.utils.stock_utils import SELLING_TYPES, _get_cylinder_items

# Columns of filled cylinders sold by Sales Type, and cylinders taken back
# on a Surrender
SALES_TYPES = SELLING_TYPES + ("Surrender",)


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
        *[
            {
                "fieldname": sales_type.lower() + "_qty",
                "label": _(sales_type),
                "fieldtype": "Float",
                "width": 100,
            }
            for sales_type in SALES_TYPES
        ],
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

    # Item-level figures aggregated separately, in stock UOM so rows sold in
    # different UOMs add up and match the exchange figures. Security deposits
    # (rows booked to a liability account) are money held for the customer:
    # left out of qty and revenue. A Surrender's rows are cylinders taken
    # back, not sales returns.
    item_data = frappe.db.sql(
        """
        SELECT
            si.gas_agency_location as location,
            COALESCE(NULLIF(si.gas_sales_type, ''), 'Normal') as sales_type,
            sii.item_code,
            COALESCE(acc.root_type, '') = 'Liability' as is_deposit,
            SUM(sii.stock_qty) as qty,
            SUM(sii.net_amount) as amount
        FROM `tabSales Invoice` si
        INNER JOIN `tabSales Invoice Item` sii ON sii.parent = si.name
        LEFT JOIN `tabAccount` acc ON acc.name = sii.income_account
        WHERE {conditions}
        AND si.gas_agency_location IS NOT NULL
        AND si.gas_agency_location != ''
        GROUP BY si.gas_agency_location, sales_type, sii.item_code, is_deposit
        """.format(conditions=conditions),
        values,
        as_dict=True,
    )
    cylinders = _get_cylinder_items()
    item_map = {}
    for d in item_data:
        figures = item_map.setdefault(
            d.location,
            frappe._dict({"total_qty": 0, "deposits": 0, **{t.lower() + "_qty": 0 for t in SALES_TYPES}}),
        )
        if d.is_deposit:
            figures.deposits += flt(d.amount)
            continue
        if d.sales_type == "Surrender":
            if d.item_code in cylinders.filled or d.item_code in cylinders.empty:
                figures.surrender_qty -= flt(d.qty)
            continue
        figures.total_qty += flt(d.qty)
        if d.item_code in cylinders.filled:
            figures[d.sales_type.lower() + "_qty"] += flt(d.qty)

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
        items = item_map.get(location, {})
        data.append({
            "location": location,
            "total_invoices": sales.get("total_invoices") or 0,
            "total_qty": flt(items.get("total_qty")),
            "total_revenue": flt(sales.get("total_revenue")) - flt(items.get("deposits")),
            **{t.lower() + "_qty": flt(items.get(t.lower() + "_qty")) for t in SALES_TYPES},
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
