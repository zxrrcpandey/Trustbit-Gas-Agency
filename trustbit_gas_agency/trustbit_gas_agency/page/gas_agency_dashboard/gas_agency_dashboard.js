frappe.pages["gas-agency-dashboard"].on_page_load = function (wrapper) {
    var page = frappe.ui.make_app_page({
        parent: wrapper,
        title: __("Gas Agency Dashboard"),
        single_column: true,
    });

    page.main.html(frappe.render_template("gas_agency_dashboard"));

    // Add filters
    page.location_filter = page.add_field({
        fieldname: "location",
        label: __("Location"),
        fieldtype: "Link",
        options: "Gas Agency Location",
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
        render_summary_cards(page, data);
        render_stock_table(page, data.stock_summary);
        render_sales_chart(page, data);
        render_exchange_logs(page, data.exchange_logs);
    });
}

function render_summary_cards(page, data) {
    var $container = page.main.find(".summary-cards");
    $container.empty();

    var total_filled = 0;
    var total_empty = 0;
    var total_sales = 0;
    var total_revenue = 0;

    (data.stock_summary || []).forEach(function (s) {
        total_filled += s.filled_qty;
        total_empty += s.empty_qty;
    });

    (data.sales_summary || []).forEach(function (s) {
        total_sales += s.sales_count;
    });

    (data.revenue_summary || []).forEach(function (s) {
        total_revenue += s.total_revenue;
    });

    var cards = [
        {
            label: __("Filled Cylinders"),
            value: total_filled,
            cls: "filled",
        },
        {
            label: __("Empty Cylinders"),
            value: total_empty,
            cls: "empty",
        },
        {
            label: __("Total Sales"),
            value: total_sales,
            cls: "sales",
        },
        {
            label: __("Total Revenue"),
            value: format_currency(total_revenue),
            cls: "revenue",
        },
    ];

    cards.forEach(function (card) {
        $container.append(
            '<div class="summary-card ' + card.cls + '">' +
                '<div class="card-value">' + card.value + "</div>" +
                '<div class="card-label">' + card.label + "</div>" +
            "</div>"
        );
    });
}

function render_stock_table(page, stock_summary) {
    var $container = page.main.find(".stock-table");
    $container.empty();

    if (!stock_summary || !stock_summary.length) {
        $container.html('<p class="text-muted">' + __("No stock data available") + "</p>");
        return;
    }

    var html = "<table>" +
        "<thead><tr>" +
        "<th>" + __("Location") + "</th>" +
        "<th>" + __("Filled Qty") + "</th>" +
        "<th>" + __("Empty Qty") + "</th>" +
        "<th>" + __("Filled KG") + "</th>" +
        "<th>" + __("Empty KG") + "</th>" +
        "</tr></thead><tbody>";

    stock_summary.forEach(function (row) {
        html += "<tr>" +
            "<td>" + row.location + "</td>" +
            "<td>" + row.filled_qty + "</td>" +
            "<td>" + row.empty_qty + "</td>" +
            "<td>" + row.filled_kg.toFixed(2) + "</td>" +
            "<td>" + row.empty_kg.toFixed(2) + "</td>" +
            "</tr>";
    });

    html += "</tbody></table>";
    $container.html(html);
}

function render_sales_chart(page, data) {
    var $container = page.main.find(".sales-chart");
    $container.empty();

    var sales_summary = data.sales_summary || [];
    var revenue_summary = data.revenue_summary || [];

    if (!sales_summary.length) {
        $container.html('<p class="text-muted">' + __("No sales data available") + "</p>");
        return;
    }

    var labels = sales_summary.map(function (s) {
        return s.location;
    });
    var sales_values = sales_summary.map(function (s) {
        return s.sales_count;
    });
    var revenue_values = revenue_summary.map(function (s) {
        return s.total_revenue;
    });

    new frappe.Chart($container[0], {
        type: "bar",
        height: 300,
        data: {
            labels: labels,
            datasets: [
                { name: __("Sales Count"), values: sales_values },
                { name: __("Revenue"), values: revenue_values },
            ],
        },
        colors: ["#4CAF50", "#9C27B0"],
        barOptions: {
            spaceRatio: 0.4,
        },
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
        "<th>" + __("Stock Entry") + "</th>" +
        "</tr></thead><tbody>";

    logs.forEach(function (log) {
        var source_link =
            '<a href="/app/' +
            frappe.router.slug(log.source_doctype) +
            "/" +
            log.source_name +
            '">' +
            log.source_name +
            "</a>";
        var se_link = log.stock_entry
            ? '<a href="/app/stock-entry/' +
              log.stock_entry +
              '">' +
              log.stock_entry +
              "</a>"
            : "-";

        html += "<tr>" +
            "<td>" + frappe.datetime.str_to_user(log.exchange_date) + "</td>" +
            "<td>" + source_link + "</td>" +
            "<td>" + (log.location || "-") + "</td>" +
            "<td>" + log.filled_item + "</td>" +
            "<td>" + log.empty_item + "</td>" +
            "<td>" + log.qty + "</td>" +
            "<td>" + (log.weight_kg || 0).toFixed(2) + "</td>" +
            "<td>" + se_link + "</td>" +
            "</tr>";
    });

    html += "</tbody></table>";
    $container.html(html);
}
