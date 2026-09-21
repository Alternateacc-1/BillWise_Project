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
| `Retail_Price_Information.csv` | 1.13 MB | same, and the tests parse it on every run. **See the note below.** |

These are NPPA publications, kept byte-faithful. The parser never edits a
source file; unparseable rows are quarantined with a reason and logged.

**The ceiling list also exists as a PDF, and it is NOT shipped.** No code
parses it — its embedded font has no ToUnicode map, so extraction yields
`(cid:0)` between every glyph — and a PDF sitting in our own repository
authenticates nothing, since we could have edited it. What actually proves a
flag is the `so_number` and `so_date` carried on every reference row, which
point at the government's published notification. A megabyte to look
trustworthy was not worth it.

---

## `reference/` — generated, and committed so the repo runs out of the box

| File | Size | What it is |
|---|---|---|
| `reference_prices.csv` | 0.26 MB | the engine's reference: 915 ceiling + 22 special-feature rows |
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

`Retail_Price_Information.csv` is parsed into 3,881 rows, and **the engine
never reads them**. `backend/app/pipeline/match.py` accepts only `ceiling` and
`special_feature` (`CEILING_SOURCES`), because retail prices are per-company
approvals that bind one manufacturer — they are not ceilings binding anyone
else, so they can never justify a finding.

**They are no longer written to `reference_prices.csv`.** That file is the
engine's reference and now carries only rows the engine can act on: 937
instead of 4,818, 3.11 MB down to 0.26 MB. `prepare_reference.build()` still
returns every row in memory, so the tests keep exercising the retail parser
against the real source file, and `quarantine_log.csv` still records the six
retail rows the parser refused.

The raw file stays, for two reasons:

- **They are tested.** `tests/test_reference_data.py` exercises the retail
  parser specifically — it is a different file format with free-text
  compositions, and it has its own failure modes. One of them is a real bug
  the tests pin: a drug strength is not a container size, and reading a pack
  volume out of a retail composition once priced an item per 1.4 gm of vial.
- **They are the evidence for a decision.** `docs/DECISIONS.md` records that
  ceilings and retail prices cover different medicines by design, with zero
  overlap between 372 and 1,818 salt sets. That measurement needs the data.

If the retail tier is ever built, `docs/LIMITS.md` lists what blocks it: 21%
clean salt parsing, a manufacturer field the parser drops, and no way to tell
whether a 2013 notification is still in force.

---

## Not in the repo

`data/blobs/` (uploaded files), `data/*.sqlite*` (the local database) and
`data/raw/brands/` (downloaded third-party data) are all gitignored. No real
bill, and no patient detail, ever enters this repository.
