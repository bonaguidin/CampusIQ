#!/usr/bin/env python3
"""
GradusIQ — O*NET loader
Downloads an O*NET tabular release, trims it to what GradusIQ actually queries,
and writes Supabase-ready CSVs plus a coverage report.

Run:  python build_onet.py --version 30_3
      python build_onet.py --version 31_0 --keep-level

Re-run this after each annual O*NET refresh. Do not hand-edit the output.
"""

import argparse, csv, io, os, sys, zipfile, urllib.request
from collections import defaultdict

# ---------------------------------------------------------------- config

DL = "https://www.onetcenter.org/dl_files/database/db_{v}_text.zip"

# Rating files -> domain label written into occupation_skills.domain.
# NOTE: O*NET 30.3 renamed these. Pre-30.3 releases used a single "Skills.txt".
# If a release renames them again, this dict is the only thing to change.
RATING_FILES = {
    "Essential Skills.txt":    "essential_skill",
    "Transferable Skills.txt": "transferable_skill",
    "Knowledge.txt":           "knowledge",
    "Abilities.txt":           "ability",
}

OUT = "out"

# ---------------------------------------------------------------- helpers

def soc6(code):
    """13-2051.00 -> 13-2051. O*NET uses 8-digit extended codes with .01/.02
    sub-specializations; BLS wage data and most crosswalks use 6-digit."""
    return code.split(".")[0].strip()

def read(folder, name):
    """O*NET ships tab-delimited, CRLF, BOM. utf-8-sig handles the BOM."""
    path = os.path.join(folder, name)
    if not os.path.exists(path):
        sys.exit(f"MISSING FILE: {name}\n  The release may have renamed it. "
                 f"Check the migration reference on onetcenter.org and update RATING_FILES.")
    with open(path, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f, delimiter="\t"))

def write(name, header, rows):
    os.makedirs(OUT, exist_ok=True)
    path = os.path.join(OUT, name)
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)
    kb = os.path.getsize(path) / 1024
    print(f"  {name:<28} {len(rows):>7,} rows   {kb:>8,.0f} KB")
    return len(rows)

def fetch(version, workdir):
    """Download + unzip unless already present."""
    folder = os.path.join(workdir, f"db_{version}_text")
    if os.path.isdir(folder):
        print(f"Using cached {folder}")
        return folder
    url = DL.format(v=version)
    print(f"Downloading {url}")
    with urllib.request.urlopen(url) as r:
        data = r.read()
    zipfile.ZipFile(io.BytesIO(data)).extractall(workdir)
    if not os.path.isdir(folder):
        # some releases nest differently; find the one dir that exists
        cands = [d for d in os.listdir(workdir) if os.path.isdir(os.path.join(workdir, d))]
        sys.exit(f"Unexpected archive layout. Found: {cands}")
    return folder

# ---------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--version", default="30_3", help="O*NET release, e.g. 30_3 or 31_0")
    ap.add_argument("--keep-level", action="store_true",
                    help="keep LV (Level) ratings as well as IM (Importance)")
    ap.add_argument("--keep-suppressed", action="store_true",
                    help="keep rows O*NET flags Recommend Suppress / Not Relevant (don't)")
    ap.add_argument("--workdir", default="onet_src")
    args = ap.parse_args()

    os.makedirs(args.workdir, exist_ok=True)
    src = fetch(args.version, args.workdir)
    scales = {"IM"} | ({"LV"} if args.keep_level else set())

    print(f"\nBuilding from {src}")
    print(f"  scales kept: {sorted(scales)}")
    print(f"  suppressed rows: {'KEPT' if args.keep_suppressed else 'dropped'}\n")

    # ---- occupations -------------------------------------------------
    occ = read(src, "Occupation Data.txt")
    occ_rows = [[r["O*NET-SOC Code"].strip(), soc6(r["O*NET-SOC Code"]),
                 r["Title"].strip(), r["Description"].strip()] for r in occ]
    all_socs = {r[0] for r in occ_rows}
    titles = {r[0]: r[2] for r in occ_rows}

    # ---- ratings: four files unified into one table -------------------
    # Unified rather than four tables because GAP asks one question
    # ("what matters for this role") across all four domains. A `domain`
    # column keeps them separable without four joins at query time.
    rating_rows, rated, dropped = [], set(), defaultdict(int)
    for fname, domain in RATING_FILES.items():
        for r in read(src, fname):
            if r["Scale ID"].strip() not in scales:
                continue
            if not args.keep_suppressed:
                if r.get("Recommend Suppress", "").strip() == "Y":
                    dropped["suppressed"] += 1; continue
                if r.get("Not Relevant", "").strip() == "Y":
                    dropped["not_relevant"] += 1; continue
            code = r["O*NET-SOC Code"].strip()
            rated.add(code)
            rating_rows.append([code, soc6(code), domain,
                                r["Element ID"].strip(), r["Element Name"].strip(),
                                r["Scale ID"].strip(), r["Data Value"].strip(),
                                r.get("N", "").strip()])

    # ---- software / tools: the ATS matcher's vocabulary ---------------
    sw = read(src, "Software Skills.txt")
    sw_rows = [[r["O*NET-SOC Code"].strip(), soc6(r["O*NET-SOC Code"]),
                r["Workplace Example"].strip(), r["Element Name"].strip(),
                r["Hot Technology"].strip() == "Y", r["In Demand"].strip() == "Y"]
               for r in sw]

    # Deduped product list — this is what the posting matcher scans against.
    vocab = {}
    for r in sw:
        p = r["Workplace Example"].strip()
        hot = r["Hot Technology"].strip() == "Y"
        dem = r["In Demand"].strip() == "Y"
        cur = vocab.get(p, (False, False, ""))
        vocab[p] = (cur[0] or hot, cur[1] or dem, r["Element Name"].strip())
    vocab_rows = [[p, cat, hot, dem] for p, (hot, dem, cat) in sorted(vocab.items())]

    # ---- titles for free-text resolution ------------------------------
    jt = read(src, "Job Titles.txt")
    title_rows = [[r["O*NET-SOC Code"].strip(), soc6(r["O*NET-SOC Code"]),
                   r["Job Title"].strip()] for r in jt]

    rt = read(src, "Sample of Reported Titles.txt")
    title_rows += [[r["O*NET-SOC Code"].strip(), soc6(r["O*NET-SOC Code"]),
                    r["Reported Job Title"].strip()] for r in rt]
    seen, deduped = set(), []
    for row in title_rows:
        k = (row[0], row[2].lower())
        if k not in seen:
            seen.add(k); deduped.append(row)
    title_rows = deduped

    # ---- job zones (entry-level filtering) ----------------------------
    jz = read(src, "Job Zones.txt")
    jz_rows = [[r["O*NET-SOC Code"].strip(), soc6(r["O*NET-SOC Code"]),
                r["Job Zone"].strip()] for r in jz]

    # ---- write --------------------------------------------------------
    print("Writing:")
    write("occupations.csv",
          ["onet_soc_code", "soc6", "title", "description"], occ_rows)
    write("occupation_skills.csv",
          ["onet_soc_code", "soc6", "domain", "element_id", "element_name",
           "scale_id", "data_value", "sample_n"], rating_rows)
    write("occupation_software.csv",
          ["onet_soc_code", "soc6", "product", "category",
           "hot_technology", "in_demand"], sw_rows)
    write("skill_vocabulary.csv",
          ["product", "category", "hot_technology", "in_demand"], vocab_rows)
    write("occupation_titles.csv",
          ["onet_soc_code", "soc6", "title"], title_rows)
    write("job_zones.csv",
          ["onet_soc_code", "soc6", "job_zone"], jz_rows)

    # ---- coverage report ----------------------------------------------
    # The point of this file: know which occupations have NO ratings data
    # before a student's target role returns an empty result in production.
    unrated = sorted(all_socs - rated)
    write("coverage_gaps.csv",
          ["onet_soc_code", "title"], [[c, titles[c]] for c in unrated])

    total_kb = sum(os.path.getsize(os.path.join(OUT, f))
                   for f in os.listdir(OUT)) / 1024
    print(f"\n  {'TOTAL':<28} {'':>7}        {total_kb:>8,.0f} KB")

    print(f"\nFiltering dropped:")
    for k, v in sorted(dropped.items()):
        print(f"  {k:<20} {v:>7,} rows")

    print(f"\nCoverage:")
    print(f"  occupations in release      {len(all_socs):>6,}")
    print(f"  with ratings data           {len(rated):>6,}")
    print(f"  WITHOUT any ratings         {len(unrated):>6,}   -> out/coverage_gaps.csv")
    print(f"  software products (unique)  {len(vocab_rows):>6,}")
    print(f"  hot technologies            {sum(1 for r in vocab_rows if r[2]):>6,}")
    print(f"\nDone. Import out/*.csv into Supabase.")

if __name__ == "__main__":
    main()
