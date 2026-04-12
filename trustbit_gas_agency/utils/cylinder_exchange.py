import frappe
from frappe import _
from frappe.utils import nowdate, flt


def process_cylinder_exchange(doc, method):
    """
    Process cylinder exchange on Sales Invoice / Delivery Note submit.
    For each sold filled cylinder item, create a Stock Entry (Material Receipt)
    to add the corresponding empty cylinder back to stock.
    """
    settings = frappe.get_cached_doc("Gas Agency Settings")

    if not settings.enable_auto_exchange:
        return

    # Check if exchange should be triggered for this doctype
    if settings.create_exchange_on not in ("Both", doc.doctype):
        return

    exchange_items = _collect_exchange_items(doc, settings)

    if not exchange_items:
        return

    try:
        stock_entry = _create_stock_entry(doc, exchange_items, settings)

        # Create exchange logs
        for item in exchange_items:
            _create_exchange_log(
                doc=doc,
                item=item,
                stock_entry=stock_entry,
                status="Completed",
            )

        frappe.msgprint(
            _("Cylinder Exchange: {0} empty cylinder(s) added to stock via {1}").format(
                len(exchange_items), frappe.get_desk_link("Stock Entry", stock_entry.name)
            ),
            alert=True,
            indicator="green",
        )

    except Exception as e:
        frappe.log_error(
            title=_("Cylinder Exchange Error"),
            message=frappe.get_traceback(),
        )
        for item in exchange_items:
            _create_exchange_log(
                doc=doc,
                item=item,
                stock_entry=None,
                status="Error",
                error_message=str(e),
            )
        frappe.msgprint(
            _("Cylinder Exchange Error: {0}").format(str(e)),
            alert=True,
            indicator="red",
        )


def cancel_cylinder_exchange(doc, method):
    """
    Cancel cylinder exchange when source document is cancelled.
    Cancels the linked Stock Entries and updates exchange logs.
    """
    logs = frappe.get_all(
        "Cylinder Exchange Log",
        filters={
            "source_doctype": doc.doctype,
            "source_name": doc.name,
            "status": "Completed",
        },
        fields=["name", "stock_entry"],
        order_by="creation desc",
    )

    if not logs:
        return

    # Collect unique stock entries to cancel
    stock_entries_to_cancel = set()
    for log in logs:
        if log.stock_entry:
            stock_entries_to_cancel.add(log.stock_entry)

    # Cancel stock entries
    for se_name in stock_entries_to_cancel:
        try:
            se = frappe.get_doc("Stock Entry", se_name)
            if se.docstatus == 1:
                se.cancel()
        except Exception as e:
            frappe.log_error(
                title=_("Cylinder Exchange Cancel Error"),
                message=frappe.get_traceback(),
            )

    # Update all logs to cancelled
    for log in logs:
        frappe.db.set_value("Cylinder Exchange Log", log.name, "status", "Cancelled")

    frappe.msgprint(
        _("Cylinder Exchange: {0} exchange(s) cancelled").format(len(logs)),
        alert=True,
        indicator="orange",
    )


def _collect_exchange_items(doc, settings):
    """
    Scan document items (and packed_items for Product Bundles) to find
    items that have active Cylinder Exchange Rules.
    """
    exchange_items = []

    # Check regular items
    for row in doc.items:
        rule = _get_exchange_rule(row.item_code)
        if rule:
            target_warehouse = _get_target_warehouse(doc, row, settings)
            exchange_items.append({
                "filled_item": row.item_code,
                "empty_item": rule.empty_item,
                "qty": flt(row.qty) * flt(rule.exchange_ratio),
                "weight_kg": flt(row.qty) * flt(rule.filled_weight_kg) if settings.enable_kg_tracking else 0,
                "target_warehouse": target_warehouse,
                "location": getattr(doc, "gas_agency_location", None),
                "rule": rule,
            })

    # Check packed_items (Product Bundle unpacked items in Delivery Notes)
    if hasattr(doc, "packed_items") and doc.packed_items:
        for row in doc.packed_items:
            rule = _get_exchange_rule(row.item_code)
            if rule:
                target_warehouse = _get_target_warehouse(doc, row, settings)
                exchange_items.append({
                    "filled_item": row.item_code,
                    "empty_item": rule.empty_item,
                    "qty": flt(row.qty) * flt(rule.exchange_ratio),
                    "weight_kg": flt(row.qty) * flt(rule.filled_weight_kg) if settings.enable_kg_tracking else 0,
                    "target_warehouse": target_warehouse,
                    "location": getattr(doc, "gas_agency_location", None),
                    "rule": rule,
                })

    return exchange_items


def _get_exchange_rule(item_code):
    """Get active Cylinder Exchange Rule for the given item code."""
    try:
        rule = frappe.get_cached_doc("Cylinder Exchange Rule", item_code)
        if rule.is_active:
            return rule
    except frappe.DoesNotExistError:
        pass
    return None


def _get_target_warehouse(doc, row, settings):
    """
    Determine target warehouse for empty cylinder receipt.
    Priority:
    1. Location's default_target_warehouse (from doc.gas_agency_location)
    2. Gas Agency Settings default_exchange_warehouse
    3. Same warehouse as the sold item
    """
    location_name = getattr(doc, "gas_agency_location", None)
    if location_name:
        location = frappe.get_cached_doc("Gas Agency Location", location_name)
        if location.default_target_warehouse:
            return location.default_target_warehouse

    if settings.default_exchange_warehouse:
        return settings.default_exchange_warehouse

    return row.warehouse


def _create_stock_entry(doc, exchange_items, settings):
    """Create a Stock Entry (Material Receipt) for empty cylinders."""
    stock_entry = frappe.new_doc("Stock Entry")
    stock_entry.stock_entry_type = "Material Receipt"
    stock_entry.company = doc.company
    stock_entry.posting_date = nowdate()
    stock_entry.remarks = _("Auto cylinder exchange from {0} {1}").format(
        doc.doctype, doc.name
    )

    for item in exchange_items:
        stock_entry.append("items", {
            "item_code": item["empty_item"],
            "qty": item["qty"],
            "t_warehouse": item["target_warehouse"],
            "basic_rate": 0,
        })

    stock_entry.insert(ignore_permissions=True)

    if settings.auto_submit_stock_entry:
        stock_entry.submit()

    return stock_entry


def _create_exchange_log(doc, item, stock_entry, status, error_message=None):
    """Create a Cylinder Exchange Log record."""
    log = frappe.new_doc("Cylinder Exchange Log")
    log.source_doctype = doc.doctype
    log.source_name = doc.name
    log.stock_entry = stock_entry.name if stock_entry else None
    log.location = item.get("location")
    log.filled_item = item["filled_item"]
    log.empty_item = item["empty_item"]
    log.qty = item["qty"]
    log.weight_kg = item.get("weight_kg", 0)
    log.status = status
    log.error_message = error_message
    log.exchange_date = nowdate()
    log.insert(ignore_permissions=True)
    return log
