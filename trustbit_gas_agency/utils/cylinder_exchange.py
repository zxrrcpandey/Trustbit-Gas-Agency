import frappe
from frappe import _
from frappe.utils import nowdate, nowtime, flt


def process_cylinder_exchange(doc, method):
    """
    Process cylinder exchange on Sales Invoice / Delivery Note submit.
    For each sold filled cylinder item, create a Stock Entry (Material Receipt)
    to add the corresponding empty cylinder back to stock. Empties the customer
    didn't hand over (Empties Not Received) are logged as pending instead. On
    a return the customer takes those empties back, so they are issued out
    (Material Issue).
    """
    settings = frappe.get_cached_doc("Gas Agency Settings")

    if not settings.enable_auto_exchange:
        return

    # Check if exchange should be triggered for this doctype
    if settings.create_exchange_on not in ("Both", doc.doctype):
        return

    if not takes_empties(doc):
        return

    if doc.get("is_return"):
        exchange_items = _collect_return_items(doc, settings)
        purpose = "Material Issue"
    else:
        # A debit note that moves no stock only adjusts an earlier sale's rate
        if doc.get("is_debit_note") and not doc.get("update_stock"):
            return
        exchange_items = _collect_exchange_items(doc, settings)
        purpose = "Material Receipt"

    if not exchange_items:
        return

    # A row whose empties are all pending, or a return that only clears
    # pending empties, moves no stock but is still logged
    stock_items = [item for item in exchange_items if flt(item["qty"], 3)]
    stock_entry = None
    message_count = len(frappe.local.message_log)
    try:
        if stock_items:
            stock_entry = _in_savepoint(
                "tga_insert_se", lambda: _create_stock_entry(doc, stock_items, purpose)
            )
            if settings.auto_submit_stock_entry:
                # A failed submit is undone back to the draft the Error log links to
                _in_savepoint("tga_submit_se", stock_entry.submit)

        # Create exchange logs
        for item in exchange_items:
            _create_exchange_log(
                doc=doc,
                item=item,
                stock_entry=stock_entry,
                status="Completed",
            )

        if stock_entry:
            total_qty = flt(sum(abs(item["qty"]) for item in stock_items))
            message = (
                _("Cylinder Exchange: {0} empty cylinder(s) given back via {1}")
                if purpose == "Material Issue"
                else _("Cylinder Exchange: {0} empty cylinder(s) added to stock via {1}")
            )
            frappe.msgprint(
                message.format(
                    "{0:g}".format(total_qty),
                    # Stock Entry's title is its type; show the entry number too
                    frappe.get_desk_link("Stock Entry", stock_entry.name, show_title_with_name=True),
                ),
                alert=True,
                indicator="green",
            )

        pending_qty = flt(sum(item["pending_qty"] for item in exchange_items))
        if pending_qty > 0:
            frappe.msgprint(
                _("Cylinder Exchange: {0} empty cylinder(s) pending from the customer").format(
                    "{0:g}".format(pending_qty)
                ),
                alert=True,
                indicator="orange",
            )
        elif pending_qty < 0:
            frappe.msgprint(
                _("Cylinder Exchange: {0} pending empty cylinder(s) cleared by this return").format(
                    "{0:g}".format(-pending_qty)
                ),
                alert=True,
                indicator="green",
            )

    except frappe.QueryDeadlockError:
        # The database has rolled back the whole transaction, source document
        # included, so fail the request for a retry instead of carrying on
        raise
    except Exception as e:
        # Drop the error dialog the failure queued: it would replace the alert
        # below and make the source document itself look like it failed
        del frappe.local.message_log[message_count:]
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

    _refresh_pending_empties(doc)


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
        message_count = len(frappe.local.message_log)
        try:
            se = frappe.get_doc("Stock Entry", se_name)
            if se.docstatus == 1:
                # The receipt was submitted with ignore_permissions, so anyone
                # allowed to cancel the source must be able to reverse it too
                se.flags.ignore_permissions = True
                # e.g. negative stock after the empties left: undo the partial
                # reversal rather than commit a half-reversed ledger
                _in_savepoint("tga_cancel_se", se.cancel)
            elif se.docstatus == 0:
                # A draft receipt never touched stock; remove it rather than
                # orphaning it
                _in_savepoint("tga_delete_draft_se", lambda: _delete_draft_stock_entry(se_name))
        except frappe.QueryDeadlockError:
            # The source cancel was rolled back with it; fail for a retry
            raise
        except Exception:
            # Reported by the alert below and the log; drop the error dialog
            # that would replace it and make the cancel itself look failed
            del frappe.local.message_log[message_count:]
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

    _refresh_pending_empties(doc)


def takes_empties(doc):
    """
    Only a Normal sale (a refill) swaps the filled cylinders for the
    customer's empties, and so do its credit notes. NC and DBC cylinders go
    out with no empty back; a Surrender's cylinders come in on the credit
    note itself. A Delivery Note has no Sales Type and is always Normal.
    """
    return (doc.get("gas_sales_type") or "Normal") == "Normal"


def set_sales_type(doc):
    """
    A credit note made from an invoice keeps that invoice's Sales Type. A
    Surrender (connection closed: the customer hands back the cylinder and
    regulator and gets the deposit back) is a credit note of its own that
    moves stock, so it is marked as a return with Update Stock, its
    quantities are made negative, and its empties go to the empty cylinder
    warehouse like exchanged ones.
    """
    if doc.get("return_against"):
        doc.gas_sales_type = (
            frappe.db.get_value("Sales Invoice", doc.return_against, "gas_sales_type") or "Normal"
        )

    if doc.get("gas_sales_type") != "Surrender":
        return

    doc.is_return = 1
    doc.update_stock = 1
    settings = frappe.get_cached_doc("Gas Agency Settings")
    empty_items = set(
        frappe.get_all("Cylinder Exchange Rule", filters={"is_active": 1}, pluck="empty_item")
    )
    for row in doc.items:
        row.qty = -abs(flt(row.qty))
        if row.item_code in empty_items:
            row.warehouse = _get_target_warehouse(doc, row, settings)


def validate_empties_not_received(doc):
    """
    Mark each Sales Invoice row's cylinder rule, and keep Empties Not
    Received between 0 and the empties its cylinders bring in.
    """
    for row in doc.items:
        rule = _get_exchange_rule(row.item_code)
        row.is_gas_cylinder = 1 if rule else 0
        row.cylinder_exchange_rule = rule.name if rule else None

        if not rule or doc.get("is_return") or not takes_empties(doc):
            row.empties_not_received = 0
            continue

        expected = _cylinder_count(row) * flt(rule.exchange_ratio)
        if flt(row.empties_not_received) > expected:
            frappe.throw(
                _("Row {0}: Empties Not Received ({1}) can't be more than the {2} empties due for {3}").format(
                    row.idx, "{0:g}".format(flt(row.empties_not_received)), "{0:g}".format(expected), row.item_code
                )
            )


def get_pending_empties(sales_invoice):
    """
    Empties a customer still owes on a sales invoice, by empty item. Each
    exchange log of the invoice and its credit notes carries its change to
    the count: + not handed over at billing, - brought back later or
    cleared by returned cylinders.
    """
    if frappe.db.get_value("Sales Invoice", sales_invoice, "docstatus") != 1:
        return {}

    sources = [sales_invoice] + frappe.get_all(
        "Sales Invoice",
        filters={"return_against": sales_invoice, "is_return": 1, "docstatus": 1},
        pluck="name",
    )
    pending = {}
    for log in frappe.get_all(
        "Cylinder Exchange Log",
        filters={
            "source_doctype": "Sales Invoice",
            "source_name": ["in", sources],
            # An Error log's Stock Entry failed, but its empties changed hands
            # (or didn't) all the same
            "status": ["in", ["Completed", "Error"]],
        },
        fields=["empty_item", "pending_qty"],
    ):
        pending[log.empty_item] = pending.get(log.empty_item, 0) + flt(log.pending_qty)

    return {item: flt(qty, 3) for item, qty in pending.items() if flt(qty, 3) > 0}


def update_pending_empties(sales_invoice):
    """Store an invoice's pending empties total for its form, list and the Credit Sales report."""
    total = sum(get_pending_empties(sales_invoice).values())
    # Leave modified alone: the open form would otherwise count as outdated
    frappe.db.set_value(
        "Sales Invoice", sales_invoice, "pending_empties", total, update_modified=False
    )
    return total


def _refresh_pending_empties(doc):
    """Update pending empties on the invoice this document sold or returned."""
    if doc.doctype != "Sales Invoice":
        return

    invoice = doc.return_against if doc.get("is_return") else doc.name
    if not invoice:
        return

    total = update_pending_empties(invoice)
    if invoice == doc.name:
        # The form is sent this in-memory copy, not the row just written
        doc.pending_empties = total


@frappe.whitelist()
def list_pending_empties(sales_invoice):
    """Pending empties of an invoice, for the Receive Empties dialog."""
    frappe.has_permission("Sales Invoice", "read", sales_invoice, throw=True)
    return [
        {
            "empty_item": item,
            "item_name": frappe.get_cached_value("Item", item, "item_name"),
            "qty": qty,
        }
        for item, qty in get_pending_empties(sales_invoice).items()
    ]


@frappe.whitelist()
def receive_empties(sales_invoice, empties):
    """
    Book empties a customer brings back after billing against the invoice
    they are pending on: a Material Receipt, and logs that lower the count.
    empties maps each empty item to the qty brought back.
    """
    doc = frappe.get_doc("Sales Invoice", sales_invoice)
    doc.check_permission("submit")
    if doc.docstatus != 1 or doc.is_return:
        frappe.throw(_("Empties can only be received against a submitted Sales Invoice"))

    settings = frappe.get_cached_doc("Gas Agency Settings")
    pending = get_pending_empties(doc.name)
    items = []
    for empty_item, qty in frappe.parse_json(empties).items():
        qty = flt(qty)
        if qty <= 0:
            continue
        if qty > pending.get(empty_item, 0):
            frappe.throw(
                _("Only {0} of {1} pending on this invoice").format(
                    "{0:g}".format(pending.get(empty_item, 0)), empty_item
                )
            )

        # The row that left the empties pending, for its warehouse
        filled_item = frappe.db.get_value(
            "Cylinder Exchange Log",
            {"source_doctype": "Sales Invoice", "source_name": doc.name, "empty_item": empty_item},
            "filled_item",
        )
        row = next(row for row in doc.items if row.item_code == filled_item)
        items.append({
            "filled_item": filled_item,
            "empty_item": empty_item,
            "qty": qty,
            "pending_qty": -qty,
            "warehouse": _get_target_warehouse(doc, row, settings),
            "location": doc.get("gas_agency_location"),
        })

    if not items:
        frappe.throw(_("Enter the number of empties received"))

    stock_entry = _create_stock_entry(doc, items, "Material Receipt", received_later=True)
    if settings.auto_submit_stock_entry:
        stock_entry.submit()

    for item in items:
        _create_exchange_log(doc=doc, item=item, stock_entry=stock_entry, status="Completed")

    update_pending_empties(doc.name)
    return stock_entry.name


def cancel_empties_received(doc, method=None):
    """
    A Stock Entry of empties received after billing was cancelled, so those
    empties are pending again. A sale's own exchange entry is left alone:
    its logs also hold what was pending at billing.
    """
    logs = frappe.get_all(
        "Cylinder Exchange Log",
        # Only a later receipt adds stock (+qty) while lowering the count
        filters={"stock_entry": doc.name, "status": "Completed", "qty": [">", 0], "pending_qty": ["<", 0]},
        fields=["name", "source_name"],
    )
    for log in logs:
        frappe.db.set_value("Cylinder Exchange Log", log.name, "status", "Cancelled")
    for invoice in {log.source_name for log in logs}:
        update_pending_empties(invoice)


def _in_savepoint(save_point, action):
    """
    Run action() inside a savepoint and roll its writes back if it fails, so a
    half-done Stock Entry insert, submit, cancel or delete is never committed
    with the source document. A deadlock is re-raised as is: the database has
    already rolled back the whole transaction, savepoint included.
    """
    frappe.db.savepoint(save_point)
    try:
        return action()
    except frappe.QueryDeadlockError:
        raise
    except Exception:
        try:
            frappe.db.rollback(save_point=save_point)
        except Exception as rollback_error:
            # The savepoint is gone, so the database already rolled back the
            # whole transaction (e.g. a lock wait timeout with
            # innodb_rollback_on_timeout on); fail the request like a deadlock
            raise frappe.QueryDeadlockError(rollback_error) from rollback_error
        raise


def _delete_draft_stock_entry(se_name):
    """Delete a draft exchange Stock Entry after unlinking it from its logs."""
    # Frappe's link check blocks the delete while logs still point at it
    frappe.db.set_value("Cylinder Exchange Log", {"stock_entry": se_name}, "stock_entry", None)
    frappe.delete_doc("Stock Entry", se_name, ignore_permissions=True)


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
    cylinders = _cylinder_count(row)
    # Empties the customer didn't hand over: only Sales Invoice rows have them
    pending_qty = flt(row.get("empties_not_received"))
    return {
        "filled_item": row.item_code,
        "empty_item": rule.empty_item,
        "qty": cylinders * flt(rule.exchange_ratio) - pending_qty,
        "pending_qty": pending_qty,
        "weight_kg": cylinders * flt(rule.filled_weight_kg) if settings.enable_kg_tracking else 0,
        "warehouse": _get_target_warehouse(doc, row, settings),
        "location": doc.get("gas_agency_location"),
        "rule": rule,
    }


def _cylinder_count(row):
    """
    Cylinders on a row in stock UOM. SI/DN item rows carry it in stock_qty
    (qty may be in a sales UOM such as Kg); Packed Item has no stock_qty
    because its qty is already in stock UOM. Rounded to the field's
    precision, since qty x conversion factor can give 2.000000002.
    """
    qty_field = "stock_qty" if row.get("stock_qty") else "qty"
    return flt(row.get(qty_field), row.precision(qty_field))


def _collect_return_items(doc, settings):
    """
    Empties to give back for a credit note made from the invoice (Return /
    Credit Note) with Update Stock ticked: the filled cylinders came back, so
    reverse the invoice's exchange for the returned rows. Returned cylinders
    first clear empties still pending on the invoice; only the rest are
    given back. ERPNext won't let returns add up to more than was sold, so
    this can't give back more than came in. Other returns are left to a
    manual adjustment.
    """
    # Without Update Stock a credit note only corrects the bill; the customer
    # kept the filled cylinders
    if doc.doctype == "Sales Invoice" and not doc.get("update_stock"):
        return []

    # Only an invoice whose sale ran the exchange has empties to settle
    sale_exchanged = (
        doc.doctype == "Sales Invoice"
        and doc.get("return_against")
        and frappe.db.exists(
            "Cylinder Exchange Log",
            {
                "source_doctype": "Sales Invoice",
                "source_name": doc.return_against,
                "status": "Completed",
            },
        )
    )
    if not sale_exchanged:
        _alert_manual_give_back(doc)
        return []

    bundle_parents = {pi.parent_item for pi in (doc.get("packed_items") or [])}
    rows = [row for row in doc.items if row.item_code not in bundle_parents]
    rows += doc.get("packed_items") or []

    pending = get_pending_empties(doc.return_against)
    items = []
    for row in rows:
        rule = _get_exchange_rule(row.item_code)
        # Return rows carry negative quantities, so the logs come out negative
        # and exchange totals net the return out
        if rule and flt(row.qty) < 0:
            item = _build_exchange_item(doc, row, rule, settings)
            # Cylinders the customer never gave empties for cancel what they owe
            available = pending.get(rule.empty_item, 0)
            cleared = min(-item["qty"], available)
            pending[rule.empty_item] = available - cleared
            item["qty"] += cleared
            item["pending_qty"] = -cleared
            items.append(item)
    return items


def _alert_manual_give_back(doc):
    """Tell the user when returned cylinders' empties need a manual Material Issue."""
    rows = list(doc.items) + list(doc.get("packed_items") or [])
    if any(_get_exchange_rule(row.item_code) for row in rows):
        frappe.msgprint(
            _(
                "Cylinder Exchange: empty cylinders were not given back automatically for this "
                "return. If the customer took their empties, record a Material Issue."
            ),
            alert=True,
            indicator="orange",
        )


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
                        # Receipts only: return documents share so_detail with
                        # the sale, but their give-back logs aren't exchanges
                        "qty": [">", 0],
                    },
                )
            )
        if cache[counterpart_name]:
            return True

    return False


def _get_exchange_rule(item_code):
    """Get active Cylinder Exchange Rule for the given item code."""
    # Check with get_value first: loading a missing rule through
    # get_cached_doc leaves a "not found" error in the message log, which the
    # desk shows as a red dialog after an otherwise successful submit
    if not frappe.db.get_value("Cylinder Exchange Rule", item_code, "is_active"):
        return None
    return frappe.get_cached_doc("Cylinder Exchange Rule", item_code)


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

    # A credit note row may sit in a sales-return warehouse; the empties being
    # given back went into the sold row's warehouse
    if row.get("sales_invoice_item"):
        return frappe.db.get_value("Sales Invoice Item", row.sales_invoice_item, "warehouse")

    return row.warehouse


def _create_stock_entry(doc, exchange_items, purpose, received_later=False):
    """
    Create the empty-cylinder Stock Entry: a Material Receipt for a sale or
    for pending empties received later, or a Material Issue giving the
    empties back for a return.
    """
    stock_entry = frappe.new_doc("Stock Entry")
    stock_entry.stock_entry_type = purpose
    stock_entry.company = doc.company
    if received_later:
        # Pending empties come in today, not on the invoice's date
        stock_entry.posting_date = nowdate()
        stock_entry.posting_time = nowtime()
    else:
        stock_entry.posting_date = doc.get("posting_date") or nowdate()
        # The source document's own time, not the clock: a give-back posted
        # earlier in the day than its sale's receipt would find no empties
        # (a loaded document's midnight is timedelta(0), which is falsy)
        posting_time = doc.get("posting_time")
        stock_entry.posting_time = nowtime() if posting_time is None else posting_time
        stock_entry.set_posting_time = 1

    if received_later:
        remarks = _("Pending empty cylinders received for {0} {1}")
    elif purpose == "Material Issue":
        remarks = _("Empty cylinders given back for return {0} {1}")
    else:
        remarks = _("Auto cylinder exchange from {0} {1}")
    stock_entry.remarks = remarks.format(doc.doctype, doc.name)

    cost_center = None
    location_name = doc.get("gas_agency_location")
    if location_name:
        cost_center = frappe.get_cached_doc("Gas Agency Location", location_name).cost_center

    for item in exchange_items:
        row = {
            "item_code": item["empty_item"],
            "qty": abs(item["qty"]),
            "cost_center": cost_center,
        }
        if purpose == "Material Issue":
            row["s_warehouse"] = item["warehouse"]
        else:
            row.update({"t_warehouse": item["warehouse"], "basic_rate": 0})
        stock_entry.append("items", row)

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
    log.pending_qty = item.get("pending_qty", 0)
    log.weight_kg = item.get("weight_kg", 0)
    log.status = status
    log.error_message = error_message
    # Its Stock Entry's date: empties received later come in after the invoice
    log.exchange_date = (stock_entry and stock_entry.posting_date) or doc.get("posting_date") or nowdate()
    log.insert(ignore_permissions=True)
    return log
