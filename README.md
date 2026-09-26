# Trustbit Gas Agency

A Frappe app for an LPG gas agency (client: HP Kapoor) on **ERPNext v15**. When a filled
cylinder is sold, the customer's empty comes back into stock by itself. The app also tracks
credit sales (money or empties still owed), the four sales types of a gas agency
(Normal, NC, DBC, Surrender), vehicles and brokers, and gives the owner dashboards and
bell alerts.

| | |
|---|---|
| Frappe / ERPNext | `>=15,<16` (declared in `pyproject.toml`). v16 is out of scope. |
| Other apps | none required. The production site also runs india_compliance, which shapes the GST rules below. |
| Version | `1.1.0` (`__init__.py`). Everything after commit `f6e2298` is unreleased and untagged; see [Changes](#changes). |
| Production | `https://kvk.trustbit.cloud` (demo data until go-live) |
| Tester guide | `HP Kapoor/TGA_Tester_Guide_v1.2.pdf` and `.md`, in the project folder next to `App/` |

## What it does

### Cylinder exchange

Each filled cylinder item has a **Cylinder Exchange Rule**: its empty item, weights and ratio.
When a Sales Invoice (or Delivery Note, see Gas Agency Settings) is submitted, the app makes
a **Material Receipt** of the empties into the branch's empty warehouse and writes a
**Cylinder Exchange Log** per row. Cancelling the invoice cancels that receipt.

### Sales Types

Every Sales Invoice has a **Sales Type** (`gas_sales_type`, default Normal). Only a Normal
sale exchanges empties.

| Sales Type | Filled cylinder | Empty cylinder | Money |
|---|---|---|---|
| **Normal** (refill) | out | back into stock automatically; may be left pending | gas |
| **NC** (new connection) | out | none taken, none owed | gas + deposits + accessories |
| **DBC** (extra cylinder on an existing connection) | out | none taken, none owed | gas + deposit |
| **Surrender** (connection closed) | — | cylinder and regulator come back | deposits refunded |

A Surrender is a standalone credit note. Before validation the app forces **Is Return** and
**Update Stock**, makes every quantity negative, sets stock rows to ₹0 (clearing price list
rate, discount and margin too, or ERPNext fills the price back in) and sends empties to the
empty warehouse. Only the non-stock deposit rows carry the refund. A credit note made from
an invoice always keeps that invoice's Sales Type; the field is read-only there.

### Credit sales

An invoice is a credit sale while it owes money (`outstanding_amount`) or empties
(`pending_empties`). The type is worked out, never picked: **Amount Pending**,
**Cylinder Pending** or **Both Pending**. It shows in the form, in the Sales Invoice list
(in place of ERPNext's Unpaid/Overdue labels) and on the dashboards.

- **Empties Not Received** on an invoice row leaves empties pending (Normal sales only).
- **Gas Agency → Receive Empties** books empties brought back later as a Material Receipt
  against the same invoice. Cancelling that Stock Entry makes them pending again.
- A credit note with Update Stock first clears the empties still pending on its invoice;
  only the rest are given back (Material Issue). A credit note without Update Stock is a
  price correction and moves nothing.

### Other features

- **Broker** and **Gas Vehicle** masters. Vehicle is required on Sales Invoice; broker is an
  optional tag (no commission). A Payment Entry fills blank broker and vehicle from the first
  Sales Invoice it references. Vehicle numbers are saved in capitals without spaces or dashes.
- **Purchase Invoice**: Vehicle (required), Driver Name and Driver Mobile, filled from the
  vehicle and editable per trip.
- **Admin bell alerts**: role *Gas Agency Admin* gets a notification on every submitted Sales
  and Purchase Invoice (returns are labelled as returns). Bell only; the server has no SMTP.
- **Dashboard Stats** and **Dashboard List View** pages, and the reports **Cylinder Stock
  Summary**, **Location Wise Sales** and **Credit Sales**.

## Business rules the client decided

- The counter bills on a **Sales Invoice with Update Stock**. Returns use Return / Credit Note.
- One Sales Type per invoice. A refill plus a DBC for one customer is two invoices.
- Security deposits go on the invoice as items booked to a **liability** account and are left
  out of every sales figure (rows whose income account's root type is Liability).
- Location Wise Sales and Credit Sales: Accounts User and Accounts Manager only. Storekeepers
  don't see sales money.
- Keep it simple: build for this flow. Other flows get a clear alert or a manual step, not
  more code.

## Setting up a site

The app ships its custom fields, the Gas Agency Admin role and the two notifications as
fixtures. Everything else is data:

1. **Gas Agency Settings**: auto exchange on, create exchange on Sales Invoice (or Both),
   auto-submit Stock Entry, KG tracking.
2. **Gas Agency Location** per branch: filled warehouse, **Empty Cylinder Warehouse**,
   cost center, minimum filled cylinders.
3. **Cylinder Exchange Rule** per filled item.
4. **Deposits** (setup, not code): a *Customer Security Deposits* account under Current
   Liabilities per company, and non-stock items *Cylinder Security Deposit* and *Regulator
   Security Deposit* whose Item Defaults point their income account at it. Give them the
   **Nil-Rated** item tax template: india_compliance refuses Non-GST rows on an invoice that
   also has GST rows (*Items not covered under GST cannot be clubbed with items for which
   GST is applicable*). It also needs an HSN code on every row. On kvk these use 731100 and
   84811000; the client's CA should confirm the treatment.
5. **Gas Vehicle**, **Broker**, and the Gas Agency Admin role for the owner's user.

## Code map

| Path | What it does |
|---|---|
| `utils/cylinder_exchange.py` | Exchange on submit and cancel, Sales Type rules (`takes_empties`, `set_sales_type`), pending empties, Receive Empties API |
| `overrides/sales_invoice.py` | `before_validate` (Sales Type), `validate` (Empties Not Received), `on_submit`, `on_cancel` |
| `overrides/delivery_note.py`, `stock_entry.py`, `payment_entry.py` | DN exchange; receipt cancel restores pending; Payment Entry broker/vehicle |
| `utils/stock_utils.py` | Dashboard Stats data, including the Sales Type split and the deposit exclusion |
| `utils/list_dashboard.py` | Dashboard List View data |
| `public/js/sales_invoice.js` | Receive Empties dialog, credit type banner, Surrender form behaviour |
| `public/js/sales_invoice_list.js` | Credit type labels in the list |
| `fixtures/` | Custom fields, the Gas Agency Admin role, the two notifications |
| `trustbit_gas_agency/page/`, `report/`, `doctype/` | Pages, reports, and the doctypes: Gas Agency Settings, Gas Agency Location, Cylinder Exchange Rule, Cylinder Exchange Log, Broker, Gas Vehicle |

Custom fields worth knowing: Sales Invoice `gas_agency_location`, `gas_sales_type`,
`pending_empties`, `broker`, `gas_vehicle`; Sales Invoice Item `is_gas_cylinder`,
`cylinder_exchange_rule`, `empties_not_received`; Purchase Invoice `gas_vehicle`,
`gas_driver_name`, `gas_driver_mobile`. The `gas_` prefix avoids india_compliance's own
`vehicle_no` / `driver` / `driver_name`, and the doctype is *Gas Vehicle* because ERPNext
already has *Vehicle*.

## Developing and testing

- The local v15 bench links `apps/trustbit_gas_agency` to this folder. Its site `kvk.local`
  has never run the setup wizard, so full invoice flows can't be tested there.
- Flows are tested on the server with a Python script piped into the site that creates
  documents, asserts the results and calls `frappe.db.rollback()` in `finally`. Stub
  `frappe.enqueue` first: the admin alerts are enqueued, so a rolled-back submit would
  otherwise still queue a notification about a document that no longer exists. Afterwards,
  check from a fresh connection that nothing persisted.
- Testers follow the Tester Guide v1.2 on the DEMO branch and customers.

## Deploying

Follow the server runbook `docs/08-kvk-custom-app.md` in the
[VM-Server-Trustbit](https://github.com/zxrrcpandey/VM-Server-Trustbit) repo. Then on the server:

```bash
export PATH=$HOME/.local/bin:$PATH        # one-shot ssh: bench needs uv on the PATH
cd ~/frappe-bench
bench --site kvk.trustbit.cloud backup --with-files
git -C apps/trustbit_gas_agency pull --ff-only upstream main
bench --site kvk.trustbit.cloud migrate
bench build --app trustbit_gas_agency
sudo supervisorctl restart frappe-bench-web: frappe-bench-workers:
```

- **Changed a page's JS or HTML?** Bump `modified` in that page's `.json`. The desk keeps
  page code in the browser's localStorage and only drops it when that stamp changes.
- **Changed `hooks.py`?** The merged hooks stay cached in redis. Clear just those keys from
  `bench --site kvk.trustbit.cloud console`: `frappe.cache().delete_keys("hooks")` and
  `frappe.cache().delete_keys("app_hooks")`.
- **Don't run `bench clear-cache` on production.** It deletes every redis key for the site.
  Use the targeted clears above.

## Changes

All on `main`; the version stays 1.1.0 until the client signs off and it is tagged.

| Date | Commit | Change |
|---|---|---|
| 2026-09-26 | `69515b5` | Surrender: returned cylinder and regulator carry no charge |
| 2026-09-26 | `8e7c78e` | Sales Type (Normal, NC, DBC, Surrender); type split on dashboards and reports; deposits left out of sales |
| 2026-09-26 | `187cbae` | Vehicle, driver name and mobile on Purchase Invoice |
| 2026-09-26 | `df6415c`, `bfddb44` | Admin bell alerts; credit types on the dashboards |
| 2026-09-26 | `4efdf84`, `c3f52a5`, `94a138f` | Credit sales: pending empties, Receive Empties, list labels, Credit Sales report |
| 2026-09-26 | `4b544ab` | Broker and Gas Vehicle masters on Sales Invoice and Payment Entry |
| 2026-09-24/25 | `cd7fab1` … `5cc4cf3` | Location-wise dashboard (Dashboard Stats), filters, Dashboard List View |
| 2026-09-24 | `f6e2298` | Release 1.1.0: bug fixes, returns give empties back, `pyproject.toml` |
| 2026-04-12 | `f1ae964` | 1.0.0 |

## License

MIT, see `license.txt`.
