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

    # Returns bring filled cylinders back; they never generate an empty receipt
    if doc.get("is_return"):
        return

    exchange_items = _collect_exchange_items(doc, settings)

    if not exchange_items:
        return

    stock_entry = None
    try:
        stock_entry = _create_stock_entry(doc, exchange_items, settings)
        if settings.auto_submit_stock_entry:
            stock_entry.submit()

        # Create exchange logs
        for item in exchange_items:
            _create_exchange_log(
                doc=doc,
                item=item,
                stock_entry=stock_entry,
                status="Completed",
            )

        total_qty = flt(sum(item["qty"] for item in exchange_items))
        frappe.msgprint(
            _("Cylinder Exchange: {0} empty cylinder(s) added to stock via {1}").format(
                "{0:g}".format(total_qty),
                frappe.get_desk_link("Stock Entry", stock_entry.name),
            ),
            alert=True,
            indicator="green",
        )

    except Exception as e:
        frappe.log_error(
            title=_("Cylinder Exchange Error"),
            message=frappe.get_traceback(),
        )
        # stock_entry may be a persisted draft if insert succeeded but submit
        # failed — keep the link so the leftover entry stays reachable
        for item in exchange_items:
            _create_exchange_log(
                doc=doc,
                item=item,
                stock_entry=stock_entry,
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
            "status": ["in", ["Completed", "Error"]],
        },
        fields=["name", "stock_entry", "status"],
        order_by="creation desc",
    )

    if not logs:
        return

    completed_logs = [log for log in logs if log.status == "Completed"]
    error_logs = [log for log in logs if log.status == "Error"]

    # Error logs that still reference a persisted Stock Entry (insert
    # succeeded but submit failed) need the same cleanup as completed ones
    actionable_logs = completed_logs + [log for log in error_logs if log.stock_entry]

    # Cancel each unique stock entry, tracking which ones failed
    stock_entries_to_cancel = {log.stock_entry for log in actionable_logs if log.stock_entry}
    failed_stock_entries = set()

    for se_name in stock_entries_to_cancel:
        try:
            se = frappe.get_doc("Stock Entry", se_name)
            if se.docstatus == 1:
                se.cancel()
            elif se.docstatus == 0:
                # A draft receipt never touched stock; remove it rather than
                # orphaning it. Log links must be cleared for the delete to
                # pass Frappe's link check, so roll both back if it fails.
                frappe.db.savepoint("tga_delete_draft_se")
                try:
                    frappe.db.set_value(
                        "Cylinder Exchange Log", {"stock_entry": se_name}, "stock_entry", None
                    )
                    frappe.delete_doc("Stock Entry", se_name, ignore_permissions=True)
                except Exception:
                    frappe.db.rollback(save_point="tga_delete_draft_se")
                    raise
        except Exception:
            failed_stock_entries.add(se_name)
            frappe.log_error(
                title=_("Cylinder Exchange Cancel Error"),
                message=frappe.get_traceback(),
            )

    # Mark each log according to whether its stock entry was actually cancelled
    cancelled_count = 0
    error_count = 0
    for log in actionable_logs:
        if log.stock_entry and log.stock_entry in failed_stock_entries:
            frappe.db.set_value(
                "Cylinder Exchange Log",
                log.name,
                {
                    "status": "Error",
                    "error_message": _("Linked Stock Entry {0} could not be cancelled").format(
                        log.stock_entry
                    ),
                },
            )
            error_count += 1
        else:
            frappe.db.set_value("Cylinder Exchange Log", log.name, "status", "Cancelled")
            cancelled_count += 1

    # Submit-time failures with no persisted Stock Entry have nothing left
    # to follow up once the source is gone
    for log in error_logs:
        if not log.stock_entry:
            frappe.db.set_value("Cylinder Exchange Log", log.name, "status", "Cancelled")

    if error_count:
        frappe.msgprint(
            _("Cylinder Exchange: {0} cancelled, {1} failed — check Cylinder Exchange Log").format(
                cancelled_count, error_count
            ),
            alert=True,
            indicator="red",
        )
    elif cancelled_count:
        frappe.msgprint(
            _("Cylinder Exchange: {0} exchange(s) cancelled").format(cancelled_count),
            alert=True,
            indicator="orange",
        )


def _collect_exchange_items(doc, settings):
    """
    Scan document items (and packed_items for Product Bundles) to find
    items that have active Cylinder Exchange Rules.
    """
    exchange_items = []
    counterpart_cache = {}

    # Items expanded from a Product Bundle appear in packed_items; skip their
    # parent rows so a bundle can never be exchanged twice
    bundle_parents = {pi.parent_item for pi in (doc.get("packed_items") or [])}

    # Check regular items
    for row in doc.items:
        if row.item_code in bundle_parents:
            continue
        if flt(row.qty) <= 0:
            continue
        if _row_already_exchanged(doc, row, counterpart_cache):
            continue
        rule = _get_exchange_rule(row.item_code)
        if rule:
            exchange_items.append(_build_exchange_item(doc, row, rule, settings))

    # Check packed_items (Product Bundle unpacked items in Delivery Notes)
    if doc.get("packed_items"):
        items_by_name = {row.name: row for row in doc.items}
        for row in doc.packed_items:
            if flt(row.qty) <= 0:
                continue
            parent_row = items_by_name.get(row.parent_detail_docname)
            if parent_row and _row_already_exchanged(doc, parent_row, counterpart_cache):
                continue
            rule = _get_exchange_rule(row.item_code)
            if rule:
                exchange_items.append(_build_exchange_item(doc, row, rule, settings))

    return exchange_items


def _build_exchange_item(doc, row, rule, settings):
    """Build one exchange entry from a document row and its matched rule."""
    return {
        "filled_item": row.item_code,
        "empty_item": rule.empty_item,
        "qty": flt(row.qty) * flt(rule.exchange_ratio),
        "weight_kg": flt(row.qty) * flt(rule.filled_weight_kg) if settings.enable_kg_tracking else 0,
        "target_warehouse": _get_target_warehouse(doc, row, settings),
        "location": doc.get("gas_agency_location"),
        "rule": rule,
    }


def _row_already_exchanged(doc, row, cache):
    """
    True when this row's stock movement already produced an exchange on the
    counterpart document (a Sales Invoice billed from a Delivery Note, or a
    Delivery Note made from a Sales Invoice — directly linked, or siblings
    created from the same Sales Order row). Prevents double exchanges when
    Gas Agency Settings fires on Both doctypes.
    """
    if doc.doctype == "Sales Invoice":
        counterpart_doctype, counterpart_item_table = "Delivery Note", "Delivery Note Item"
        direct_link = row.get("delivery_note")
    elif doc.doctype == "Delivery Note":
        counterpart_doctype, counterpart_item_table = "Sales Invoice", "Sales Invoice Item"
        direct_link = row.get("against_sales_invoice")
    else:
        return False

    counterpart_names = {direct_link} if direct_link else set()

    # SO-mediated flow: a DN and an SI both created from the same Sales Order
    # carry no direct link to each other but share so_detail (the SO Item row)
    if row.get("so_detail"):
        counterpart_names.update(
            frappe.get_all(
                counterpart_item_table,
                filters={"so_detail": row.so_detail, "docstatus": 1},
                pluck="parent",
            )
        )

    for counterpart_name in counterpart_names:
        if counterpart_name not in cache:
            cache[counterpart_name] = bool(
                frappe.db.exists(
                    "Cylinder Exchange Log",
                    {
                        "source_doctype": counterpart_doctype,
                        "source_name": counterpart_name,
                        "status": "Completed",
                    },
                )
            )
        if cache[counterpart_name]:
            return True

    return False


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
    stock_entry.posting_date = doc.get("posting_date") or nowdate()
    stock_entry.set_posting_time = 1
    stock_entry.remarks = _("Auto cylinder exchange from {0} {1}").format(
        doc.doctype, doc.name
    )

    cost_center = None
    location_name = doc.get("gas_agency_location")
    if location_name:
        cost_center = frappe.get_cached_doc("Gas Agency Location", location_name).cost_center

    for item in exchange_items:
        stock_entry.append("items", {
            "item_code": item["empty_item"],
            "qty": item["qty"],
            "t_warehouse": item["target_warehouse"],
            "basic_rate": 0,
            "cost_center": cost_center,
        })

    stock_entry.insert(ignore_permissions=True)

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
    log.exchange_date = doc.get("posting_date") or nowdate()
    log.insert(ignore_permissions=True)
    return log
