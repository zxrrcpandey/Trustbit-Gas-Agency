import frappe
from frappe import _
from frappe.utils import flt


# Accounts Users bill at the counter but have no read access to Product Bundle,
# so the Sales Invoice "Get Items From > Product Bundle" dialog reads bundles
# through these methods, gated on Sales Invoice access instead.


@frappe.whitelist()
def list_product_bundles():
    """Enabled Product Bundles, for the dialog's dropdown."""
    frappe.has_permission("Sales Invoice", "create", throw=True)
    return frappe.get_all(
        "Product Bundle", filters={"disabled": 0}, pluck="name", order_by="name asc"
    )


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
