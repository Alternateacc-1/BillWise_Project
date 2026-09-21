# data/

Every file here, what reads it, and why it is in the repo at all.

Nothing in this directory needs building before you run the project — the
generated reference already ships.

---

## `raw/` — the government source files, unmodified

| File | Size | Read by |
|---|---|---|
| `All_Drugs_Ceiling_Prices.csv` | 0.09 MB | `scripts/prepare_reference.py` → **915 ceiling rows** |
| `Special_Feature_Schedule_..._for_Specific_Companies.pdf` | 0.03 MB | same → **22 rows** |
| `Retail_Price_Information.csv` | 1.13 MB | same → 3,881 rows. **See the note below.** |
| `All_Drugs_Ceiling_Prices_provenance.pdf` | 1.05 MB | **nothing parses it** |

These are NPPA publications, kept byte-faithful. The parser never edits a
source file; unparseable rows are quarantined with a reason and logged.

**Why the provenance PDF is here when no code reads it.** It is the
government's own published document behind the 915 rows, and the whole claim
of this project is that every number comes from that list. Shipping it means
anyone can check the CSV against the original rather than taking our word for
it. That is worth a megabyte.

**Never parse the provenance PDF.** It embeds a font with no usable ToUnicode
map, so text extraction yields `(cid:0)` between every glyph. The CSV holds
the same 915 rows and is strictly better.

---

## `reference/` — generated, and committed so the repo runs out of the box

| File | Size | What it is |
|---|---|---|
| `reference_prices.csv` | 3.11 MB | the parsed, normalised reference. 4,818 rows across three sources |
| `salt_synonyms.json` | tiny | spelling variants; load-bearing for matching |
| `quarantine_log.csv` | tiny | every row the parser refused, with a reason code |
| `unit_coverage.json` | tiny | which unit strings were recognised |
| `brand_index_report.json` | tiny | summary of the brand-index build |

Rebuild with `python scripts/prepare_reference.py` — offline, no network.

`brand_index.csv` (36 MB) is **not** here: it is gitignored and rebuilt from
the network. You do not need it. The reduced index the engine actually uses
is committed at `backend/reference_data/brand_index.csv`.

---

## The retail rows, and why they are kept

`reference_prices.csv` holds 3,881 `retail_new_drug` rows, and **the engine
never reads them**. `match.py` accepts only `ceiling` and `special_feature`
(`CEILING_SOURCES`), because retail prices are per-company approvals that bind
one manufacturer — they are not ceilings binding anyone else, so they can
never justify a finding.

They are not dead weight in the repo, for two reasons:

- **They are tested.** `tests/test_reference_data.py` exercises the retail
  parser specifically — it is a different file format with free-text
  compositions, and it has its own failure modes. One of them is a real bug
  the tests pin: a drug strength is not a container size, and reading a pack
  volume out of a retail composition once priced an item per 1.4 gm of vial.
- **They are the evidence for a decision.** `docs/DECISIONS.md` records that
  ceilings and retail prices cover different medicines by design, with zero
  overlap between 372 and 1,818 salt sets. That measurement needs the data.

**They are excluded from the Lambda bundle.** `scripts/stage_lambda.py` stages
only the rows the engine can act on — 937 instead of 4,818, taking the
deployed file from 3.2 MB to 0.27 MB. Shipping rows that cannot produce a
verdict would cost cold-start time for nothing.

If the retail tier is ever built, `docs/LIMITS.md` lists what blocks it: 21%
clean salt parsing, a manufacturer field the parser drops, and no way to tell
whether a 2013 notification is still in force.

---

## Not in the repo

`data/blobs/` (uploaded files), `data/*.sqlite*` (the local database) and
`data/raw/brands/` (downloaded third-party data) are all gitignored. No real
bill, and no patient detail, ever enters this repository.
