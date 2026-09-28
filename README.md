# InvenTree Parts Sheet

A familiar editable sheet for the **entire InvenTree parts catalogue**. Add a row,
save it, and the plugin creates a real InvenTree part and assigns its next number.
Existing part numbers link straight to their InvenTree part pages.

## Install

Supported host: **InvenTree 1.3.2–1.3.x**. The release is validated against 1.3.5.
Customer Pricing integration targets `damatter/inventree-customer-pricing` **0.6.1**.
Parts Sheet also works when Customer Pricing is not installed; pricing controls are hidden.

In InvenTree's plugin installer:

* Package name: `inventree-parts-sheet`
* Source URL:

```text
git+https://github.com/damatter/inventree-parts-sheet.git@0.1.0
```

Leave the separate version field blank. Enable **Parts Sheet**, **App integration**
and **User interface integration** in plugin settings. Run your usual update so the
plugin's database migrations are applied, then restart both processes:

```sh
docker compose run --rm inventree-server invoke update
docker compose restart inventree-server inventree-worker
```

Use your own Compose service names if different. Install/update plugins one at a
time. A migration or restart is required even though this plugin serves its browser
assets directly and does not depend on shared static-file collection.

Open `/plugin/parts-sheet/` on your InvenTree server, use the **Parts Sheet** command
in InvenTree search, or add its dashboard tile. Hard-refresh after updating.

## Everyday use

1. Search by number, name or description. Filter by category or Active status.
2. Click a cell and type. Tab moves across, Enter moves down, and a tab-separated
   block copied from Excel can be pasted into the grid. Yellow rows have unsaved edits.
3. Click **Save changes** (or Ctrl+S). All rows in that save succeed together.
4. Click a part number to open the same InvenTree part used by stock, quotes,
   reports, images, attachments, BOMs and prices.

For a new part, choose its number series and click **Add part**. Enter a description,
category and other cells, then save. A blank number receives the next number;
a supplied special number such as `HYD 704-6` is preserved. Set **Assembly /
manufactured**, Component, Purchasable and Salable under **Details** as appropriate.
New parts start **inactive** until you choose Active. Creating a part does not
create stock or a manufacturing/build record.

Active is the real InvenTree `Part.active` flag. Your Website Parts plugin/catalogue
sync uses that same flag; it also affects native InvenTree part availability.
Use **Sync to website** to invoke the existing Part Visibility plugin's configured
Lambda. Leaving the page after saving also sends a best-effort sync request.
The existing scheduled catalogue sync remains the fallback if the browser closes
or the network fails. Activating a part makes it eligible for the catalogue; other
rules in your existing exporter still apply.

The sheet uses 50-row pages and supports up to 100 edited/new rows in one save.
An attempted view change with unsaved edits is blocked; leaving the page shows the
browser's unsaved-changes warning. **Discard edits** reloads saved data.

## Customer Pricing

Select an existing InvenTree customer and a quantity break above the grid. The
**Customer price** column edits that customer's **exact quantity tier** in the
existing Customer Pricing plugin. Blank means no tier at that exact quantity,
not a calculated zero or a fallback selling price. Currency is shown per row.

Saving a price creates a missing customer list/tier, or updates that tier. Other
customers and quantity breaks are preserved. Existing list currencies cannot be
changed here, and inactive lists must first be activated in Part Pricing. A new
list uses the chosen currency (initially the customer's currency or CAD).

The integration uses Customer Pricing's own models and serializers. Its save
signals continue to update native InvenTree sale-price breaks. Those same records
remain available to Quote Generator and Inventory Manager. No price table is
duplicated. **Details** shows customer schedules and permitted material-cost
information, with a link to the native part page for the full Part Pricing tab.

Customer Pricing's configured access group is enforced, along with sales view/change
roles. Material-cost/reference purchase prices require purchase view access.
Part view/add/change permissions are enforced separately. Existing sensitive
prices are never exposed merely because someone can view the Parts Sheet.

## Migrate the Burt workbook

1. Open **Import spreadsheet** and select the original `.xls` file. `.xlsx` and
   UTF-8 `.csv` with equivalent headers are also accepted.
2. Click **Preview import**. Review existing matches, new parts, missing numbers
   and conflicts. Existing matches include a link and their current native name.
3. Choose the category for **new** parts. Existing categories, names and Active
   flags are kept. Choose whether new parts should be active.
4. Optionally assign numbers to rows with no DiCor number, using a selected series.
5. Optionally select a real customer to copy **DC Sell (CAD)** into their quantity-1
   pricing. Existing tiers, inactive schedules and non-CAD lists are kept.
6. Click **Import reviewed rows**. The import runs as one transaction and reports
   created, matched, skipped and price counts.

The importer matches the native **IPN** field case-insensitively; it does not guess
matches from names or OEM numbers. If your old catalogue stores DiCor numbers only
in names, populate native IPNs first. Multiple native revisions with the same IPN
are flagged as ambiguous instead of silently choosing one.

Original OEM/Burt numbers, required quantities, drawing notes, material, make/model,
size, date and extra notes are retained in supplemental cells linked to that part.
OEM USD, local-supplier and DC Sell prices remain reference values unless you
explicitly choose a customer for sell-price migration. Text such as `69.00 USD`
or `137 plus ship` is preserved verbatim, never silently converted or treated as CAD.
Dates entered as text remain text. Required quantities are references, not stock
quantities or BOM allocations.

Section headings and sheets without a part-number column (such as Glue Pot Drive)
are skipped with visible messages. The original workbook stays untouched. Repeating
the same import links existing numbers instead of duplicating them; unnumbered rows
already imported from the same sheet/row/name also reuse their earlier part.
If a previously unnumbered row moves or changes its name, assign its existing IPN
before importing again.

Duplicate numbers in the upload or native catalogue block import. Resolve them
and upload a fresh preview. Previews expire after 24 hours. Limits: 10 MB input,
50 MB expanded XLSX, 2,000 part rows per import. Import requires part add and change.

## Numbering

Three neutral initial series preserve the workbook's structure: `1007` + 3 digits,
`1008` + 3 digits, and `1009` + 3 digits. Administrators can label them, add other
prefixes, and advance the last number used under **Numbering**. Their business
meanings are deliberately not guessed. The native catalogue and imported workbook
rows are checked before allocation; a stale last-used spreadsheet cell cannot
cause a number to be reused. The `1008` series includes numbers beyond the workbook's
manually maintained counter, so its next number may be higher than that cell suggests.

Counters never decrease or recycle deleted numbers. A full series stops with a
clear error rather than rolling into another series. Existing manual and
alphanumeric IPNs are preserved. Existing IPNs are read-only in the grid to avoid
accidental renumbering; deliberate renumbering remains available on the native part.

Plugin writes use database transactions and a shared database lock, including on
SQLite. Retrying the same request after a lost response does not create another part.
Concurrent edits are detected using a snapshot token. These locks coordinate
Parts Sheet operations; unrelated scripts/native API writers do not take the plugin
lock. Keep InvenTree's **Allow duplicate IPN** setting disabled and use Parts Sheet
for allocating numbers in these series.

## Integration and data ownership

| System | Shared records / behavior |
| --- | --- |
| InvenTree | Native Part ID, IPN, name, description, category and flags |
| Customer Pricing | Existing CustomerPriceList and CustomerPriceBreak, native-price sync |
| Quote Generator | Same native part IDs and customer price records |
| Inventory Manager | Same parts, stock and native pricing; no duplicate inventory |
| Part Visibility / catalogue sync | Same Active flag and existing sync endpoint |

No other plugin needs a schema change. Supplemental spreadsheet cells, numbering
counters, import links, request receipts and an audit record are stored in the Parts
Sheet database tables. Include the InvenTree database in your normal backups.
Disabling this plugin leaves native parts and customer pricing intact. There is no
automatic undo of an imported catalogue; review the preview and retain your backup.

## Development and verification

```sh
python -m venv .venv
. .venv/bin/activate
pip install -e . Django~=5.2 djangorestframework django-money pytest ruff build
git clone https://github.com/damatter/inventree-customer-pricing.git ../customer-pricing
git -C ../customer-pricing checkout 4fb8551178668cffc54e7dda8cfde39cf880083a
pytest -q
ruff check src tests
python -m build
```

The fast tests use a minimal Django host model contract and **actual Customer Pricing
0.6.1 models, serializers and sync signals**. They test allocation, concurrency,
rollback, retry receipts, conflicts, permissions, parsing, migration matching,
customer tier preservation, native sale-price sync, and export escaping.
The CI smoke job installs the package into a disposable official InvenTree 1.3.5
container and runs migrations and a native-part/pricing workflow. Production data
is never used by tests. The user's workbook is not included in this repository.

Official references: [plugin installation](https://docs.inventree.org/en/1.3.x/plugins/install/),
[plugin UI integration](https://docs.inventree.org/en/1.3.x/plugins/mixins/ui/).
