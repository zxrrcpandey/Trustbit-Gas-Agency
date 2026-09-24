frappe.pages["gas-agency-dashboard"].on_page_load = function (wrapper) {
    var page = frappe.ui.make_app_page({
        parent: wrapper,
        title: __("Gas Agency Dashboard"),
        single_column: true,
    });

    page.main.html(frappe.render_template("gas_agency_dashboard"));

    // Add filters
    // Filled with the company's active locations on each refresh
    page.location_filter = page.add_field({
        fieldname: "location",
        label: __("Location"),
        fieldtype: "Select",
        options: [{ value: "", label: __("All Locations") }],
        change: function () {
            refresh_dashboard(page);
        },
    });

    page.from_date_filter = page.add_field({
        fieldname: "from_date",
        label: __("From Date"),
        fieldtype: "Date",
        default: frappe.datetime.add_days(frappe.datetime.nowdate(), -30),
        change: function () {
            refresh_dashboard(page);
        },
    });

    page.to_date_filter = page.add_field({
        fieldname: "to_date",
        label: __("To Date"),
        fieldtype: "Date",
        default: frappe.datetime.nowdate(),
        change: function () {
            refresh_dashboard(page);
        },
    });

    page.company_filter = page.add_field({
        fieldname: "company",
        label: __("Company"),
        fieldtype: "Link",
        options: "Company",
        default: frappe.defaults.get_default("company"),
        change: function () {
            refresh_dashboard(page);
        },
    });

    // Initial load
    refresh_dashboard(page);
};

function refresh_dashboard(page) {
    var filters = {
        location: page.fields_dict.location.get_value(),
        from_date: page.fields_dict.from_date.get_value(),
        to_date: page.fields_dict.to_date.get_value(),
        company: page.fields_dict.company.get_value(),
    };

    frappe.xcall(
        "trustbit_gas_agency.utils.stock_utils.get_dashboard_data",
        filters
    ).then(function (data) {
        if (!update_location_options(page, data.location_options || [])) {
            // The selected location isn't in this company; clearing it refreshes again
            return;
        }
        render_summary_cards(page, data.locations || []);
        render_location_table(page, data.locations || []);
        render_sales_trend(page, data.daily_sales || []);
        render_exchange_logs(page, data.exchange_logs);
    });
}

function update_location_options(page, location_names) {
    // Returns false when the selection had to be cleared (its change handler refreshes)
    var field = page.fields_dict.location;
    var selected = field.get_value();

    field.df.options = [{ value: "", label: __("All Locations") }].concat(location_names);
    field.set_options(selected);

    if (selected && location_names.indexOf(selected) === -1) {
        field.set_value("");
        return false;
    }
    return true;
}

function sum(rows, field) {
    return rows.reduce(function (total, row) {
        return total + (row[field] || 0);
    }, 0);
}

function fmt_qty(value) {
    value = value || 0;
    return format_number(value, null, value % 1 === 0 ? 0 : 2);
}

function render_summary_cards(page, locations) {
    var $container = page.main.find(".summary-cards");
    $container.empty();

    var low_stock_count = locations.filter(function (row) {
        return row.low_stock;
    }).length;

    var cards = [
        {
            label: __("Purchase"),
            value: format_currency(sum(locations, "purchase_amount")),
            note: __("{0} filled cylinders", [fmt_qty(sum(locations, "purchase_qty"))]),
            cls: "purchase",
        },
        {
            label: __("To Pay"),
            value: format_currency(sum(locations, "pending_purchase")),
            note: __("unpaid supplier bills"),
            cls: "to-pay",
        },
        {
            label: __("Sales"),
            value: format_currency(sum(locations, "sales_amount")),
            note: __("{0} cylinders · {1} KG", [
                fmt_qty(sum(locations, "sales_qty")),
                fmt_qty(sum(locations, "sales_kg")),
            ]),
            cls: "sales",
        },
        {
            label: __("To Collect"),
            value: format_currency(sum(locations, "pending_sales")),
            note: __("unpaid customer invoices"),
            cls: "to-collect",
        },
        {
            label: __("Collected"),
            value: format_currency(sum(locations, "collected")),
            note: __("payments received"),
            cls: "collected",
        },
        {
            label: __("Cylinders in Hand"),
            value: fmt_qty(sum(locations, "filled_qty")),
            note: __("filled · {0} empty", [fmt_qty(sum(locations, "empty_qty"))]),
            cls: "stock",
        },
    ];

    if (low_stock_count) {
        cards.push({
            label: __("Low Stock"),
            value: low_stock_count,
            note: __("location(s) below minimum"),
            cls: "low",
        });
    }

    cards.forEach(function (card) {
        $container.append(
            '<div class="summary-card ' + card.cls + '">' +
                '<div class="card-value">' + card.value + "</div>" +
                '<div class="card-label">' + card.label + "</div>" +
                '<div class="card-note">' + card.note + "</div>" +
            "</div>"
        );
    });
}

function escape_html(value) {
    if (value === null || value === undefined) {
        return "";
    }
    return String(value).replace(/[&<>"']/g, function (c) {
        return {
            "&": "&amp;",
            "<": "&lt;",
            ">": "&gt;",
            '"': "&quot;",
            "'": "&#39;",
        }[c];
    });
}

function num_cell(main, sub) {
    return '<td class="num">' + main + (sub ? '<div class="sub">' + sub + "</div>" : "") + "</td>";
}

function render_location_table(page, locations) {
    var $container = page.main.find(".location-table");
    $container.empty();

    if (!locations.length) {
        $container.html('<p class="text-muted">' + __("No active locations") + "</p>");
        return;
    }

    var html = "<table>" +
        "<thead><tr>" +
        "<th>" + __("Location") + "</th>" +
        '<th class="num">' + __("Purchase") + "</th>" +
        '<th class="num">' + __("To Pay") + "</th>" +
        '<th class="num">' + __("Sales") + "</th>" +
        '<th class="num">' + __("To Collect") + "</th>" +
        '<th class="num">' + __("Collected") + "</th>" +
        '<th class="num">' + __("Filled in Hand") + "</th>" +
        '<th class="num">' + __("Empty in Hand") + "</th>" +
        '<th class="num">' + __("Empties In") + "</th>" +
        '<th class="num">' + __("Empties Out") + "</th>" +
        "</tr></thead><tbody>";

    locations.forEach(function (row) {
        var location =
            '<a href="/app/gas-agency-location/' + encodeURIComponent(row.location) + '">' +
            escape_html(row.location) +
            "</a>";
        if (row.low_stock) {
            location +=
                ' <span class="indicator-pill red">' +
                __("Low stock (min {0})", [row.min_filled_qty]) +
                "</span>";
        }

        html += '<tr class="' + (row.low_stock ? "low-stock" : "") + '">' +
            "<td>" + location + "</td>" +
            num_cell(format_currency(row.purchase_amount), __("{0} cyl", [fmt_qty(row.purchase_qty)])) +
            num_cell(format_currency(row.pending_purchase)) +
            num_cell(
                format_currency(row.sales_amount),
                __("{0} cyl · {1} KG", [fmt_qty(row.sales_qty), fmt_qty(row.sales_kg)])
            ) +
            num_cell(format_currency(row.pending_sales)) +
            num_cell(format_currency(row.collected)) +
            num_cell(fmt_qty(row.filled_qty), __("{0} KG", [fmt_qty(row.filled_kg)])) +
            num_cell(fmt_qty(row.empty_qty), __("{0} KG", [fmt_qty(row.empty_kg)])) +
            num_cell(fmt_qty(row.empties_in)) +
            num_cell(fmt_qty(row.empties_out)) +
            "</tr>";
    });

    html += "</tbody></table>";
    $container.html(html);
}

function render_sales_trend(page, days) {
    var $container = page.main.find(".sales-trend");
    $container.empty();

    var has_sales = days.some(function (day) {
        return day.amount;
    });
    if (!has_sales) {
        $container.html('<p class="text-muted">' + __("No sales in the selected dates") + "</p>");
        return;
    }

    new frappe.Chart($container[0], {
        type: "line",
        height: 250,
        data: {
            labels: days.map(function (day) {
                return frappe.datetime.str_to_user(day.date);
            }),
            datasets: [
                {
                    name: __("Sales"),
                    values: days.map(function (day) {
                        return day.amount;
                    }),
                },
            ],
        },
        colors: ["#4CAF50"],
        axisOptions: { xIsSeries: 1 },
        lineOptions: { regionFill: 1 },
    });
}

function render_exchange_logs(page, logs) {
    var $container = page.main.find(".exchange-logs-table");
    $container.empty();

    if (!logs || !logs.length) {
        $container.html(
            '<p class="text-muted">' + __("No recent exchanges") + "</p>"
        );
        return;
    }

    var html = "<table>" +
        "<thead><tr>" +
        "<th>" + __("Date") + "</th>" +
        "<th>" + __("Source") + "</th>" +
        "<th>" + __("Location") + "</th>" +
        "<th>" + __("Filled Item") + "</th>" +
        "<th>" + __("Empty Item") + "</th>" +
        "<th>" + __("Qty") + "</th>" +
        "<th>" + __("KG") + "</th>" +
        "<th>" + __("Status") + "</th>" +
        "<th>" + __("Stock Entry") + "</th>" +
        "</tr></thead><tbody>";

    var status_colors = { Completed: "green", Cancelled: "orange", Error: "red" };

    logs.forEach(function (log) {
        var source_href =
            "/app/" +
            encodeURIComponent(frappe.router.slug(log.source_doctype)) +
            "/" +
            encodeURIComponent(log.source_name);
        var source_link =
            '<a href="' + source_href + '">' + escape_html(log.source_name) + "</a>";
        var se_link = log.stock_entry
            ? '<a href="/app/stock-entry/' +
              encodeURIComponent(log.stock_entry) +
              '">' +
              escape_html(log.stock_entry) +
              "</a>"
            : "-";

        var status_pill =
            '<span class="indicator-pill ' +
            (status_colors[log.status] || "gray") +
            '" title="' +
            escape_html(log.error_message || "") +
            '">' +
            escape_html(log.status) +
            "</span>";

        html += "<tr>" +
            "<td>" + escape_html(frappe.datetime.str_to_user(log.exchange_date)) + "</td>" +
            "<td>" + source_link + "</td>" +
            "<td>" + escape_html(log.location || "-") + "</td>" +
            "<td>" + escape_html(log.filled_item) + "</td>" +
            "<td>" + escape_html(log.empty_item) + "</td>" +
            "<td>" + escape_html(log.qty) + "</td>" +
            "<td>" + escape_html((log.weight_kg || 0).toFixed(2)) + "</td>" +
            "<td>" + status_pill + "</td>" +
            "<td>" + se_link + "</td>" +
            "</tr>";
    });

    html += "</tbody></table>";
    $container.html(html);
}
