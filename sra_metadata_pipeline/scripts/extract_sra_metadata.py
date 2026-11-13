"""
Pull SRA run info + BioSample attributes for a list of SRA IDs and build
BV-BRC influenza metadata.

Usage:
    python extract_sra_metadata.py list_sra_ids.txt output.xlsx
    python extract_sra_metadata.py ids.txt out.xlsx --subtype H5N1   # fallback when not found in metadata
    python extract_sra_metadata.py ids.txt out.xlsx --location country --subtype-suffix
        # -> genome_name 'Influenza A virus A/cattle/USA/24-008749/2024(H5N1)'

Output Excel sheets:
    Raw Data  - SRA runinfo merged with BioSample attributes
    BVBRC     - BV-BRC metadata columns
    Failed    - (only if any) IDs that could not be fetched/parsed, with the reason

Set NCBI_API_KEY in your environment to raise NCBI's rate limit from 3 to 10 requests/s.
"""
import argparse
import csv
import os
import re
import shlex
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from io import StringIO
from pathlib import Path

import pandas as pd

SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_EDIRECT = os.path.expanduser("~/edirect")

# SRA run/experiment/sample/study accessions (SRA, ENA, DDBJ)
SRA_ID_RE = re.compile(r"^[SED]R[RXSP]\d+$", re.IGNORECASE)
BIOSAMPLE_RE = re.compile(r"^SAM[NED][A-Z]?\d+$", re.IGNORECASE)

state_abbreviations = {
    'AL': 'Alabama', 'AK': 'Alaska', 'AZ': 'Arizona', 'AR': 'Arkansas', 'CA': 'California',
    'CO': 'Colorado', 'CT': 'Connecticut', 'DE': 'Delaware', 'FL': 'Florida', 'GA': 'Georgia',
    'HI': 'Hawaii', 'ID': 'Idaho', 'IL': 'Illinois', 'IN': 'Indiana', 'IA': 'Iowa',
    'KS': 'Kansas', 'KY': 'Kentucky', 'LA': 'Louisiana', 'ME': 'Maine', 'MD': 'Maryland',
    'MA': 'Massachusetts', 'MI': 'Michigan', 'MN': 'Minnesota', 'MS': 'Mississippi', 'MO': 'Missouri',
    'MT': 'Montana', 'NE': 'Nebraska', 'NV': 'Nevada', 'NH': 'New Hampshire', 'NJ': 'New Jersey',
    'NM': 'New Mexico', 'NY': 'New York', 'NC': 'North Carolina', 'ND': 'North Dakota', 'OH': 'Ohio',
    'OK': 'Oklahoma', 'OR': 'Oregon', 'PA': 'Pennsylvania', 'RI': 'Rhode Island', 'SC': 'South Carolina',
    'SD': 'South Dakota', 'TN': 'Tennessee', 'TX': 'Texas', 'UT': 'Utah', 'VT': 'Vermont',
    'VA': 'Virginia', 'WA': 'Washington', 'WV': 'West Virginia', 'WI': 'Wisconsin', 'WY': 'Wyoming',
    'DC': 'District of Columbia', 'PR': 'Puerto Rico',
}
_state_lookup = {k.lower(): v for k, v in state_abbreviations.items()}
_state_lookup.update({v.lower(): v for v in state_abbreviations.values()})

# Country -> BV-BRC geographic group (built in from GeoLocation.csv; 'Artic Ocean' typo fixed).
# To use a different table instead, pass --geo <csv> (columns: country, group; header row).
GEOGRAPHIC_GROUPS = {
    'Africa': [
        'Algeria', 'Angola', 'Belgian Congo', 'Benin', 'Botswana', 'Burkina Faso', 'Burundi',
        'Cameroon', 'Cape Verde', 'Central African Republic', 'Chad', "Cote d'Ivoire",
        'Democratic Republic of the Congo', 'Djibouti', 'Egypt', 'Equatorial Guinea', 'Eritrea',
        'Eswatini', 'Ethiopia', 'Gabon', 'Gambia', 'Ghana', 'Guinea', 'Guinea-Bissau', 'Kenya',
        'Lesotho', 'Liberia', 'Libya', 'Malawi', 'Mali', 'Mauritania', 'Morocco', 'Mozambique',
        'Namibia', 'Niger', 'Nigeria', 'Republic of the Congo', 'Rwanda', 'Senegal', 'Sierra Leone',
        'Somalia', 'South Africa', 'South Sudan', 'Sudan', 'Swaziland', 'Tanzania', 'Togo',
        'Tunisia', 'Uganda', 'Western Sahara', 'Zaire', 'Zambia', 'Zimbabwe',
    ],
    'Indian Ocean': [
        'Madagascar', 'Bassas da India', 'Comoros', 'Europa Island', 'Glorioso Islands',
        'Juan de Nova Island', 'Maldives', 'Mauritius', 'Mayotte', 'Reunion', 'Seychelles',
        'Tromelin Island', 'Indian Ocean',
    ],
    'Antarctica': [
        'Antarctica',
    ],
    'Atlantic Ocean': [
        'Bouvet Island', 'Antigua and Barbuda', 'Bahamas', 'Bermuda', 'British Virgin Islands',
        'Cayman Islands', 'Cuba', 'Curacao', 'Dominica', 'Dominican Republic',
        'Falkland Islands (Islas Malvinas)', 'Faroe Islands', 'Grenada', 'Guadeloupe', 'Haiti',
        'Jamaica', 'Martinique', 'Navassa Island', 'Netherlands Antilles', 'Puerto Rico',
        'Saint Barthelemy', 'Saint Helena', 'Saint Kitts and Nevis', 'Saint Lucia', 'Saint Martin',
        'Saint Pierre and Miquelon', 'Saint Vincent and the Grenadines', 'Sao Tome and Principe',
        'Sint Maarten', 'South Georgia and the South Sandwich Islands', 'Trinidad and Tobago',
        'Turks and Caicos Islands', 'Virgin Islands', 'Anguilla', 'Aruba', 'Barbados', 'Montserrat',
        'Atlantic Ocean',
    ],
    'Arctic Ocean': [
        'Jan Mayen', 'Svalbard', 'Arctic Ocean',
    ],
    'Asia': [
        'Afghanistan', 'Armenia', 'Azerbaijan', 'Bahrain', 'Bangladesh', 'Bhutan', 'Borneo',
        'Brunei', 'Burma', 'Cambodia', 'China', 'Cyprus', 'East Timor', 'Gaza Strip', 'Georgia',
        'Hong Kong', 'India', 'Indonesia', 'Iran', 'Iraq', 'Israel', 'Japan', 'Jordan',
        'Kazakhstan', 'Korea', 'Kuwait', 'Kyrgyzstan', 'Laos', 'Lebanon', 'Macau', 'Malaysia',
        'Mongolia', 'Myanmar', 'Nepal', 'North Korea', 'Oman', 'Pakistan', 'Philippines', 'Qatar',
        'Saudi Arabia', 'Siam', 'Singapore', 'South Korea', 'Sri Lanka', 'State of Palestine',
        'Syria', 'Taiwan', 'Tajikistan', 'Thailand', 'Timor-Leste', 'Turkey', 'Turkmenistan',
        'United Arab Emirates', 'Uzbekistan', 'Viet Nam', 'West Bank', 'Yemen',
    ],
    'Baltic Sea': [
        'Aland Islands', 'Baltic Sea',
    ],
    'Europe': [
        'Albania', 'Andorra', 'Austria', 'Belarus', 'Belgium', 'Bosnia and Herzegovina', 'Bulgaria',
        'Croatia', 'Czech Republic', 'Czechia', 'Czechoslovakia', 'Denmark', 'Estonia', 'Finland',
        'France', 'Germany', 'Gibraltar', 'Greece', 'Guernsey', 'Holy See', 'Hungary', 'Iceland',
        'Ireland', 'Isle of Man', 'Italy', 'Jersey', 'Kosovo', 'Latvia', 'Liechtenstein',
        'Lithuania', 'Luxembourg', 'Macedonia', 'Moldova', 'Monaco', 'Montenegro', 'Netherlands',
        'North Macedonia', 'Norway', 'Poland', 'Portugal', 'Romania', 'Russia', 'San Marino',
        'Serbia', 'Serbia and Montenegro', 'Slovakia', 'Slovenia', 'Spain', 'Sweden', 'Switzerland',
        'The former Yugoslav Republic of Macedonia', 'Ukraine', 'United Kingdom', 'USSR',
        'Yugoslavia',
    ],
    'Mediterranean Sea': [
        'Malta', 'Mediterranean Sea',
    ],
    'North America': [
        'Belize', 'Canada', 'Costa Rica', 'El Salvador', 'Greenland', 'Guatemala', 'Honduras',
        'Mexico', 'Nicaragua', 'Panama', 'USA',
    ],
    'Oceania': [
        'American Samoa', 'Ashmore and Cartier Islands', 'Australia', 'Christmas Island',
        'Cocos Islands', 'Cook Islands', 'Coral Sea Islands', 'Fiji', 'French Polynesia', 'Guam',
        'Johnston Atoll', 'Kiribati', 'Line Islands', 'Marshall Islands', 'Micronesia',
        'Micronesia, Federated States of', 'Midway Islands', 'Nauru', 'New Caledonia',
        'New Zealand', 'Niue', 'Norfolk Island', 'Northern Mariana Islands', 'Palau',
        'Papua New Guinea', 'Pitcairn Islands', 'Samoa', 'Solomon Islands', 'Tokelau', 'Tonga',
        'Tuvalu', 'Vanuatu', 'Wake Island', 'Wallis and Futuna',
    ],
    'Pacific Ocean': [
        'Baker Island', 'Clipperton Island', 'Howland Island', 'Jarvis Island', 'Kingman Reef',
        'Palmyra Atoll', 'Paracel Islands', 'Spratly Islands', 'Pacific Ocean',
    ],
    'South America': [
        'Argentina', 'Bolivia', 'Brazil', 'British Guiana', 'Chile', 'Colombia', 'Ecuador',
        'French Guiana', 'Guyana', 'Paraguay', 'Peru', 'Suriname', 'Uruguay', 'Venezuela',
    ],
    'Southern Ocean': [
        'French Southern and Antarctic Lands', 'Heard Island and McDonald Islands',
        'Kerguelen Archipelago', 'Southern Ocean',
    ],
    'North Sea': [
        'North Sea',
    ],
    'Ross Sea': [
        'Ross Sea',
    ],
    'Tasman Sea': [
        'Tasman Sea',
    ],
}
COUNTRY_GROUPS = {c: grp for grp, cs in GEOGRAPHIC_GROUPS.items() for c in cs}

# Country spellings seen in BioSamples that differ from the table above
COUNTRY_ALIASES = {
    "united states": "USA", "united states of america": "USA", "us": "USA",
    "vietnam": "Viet Nam", "uk": "United Kingdom",
}

HUMAN_HOSTS = {"human", "homo sapiens"}
MISSING_VALUES = {"", "missing", "not collected", "not provided", "not applicable",
                  "unknown", "na", "n/a", "none", "restricted access"}


# --------------------------------------------------------------------------- NCBI

class Fetcher:
    def __init__(self, edirect_path, retries=3):
        self.edirect = edirect_path
        self.retries = retries
        # NCBI: 3 req/s without a key, 10 with one. Each esearch|efetch is ~2 requests.
        self.delay = 0.25 if os.environ.get("NCBI_API_KEY") else 0.7
        self._last = 0.0
        self._biosample_cache = {}

    def _tool(self, name):
        return shlex.quote(os.path.join(self.edirect, name)) if self.edirect else name

    def _run(self, command):
        last_err = ""
        for attempt in range(1, self.retries + 1):
            wait = self.delay - (time.time() - self._last)
            if wait > 0:
                time.sleep(wait)
            self._last = time.time()
            result = subprocess.run(command, shell=True, capture_output=True, text=True)
            if result.returncode == 0 and result.stdout.strip():
                return result.stdout
            last_err = (result.stderr or "empty response").strip().splitlines()
            last_err = last_err[-1] if last_err else "empty response"
            time.sleep(2 * attempt)  # back off (rate limits / transient errors)
        raise RuntimeError(last_err)

    def runinfo(self, sra_id):
        cmd = (f"{self._tool('esearch')} -db sra -query {shlex.quote(sra_id)} | "
               f"{self._tool('efetch')} -format runinfo")
        df = pd.read_csv(StringIO(self._run(cmd)), dtype=str)
        # runinfo can repeat the header line when results are paged
        df = df[df["Run"].notna() & (df["Run"] != "Run")].reset_index(drop=True)
        if df.empty:
            raise RuntimeError("no runs returned")
        return df

    def biosample(self, biosample_id):
        if biosample_id not in self._biosample_cache:
            cmd = (f"{self._tool('esearch')} -db biosample -query {shlex.quote(biosample_id)} | "
                   f"{self._tool('efetch')} -format xml")
            self._biosample_cache[biosample_id] = parse_biosample_xml(self._run(cmd))
        return self._biosample_cache[biosample_id]


def parse_biosample_xml(xml_data):
    """Attributes keyed by harmonized_name, falling back to attribute_name for non-harmonized ones."""
    root = ET.fromstring(xml_data)
    info, extra = {}, {}
    for attr in root.iter("Attribute"):
        value = (attr.text or "").strip()
        if not value:
            continue
        harmonized = attr.attrib.get("harmonized_name")
        if harmonized:
            info[harmonized] = value
        elif attr.attrib.get("attribute_name"):
            extra[attr.attrib["attribute_name"]] = value
    for k, v in extra.items():
        info.setdefault(k, v)
    if not info:
        raise RuntimeError("BioSample has no attributes")
    return info


# --------------------------------------------------------------------------- geography

def is_missing(value):
    return value is None or (isinstance(value, float) and pd.isna(value)) or \
        str(value).strip().lower() in MISSING_VALUES


def clean_geo_loc(geo_loc):
    """Return [country, city, state] from an INSDC geo_loc_name like 'USA: Texas, Amarillo'."""
    if is_missing(geo_loc):
        return ["", "", ""]
    country, _, region = str(geo_loc).partition(":")
    country = country.strip()
    parts = [p.strip() for p in region.split(",") if p.strip()]
    state = city = ""
    if not parts:
        return [country, city, state]

    if COUNTRY_ALIASES.get(country.lower(), country) == "USA":
        # US records come both as 'State, City' and 'City, State' - pick the part that is a state
        for i, p in enumerate(parts):
            if p.lower().rstrip(".") in _state_lookup:
                state = _state_lookup[p.lower().rstrip(".")]
                rest = parts[:i] + parts[i + 1:]
                city = rest[0] if rest else ""
                break
        else:
            state = parts[0]
            city = parts[1] if len(parts) > 1 else ""
    else:
        # INSDC convention: country: region, locality (largest first)
        state = parts[0]
        city = parts[1] if len(parts) > 1 else ""
    return [country, city, state]


def load_country_geographic_groups(csv_filename=None):
    """{lowercase country: (country, group)} from the built-in table, or from a CSV if given."""
    if not csv_filename:
        return {c.lower(): (c, grp) for c, grp in COUNTRY_GROUPS.items()}
    country_groups = {}
    with open(csv_filename, "r", newline="", encoding="utf-8-sig") as fh:
        reader = csv.reader(fh)
        next(reader, None)  # header: GeoLocation,BVBRC Geographic Group
        for row in reader:
            if len(row) < 2 or not row[0].strip():
                continue
            country_groups[row[0].strip().lower()] = (row[0].strip(), row[1].strip())
    return country_groups


def match_country(country, country_groups):
    """Exact (case-insensitive) match -> (country name as in CSV, geographic group)."""
    if not country:
        return None, None
    key = country.strip().lower()
    key = COUNTRY_ALIASES.get(key, key).lower()
    return country_groups.get(key, (None, None))


# --------------------------------------------------------------------------- flu naming

# (?!\d) rather than \b at the end so suffixed forms like H1N1pdm09 and H3N2v still match
SUBTYPE_RE = re.compile(r"\bH(\d{1,2})N(\d{1,2})(?!\d)", re.IGNORECASE)


def find_subtype(*values):
    for v in values:
        if is_missing(v):
            continue
        m = SUBTYPE_RE.search(str(v))
        if m:
            return f"H{m.group(1)}N{m.group(2)}"
    return None


def extract_year(date):
    if is_missing(date):
        return pd.NA
    m = re.search(r"(?<!\d)(\d{4})(?!\d)", str(date))
    return int(m.group(1)) if m else pd.NA


TRAILING_SUBTYPE_RE = re.compile(r"\s*\(H\d{1,2}N\d{1,2}\)+\s*$", re.IGNORECASE)


def build_strain(row, location="state"):
    """A/host/location/isolate/year (host omitted for human). location: 'state' or 'country'."""
    isolate = "" if is_missing(row["isolate"]) else str(row["isolate"]).strip()
    # Isolate is often already a full strain name, e.g. A/cattle/Texas/24-008749-003/2024(H5N1);
    # failing that, the BioSample 'strain' attribute often is. Use whichever is a full name.
    source_strain = row.get("source_strain")
    source_strain = "" if is_missing(source_strain) else str(source_strain).strip()
    for full_name in (isolate, source_strain):
        if full_name.upper().startswith("A/"):
            return TRAILING_SUBTYPE_RE.sub("", "A/" + full_name[2:])
    if location == "country":
        loc = row["isolation_country"] or row["raw_country"] or ""
    else:
        loc = row["state"] or row["isolation_country"] or row["raw_country"] or ""
    year = "" if pd.isna(row["collection_year"]) else str(row["collection_year"])
    host = "" if is_missing(row["Host"]) else str(row["Host"]).strip()
    if host.lower() in HUMAN_HOSTS:  # human strains omit the host field
        fields = [loc, isolate, year]
    else:
        fields = [host, loc, isolate, year]
    return "A/" + "/".join(f for f in fields if f)  # skip missing fields instead of leaving "//"


def metadata_subtypes(combined_df):
    """Subtype per row from BioSample/SRA metadata (serotype, subtype, strain, isolate, organism...)."""
    return combined_df.apply(lambda r: find_subtype(
        r.get("serotype"), r.get("subtype"), r.get("strain"), r.get("isolate"),
        r.get("ScientificName"), r.get("SampleName")), axis=1)


def _type_value(value):
    """H/N number as a clean string ('5'), or None when missing (None, NaN, pd.NA, '')."""
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    text = str(value).strip()
    if text.endswith(".0"):  # numbers that came through as floats, e.g. 5.0
        text = text[:-2]
    return text or None


def _type_num(value, letter):
    if is_missing(value):
        return None
    m = re.search(letter + r"?(\d{1,2})", str(value), re.IGNORECASE)
    return m.group(1) if m else None


def build_bvbrc_table(combined_df, country_groups, h_types=None, n_types=None,
                      default_subtype=None, location="state", subtype_suffix=False):
    """
    Build the BV-BRC sheet from the merged runinfo+BioSample table.

    h_types / n_types: optional per-row Series of H and N numbers (e.g. '5', '1') that
    override the metadata-derived subtype (used by the pipeline with assembly results).
    """
    out = combined_df.reindex(columns=list(BVBRC_SOURCE_COLUMNS)).rename(columns=BVBRC_SOURCE_COLUMNS)

    geo = out["geographic_location"].apply(clean_geo_loc)
    matched = geo.apply(lambda g: match_country(g[0], country_groups))
    out["geographic_group"] = matched.str[1]
    out["isolation_country"] = matched.str[0]

    if h_types is None or n_types is None:
        subs = metadata_subtypes(combined_df)
        if default_subtype:
            subs = subs.fillna(default_subtype.upper())
        h_types = subs.apply(lambda v: _type_num(v, "H"))
        n_types = subs.apply(lambda v: _type_num(re.sub(r"^H\d+", "", v) if isinstance(v, str) else v, "N"))
    # Plain Python lists with real None for "unknown": pandas (3.x especially) turns None
    # into NaN inside a Series, and NaN is truthy, which used to produce subtype 'HnanNnan'.
    h = [_type_value(v) for v in h_types]
    n = [_type_value(v) for v in n_types]
    out["subtype"] = pd.Series([f"H{a}N{b}" if a and b else None for a, b in zip(h, n)],
                               index=out.index, dtype=object)
    out["h_type"] = pd.Series(h, index=out.index, dtype=object)
    out["n_type"] = pd.Series(n, index=out.index, dtype=object)

    out["collection_year"] = out["collection_date"].apply(extract_year).astype("Int64")
    out["state"] = geo.str[2]

    source_strain = combined_df["strain"] if "strain" in combined_df.columns else ""
    helper = out.assign(raw_country=geo.str[0], source_strain=source_strain)
    out["strain"] = helper.apply(build_strain, axis=1, location=location) if len(out) else pd.Series(dtype=str)
    out.loc[out["strain"] == "A/", "strain"] = ""  # no metadata to build a name from
    suffix = out["subtype"].apply(lambda s: f"({s})" if subtype_suffix and isinstance(s, str) and s else "")
    out["genome_name"] = ("Influenza A virus " + out["strain"] + suffix).where(out["strain"] != "", "")
    out = out[[c for c in out.columns if c != "strain"] + ["strain"]]  # keep original column order

    # Countries that did not map to a group (compare per row, so aliases such as
    # 'United States' -> 'USA' are not reported as unmatched).
    unmatched = sorted({g[0] for g, (name, _) in zip(geo, matched) if g[0] and name is None})
    if unmatched:
        print(f"WARNING: countries not in the geographic group table: {', '.join(unmatched)}", file=sys.stderr)
    return out


# --------------------------------------------------------------------------- main

BVBRC_SOURCE_COLUMNS = {
    'Run': 'sra_accession',
    'Model': 'sequencing_platform',
    'BioProject': 'bioproject_accession',
    'BioSample': 'biosample_accession',
    'ScientificName': 'organism',
    'isolate': 'isolate',
    'CenterName': 'sequencing_centers',
    'geo_loc_name': 'geographic_location',
    'host': 'Host',
    'collection_date': 'collection_date',
}


def read_ids(input_file):
    ids, seen = [], set()
    with open(input_file) as fh:
        for line in fh:
            sra_id = line.split("#", 1)[0].strip()
            if sra_id and sra_id not in seen:
                seen.add(sra_id)
                ids.append(sra_id)
    return ids


def fetch_records(sra_ids, fetcher):
    """Return (list of merged runinfo+BioSample row dicts, list of (id, reason) failures)."""
    combined, failed = [], []
    seen_runs = set()  # an SRX/SRS/SRP and one of its SRRs can both be in the input list
    for n, sra_id in enumerate(sra_ids, 1):
        print(f"[{n}/{len(sra_ids)}] {sra_id}", file=sys.stderr)
        if not SRA_ID_RE.match(sra_id):
            failed.append((sra_id, "not an SRA accession"))
            continue
        try:
            sra_df = fetcher.runinfo(sra_id)
        except Exception as e:
            failed.append((sra_id, f"SRA fetch failed: {e}"))
            continue
        # one row per run; each run gets its own BioSample's attributes
        for _, run in sra_df.iterrows():
            row = run.to_dict()
            run_acc = str(row.get("Run") or "").strip()
            if run_acc in seen_runs:
                print(f"  {run_acc} already fetched via an earlier ID; skipping duplicate", file=sys.stderr)
                continue
            seen_runs.add(run_acc)
            bs_id = str(row.get("BioSample") or "").strip()
            if not BIOSAMPLE_RE.match(bs_id):
                failed.append((row.get("Run", sra_id), f"no BioSample in runinfo ({bs_id or 'blank'})"))
                continue
            try:
                info = fetcher.biosample(bs_id)
            except Exception as e:
                failed.append((row.get("Run", sra_id), f"BioSample {bs_id} failed: {e}"))
                continue
            for k, v in info.items():
                if k not in run.index:  # never overwrite SRA runinfo columns
                    row[k] = v
            row["SRA_ID"] = sra_id
            combined.append(row)
    return combined, failed


def write_workbook(output_file, combined_df, bvbrc_df, failed, extra_sheets=None):
    with pd.ExcelWriter(output_file, engine="openpyxl") as writer:
        combined_df.to_excel(writer, sheet_name="Raw Data", index=False)
        bvbrc_df.to_excel(writer, sheet_name="BVBRC", index=False)
        for name, df in (extra_sheets or {}).items():
            df.to_excel(writer, sheet_name=name, index=False)
        if failed:
            pd.DataFrame(failed, columns=["id", "reason"]).to_excel(writer, sheet_name="Failed", index=False)


def main(input_file, output_file, edirect_path, geo_csv, default_subtype,
         location="state", subtype_suffix=False, allow_empty=False):
    sra_ids = read_ids(input_file)
    country_groups = load_country_geographic_groups(geo_csv)  # fail early, before fetching
    combined, failed = fetch_records(sra_ids, Fetcher(edirect_path))

    if not combined and not allow_empty:
        sys.exit("No records retrieved; nothing written. Failures:\n" +
                 "\n".join(f"  {i}: {r}" for i, r in failed))

    combined_df = pd.DataFrame(combined)
    if combined_df.empty:
        combined_df = pd.DataFrame(columns=list(BVBRC_SOURCE_COLUMNS) + ["SRA_ID"])
    out = build_bvbrc_table(combined_df, country_groups, default_subtype=default_subtype,
                            location=location, subtype_suffix=subtype_suffix)
    n_nosub = out["subtype"].isna().sum()
    if n_nosub:
        print(f"WARNING: {n_nosub} record(s) with no subtype found (use --subtype to set a fallback)",
              file=sys.stderr)

    write_workbook(output_file, combined_df, out, failed)
    print(f"Wrote {len(out)} record(s) to {output_file}"
          + (f"; {len(failed)} failed (see 'Failed' sheet)" if failed else ""), file=sys.stderr)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Process SRA and BioSample data into BV-BRC metadata.")
    parser.add_argument("input_file", help="Text file with one SRA ID per line (# comments allowed)")
    parser.add_argument("output_file", help="Output Excel file")
    parser.add_argument("--edirect", default=os.environ.get("EDIRECT_PATH") or
                        (DEFAULT_EDIRECT if os.path.isdir(DEFAULT_EDIRECT) else ""),
                        help="Directory with esearch/efetch (default: $EDIRECT_PATH, "
                             f"{DEFAULT_EDIRECT}, or PATH)")
    parser.add_argument("--geo", default=None,
                        help="Optional country -> BV-BRC geographic group CSV to use instead of the built-in table")
    parser.add_argument("--subtype", default=None,
                        help="Fallback subtype (e.g. H5N1) for records where none is found in the metadata")
    parser.add_argument("--location", choices=["state", "country"], default="state",
                        help="Location field used in strain names (default: state, falling back to country)")
    parser.add_argument("--subtype-suffix", action="store_true",
                        help="Append (HxNy) to genome_name, e.g. 'Influenza A virus A/cattle/USA/x/2024(H5N1)'")
    parser.add_argument("--allow-empty", action="store_true",
                        help="Write the workbook even if no records could be fetched")
    args = parser.parse_args()
    main(args.input_file, args.output_file, args.edirect, args.geo, args.subtype,
         args.location, args.subtype_suffix, args.allow_empty)
