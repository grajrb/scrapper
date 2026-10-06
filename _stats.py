import csv
from collections import Counter
with open("config/companies.csv", encoding="utf-8-sig") as f:
    rows = list(csv.DictReader(f))
print("rows:", len(rows))
print("enabled:", Counter(r["enabled"] for r in rows))
print("priority:", Counter(r["priority"] for r in rows))
print("blank domain:", sum(1 for r in rows if not r["company_domain"].strip()))
print("blank name:", sum(1 for r in rows if not r["company_name"].strip()))
names = [r["company_name"] for r in rows]
print("exact dupes:", [n for n in set(names) if names.count(n) > 1])

