import frappe
from frappe import _
from frappe.utils import flt


# Accounts Users bill at the counter but have no read access to Product Bundle,
# so the Sales Invoice "Get Items From > Product Bundle" dialog reads bundles
# through these methods, gated on Sales Invoice access instead.


@frappe.whitelist()
def list_product_bundles():
    """Enabled Product Bundles, for the dialog's dropdown, labelled with the item name."""
    frappe.has_permission("Sales Invoice", "create", throw=True)
    bundles = frappe.get_all(
        "Product Bundle", filters={"disabled": 0}, fields=["name", "new_item_code"], order_by="name asc"
    )
    labels = []
    for bundle in bundles:
        # Items named by series (ITEM-2026-00751) mean nothing at the counter
        item_name = frappe.get_cached_value("Item", bundle.new_item_code, "item_name")
        label = bundle.name if item_name in (None, bundle.name) else f"{item_name} ({bundle.name})"
        labels.append({"value": bundle.name, "label": label})
    return labels


@frappe.whitelist()
def get_product_bundle_items(product_bundle, quantity=1):
    """The bundle's items, each qty multiplied by the number of bundles."""
    frappe.has_permission("Sales Invoice", "create", throw=True)
    if not frappe.db.exists("Product Bundle", {"name": product_bundle, "disabled": 0}):
        frappe.throw(_("Product Bundle {0} not found or disabled").format(product_bundle))

    return [
        {"item_code": row.item_code, "qty": flt(row.qty) * flt(quantity)}
        for row in frappe.get_all(
            "Product Bundle Item",
            filters={"parent": product_bundle, "parenttype": "Product Bundle"},
            fields=["item_code", "qty"],
            order_by="idx asc",
        )
    ]
