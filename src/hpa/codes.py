"""What a code on a price line is, in a sentence: the code *type* (CPT, revenue code,
chargemaster number …) and, for revenue codes, the category the code belongs to.

Revenue codes are the UB-04 codes every hospital claim carries, published by the National
Uniform Billing Committee and listed in CMS's Medicare Claims Processing Manual (chapter
25). The category is fixed by the first three digits; the fourth digit picks a sub-type,
where 0 is "general" and 9 "other". CPT descriptions are AMA-copyrighted and are not here.
"""

# Code types as hospital files name them (the CMS template's `code | n | type` column).
CODE_TYPES = {
    "CPT": "CPT: the AMA procedure code for the service; the code the catalog searches for",
    "HCPCS": "HCPCS: the CMS procedure code; a five-digit numeric one is the same code as the CPT",
    "MS-DRG": "MS-DRG: the Medicare diagnosis-related group, which prices a whole inpatient stay",
    "APR-DRG": "APR-DRG: a diagnosis-related group used by Medicaid and some insurers for a whole stay",
    "TRIS-DRG": "TRIS-DRG: a diagnosis-related group used by TRICARE for a whole stay",
    "DRG": "DRG: a diagnosis-related group, which prices a whole inpatient stay",
    "RC": "Revenue code: the UB-04 billing category the charge is booked under (the department or kind of service)",
    "CDM": "Chargemaster number: the hospital's own line number for this item, meaningful only inside this file",
    "NDC": "NDC: the national drug code of a drug or supply",
    "APC": "APC: the Medicare outpatient payment group the service falls in",
    "HIPPS": "HIPPS: a Medicare payment code for nursing, home health or rehabilitation stays",
    "ICD": "ICD: a diagnosis or inpatient procedure code",
    "LOCAL": "Local code: a code this hospital or its state uses, not a national one",
}

# Revenue code series (first three digits) -> category. From the public UB-04 list.
REVENUE_SERIES = {
    "001": "total charge", "010": "all-inclusive rate", "011": "room and board, private",
    "012": "room and board, semi-private (two beds)", "013": "room and board, semi-private (three or four beds)",
    "014": "room and board, deluxe private", "015": "room and board, ward", "016": "room and board, other",
    "017": "nursery", "018": "leave of absence", "019": "subacute care", "020": "intensive care unit",
    "021": "coronary care unit", "022": "special charges", "023": "incremental nursing charge",
    "024": "all-inclusive ancillary", "025": "pharmacy", "026": "IV therapy",
    "027": "medical and surgical supplies and devices", "028": "oncology", "029": "durable medical equipment",
    "030": "laboratory", "031": "laboratory, pathology", "032": "radiology, diagnostic",
    "033": "radiology, therapeutic, and chemotherapy administration", "034": "nuclear medicine", "035": "CT scan",
    "036": "operating room services", "037": "anesthesia", "038": "blood and blood components",
    "039": "blood storage and processing", "040": "other imaging services", "041": "respiratory services",
    "042": "physical therapy", "043": "occupational therapy", "044": "speech-language pathology",
    "045": "emergency room", "046": "pulmonary function", "047": "audiology", "048": "cardiology",
    "049": "ambulatory surgical care", "050": "outpatient services", "051": "clinic", "052": "freestanding clinic",
    "053": "osteopathic services", "054": "ambulance", "055": "skilled nursing", "056": "medical social services",
    "057": "home health aide", "058": "home health, other visits", "059": "home health, units of service",
    "060": "home health, oxygen", "061": "MRI", "062": "medical and surgical supplies (extension of 027x)",
    "063": "pharmacy (extension of 025x)", "064": "home IV therapy services", "065": "hospice services",
    "066": "respite care", "067": "outpatient special residence charges", "068": "trauma response",
    "069": "pre-hospice / palliative care", "070": "cast room", "071": "recovery room",
    "072": "labor room and delivery", "073": "EKG / ECG", "074": "EEG", "075": "gastro-intestinal services",
    "076": "treatment or observation room", "077": "preventive care services", "078": "telemedicine",
    "079": "extracorporeal shock wave therapy", "080": "inpatient renal dialysis",
    "081": "acquisition of body components", "082": "hemodialysis, outpatient or home",
    "083": "peritoneal dialysis, outpatient or home", "084": "continuous ambulatory peritoneal dialysis",
    "085": "continuous cycling peritoneal dialysis", "088": "miscellaneous dialysis",
    "090": "behavioral health treatments and services", "091": "behavioral health treatments (extension of 090x)",
    "092": "other diagnostic services", "093": "medical rehabilitation day program",
    "094": "other therapeutic services", "095": "other therapeutic services (extension of 094x)",
    "096": "professional fees", "097": "professional fees (extension of 096x)",
    "098": "professional fees (extension of 097x)", "099": "patient convenience items",
    "100": "behavioral health accommodations", "210": "alternative therapy services", "310": "adult care",
}

# Fourth digits that name something a reader would want to know, beyond "general"/"other".
REVENUE_SPECIFIC = {
    "0361": "operating room services: minor surgery", "0362": "operating room services: organ transplant, other than kidney",
    "0367": "operating room services: kidney transplant", "0401": "diagnostic mammography",
    "0402": "ultrasound", "0403": "screening mammography", "0404": "positron emission tomography (PET)",
    "0450": "emergency room, general", "0456": "emergency room: urgent care", "0459": "emergency room, other",
    "0481": "cardiac catheterization lab", "0482": "stress test", "0483": "echocardiology",
    "0611": "MRI: brain (including brainstem)", "0612": "MRI: spinal cord (including spine)", "0614": "MRI: other",
    "0615": "MRA: head and neck", "0616": "MRA: lower extremities", "0618": "MRA: other",
    "0636": "pharmacy: drugs requiring detailed coding", "0637": "pharmacy: self-administrable drugs",
    "0750": "gastro-intestinal services, general", "0762": "observation room", "0942": "education and training",
    "0972": "professional fees: radiology, diagnostic", "0975": "professional fees: CT scan",
    "0982": "professional fees: outpatient services", "0983": "professional fees: clinic",
}


def revenue_code(code: str) -> str | None:
    """'360' or '0360' -> 'Revenue code 0360: operating room services (general)'."""
    digits = "".join(ch for ch in code if ch.isdigit())
    if len(digits) == 3:
        digits = "0" + digits
    if len(digits) != 4:
        return None
    if digits in REVENUE_SPECIFIC:
        return f"Revenue code {digits}: {REVENUE_SPECIFIC[digits]}"
    series = REVENUE_SERIES.get(digits[:3])
    if series is None:
        return f"Revenue code {digits}"
    sub = {"0": " (general)", "9": " (other)"}.get(digits[3], "")
    return f"Revenue code {digits}: {series}{sub}"


def explain(token: str) -> str | None:
    """A sentence for one code as a price line shows it: 'RC 360', 'CPT 45378', 'CDM 36100443'."""
    code_type, _, code = token.partition(" ")
    if code_type == "RC" and code:
        return revenue_code(code)
    return CODE_TYPES.get(code_type)


def explain_all(tokens) -> dict[str, str]:
    out = {}
    for t in tokens:
        text = explain(t)
        if text:
            out[t] = text
    return out
