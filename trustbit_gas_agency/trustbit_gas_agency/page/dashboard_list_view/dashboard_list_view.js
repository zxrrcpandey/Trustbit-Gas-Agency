// Wrapped in a function so its helpers don't collide with Dashboard Stats'
// globals (page scripts share the desk's global scope)
(function () {
    var TYPE_LABELS = {
        "Purchase Order": __("Order"),
        "Purchase Receipt": __("Receipt"),
        "Purchase Invoice": __("Invoice"),
        "Sales Order": __("Order"),
        "Sales Invoice": __("Invoice"),
    };

    var STATUS_COLORS = {
        Draft: "gray",
        Paid: "green",
        Completed: "green",
        Submitted: "blue",
        "To Bill": "blue",
        Unpaid: "orange",
        "To Receive": "orange",
        "To Receive and Bill": "orange",
        "To Deliver": "orange",
        "To Deliver and Bill": "orange",
        "Partly Paid": "yellow",
        Overdue: "red",
        Return: "gray",
        "Credit Note Issued": "gray",
    };

    var SECTIONS = [
        {
            key: "purchases",
            title: __("Purchases"),
            note: __("Purchase orders, receipts and invoices"),
            columns: [
                col(__("Date"), function (r) { return fmt_date(r.date); }),
                col(__("Type"), function (r) { return TYPE_LABELS[r.doctype]; }),
                col(__("Document"), function (r) { return doc_link(r.doctype, r.name); }),
                col(__("Supplier"), function (r) { return escape_html(r.party); }),
                col(__("Amount"), function (r) { return format_currency(r.amount); }, true),
                col(__("Status"), function (r) { return status_pill(r.status); }),
            ],
            more: function (f, data) {
                return [
                    more(__("All Orders"), "Purchase Order",
                        doc_filters(f, "transaction_date", branch_items(f, data, "Purchase Order Item"))),
                    more(__("All Receipts"), "Purchase Receipt",
                        doc_filters(f, "posting_date", branch_items(f, data, "Purchase Receipt Item"))),
                    more(__("All Invoices"), "Purchase Invoice",
                        doc_filters(f, "posting_date", branch_items(f, data, "Purchase Invoice Item"))),
                ];
            },
        },
        {
            key: "sales",
            title: __("Sales"),
            note: __("Sales orders and invoices"),
            columns: [
                col(__("Date"), function (r) { return fmt_date(r.date); }),
                col(__("Type"), function (r) { return TYPE_LABELS[r.doctype]; }),
                col(__("Document"), function (r) { return doc_link(r.doctype, r.name); }),
                col(__("Customer"), function (r) { return escape_html(r.party); }),
                col(__("Amount"), function (r) { return format_currency(r.amount); }, true),
                col(__("Status"), function (r) { return status_pill(r.status); }),
            ],
            more: function (f, data) {
                var invoice_filters = f.location ? { gas_agency_location: f.location } : {};
                return [
                    more(__("All Orders"), "Sales Order",
                        doc_filters(f, "transaction_date", branch_items(f, data, "Sales Order Item"))),
                    more(__("All Invoices"), "Sales Invoice", doc_filters(f, "posting_date", invoice_filters)),
                ];
            },
        },
        {
            key: "supplier_payments",
            title: __("Payments to Suppliers"),
            note: __("For a branch: payments against its purchase invoices"),
            columns: payment_columns(__("Supplier")),
            more: function (f) {
                return [more(__("All Supplier Payments"), "Payment Entry",
                    doc_filters(f, "posting_date", { payment_type: "Pay", docstatus: 1 }))];
            },
        },
        {
            key: "customer_payments",
            title: __("Payments Received"),
            note: __("Done: payments from customers"),
            columns: payment_columns(__("Customer")),
            more: function (f) {
                return [more(__("All Payments Received"), "Payment Entry",
                    doc_filters(f, "posting_date", { payment_type: "Receive", docstatus: 1 }))];
            },
        },
        {
            key: "pending_invoices",
            title: __("Pending Customer Payments"),
            note: __("Invoices not yet fully paid, as of now"),
            columns: [
                col(__("Date"), function (r) { return fmt_date(r.date); }),
                col(__("Invoice"), function (r) { return doc_link("Sales Invoice", r.name); }),
                col(__("Customer"), function (r) { return escape_html(r.party); }),
                col(__("Due"), function (r) { return fmt_date(r.due_date); }),
                col(__("Amount"), function (r) { return format_currency(r.amount); }, true),
                col(__("Outstanding"), function (r) { return format_currency(r.outstanding_amount); }, true),
                col(__("Status"), function (r) { return status_pill(r.status); }),
            ],
            more: function (f) {
                var filters = { docstatus: 1, outstanding_amount: [">", 0] };
                if (f.company) filters.company = f.company;
                if (f.location) filters.gas_agency_location = f.location;
                return [more(__("All Unpaid Invoices"), "Sales Invoice", filters)];
            },
        },
        {
            key: "cylinder_movements",
            title: __("Filled / Empty Cylinders"),
            note: __("Latest stock movements of cylinders"),
            columns: [
                col(__("Date"), function (r) { return fmt_date(r.date); }),
                col(__("Cylinder"), function (r) {
                    return '<span class="indicator-pill ' + (r.kind === "Filled" ? "blue" : "orange") + '">' +
                        __(r.kind) + "</span>";
                }),
                col(__("Item"), function (r) { return escape_html(r.item_code); }),
                col(__("Warehouse"), function (r) { return escape_html(r.warehouse); }),
                col(__("In / Out"), function (r) { return (r.actual_qty > 0 ? "+" : "") + fmt_qty(r.actual_qty); }, true),
                col(__("Balance"), function (r) { return fmt_qty(r.qty_after_transaction); }, true),
                col(__("Document"), function (r) { return doc_link(r.voucher_type, r.voucher_no); }),
            ],
            more: function (f, data) {
                var filters = doc_filters(f, "posting_date", {
                    is_cancelled: 0,
                    item_code: ["in", data.cylinder_items],
                });
                if (f.location) filters.warehouse = ["in", data.branch_warehouses];
                return [more(__("All Cylinder Movements"), "Stock Ledger Entry", filters)];
            },
        },
        {
            key: "low_stock",
            title: __("Low Stock"),
            note: __("Branches below their Minimum Filled Cylinders, as of now"),
            columns: [
                col(__("Branch"), function (r) { return doc_link("Gas Agency Location", r.location); }),
                col(__("Company"), function (r) { return escape_html(r.company); }),
                col(__("Filled in Hand"), function (r) { return fmt_qty(r.filled_qty); }, true),
                col(__("Minimum"), function (r) { return fmt_qty(r.min_filled_qty); }, true),
                col(__("Short by"), function (r) {
                    return '<span class="text-danger">' + fmt_qty(r.shortfall) + "</span>";
                }, true),
                col(__("Empty in Hand"), function (r) { return fmt_qty(r.empty_qty); }, true),
            ],
            more: function (f) {
                return [more(__("All Branches"), "Gas Agency Location", f.company ? { company: f.company } : {})];
            },
        },
        {
            key: "exchange_errors",
            title: __("Exchange Errors"),
            note: __("Cylinder exchanges that failed and need a look"),
            columns: [
                col(__("Date"), function (r) { return fmt_date(r.exchange_date); }),
                col(__("Source"), function (r) { return doc_link(r.source_doctype, r.source_name); }),
                col(__("Branch"), function (r) { return escape_html(r.location || "-"); }),
                col(__("Item"), function (r) { return escape_html(r.filled_item); }),
                col(__("Qty"), function (r) { return fmt_qty(r.qty); }, true),
                col(__("Error"), function (r) {
                    // error messages can carry HTML from ERPNext; show their text only
                    return '<div class="error-text">' + escape_html($("<div>").html(r.error_message || "").text()) + "</div>";
                }),
            ],
            more: function (f) {
                var filters = doc_filters(f, "exchange_date", { status: "Error" });
                delete filters.company;
                if (f.location) filters.location = f.location;
                return [more(__("All Exchange Errors"), "Cylinder Exchange Log", filters)];
            },
        },
    ];

    frappe.pages["dashboard-list-view"].on_page_load = function (wrapper) {
        var page = frappe.ui.make_app_page({
            parent: wrapper,
            title: __("Dashboard List View"),
            single_column: true,
        });

        // Append, don't replace: page.main already holds the page's filter bar
        page.main.append(frappe.render_template("dashboard_list_view"));

        // Same filters as Dashboard Stats: Company, then its branches, then the dates
        var default_company = frappe.defaults.get_default("company") || "";
        page.add_field({
            fieldname: "company",
            label: __("Company"),
            fieldtype: "Select",
            options: [{ value: "", label: __("All Companies") }].concat(
                default_company ? [default_company] : []
            ),
            default: default_company,
            change: function () { refresh(page); },
        });
        page.add_field({
            fieldname: "location",
            label: __("Location"),
            fieldtype: "Select",
            options: [{ value: "", label: __("All Locations") }],
            change: function () { refresh(page); },
        });
        page.add_field({
            fieldname: "from_date",
            label: __("From Date"),
            fieldtype: "Date",
            default: frappe.datetime.add_days(frappe.datetime.nowdate(), -30),
            change: function () { refresh(page); },
        });
        page.add_field({
            fieldname: "to_date",
            label: __("To Date"),
            fieldtype: "Date",
            default: frappe.datetime.nowdate(),
            change: function () { refresh(page); },
        });

        page.main.on("click", ".more-link", function () {
            frappe.route_options = JSON.parse($(this).attr("data-filters"));
            frappe.set_route("List", $(this).attr("data-doctype"));
        });

        refresh(page);
    };

    function refresh(page) {
        var fields = page.fields_dict;
        var f = {
            company: fields.company.get_value(),
            location: fields.location.get_value(),
            from_date: fields.from_date.get_value(),
            to_date: fields.to_date.get_value(),
        };

        frappe.xcall("trustbit_gas_agency.utils.list_dashboard.get_list_dashboard_data", f).then(function (data) {
            if (
                !set_select_options(fields.company, __("All Companies"), data.company_options || []) ||
                !set_select_options(fields.location, __("All Locations"), data.location_options || [])
            ) {
                // A selection is no longer offered; clearing it refreshes again
                return;
            }
            render(page, f, data);
        });
    }

    function set_select_options(field, all_label, names) {
        // Returns false when the selection had to be cleared (its change handler refreshes)
        var selected = field.get_value();
        field.df.options = [{ value: "", label: all_label }].concat(names);
        field.set_options(selected);
        if (selected && names.indexOf(selected) === -1) {
            field.set_value("");
            return false;
        }
        return true;
    }

    function render(page, f, data) {
        var $sections = page.main.find(".list-dashboard-sections").empty();
        SECTIONS.forEach(function (section) {
            $sections.append(
                '<div class="list-section">' +
                    '<div class="list-section-head"><h5>' + section.title + "</h5>" +
                    '<div class="note">' + section.note + "</div></div>" +
                    '<div class="list-section-body">' + table(section.columns, data[section.key] || []) + "</div>" +
                    '<div class="list-section-foot">' + section.more(f, data).map(more_link).join("") + "</div>" +
                "</div>"
            );
        });
    }

    function table(columns, rows) {
        if (!rows.length) {
            return '<p class="text-muted">' + __("Nothing to show") + "</p>";
        }
        var head = columns.map(function (c) {
            return "<th" + (c.num ? ' class="num"' : "") + ">" + c.label + "</th>";
        });
        var body = rows.map(function (row) {
            return "<tr>" + columns.map(function (c) {
                var value = c.value(row);
                return "<td" + (c.num ? ' class="num"' : "") + ">" + (value == null ? "" : value) + "</td>";
            }).join("") + "</tr>";
        });
        return "<table><thead><tr>" + head.join("") + "</tr></thead><tbody>" + body.join("") + "</tbody></table>";
    }

    function col(label, value, num) {
        return { label: label, value: value, num: num };
    }

    function more(label, doctype, filters) {
        return { label: label, doctype: doctype, filters: filters };
    }

    function more_link(m) {
        return '<a class="more-link" data-doctype="' + escape_html(m.doctype) + '" data-filters="' +
            escape_html(JSON.stringify(m.filters)) + '">' + m.label + " →</a>";
    }

    function doc_filters(f, date_field, extra) {
        var filters = {};
        if (f.company) filters.company = f.company;
        filters[date_field] = ["between", [f.from_date, f.to_date]];
        return Object.assign(filters, extra || {});
    }

    function branch_items(f, data, item_doctype) {
        // A branch narrows a list to documents with an item in its warehouses
        var extra = {};
        if (f.location) extra[item_doctype + ".warehouse"] = ["in", data.branch_warehouses];
        return extra;
    }

    function payment_columns(party_label) {
        return [
            col(__("Date"), function (r) { return fmt_date(r.date); }),
            col(__("Payment"), function (r) { return doc_link("Payment Entry", r.name); }),
            col(party_label, function (r) { return escape_html(r.party); }),
            col(__("Mode"), function (r) { return escape_html(r.mode_of_payment || "-"); }),
            col(__("Amount"), function (r) { return format_currency(r.amount); }, true),
        ];
    }

    function doc_link(doctype, name) {
        if (!doctype || !name) return "-";
        return '<a href="/app/' + encodeURIComponent(frappe.router.slug(doctype)) + "/" +
            encodeURIComponent(name) + '">' + escape_html(name) + "</a>";
    }

    function status_pill(status) {
        if (!status) return "";
        return '<span class="indicator-pill ' + (STATUS_COLORS[status] || "gray") + '">' +
            escape_html(__(status)) + "</span>";
    }

    function fmt_date(value) {
        return value ? escape_html(frappe.datetime.str_to_user(value)) : "";
    }

    function fmt_qty(value) {
        value = value || 0;
        return format_number(value, null, value % 1 === 0 ? 0 : 2);
    }

    function escape_html(value) {
        if (value === null || value === undefined) return "";
        return String(value).replace(/[&<>"']/g, function (c) {
            return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
        });
    }
})();
