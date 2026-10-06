"""One-shot builder for config/companies.csv from the 420-company master list.

Reads the user's master list (embedded below as tier blocks), dedupes by
normalized name, fills domains from a curated map (blank when unknown -
never guessed), and writes companies.csv with 8 disabled .example fixture
companies appended for offline tests.
"""
import csv
import re
from pathlib import Path

# (name, priority) in document order. Priority mapping from the master doc:
#   A = top-30 / Phase-1 picks + Azure+GenAI matches
#   B = best-fit tiers (FAANG/global product/unicorns/fintech/data)
#   C = everything else
TIERS = []
A = "A"; B = "B"; C = "C"

# Tier 1 - FAANG & Global Elite
TIERS += [
    ("Google", A), ("Microsoft", A), ("Amazon", A), ("Meta", A),
    ("Apple", B), ("Netflix", B), ("Uber", B), ("LinkedIn", B),
]
# Tier 2 - High-Pay Global Product
TIERS += [
    ("Atlassian", A), ("Stripe", A), ("Airbnb", B), ("Salesforce", B),
    ("Adobe", A), ("Intuit", B), ("Workday", B), ("ServiceNow", B),
    ("Snowflake", B), ("Databricks", A), ("Confluent", B), ("Shopify", B),
    ("Twitch", B), ("Dropbox", B), ("GitHub", B), ("HashiCorp", B),
    ("Postman", B), ("Figma", B),
]
# Tier 3 - Indian Unicorns & Soonicorns
TIERS += [
    ("Zepto", A), ("CRED", A), ("Razorpay", A), ("Swiggy", A),
    ("Zomato", B), ("Meesho", B), ("Groww", B), ("PhonePe", B),
    ("BrowserStack", B), ("Glean", A), ("Sarvam AI", A), ("Krutrim", B),
    ("Navi", B), ("Slice", B), ("Jupiter", B), ("Fi Money", B),
    ("Open Financial", B), ("Cashfree", B), ("Porter", B), ("Udaan", B),
    ("Dunzo", B), ("Ola Electric", B), ("Rapido", B), ("Lenskart", B),
]
# Tier 4 - Global Retail & Consumer GCCs
TIERS += [
    ("Target Corporation", A), ("Walmart Global Tech", A), ("Nike Technology", A),
    ("Levi's Technology", B), ("H&M Technology", B), ("Puma Technology", B),
    ("Under Armour", B), ("Marks & Spencer Technology", B),
    ("Decathlon Technology", B), ("IKEA Technology", B),
]
# Tier 5 - Automotive & Industrial GCCs
TIERS += [
    ("Mercedes-Benz R&D India", A), ("Bosch Global Software Technologies", C),
    ("Continental", C), ("Harman", C), ("Aptiv", C),
    ("ZF Friedrichshafen", C), ("Volvo Group India", C),
    ("Mahindra Digital", C), ("Tata Elxsi", C), ("Honeywell Technology Solutions", C),
    ("Schneider Electric India", C), ("Siemens Technology India", C),
    ("ABB India", C),
]
# Tier 6 - HealthTech & Pharma GCCs
TIERS += [
    ("Philips Healthcare", C), ("Siemens Healthineers", C),
    ("GE Healthcare", C), ("Abbott India Technology", C),
    ("Baxter India", C), ("Practo", C), ("MediBuddy", C),
    ("Tata 1mg", C), ("Niramai", C), ("Innovaccer", C),
]
# Tier 7 - Travel, Logistics & Supply Chain
TIERS += [
    ("Booking.com", A), ("Agoda", C), ("Expedia Group", C),
    ("MakeMyTrip", C), ("Cleartrip", C), ("ixigo", C),
    ("FedEx Digital", C), ("DHL IT Services", C), ("Maersk Technology", C),
    ("Locus.sh", C), ("LogiNext", C), ("Delhivery", C),
    ("Ecom Express", C), ("Shadowfax", C), ("Shiprocket", C),
]
# Tier 8 - FinTech & Payments
TIERS += [
    ("Paytm", C), ("BharatPe", C), ("Setu", C), ("M2P Fintech", C),
    ("Visa", C), ("Mastercard", C), ("American Express", C),
    ("PayPal", C), ("Western Union Technology", C), ("CreditStacks", C),
    ("KreditBee", C), ("MoneyTap", C),
]
# Tier 9 - Indian SaaS & Product
TIERS += [
    ("Freshworks", B), ("Zoho Corporation", B), ("Chargebee", B),
    ("LeadSquared", C), ("CleverTap", C), ("MoEngage", C),
    ("WebEngage", C), ("Capillary Technologies", C), ("Wingify", C),
    ("Perfios", C), ("LTIMindtree", C), ("Mphasis", C), ("Zensar", C),
]
# Tier 10 - AdTech, Data Platforms & MarTech
TIERS += [
    ("InMobi", B), ("Glance", B), ("PubMatic", B), ("Media.net", B),
    ("Affle", C), ("AppsFlyer", B), ("Sprinklr", B), ("Quantcast", B),
    ("Criteo", C), ("Oracle India", B), ("mParticle", B),
    ("Segment", B),
]
# Tier 11 - PropTech & Real Estate Tech
TIERS += [
    ("NoBroker", B), ("Housing.com", C), ("MagicBricks", C),
    ("Square Yards", C), ("Airbnb India", B), ("Compass India", B),
    ("Zillow India", B), ("99acres", C),
]
# Tier 12 - Banking & Finance GCCs
TIERS += [
    ("Goldman Sachs India", A), ("Morgan Stanley India", A),
    ("JPMC AI Lab", A), ("Standard Chartered India", B),
    ("Deutsche Bank India", A), ("Barclays India", A),
    ("BNY Mellon India", B), ("Fidelity Investments India", B),
    ("NatWest Group India", B), ("Societe Generale India", B),
    ("UBS India", B), ("HDFC Bank Technology", B),
    ("ICICI Bank Technology", B), ("Citibank India Technology", B),
    ("Credit Suisse India", B),
    ("HSBC Technology India", B), ("Nomura India", B),
    ("Macquarie India", B),
]
# Tier 13 - Emerging GenAI & DeepTech India
TIERS += [
    ("Karya", B), ("Rephrase.ai", B), ("Gan.ai", B),
    ("GreyOrange", B), ("Uniphore", B), ("Observe.ai", A),
    ("Eka Software", C), ("Darwinbox", C), ("Haptik", B),
    ("Yellow.ai", B), ("Leena AI", B), ("Vernacular.ai", B),
    ("CoRover.ai", B), ("Avaamo", B), ("Mihup", B),
    ("Better.com India", B),
]
# Tier 14 - Cybersecurity, Observability & Specialized SaaS
TIERS += [
    ("Zscaler", B), ("Cloudflare", A), ("SentinelOne", B),
    ("CrowdStrike", B), ("AppDynamics", B), ("New Relic", B),
    ("Datadog", A), ("PagerDuty", B), ("Eightfold.ai", B),
    ("Phenom", B), ("MindTickle", B), ("Icertis", B),
    ("G2", C), ("HighRadius", C), ("Zenoti", C),
    ("Druva", B), ("Rubrik", B), ("Palo Alto Networks", B),
]
# Tier 15 - Global Mix: Asian Tech, Consumer & Communications
TIERS += [
    ("Rakuten India", C), ("Mercari India", A), ("Coupang India", A),
    ("Grab India", B), ("Gojek India", B), ("Twilio India", B),
    ("Lyft India", B), ("Block India", B), ("Coinbase India", B),
    ("Ripple India", B), ("ByteDance India", B), ("Xiaomi India Tech", C),
    ("Samsung R&D India", B),
]
# Tier 16 - EdTech & Learning Platforms
TIERS += [
    ("BYJU'S", C), ("Unacademy", C), ("upGrad", C),
    ("Physics Wallah", C), ("Coursera India", B), ("Duolingo India", B),
    ("Vedantu", C), ("Great Learning", C),
]
# Tier 17 - Data Analytics & BI (DA Track)
TIERS += [
    ("Mu Sigma", B), ("Fractal Analytics", A), ("Tiger Analytics", B),
    ("ThoughtSpot", A), ("Domo India", B), ("Looker", A),
    ("MicroStrategy India", B), ("Qlik India", B), ("Alteryx India", B),
    ("TIBCO India", C), ("SAS Institute India", C), ("Teradata India", C),
]
# (Target/Walmart dup rows skipped: canonical entries already in Tier 4)
# Tier 18 - Additional High-Paying Companies
TIERS += [
    ("Ethos Life India", C), ("Flipkart", B), ("OYO", C),
    ("Cure.fit", C), ("ShareChat", C), ("Moj", C),
    ("Dailyhunt", C), ("Upstox", B), ("Shoonya", C),
    ("ClearTax", C), ("Khatabook", C), ("Fyle", C),
    ("Happay", C), ("Slang Labs", B), ("Mad Street Den", B),
    ("Infra.Market", C), ("Moglix", C), ("Industrybuying", C),
    ("Tracxn", C), ("CoinDCX", C), ("Policybazaar", C),
    ("Digit Insurance", C), ("LendingKart", C), ("Growfo", C),
    ("HDFC Securities Technology", C), ("Motilal Oswal Technology", C),
    ("Verifone India", C), ("Sanketha", C), ("Indifi", C),
    ("EaseBuzz", C), ("Instamojo", C),
    ("UniSupply", C),
    ("Asanify", C), ("BeNext", C), ("Apptio India", B),
    ("Testbook", C), ("Scaler", C),
    ("Pepo", C), ("Josh", C), ("Gaana", C),
    ("Wynk Music", C), ("Airtel Xstream", C),
]
# Tier 19 - Emerging & Specialized
TIERS += [
    ("Nasscom Foundation Tech", C), ("ISB Ventures", C),
    ("Vertex Ventures India", C), ("Matrix Partners India Ops", C),
    ("Peak XV Tech", C),
    ("Apollo Hospitals Technology", C),
    ("Manipal Hospital Technology", C), ("Narayana Health Technology", C),
    ("Max Healthcare Technology", C), ("Cloudmetrics", C),
    ("Credo India", C), ("Hexnode", C), ("Unified India", C),
    ("Opstream", C), ("Snapbizz", C),
    ("Infinimap", C),
]
# Tier 20 - GenAI Leaders & DeepTech Specialists
TIERS += [
    ("Perplexity AI India", A), ("Anthropic India", A),
    ("Hugging Face India", A), ("Together AI India", A),
    ("Weights & Biases India", A), ("Modal Labs India", A),
    ("Qdrant India", A), ("Scale AI India", A),
    ("Stability AI India", A), ("Mux India", A),
    ("Accenture GenAI Labs", B), ("Cognizant GenAI", C),
    ("Capgemini Cloud AI", B), ("TCS AI Labs", C),
    ("Infosys AI Services", C), ("Wipro GenAI Practice", C),
    ("HCL AI Labs", C),
]
# Tier 21 - Global Banking & Finance GCCs (APAC/Intl)
TIERS += [
    ("ANZ India", B), ("Commonwealth Bank India", B),
    ("Westpac India", B), ("NAB India", B),
    ("DBS Bank India", B), ("OCBC Bank India", B),
    ("UOB India", B), ("Bank of Tokyo-Mitsubishi UFJ India", B),
    ("Sumitomo Mitsui India", B), ("Mizuho Financial India", B),
    ("Nationwide India", B), ("Prudential Asia Technology", B),
    ("AIA Group India", B), ("ING Bank India", B),
]
# (Maybank/Bangkok Bank skipped: no verifiable official domain)
# Tier 22 - Fortune 500 & Global Tech Giants (India GCC)
TIERS += [
    ("Intel India", C), ("NVIDIA India", B), ("AMD India", C),
    ("Qualcomm India", B), ("Broadcom India", C), ("Sony India R&D", C),
    ("Panasonic India Technology", C), ("LG Electronics India R&D", C),
    ("Canon India Technology", C), ("Nikon India Technology", C),
    ("GoPro India", C), ("Lenovo India Technology", C),
    ("ASUS India", C), ("Razer India", C), ("3M India Technology", C),
    ("Corning India", C),
]
# (Philips/Ricoh/DJI dup rows skipped: canonical entries already exist)
# Tier 23 - Global Telecom Giants (India GCC)
TIERS += [
    ("AT&T India", B), ("Verizon India", B), ("T-Mobile India", B),
    ("Orange India", B), ("Deutsche Telekom India", B),
    ("Vodafone India Technology", B), ("BT Group India", B),
    ("Swisscom India", B), ("Telia India", C), ("Telefonica India", B),
    ("KPN India", C),
    ("Jio Platforms", B), ("Airtel Technology", B),
]
# (China Mobile/NTT/KDDI/SK/LG U+/Idea/Vi skipped: no verifiable domain)
# Tier 24 - Enterprise IT Infrastructure & Networking
TIERS += [
    ("Cisco India", B), ("Juniper Networks India", B),
    ("Arista Networks India", A), ("F5 Networks India", B),
    ("Fortinet India", B), ("Sophos India", B),
    ("Trend Micro India", B), ("Citrix India", B),
    ("VMware by Broadcom India", B), ("Dell Technologies India", B),
    ("HPE India", B), ("NetApp India", B),
    ("Pure Storage India", B), ("Nutanix India", B),
    ("Equinix India", B), ("Akamai India", A),
    ("DigitalOcean India", A), ("Linode India", A), ("Fastly India", A),
]
# (Limelight skipped: no verifiable standalone domain)
# Tier 25 - Enterprise Software & Middleware Giants
TIERS += [
    ("SAP India", B), ("SailPoint India", B), ("Okta India", A),
    ("Auth0 India", A), ("JFrog India", A), ("GitLab India", A),
    ("Canonical India", A), ("Red Hat India", B),
    ("Elastic India", A), ("MongoDB India", A), ("Redis India", A),
    ("PlanetScale India", A), ("Supabase India", A), ("MariaDB India", A),
    ("Neo4j India", A), ("InfluxData India", A), ("Timescale India", A),
]
# (Oracle/HashiCorp/CockroachDB dup rows skipped: canonical entries exist)

# Quick-ref top-30 / Phase picks from the master doc not already A:
TOP30_EXTRA_A = {
    "coupang india", "booking.com", "mercedes-benz r&d india",
    "fractal analytics", "thoughtspot", "looker",
}
DOMAINS = {
    "google": "google.com", "microsoft": "microsoft.com",
    "amazon": "amazon.jobs", "meta": "meta.com",
    "apple": "apple.com", "netflix": "netflix.com",
    "uber": "uber.com", "linkedin": "linkedin.com",
    "atlassian": "atlassian.com", "stripe": "stripe.com",
    "airbnb": "airbnb.com", "salesforce": "salesforce.com",
    "adobe": "adobe.com", "intuit": "intuit.com",
    "workday": "workday.com", "servicenow": "servicenow.com",
    "snowflake": "snowflake.com", "databricks": "databricks.com",
    "confluent": "confluent.io", "shopify": "shopify.com",
    "twitch": "twitch.tv", "dropbox": "dropbox.com",
    "github": "github.com", "hashicorp": "hashicorp.com",
    "postman": "postman.com", "figma": "figma.com",
    "zepto": "zeptonow.com", "cred": "cred.club",
    "razorpay": "razorpay.com", "swiggy": "swiggy.com",
    "zomato": "zomato.com", "meesho": "meesho.com",
    "groww": "groww.in", "phonepe": "phonepe.com",
    "browserstack": "browserstack.com", "glean": "glean.com",
    "sarvam ai": "sarvam.ai", "krutrim": "krutrim.com",
    "navi": "navi.com", "slice": "sliceit.com",
    "jupiter": "jupiter.money", "fi money": "fi.money",
    "cashfree": "cashfree.com", "porter": "porter.in",
    "udaan": "udaan.com", "dunzo": "dunzo.com",
    "ola electric": "olaelectric.com", "rapido": "rapido.bike",
    "lenskart": "lenskart.com",
    "target corporation": "target.com",
    "walmart global tech": "walmart.com",
    "nike technology": "nike.com",
    "booking.com": "booking.com", "agoda": "agoda.com",
    "expedia group": "expedia.com", "makemytrip": "makemytrip.com",
    "cleartrip": "cleartrip.com", "ixigo": "ixigo.com",
    "fedex digital": "fedex.com", "dhl it services": "dhl.com",
    "maersk technology": "maersk.com",
    "locus.sh": "locus.sh", "loginext": "loginextsolutions.com",
    "delhivery": "delhivery.com", "ecom express": "ecomexpress.in",
    "shadowfax": "shadowfax.in", "shiprocket": "shiprocket.in",
    "paytm": "paytm.com", "bharatpe": "bharatpe.com",
    "setu": "setu.co", "m2p fintech": "m2pfintech.com",
    "visa": "visa.com", "mastercard": "mastercard.com",
    "american express": "americanexpress.com", "paypal": "paypal.com",
    "kreditbee": "kreditbee.in",
    "freshworks": "freshworks.com", "zoho corporation": "zoho.com",
    "chargebee": "chargebee.com", "leadsquared": "leadsquared.com",
    "clevertap": "clevertap.com", "moengage": "moengage.com",
    "webengage": "webengage.com",
    "capillary technologies": "capillarytech.com",
    "wingify": "wingify.com", "perfios": "perfios.com",
    "ltimindtree": "ltimindtree.com", "mphasis": "mphasis.com",
    "zensar": "zensar.com",
    "inmobi": "inmobi.com", "glance": "glance.com",
    "pubmatic": "pubmatic.com", "media.net": "media.net",
    "appsflyer": "appsflyer.com", "sprinklr": "sprinklr.com",
    "quantcast": "quantcast.com", "criteo": "criteo.com",
    "oracle india": "oracle.com", "segment": "segment.com",
    "mparticle": "mparticle.com",
    "nobroker": "nobroker.in", "housing.com": "housing.com",
    "magicbricks": "magicbricks.com",
    "square yards": "squareyards.com",
    "99acres": "99acres.com",
    "karya": "karya.in", "greyorange": "greyorange.com",
    "uniphore": "uniphore.com", "observe.ai": "observe.ai",
    "eka software": "eka1.com", "darwinbox": "darwinbox.com",
    "haptik": "haptik.ai", "yellow.ai": "yellow.ai",
    "leena ai": "leena.ai", "corover.ai": "corover.ai",
    "avaamo": "avaamo.ai", "mihup": "mihup.com",
    "zscaler": "zscaler.com", "cloudflare": "cloudflare.com",
    "sentinelone": "sentinelone.com", "crowdstrike": "crowdstrike.com",
    "new relic": "newrelic.com", "datadog": "datadog.com",
    "pagerduty": "pagerduty.com", "eightfold.ai": "eightfold.ai",
    "phenom": "phenom.com", "mindtickle": "mindtickle.com",
    "icertis": "icertis.com", "g2": "g2.com",
    "highradius": "highradius.com", "zenoti": "zenoti.com",
    "druva": "druva.com", "rubrik": "rubrik.com",
    "palo alto networks": "paloaltonetworks.com",
    "samsung r&d india": "samsung.com",
    "coursera india": "coursera.org", "duolingo india": "duolingo.com",
    "vedantu": "vedantu.com", "great learning": "greatlearning.com",
    "unacademy": "unacademy.com", "upgrad": "upgrad.com",
    "physics wallah": "pw.live", "byju's": "byjus.com",
    "mu sigma": "mu-sigma.com", "fractal analytics": "fractal.ai",
    "tiger analytics": "tigeranalytics.com",
    "thoughtspot": "thoughtspot.com", "looker": "looker.com",
    "microstrategy india": "microstrategy.com",
    "flipkart": "flipkart.com", "oyo": "oyorooms.com",
    "sharechat": "sharechat.com", "dailyhunt": "dailyhunt.com",
    "upstox": "upstox.com", "cleartax": "cleartax.in",
    "khatabook": "khatabook.com", "fyle": "fylehq.com",
    "tracxn": "tracxn.com", "coindcx": "coindcx.com",
    "policybazaar": "policybazaar.com",
    "digit insurance": "godigit.com", "lendingkart": "lendingkart.com",
    "easebuzz": "easebuzz.in", "instamojo": "instamojo.com",
    "testbook": "testbook.com", "scaler": "scaler.com",
    "gaana": "gaana.com",
    "perplexity ai india": "perplexity.ai",
    "hugging face india": "huggingface.co",
    "qdrant india": "qdrant.tech", "scale ai india": "scale.com",
    "accenture genai labs": "accenture.com",
    "capgemini cloud ai": "capgemini.com",
    "tcs ai labs": "tcs.com", "infosys ai services": "infosys.com",
    "hcl ai labs": "hcl.com", "wipro genai practice": "wipro.com",
    "cognizant genai": "cognizant.com",
    "anz india": "anz.com",
    "commonwealth bank india": "commbank.com.au",
    "dbs bank india": "dbs.com", "aia group india": "aia.com",
    "ing bank india": "ing.com",
    "intel india": "intel.com", "nvidia india": "nvidia.com",
    "amd india": "amd.com", "qualcomm india": "qualcomm.com",
    "broadcom india": "broadcom.com", "sony india r&d": "sony.com",
    "lenovo india technology": "lenovo.com", "asus india": "asus.com",
    "razer india": "razer.com", "gopro india": "gopro.com",
    "cisco india": "cisco.com",
    "juniper networks india": "juniper.net",
    "arista networks india": "arista.com", "f5 networks india": "f5.com",
    "fortinet india": "fortinet.com", "sophos india": "sophos.com",
    "trend micro india": "trendmicro.com", "citrix india": "citrix.com",
    "dell technologies india": "dell.com", "hpe india": "hpe.com",
    "netapp india": "netapp.com", "pure storage india": "purestorage.com",
    "nutanix india": "nutanix.com", "equinix india": "equinix.com",
    "akamai india": "akamai.com",
    "digitalocean india": "digitalocean.com",
    "linode india": "linode.com", "fastly india": "fastly.com",
    "sap india": "sap.com", "sailpoint india": "sailpoint.com",
    "okta india": "okta.com", "auth0 india": "auth0.com",
    "jfrog india": "jfrog.com", "gitlab india": "gitlab.com",
    "canonical india": "canonical.com", "red hat india": "redhat.com",
    "elastic india": "elastic.co", "mongodb india": "mongodb.com",
    "redis india": "redis.io", "neo4j india": "neo4j.com",
    "jio platforms": "jio.com", "airtel technology": "airtel.in",
    "at&t india": "att.com", "verizon india": "verizon.com",
    "goldman sachs india": "goldmansachs.com",
    "morgan stanley india": "morganstanley.com",
    "deutsche bank india": "db.com", "barclays india": "barclays.com",
    "mercedes-benz r&d india": "mercedes-benz.com",
    "bosch global software technologies": "bosch.com",
}


def norm_key(name):
    n = name.lower()
    n = re.sub(r"\s*\bindia\b\s*", " ", n)
    n = re.sub(r"\s*\(.*?\)\s*", " ", n)
    n = re.sub(r"[^a-z0-9.& ]", " ", n)
    return re.sub(r"\s+", " ", n).strip()


SUFFIXES = (" india", " india technology", " technology", " r&d india")


def lookup_domain(name):
    key = norm_key(name)
    if key in DOMAINS:
        return DOMAINS[key]
    for sfx in SUFFIXES:
        if key.endswith(sfx):
            short = key[: -len(sfx)].strip()
            if short in DOMAINS:
                return DOMAINS[short]
    return ""


FIXTURES = [
    ("Acme Cloud", "acmecloud.example"), ("Nimbus Data", "nimbusdata.example"),
    ("Quantum Retail", "quantumretail.example"),
    ("Bluebird Health", "bluebirdhealth.example"),
    ("Orion Logistics", "orionlogistics.example"),
    ("Fernwave Media", "fernwavemedia.example"),
    ("Ironpeak Analytics", "ironpeakanalytics.example"),
    ("Lumenary Education", "lumenaryeducation.example"),
]


def main():
    seen = {}
    dupes = []
    rows = []
    for name, pri in TIERS:
        if norm_key(name) in TOP30_EXTRA_A:
            pri = "A"
        k = norm_key(name)
        if k in seen:
            dupes.append((name, seen[k]))
            continue
        seen[k] = name
        rows.append((name.strip(), lookup_domain(name), pri))
    print("tier entries:", len(TIERS), "| unique:", len(rows))
    print("dupes skipped:", dupes)
    with_dom = sum(1 for _, d, _ in rows if d)
    print("with domain:", with_dom, "| blank:", len(rows) - with_dom)
    from collections import Counter
    print("priority:", dict(Counter(p for _, _, p in rows)))
    out = Path("config/companies.csv")
    with out.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["company_name", "company_domain", "careers_url",
                    "priority", "enabled"])
        for name, dom, pri in rows:
            w.writerow([name, dom, "", pri, "true"])
        for name, dom in FIXTURES:
            w.writerow([name, dom, "", "C", "false"])
    print("wrote", out, "rows:", len(rows) + len(FIXTURES))


if __name__ == "__main__":
    main()



