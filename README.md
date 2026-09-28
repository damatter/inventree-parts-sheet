# InvenTree Parts Sheet

A familiar editable sheet for the entire native InvenTree catalogue, with automatic
internal numbers, customer pricing, compact pictures and optional opening stock.

## Install or update to 0.2.0

Supported host: **InvenTree 1.3.2–1.3.x**, validated on the official **1.3.5** image.
Customer Pricing integration targets `damatter/inventree-customer-pricing` **0.6.1**.

In the InvenTree plugin installer:

- Package name: `inventree-parts-sheet`
- Source URL: `git+https://github.com/damatter/inventree-parts-sheet.git@0.2.0`
- Version: leave blank

Enable **Parts Sheet**, **App integration**, **URL integration** and **User interface
integration**. Run your usual update and restart both processes:

```sh
docker compose run --rm inventree-server invoke update
docker compose restart inventree-server inventree-worker
```

Use your actual Compose service names. Update one plugin at a time. Hard-refresh
the browser after upgrading. Open `/plugin/parts-sheet/`, use the Parts Sheet
search command, or add its dashboard tile. Browser assets are served directly.

## The fields match your catalogue

| Sheet column | Native InvenTree field |
| --- | --- |
| DiCor Part Number | Internal part number (`Part.IPN`) |
| OEM PN | Part name (`Part.name`) |
| Part description | Description (`Part.description`) |
| Visible | Active flag (`Part.active`) |
| Photo | Existing part image and thumbnail |

Both number columns are editable. Saves update the native part immediately;
refreshing reads changes made elsewhere in InvenTree. The arrow beside the DiCor
number opens its native listing. Duplicate internal numbers are rejected.

**Visible** uses the same Active flag as the former Part Visibility plugin. It
controls eligibility for website export and still has its normal InvenTree
meaning; it is not an independent website-only flag.

Upgrading does not bulk-rename existing parts. Old supplemental OEM references are
retained under **Details**. If version 0.1.0 imported a description as a part name,
**Use imported OEM PN** puts that reference into the OEM PN cell and retains the
old name as the description when the description is empty. Review and save.

## Everyday editing

- Click cells, type or paste, then choose **Save changes** / **Ctrl+S**.
- Tab moves across; Enter moves down. Yellow rows have unsaved changes.
- Search or filter by category and visibility. Choose **25, 50, 100 or 200 parts
  per page**; the browser remembers this preference.
- Small thumbnails keep rows compact. Click one to see the full picture.
- Open **Part Pricing** directly on any saved row. Use **Details** for additional
  fields and manufacturing/assembly flags.

Up to 200 rows can be saved together. Saves are atomic. Unsaved edits prevent view
changes; Discard reloads saved data. If the server response is lost, **Retry save**
reuses the same request, so it cannot duplicate the part or opening stock.

## Add a part and optional stock

1. Click **Add part**. Enter the required **OEM part number** and a description.
2. Choose the internal-number series. Each option shows its next available
   number. Initial choices are 1007, 1008 and 1009, each followed by three digits.
3. Choose the category and whether the part should be **Visible**. New parts
   default hidden. A specific internal number can be entered under the optional
   override; otherwise numbering is automatic.
4. If stock is already on hand, select **Add a quantity in stock**, enter the
   positive quantity and choose a location. Otherwise leave it unchecked.
5. Click **Add to sheet**, review the row, then **Save changes**. A new row's
   **Setup / Stock setup** button lets you adjust these choices before saving.

Saving creates the real Part and, when requested, **one native StockItem** with
that quantity and location. Its assigned external barcode is exactly the OEM PN
entered at creation. InvenTree's native stock validation, history and barcode
lookup apply. Later name edits do not silently rewrite an existing physical
stock barcode. Opening stock is available only when creating a part; use native
stock actions for later receipts and quantity adjustments.

InvenTree requires a stock barcode to identify a single stock item. If an OEM
barcode is already assigned, the whole save is rejected with a clear message;
nothing is reassigned or partially created. Use the existing stock record, or
create the new part without opening stock. Structural locations cannot hold stock.
The operation does not create a manufacturing build or BOM allocation.

## Part Pricing

The **Part Pricing** strip is always visible. If pricing is unavailable it explains
whether the Customer Pricing plugin needs enabling/updating or the user needs
access. Existing pricing permissions are preserved.

Choose a customer and quantity break to show the customer-price column. A single
available customer is selected automatically. Blank means no price at that exact
tier. Edit a price and save; other customers and tiers remain unchanged. Existing
currencies are preserved; inactive lists must be enabled in the full pricing tab.
A new part and its customer price can be created in the same sheet save.

Each row's **Part Pricing** button shows current customer schedules and permitted
material costs. **Edit in sheet** selects that customer/tier and focuses the price
cell. The dialog also links to the native part for the full Part Pricing tab,
including material and margin editing.

The adapter uses Customer Pricing's actual models and serializers and requests
its native-sale-price synchronization after commit, including after host model
reloads. It does not maintain another price database. Customer Pricing's access
group plus sales roles control prices; purchase roles protect costs.

## Replace the Part Visibility screen

Parts Sheet now includes visibility editing, images, image enlargement and its
own **Sync to website** action. The old Part Visibility plugin is not required.
After upgrading and checking this screen, it can be disabled in plugin settings.
There is no separate visibility-data migration: both use `Part.active`.

Website sync uses the same existing server environment:

- `WEBSITE_SYNC_LAMBDA_ARN`
- Normal AWS credentials or server IAM role
- `AWS_REGION` / `AWS_DEFAULT_REGION` (fallback: `ca-central-1`)

The action asynchronously invokes the configured catalogue Lambda using the
existing event contract. It shares the old plugin's 60-second cooldown if both
are enabled. Leaving after changes sends a best-effort request; the existing
scheduled exporter remains the fallback. No AWS deployment or credential changes
are made by this plugin. A disabled sync button explains missing configuration.

## Import the workbook

1. **Import spreadsheet** accepts XLS, XLSX or UTF-8 CSV. Review the match/create
   preview before applying it.
2. DiCor numbers match native IPNs case-insensitively. Repeated or ambiguous IPNs
   block import. Existing names, categories, visibility and prices are preserved.
3. New parts take their name from **OEM PN** (the legacy **Burt #** header is also
   accepted) and their description from **Part Description**. A missing OEM PN for
   a new part must be filled before import; it is never guessed from a description.
4. Choose a category/visibility for new parts. Optionally assign internal numbers
   to unnumbered rows using a selected series.
5. Optionally copy **DC Sell (CAD)** to an existing customer's missing quantity-1
   tiers. Existing tiers, inactive schedules and non-CAD lists are retained.

The import is transactional and repeat imports reuse numbered matches and saved
links for unnumbered rows with the same sheet/row/description. If an unnumbered row
moves or changes its description, put its assigned IPN into the workbook first.

OEM costs, supplier text/currency, drawing notes, required quantities, material,
size and dates remain references. Prices containing text are preserved, not
silently converted. Required quantities are not stock quantities; bulk workbook
imports do not create stock. Section headings and sheets without number columns
are skipped with messages. Limits: 10 MB upload, 50 MB expanded XLSX, 2,000 rows;
previews expire after one day. The workbook is never modified.

## Numbering, permissions and integration

Administrators can label/add series and advance counters under **Numbering**.
Neutral initial series labels preserve the workbook's numbering without inventing
business categories. The allocator checks all native IPNs plus retained counters;
it never decreases a counter, recycles deleted numbers or rolls into another
series on exhaustion. Special alphanumeric numbers remain valid.

A shared database lock coordinates Parts Sheet writes, including SQLite.
Keep InvenTree's **Allow duplicate IPN** setting disabled; external API writers do
not take this plugin lock. Snapshot checks detect concurrent part/price changes.

Part view/add/change permissions apply. Opening stock additionally requires stock
add and location view access. Customer Pricing permissions apply independently,
including when a saved request receipt is replayed.

Quote Generator, Inventory Manager, stock, attachments and website exports use
the same native part IDs and price records. No other plugin requires a schema
change. Only supplemental cells, numbering, import links, previews, receipts and
audit data live in Parts Sheet tables. Disabling it keeps native parts, stock and
prices. Include these tables in normal database backups; imports have no automatic
undo.

## Development and validation

```sh
pip install -e . Django~=5.2 djangorestframework django-money pytest ruff build
git clone https://github.com/damatter/inventree-customer-pricing.git ../customer-pricing
git -C ../customer-pricing checkout 4fb8551178668cffc54e7dda8cfde39cf880083a
pytest -q
ruff check src tests
python -m build
```

37 tests exercise the actual Customer Pricing 0.6.1 code against a minimal Django
host contract. The separate official InvenTree 1.3.5 container job checks native
parts, stock, assigned barcode lookup/history, pricing synchronization, migrations
and HTTP routes. Browser checks cover photos/row size, pagination, field mapping,
pricing selection and a lost-response retry during combined part/stock/price
creation. Test records are disposable. Private workbook/data are excluded from
Git and packages. AWS calls are mocked in tests; production publishing is not run.
