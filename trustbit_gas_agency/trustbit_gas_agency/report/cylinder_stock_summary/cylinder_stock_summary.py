import frappe
from frappe import _
from frappe.utils import flt


def execute(filters=None):
    columns = get_columns()
    data = get_data(filters)
    return columns, data


def get_columns():
    return [
        {
            "fieldname": "location",
            "label": _("Location"),
            "fieldtype": "Link",
            "options": "Gas Agency Location",
            "width": 180,
        },
        {
            "fieldname": "item_code",
            "label": _("Item Code"),
            "fieldtype": "Link",
            "options": "Item",
            "width": 200,
        },
        {
            "fieldname": "item_name",
            "label": _("Item Name"),
            "fieldtype": "Data",
            "width": 200,
        },
        {
            "fieldname": "cylinder_type",
            "label": _("Type"),
            "fieldtype": "Data",
            "width": 100,
        },
        {
            "fieldname": "qty",
            "label": _("Qty (Nos)"),
            "fieldtype": "Float",
            "width": 120,
        },
        {
            "fieldname": "weight_kg",
            "label": _("Weight (KG)"),
            "fieldtype": "Float",
            "width": 120,
            "precision": 3,
        },
        {
            "fieldname": "warehouse",
            "label": _("Warehouse"),
            "fieldtype": "Link",
            "options": "Warehouse",
            "width": 200,
        },
    ]


def get_data(filters):
    # Get exchange rules
    rules = frappe.get_all(
        "Cylinder Exchange Rule",
        filters={"is_active": 1},
        fields=["filled_item", "empty_item", "filled_weight_kg", "empty_weight_kg"],
        order_by="creation asc",
    )

    if not rules:
        return []

    filled_items = {r.filled_item: r for r in rules}
    empty_items = {r.empty_item: r for r in rules}
    all_items = set(filled_items.keys()) | set(empty_items.keys())

    # Get locations
    location_filters = {"is_active": 1}
    if filters and filters.get("location"):
        location_filters["name"] = filters.get("location")
    if filters and filters.get("company"):
        location_filters["company"] = filters.get("company")

    locations = frappe.get_all(
        "Gas Agency Location",
        filters=location_filters,
        fields=["name", "warehouse", "default_target_warehouse"],
        order_by="name asc",
    )

    data = []
    for loc in locations:
        warehouses = [loc.warehouse]
        if loc.default_target_warehouse:
            warehouses.append(loc.default_target_warehouse)

        bins = frappe.get_all(
            "Bin",
            filters={
                "warehouse": ["in", warehouses],
                "item_code": ["in", list(all_items)],
            },
            fields=["item_code", "actual_qty", "warehouse"],
            order_by="item_code asc",
        )

        for b in bins:
            if flt(b.actual_qty) == 0:
                continue

            item_name = frappe.db.get_value("Item", b.item_code, "item_name")

            if b.item_code in filled_items:
                rule = filled_items[b.item_code]
                data.append({
                    "location": loc.name,
                    "item_code": b.item_code,
                    "item_name": item_name,
                    "cylinder_type": "Filled",
                    "qty": flt(b.actual_qty),
                    "weight_kg": flt(b.actual_qty) * flt(rule.filled_weight_kg),
                    "warehouse": b.warehouse,
                })
            elif b.item_code in empty_items:
                rule = empty_items[b.item_code]
                data.append({
                    "location": loc.name,
                    "item_code": b.item_code,
                    "item_name": item_name,
                    "cylinder_type": "Empty",
                    "qty": flt(b.actual_qty),
                    "weight_kg": flt(b.actual_qty) * flt(rule.empty_weight_kg),
                    "warehouse": b.warehouse,
                })

    return data
