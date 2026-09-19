# Mapping review sheet
*Generated 2026-09-18 by `scripts/review_sheet.py` from the scanned Houston files. For each service: does the plain-English alias mean this CMS entry, and how do the files represent it (billing class, modifiers, extra lines)? Fill in the **Decision** block; the answers go into `shoppable_services.json` as `reviewed`.*

## 'knee mri' → MRI scan of leg joint (CPT 73721)
Aliases: knee MRI, hip MRI, ankle MRI, lower extremity joint MRI. Qualifiers: {'contrast': 'without'}. Notes: Without contrast. Knee MRI with contrast (73722) or with and without (73723) is not on the CMS list.

**Texas Childrens Hospital** — file dated 2026-03-05, `https://www.texaschildrens.org/sites/tc/files/uploads/documents/741100555_texas-childrens-…`  
verdict: *comparable* — 1 other line for this code (modifiers, revenue centers or payer-only rates)

| description as written | codes | context | cash | gross | min–max | ref |
|---|---|---|---|---|---|---|
| TC MRI, EXTREMITY ANY JOINT, LOWER EXTREMITY W/O CONTR | CPT 73721 + CDM 4221830, RC 610 | inpatient, facility | $3,174.46 | $4,738.00 | $1,895.20–$4,501.10 | row 335547 |
| TC MRI, EXTREMITY ANY JOINT, LOWER EXTREMITY W/O CONTR | CPT 73721 + CDM 4221830, RC 610 | outpatient, facility | $3,174.46 | $4,738.00 | $208.84–$4,501.10 | row 28173 |

**Baylor St Lukes Medical Center** — file dated 2026-02-28, `https://www.commonspirit.org/content/dam/commonspiritorg/en/bslmc/soho/finance/price-trans…`  
verdict: *unknown: no billing class stated* — the file does not say whether this is a facility or professional charge; 1 other line for this code (modifiers, revenue centers or payer-only rates)

| description as written | codes | context | cash | gross | min–max | ref |
|---|---|---|---|---|---|---|
| HC MR LOWER EXTREM JNT WO CONT | CPT 73721 + RC 0610 | inpatient | $2,725.80 | $7,788.00 | $3,504.60–$7,788.00 | item 9143/charge 1 |
| HC MR LOWER EXTREM JNT WO CONT | CPT 73721 + RC 0610 | outpatient | $2,725.80 | $7,788.00 | $174.32–$7,788.00 | item 9144/charge 1 |

**Houston Methodist Hospital** — file dated 2026-04-01, `https://www.houstonmethodist.org/-/media/files/patient-resources/74110155_the-methodist-ho…`  
verdict: *comparable* — 1 other line for this code (modifiers, revenue centers or payer-only rates)

| description as written | codes | context | cash | gross | min–max | ref |
|---|---|---|---|---|---|---|
| HC MRI LOWER EXT JOINT W/O CONTRA | HCPCS 73721 + CDM 61000020, RC 0614 | both, facility | $1,230.00 | $2,460.00 | —–— | item 13569/charge 1 |
| Mri jnt of lwr extre w/o dye | HCPCS 73721 | outpatient, facility | — | — | $239.69–$1,691.87 | item 15496/charge 1 |

**Harris Health** — file dated 3/24/2026, `https://www.harrishealth.org/SiteCollectionDocuments/financials/charge%20description%20mas…`  
verdict: *unknown: no billing class stated* — the file does not say whether this is a facility or professional charge

| description as written | codes | context | cash | gross | min–max | ref |
|---|---|---|---|---|---|---|
| MRI LOWER EXTREMITY JOINT W/O CONTRAST | CPT 73721 + CDM 32912117, RC 610 | both | $231.94 | $3,821.00 | $208.84–$2,483.65 | row 33175 |

**Houston Methodist The Woodlands Hospital** — file dated 2026-04-01, `https://www.houstonmethodist.org/-/media/files/patient-resources/760545192_houston-methodi…`  
verdict: *comparable* — 1 other line for this code (modifiers, revenue centers or payer-only rates)

| description as written | codes | context | cash | gross | min–max | ref |
|---|---|---|---|---|---|---|
| HC MRI LOWER EXT JOINT W/O CONTRA | HCPCS 73721 + CDM 61000020, RC 0614 | both, facility | $1,243.50 | $2,487.00 | —–— | item 13552/charge 1 |
| Mri jnt of lwr extre w/o dye | HCPCS 73721 | outpatient, facility | — | — | $239.69–$1,691.87 | item 15381/charge 1 |

**CHI St Lukes Lakeside Hospital** — file dated 2026-02-28, `https://www.commonspirit.org/content/dam/commonspiritorg/en/stluh/soho/finance/price-trans…`  
verdict: *unknown: no billing class stated* — the file does not say whether this is a facility or professional charge; 1 other line for this code (modifiers, revenue centers or payer-only rates)

| description as written | codes | context | cash | gross | min–max | ref |
|---|---|---|---|---|---|---|
| HC MR LOWER EXTREM JNT WO CONT | CPT 73721 + RC 0610 | inpatient | $2,725.80 | $7,788.00 | $3,426.72–$7,788.00 | item 9185/charge 1 |
| HC MR LOWER EXTREM JNT WO CONT | CPT 73721 + RC 0610 | outpatient | $2,725.80 | $7,788.00 | $174.32–$7,788.00 | item 9186/charge 1 |

**St Luke's The Woodlands Hospital** — file dated 2026-02-28, `https://www.commonspirit.org/content/dam/commonspiritorg/en/stluh/soho/finance/price-trans…`  
verdict: *unknown: no billing class stated* — the file does not say whether this is a facility or professional charge; 1 other line for this code (modifiers, revenue centers or payer-only rates)

| description as written | codes | context | cash | gross | min–max | ref |
|---|---|---|---|---|---|---|
| HC MR LOWER EXTREM JNT WO CONT | CPT 73721 + RC 0610 | inpatient | $2,725.80 | $7,788.00 | $3,348.84–$7,788.00 | item 9185/charge 1 |
| HC MR LOWER EXTREM JNT WO CONT | CPT 73721 + RC 0610 | outpatient | $2,725.80 | $7,788.00 | $174.32–$7,788.00 | item 9186/charge 1 |

**Woodland Springs** — file dated 7/31/2026, `https://www.woodlandspringshealth.com/docs/bhwoodlandspringslibraries/3q26/352565165_woodl…`  
verdict: *not found*

**Elite Hospital Kingwood** — file dated 6/1/2026, `https://elitekingwood.com/823349983_Elite-Hospital-Kingwood_Standard-Charges.csv…`  
verdict: *unknown: no billing class stated* — the file does not say whether this is a facility or professional charge

| description as written | codes | context | cash | gross | min–max | ref |
|---|---|---|---|---|---|---|
| Magnetic resonance (eg proton) imaging any joint of lower extremity; w | CPT 73721 | both | $2,735.80 | $5,471.59 | $431.06–$574.74 | row 1570 |

**Kingwood Pines Hospital** — file dated 2026-08-31, `https://uhsfilecdn.eskycity.net/bh/731726290_kingwood-pines_standardcharges.csv…`  
verdict: *not found*

**HCA Houston Healthcare Kingwood** — file dated 2026-05-14, `https://stctrprodsnsvc00455826e6.blob.core.windows.net/pt-final-posting-files/62-1619857_H…`  
verdict: *modifier-specific lines only* — priced lines carry modifiers 50, LT, RT; no unmodified line to compare

| description as written | codes | context | cash | gross | min–max | ref |
|---|---|---|---|---|---|---|
| Magnetic resonance (eg, proton) imaging, any joint of lower extremity; | CPT 73721 + RC 321 | outpatient | — | — | $215.06–$2,974.36 | item 101622/charge 1 |
| Magnetic resonance (eg, proton) imaging, any joint of lower extremity; | CPT 73721 + RC 920 | outpatient | — | — | $215.06–$215.06 | item 103502/charge 1 |
| Magnetic resonance (eg, proton) imaging, any joint of lower extremity; | CPT 73721 + RC 350 | outpatient | — | — | $215.06–$215.06 | item 103570/charge 1 |
| Magnetic resonance (eg, proton) imaging, any joint of lower extremity; | CPT 73721 + RC 612 | outpatient | — | — | $215.06–$2,241.00 | item 110021/charge 1 |
| Magnetic resonance (eg, proton) imaging, any joint of lower extremity; | CPT 73721 + RC 340 | outpatient | — | — | $215.06–$215.06 | item 116006/charge 1 |
| Magnetic resonance (eg, proton) imaging, any joint of lower extremity; | CPT 73721 + RC 351 | outpatient | — | — | $215.06–$215.06 | item 116729/charge 1 |
| Magnetic resonance (eg, proton) imaging, any joint of lower extremity; | CPT 73721 + RC 929 | outpatient | — | — | $215.06–$215.06 | item 120769/charge 1 |
| Magnetic resonance (eg, proton) imaging, any joint of lower extremity; | CPT 73721 + RC 404 | outpatient | — | — | $215.06–$215.06 | item 125484/charge 1 |
| Magnetic resonance (eg, proton) imaging, any joint of lower extremity; | CPT 73721 + RC 732 | outpatient | — | — | $215.06–$215.06 | item 130331/charge 1 |
| Magnetic resonance (eg, proton) imaging, any joint of lower extremity; | CPT 73721 + RC 402 | outpatient | — | — | $215.06–$215.06 | item 130688/charge 1 |
| Magnetic resonance (eg, proton) imaging, any joint of lower extremity; | CPT 73721 + RC 401 | outpatient | — | — | $215.06–$215.06 | item 133126/charge 1 |
| Magnetic resonance (eg, proton) imaging, any joint of lower extremity; | CPT 73721 + RC 320 | outpatient | — | — | $215.06–$2,974.36 | item 134195/charge 1 |

*… 36 more lines; `hpa prices "knee mri" --ccn 450775 --all`*

Verdicts across hospitals: {'comparable': 3, 'unknown: no billing class stated': 5, 'not found': 2, 'modifier-specific lines only': 1}

**Decision** (edit in place):
- [ ] The alias means this service: yes / no / needs a qualifier (which?)
- [ ] Hospitals represent it as: facility line / professional line / both / varies
- [ ] Lines that should NOT count as this service (modifiers, revenue codes, bundles):
- [ ] Reviewer, date:

## 'colonoscopy' → Diagnostic examination of large bowel using an endoscope (CPT 45378)
Aliases: colonoscopy, screening colonoscopy. Qualifiers: {'biopsy': 'without'}. Notes: none

**Texas Childrens Hospital** — file dated 2026-03-05, `https://www.texaschildrens.org/sites/tc/files/uploads/documents/741100555_texas-childrens-…`  
verdict: *not found*

**Baylor St Lukes Medical Center** — file dated 2026-02-28, `https://www.commonspirit.org/content/dam/commonspiritorg/en/bslmc/soho/finance/price-trans…`  
verdict: *negotiated rates only, no cash or gross price* — 1 line, each with negotiated min/max only

| description as written | codes | context | cash | gross | min–max | ref |
|---|---|---|---|---|---|---|
| DIAGNOSTIC COLONOSCOPY | CPT 45378 | outpatient | — | — | $345.58–$7,221.00 | item 5870/charge 1 |

**Houston Methodist Hospital** — file dated 2026-04-01, `https://www.houstonmethodist.org/-/media/files/patient-resources/74110155_the-methodist-ho…`  
verdict: *comparable* — 1 other line for this code (modifiers, revenue centers or payer-only rates)

| description as written | codes | context | cash | gross | min–max | ref |
|---|---|---|---|---|---|---|
| HC COLON DIAGNOSTIC W/BRUSH OR WASH WHEN PFRMD | HCPCS 45378 + CDM 36100443, RC 0361 | both, facility | $519.00 | $1,038.00 | —–— | item 12398/charge 1 |
| Diagnostic colonoscopy | HCPCS 45378 | outpatient, facility | — | — | $934.20–$5,545.00 | item 21586/charge 1 |

**Harris Health** — file dated 3/24/2026, `https://www.harrishealth.org/SiteCollectionDocuments/financials/charge%20description%20mas…`  
verdict: *unknown: no billing class stated* — the file does not say whether this is a facility or professional charge; 5 other lines for this code (modifiers, revenue centers or payer-only rates)

| description as written | codes | context | cash | gross | min–max | ref |
|---|---|---|---|---|---|---|
| ECHG GI PROC COLONOSCOPY, FLEX ; DX | CPT 45378 + CDM 12645378, RC 750 | both | $1,835.24 | $3,880.00 | $1,940.00–$1,940.00 | row 32341 |
| Unspecified | CPT 45378 | outpatient | — | — | $859.08–$951.37 | row 14264 |
| Diagnostic colonoscopy | CPT 45378 | outpatient | — | — | $1,662.00–$1,662.00 | row 22154 |
| Diagnostic colonoscopy | CPT 45378 | outpatient | — | — | $660.00–$660.00 | row 27709 |
| AMBULATORY SURGICAL CENTER | CPT 45378 | outpatient | — | — | $328.50–$338.36 | row 6045 |
| Diagnostic colonoscopy | CPT 45378 | outpatient | — | — | $726.00–$726.00 | row 9990 |

**Houston Methodist The Woodlands Hospital** — file dated 2026-04-01, `https://www.houstonmethodist.org/-/media/files/patient-resources/760545192_houston-methodi…`  
verdict: *comparable* — 1 other line for this code (modifiers, revenue centers or payer-only rates)

| description as written | codes | context | cash | gross | min–max | ref |
|---|---|---|---|---|---|---|
| HC COLON DIAGNOSTIC W/BRUSH OR WASH WHEN PFRMD | HCPCS 45378 + CDM 36100443, RC 0361 | both, facility | $866.00 | $1,732.00 | —–— | item 12425/charge 1 |
| Diagnostic colonoscopy | HCPCS 45378 | outpatient, facility | — | — | $934.20–$5,545.00 | item 21356/charge 1 |

**CHI St Lukes Lakeside Hospital** — file dated 2026-02-28, `https://www.commonspirit.org/content/dam/commonspiritorg/en/stluh/soho/finance/price-trans…`  
verdict: *negotiated rates only, no cash or gross price* — 1 line, each with negotiated min/max only

| description as written | codes | context | cash | gross | min–max | ref |
|---|---|---|---|---|---|---|
| DIAGNOSTIC COLONOSCOPY | CPT 45378 | outpatient | — | — | $328.50–$7,221.00 | item 5908/charge 1 |

**St Luke's The Woodlands Hospital** — file dated 2026-02-28, `https://www.commonspirit.org/content/dam/commonspiritorg/en/stluh/soho/finance/price-trans…`  
verdict: *negotiated rates only, no cash or gross price* — 1 line, each with negotiated min/max only

| description as written | codes | context | cash | gross | min–max | ref |
|---|---|---|---|---|---|---|
| DIAGNOSTIC COLONOSCOPY | CPT 45378 | outpatient | — | — | $345.58–$7,221.00 | item 5908/charge 1 |

**Woodland Springs** — file dated 7/31/2026, `https://www.woodlandspringshealth.com/docs/bhwoodlandspringslibraries/3q26/352565165_woodl…`  
verdict: *not found*

**Elite Hospital Kingwood** — file dated 6/1/2026, `https://elitekingwood.com/823349983_Elite-Hospital-Kingwood_Standard-Charges.csv…`  
verdict: *not found*

**Kingwood Pines Hospital** — file dated 2026-08-31, `https://uhsfilecdn.eskycity.net/bh/731726290_kingwood-pines_standardcharges.csv…`  
verdict: *not found*

**HCA Houston Healthcare Kingwood** — file dated 2026-05-14, `https://stctrprodsnsvc00455826e6.blob.core.windows.net/pt-final-posting-files/62-1619857_H…`  
verdict: *negotiated rates only, no cash or gross price* — 20 lines, each with negotiated min/max only

| description as written | codes | context | cash | gross | min–max | ref |
|---|---|---|---|---|---|---|
| Colonoscopy, flexible; diagnostic, including collection of specimen(s) | CPT 45378 + RC 369 | outpatient | — | — | $344.93–$4,690.00 | item 103612/charge 1 |
| Colonoscopy, flexible; diagnostic, including collection of specimen(s) | CPT 45378 + RC 362 | outpatient | — | — | $344.93–$4,690.00 | item 114999/charge 1 |
| Colonoscopy, flexible; diagnostic, including collection of specimen(s) | CPT 45378 + RC 360 | outpatient | — | — | $4,255.00–$4,255.00 | item 115626/charge 1 |
| Colonoscopy, flexible; diagnostic, including collection of specimen(s) | CPT 45378 + RC 367 | outpatient | — | — | $4,690.00–$4,690.00 | item 122978/charge 1 |
| Colonoscopy, flexible; diagnostic, including collection of specimen(s) | CPT 45378 + RC 490 | outpatient | — | — | $4,255.00–$4,255.00 | item 153105/charge 1 |
| Colonoscopy, flexible; diagnostic, including collection of specimen(s) | CPT 45378 + RC 369 | outpatient | — | — | $4,255.00–$4,255.00 | item 157318/charge 1 |
| Colonoscopy, flexible; diagnostic, including collection of specimen(s) | CPT 45378 + RC 481 | outpatient | — | — | $352.49–$4,690.00 | item 167209/charge 1 |
| Colonoscopy, flexible; diagnostic, including collection of specimen(s) | CPT 45378 + RC 750 | outpatient | — | — | $352.49–$4,690.00 | item 175576/charge 1 |
| Colonoscopy, flexible; diagnostic, including collection of specimen(s) | CPT 45378 + RC 490 | outpatient | — | — | $344.93–$4,690.00 | item 176208/charge 1 |
| Colonoscopy, flexible; diagnostic, including collection of specimen(s) | CPT 45378 + RC 480 | outpatient | — | — | $2,434.00–$2,434.00 | item 209872/charge 1 |
| Colonoscopy, flexible; diagnostic, including collection of specimen(s) | CPT 45378 + RC 790 | outpatient | — | — | $4,255.00–$4,255.00 | item 221203/charge 1 |
| Colonoscopy, flexible; diagnostic, including collection of specimen(s) | CPT 45378 + RC 499 | outpatient | — | — | $344.93–$4,690.00 | item 274927/charge 1 |

*… 8 more lines; `hpa prices "colonoscopy" --ccn 450775 --all`*

Verdicts across hospitals: {'not found': 4, 'negotiated rates only, no cash or gross price': 4, 'comparable': 2, 'unknown: no billing class stated': 1}

**Decision** (edit in place):
- [ ] The alias means this service: yes / no / needs a qualifier (which?)
- [ ] Hospitals represent it as: facility line / professional line / both / varies
- [ ] Lines that should NOT count as this service (modifiers, revenue codes, bundles):
- [ ] Reviewer, date:

## 'head ct' → CT scan, head or brain, without contrast (CPT 70450)
Aliases: head CT, brain CT without contrast. Qualifiers: {'contrast': 'without'}. Notes: none

**Texas Childrens Hospital** — file dated 2026-03-05, `https://www.texaschildrens.org/sites/tc/files/uploads/documents/741100555_texas-childrens-…`  
verdict: *comparable* — 1 other line for this code (modifiers, revenue centers or payer-only rates)

| description as written | codes | context | cash | gross | min–max | ref |
|---|---|---|---|---|---|---|
| TC CT, BRAIN WITHOUT CONTRAST | CPT 70450 + CDM 4240000, RC 351 | inpatient, facility | $2,278.67 | $3,401.00 | $1,360.40–$3,230.95 | row 333039 |
| TC CT, BRAIN WITHOUT CONTRAST | CPT 70450 + CDM 4240000, RC 351 | outpatient, facility | $2,278.67 | $3,401.00 | $104.75–$3,230.95 | row 26951 |

**Baylor St Lukes Medical Center** — file dated 2026-02-28, `https://www.commonspirit.org/content/dam/commonspiritorg/en/bslmc/soho/finance/price-trans…`  
verdict: *unknown: no billing class stated* — the file does not say whether this is a facility or professional charge; 1 other line for this code (modifiers, revenue centers or payer-only rates)

| description as written | codes | context | cash | gross | min–max | ref |
|---|---|---|---|---|---|---|
| HC CT BRAIN | CPT 70450 + RC 0350 | inpatient | $2,399.25 | $6,855.00 | $3,084.75–$6,855.00 | item 8782/charge 1 |
| HC CT BRAIN | CPT 70450 + RC 0350 | outpatient | $2,399.25 | $6,855.00 | $76.69–$6,855.00 | item 8783/charge 1 |

**Houston Methodist Hospital** — file dated 2026-04-01, `https://www.houstonmethodist.org/-/media/files/patient-resources/74110155_the-methodist-ho…`  
verdict: *comparable* — 1 other line for this code (modifiers, revenue centers or payer-only rates)

| description as written | codes | context | cash | gross | min–max | ref |
|---|---|---|---|---|---|---|
| HC CT HEAD/BRAIN SCAN WO CONTRA | HCPCS 70450 + CDM 35100002, RC 0351 | both, facility | $1,120.00 | $2,240.00 | —–— | item 11945/charge 1 |
| Ct head/brain w/o dye | HCPCS 70450 | outpatient, facility | — | — | $105.02–$813.70 | item 14510/charge 1 |

**Harris Health** — file dated 3/24/2026, `https://www.harrishealth.org/SiteCollectionDocuments/financials/charge%20description%20mas…`  
verdict: *unknown: no billing class stated* — the file does not say whether this is a facility or professional charge; 1 other line for this code (modifiers, revenue centers or payer-only rates)

| description as written | codes | context | cash | gross | min–max | ref |
|---|---|---|---|---|---|---|
| CT HEAD W/O CONTRAST (MOD CT � MCARE ONLY) | CPT 70450 + CDM 33300001, RC 351 | both | $102.04 | $2,320.00 | $104.75–$1,508.00 | row 34428 |
| CT HEAD W/O CONTRAST | CPT 70450 + CDM 33329351, RC 351 | both | $102.04 | $2,320.00 | $104.75–$1,508.00 | row 34635 |

**Houston Methodist The Woodlands Hospital** — file dated 2026-04-01, `https://www.houstonmethodist.org/-/media/files/patient-resources/760545192_houston-methodi…`  
verdict: *comparable* — 1 other line for this code (modifiers, revenue centers or payer-only rates)

| description as written | codes | context | cash | gross | min–max | ref |
|---|---|---|---|---|---|---|
| HC CT HEAD/BRAIN SCAN WO CONTRA | HCPCS 70450 + CDM 35100002, RC 0351 | both, facility | $1,120.00 | $2,240.00 | —–— | item 11959/charge 1 |
| Ct head/brain w/o dye | HCPCS 70450 | outpatient, facility | — | — | $105.02–$813.70 | item 14357/charge 1 |

**CHI St Lukes Lakeside Hospital** — file dated 2026-02-28, `https://www.commonspirit.org/content/dam/commonspiritorg/en/stluh/soho/finance/price-trans…`  
verdict: *unknown: no billing class stated* — the file does not say whether this is a facility or professional charge; 1 other line for this code (modifiers, revenue centers or payer-only rates)

| description as written | codes | context | cash | gross | min–max | ref |
|---|---|---|---|---|---|---|
| HC CT BRAIN | CPT 70450 + RC 0350 | inpatient | $2,399.25 | $6,855.00 | $3,016.20–$6,855.00 | item 8824/charge 1 |
| HC CT BRAIN | CPT 70450 + RC 0350 | outpatient | $2,399.25 | $6,855.00 | $76.69–$6,855.00 | item 8825/charge 1 |

**St Luke's The Woodlands Hospital** — file dated 2026-02-28, `https://www.commonspirit.org/content/dam/commonspiritorg/en/stluh/soho/finance/price-trans…`  
verdict: *unknown: no billing class stated* — the file does not say whether this is a facility or professional charge; 1 other line for this code (modifiers, revenue centers or payer-only rates)

| description as written | codes | context | cash | gross | min–max | ref |
|---|---|---|---|---|---|---|
| HC CT BRAIN | CPT 70450 + RC 0350 | inpatient | $2,399.25 | $6,855.00 | $2,947.65–$6,855.00 | item 8824/charge 1 |
| HC CT BRAIN | CPT 70450 + RC 0350 | outpatient | $2,399.25 | $6,855.00 | $76.69–$6,855.00 | item 8825/charge 1 |

**Woodland Springs** — file dated 7/31/2026, `https://www.woodlandspringshealth.com/docs/bhwoodlandspringslibraries/3q26/352565165_woodl…`  
verdict: *not found*

**Elite Hospital Kingwood** — file dated 6/1/2026, `https://elitekingwood.com/823349983_Elite-Hospital-Kingwood_Standard-Charges.csv…`  
verdict: *unknown: no billing class stated* — the file does not say whether this is a facility or professional charge

| description as written | codes | context | cash | gross | min–max | ref |
|---|---|---|---|---|---|---|
| Computed tomography head or brain; without contrast material | CPT 70450 | both | $2,612.15 | $5,224.29 | $226.89–$302.52 | row 508 |

**Kingwood Pines Hospital** — file dated 2026-08-31, `https://uhsfilecdn.eskycity.net/bh/731726290_kingwood-pines_standardcharges.csv…`  
verdict: *not found*

**HCA Houston Healthcare Kingwood** — file dated 2026-05-14, `https://stctrprodsnsvc00455826e6.blob.core.windows.net/pt-final-posting-files/62-1619857_H…`  
verdict: *conflicting* — 5 unmodified lines disagree (cash [Decimal('10294.00'), Decimal('10294.23')])

| description as written | codes | context | cash | gross | min–max | ref |
|---|---|---|---|---|---|---|
| Computed tomography, head or brain; without contrast material | CPT 70450 + RC 619 | outpatient | — | — | $109.02–$109.02 | item 107302/charge 1 |
| Computed tomography, head or brain; without contrast material | CPT 70450 + RC 322 | outpatient | — | — | $109.02–$1,285.24 | item 118927/charge 1 |
| Computed tomography, head or brain; without contrast material | CPT 70450 + RC 610 | outpatient | — | — | $109.02–$109.02 | item 129112/charge 1 |
| Computed tomography, head or brain; without contrast material | CPT 70450 + RC 401 | outpatient | — | — | $109.02–$109.02 | item 130139/charge 1 |
| Computed tomography, head or brain; without contrast material | CPT 70450 + RC 403 | outpatient | — | — | $109.02–$109.02 | item 135001/charge 1 |
| Computed tomography, head or brain; without contrast material | CPT 70450 + RC 732 | outpatient | — | — | $109.02–$109.02 | item 149762/charge 1 |
| Computed tomography, head or brain; without contrast material | CPT 70450 + RC 349 | outpatient | — | — | $109.02–$109.02 | item 155389/charge 1 |
| Computed tomography, head or brain; without contrast material | CPT 70450 + RC 614 | outpatient | — | — | $109.02–$109.02 | item 157363/charge 1 |
| Computed tomography, head or brain; without contrast material | CPT 70450 + RC 739 | outpatient | — | — | $109.02–$109.02 | item 167881/charge 1 |
| Computed tomography, head or brain; without contrast material | CPT 70450 + RC 404 | outpatient | — | — | $109.02–$109.02 | item 181465/charge 1 |
| Computed tomography, head or brain; without contrast material | CPT 70450 + RC 323 | outpatient | — | — | $109.02–$1,285.24 | item 183333/charge 1 |
| Computed tomography, head or brain; without contrast material | CPT 70450 + RC 920 | outpatient | — | — | $109.02–$109.02 | item 185636/charge 1 |

*… 36 more lines; `hpa prices "head ct" --ccn 450775 --all`*

Verdicts across hospitals: {'comparable': 3, 'unknown: no billing class stated': 5, 'not found': 2, 'conflicting': 1}

**Decision** (edit in place):
- [ ] The alias means this service: yes / no / needs a qualifier (which?)
- [ ] Hospitals represent it as: facility line / professional line / both / varies
- [ ] Lines that should NOT count as this service (modifiers, revenue codes, bundles):
- [ ] Reviewer, date:

## 'cbc' → Complete blood count, automated (CPT 85027)
Aliases: CBC, complete blood count. Qualifiers: none. Notes: none

**Texas Childrens Hospital** — file dated 2026-03-05, `https://www.texaschildrens.org/sites/tc/files/uploads/documents/741100555_texas-childrens-…`  
verdict: *conflicting* — 4 unmodified lines disagree (cash [Decimal('75.71'), Decimal('78.39'), Decimal('80.40'), Decimal('85.76')])

| description as written | codes | context | cash | gross | min–max | ref |
|---|---|---|---|---|---|---|
| TC FETAL CBC,AUTOMATED | CPT 85027 + CDM 3410400, RC 305 | inpatient, facility | $78.39 | $117.00 | $46.80–$111.15 | row 345067 |
| TC CBC, AUTO HGB HCT RBC WBC & PLT NO DIFF | CPT 85027 + CDM 3410500, RC 300 | inpatient, facility | $75.71 | $113.00 | $45.20–$107.35 | row 345069 |
| TC CBC, AUTO HGB HCT RBC WBC & PLT NO DIF | CPT 85027 + CDM 2730010, RC 305 | inpatient, facility | $85.76 | $128.00 | $51.20–$121.60 | row 345661 |
| TC CBC, AUTO HGB HCT RBC WBC & PLT NO DIFF | CPT 85027 + CDM 3320010, RC 300 | inpatient, facility | $80.40 | $120.00 | $48.00–$114.00 | row 347119 |
| TC FETAL CBC,AUTOMATED | CPT 85027 + CDM 3410400, RC 305 | outpatient, facility | $78.39 | $117.00 | $6.47–$111.15 | row 31807 |
| TC CBC, AUTO HGB HCT RBC WBC & PLT NO DIFF | CPT 85027 + CDM 3410500, RC 300 | outpatient, facility | $75.71 | $113.00 | $6.47–$107.35 | row 31808 |
| TC CBC, AUTO HGB HCT RBC WBC & PLT NO DIF | CPT 85027 + CDM 2730010, RC 305 | outpatient, facility | $85.76 | $128.00 | $6.47–$121.60 | row 31857 |
| TC CBC, AUTO HGB HCT RBC WBC & PLT NO DIFF | CPT 85027 + CDM 3320010, RC 300 | outpatient, facility | $80.40 | $120.00 | $6.47–$114.00 | row 32530 |

**Baylor St Lukes Medical Center** — file dated 2026-02-28, `https://www.commonspirit.org/content/dam/commonspiritorg/en/bslmc/soho/finance/price-trans…`  
verdict: *unknown: no billing class stated* — the file does not say whether this is a facility or professional charge; 1 other line for this code (modifiers, revenue centers or payer-only rates)

| description as written | codes | context | cash | gross | min–max | ref |
|---|---|---|---|---|---|---|
| HC LAB CBC (W/PLT&HEMOGRAM) | CPT 85027 + RC 0300 | inpatient | $174.30 | $498.00 | $224.10–$498.00 | item 10587/charge 1 |
| HC LAB CBC (W/PLT&HEMOGRAM) | CPT 85027 + RC 0300 | outpatient | $174.30 | $498.00 | $4.66–$498.00 | item 10588/charge 1 |

**Houston Methodist Hospital** — file dated 2026-04-01, `https://www.houstonmethodist.org/-/media/files/patient-resources/74110155_the-methodist-ho…`  
verdict: *comparable* — 1 other line for this code (modifiers, revenue centers or payer-only rates)

| description as written | codes | context | cash | gross | min–max | ref |
|---|---|---|---|---|---|---|
| HC COMPLETE BLOOD COUNT CBC | HCPCS 85027 + CDM 30500007, RC 0305 | both, facility | $133.00 | $266.00 | —–— | item 10713/charge 1 |
| Complete cbc automated | HCPCS 85027 | outpatient, facility | — | — | $6.47–$79.98 | item 23714/charge 1 |

**Harris Health** — file dated 3/24/2026, `https://www.harrishealth.org/SiteCollectionDocuments/financials/charge%20description%20mas…`  
verdict: *unknown: no billing class stated* — the file does not say whether this is a facility or professional charge

| description as written | codes | context | cash | gross | min–max | ref |
|---|---|---|---|---|---|---|
| CBC/PLATELET | CPT 85027 + CDM 34439958, RC 300 | both | $6.47 | $166.00 | $5.43–$107.90 | row 36051 |

**Houston Methodist The Woodlands Hospital** — file dated 2026-04-01, `https://www.houstonmethodist.org/-/media/files/patient-resources/760545192_houston-methodi…`  
verdict: *comparable* — 1 other line for this code (modifiers, revenue centers or payer-only rates)

| description as written | codes | context | cash | gross | min–max | ref |
|---|---|---|---|---|---|---|
| HC COMPLETE BLOOD COUNT CBC | HCPCS 85027 + CDM 30500007, RC 0305 | both, facility | $95.50 | $191.00 | —–— | item 10719/charge 1 |
| Complete cbc automated | HCPCS 85027 | outpatient, facility | — | — | $6.47–$79.98 | item 24182/charge 1 |

**CHI St Lukes Lakeside Hospital** — file dated 2026-02-28, `https://www.commonspirit.org/content/dam/commonspiritorg/en/stluh/soho/finance/price-trans…`  
verdict: *unknown: no billing class stated* — the file does not say whether this is a facility or professional charge; 1 other line for this code (modifiers, revenue centers or payer-only rates)

| description as written | codes | context | cash | gross | min–max | ref |
|---|---|---|---|---|---|---|
| HC LAB CBC (W/PLT&HEMOGRAM) | CPT 85027 + RC 0300 | inpatient | $174.30 | $498.00 | $219.12–$498.00 | item 10629/charge 1 |
| HC LAB CBC (W/PLT&HEMOGRAM) | CPT 85027 + RC 0300 | outpatient | $174.30 | $498.00 | $4.66–$498.00 | item 10630/charge 1 |

**St Luke's The Woodlands Hospital** — file dated 2026-02-28, `https://www.commonspirit.org/content/dam/commonspiritorg/en/stluh/soho/finance/price-trans…`  
verdict: *unknown: no billing class stated* — the file does not say whether this is a facility or professional charge; 1 other line for this code (modifiers, revenue centers or payer-only rates)

| description as written | codes | context | cash | gross | min–max | ref |
|---|---|---|---|---|---|---|
| HC LAB CBC (W/PLT&HEMOGRAM) | CPT 85027 + RC 0300 | inpatient | $174.30 | $498.00 | $214.14–$498.00 | item 10629/charge 1 |
| HC LAB CBC (W/PLT&HEMOGRAM) | CPT 85027 + RC 0300 | outpatient | $174.30 | $498.00 | $4.66–$498.00 | item 10630/charge 1 |

**Woodland Springs** — file dated 7/31/2026, `https://www.woodlandspringshealth.com/docs/bhwoodlandspringslibraries/3q26/352565165_woodl…`  
verdict: *not found*

**Elite Hospital Kingwood** — file dated 6/1/2026, `https://elitekingwood.com/823349983_Elite-Hospital-Kingwood_Standard-Charges.csv…`  
verdict: *unknown: no billing class stated* — the file does not say whether this is a facility or professional charge

| description as written | codes | context | cash | gross | min–max | ref |
|---|---|---|---|---|---|---|
| Blood count; complete (CBC) automated (Hgb Hct RBC WBC and platelet co | CPT 85027 | both | $97.20 | $194.40 | $145.80–$145.80 | row 229 |

**Kingwood Pines Hospital** — file dated 2026-08-31, `https://uhsfilecdn.eskycity.net/bh/731726290_kingwood-pines_standardcharges.csv…`  
verdict: *not found*

**HCA Houston Healthcare Kingwood** — file dated 2026-05-14, `https://stctrprodsnsvc00455826e6.blob.core.windows.net/pt-final-posting-files/62-1619857_H…`  
verdict: *unknown: no billing class stated* — the file does not say whether this is a facility or professional charge; 33 other lines for this code (modifiers, revenue centers or payer-only rates)

| description as written | codes | context | cash | gross | min–max | ref |
|---|---|---|---|---|---|---|
| Blood count; complete (CBC), automated (Hgb, Hct, RBC, WBC and platele | CPT 85027 + RC 324 | outpatient | — | — | $26.50–$34.15 | item 12662/charge 1 |
| Blood count; complete (CBC), automated (Hgb, Hct, RBC, WBC and platele | CPT 85027 + RC 303 | outpatient | — | — | $5.54–$86.34 | item 126684/charge 1 |
| Blood count; complete (CBC), automated (Hgb, Hct, RBC, WBC and platele | CPT 85027 + RC 925 | outpatient | — | — | $5.54–$6.47 | item 1293/charge 1 |
| Blood count; complete (CBC), automated (Hgb, Hct, RBC, WBC and platele | CPT 85027 + RC 341 | outpatient | — | — | $26.50–$34.15 | item 132638/charge 1 |
| Blood count; complete (CBC), automated (Hgb, Hct, RBC, WBC and platele | CPT 85027 + RC 319 | outpatient | — | — | $5.54–$86.34 | item 149274/charge 1 |
| Blood count; complete (CBC), automated (Hgb, Hct, RBC, WBC and platele | CPT 85027 + RC 342 | outpatient | — | — | $26.50–$34.15 | item 15245/charge 1 |
| Blood count; complete (CBC), automated (Hgb, Hct, RBC, WBC and platele | CPT 85027 + RC 306 | outpatient | — | — | $5.54–$86.34 | item 161467/charge 1 |
| Blood count; complete (CBC), automated (Hgb, Hct, RBC, WBC and platele | CPT 85027 + RC 302 | outpatient | — | — | $5.54–$86.34 | item 165339/charge 1 |
| Blood count; complete (CBC), automated (Hgb, Hct, RBC, WBC and platele | CPT 85027 | outpatient | — | — | $5.32–$42.56 | item 167711/charge 1 |
| Blood count; complete (CBC), automated (Hgb, Hct, RBC, WBC and platele | CPT 85027 + RC 323 | outpatient | — | — | $26.50–$34.15 | item 182468/charge 1 |
| Blood count; complete (CBC), automated (Hgb, Hct, RBC, WBC and platele | CPT 85027 + RC 349 | outpatient | — | — | $26.50–$34.15 | item 184914/charge 1 |
| Blood count; complete (CBC), automated (Hgb, Hct, RBC, WBC and platele | CPT 85027 + RC 400 | outpatient | — | — | $26.50–$34.15 | item 194201/charge 1 |

*… 22 more lines; `hpa prices "cbc" --ccn 450775 --all`*

Verdicts across hospitals: {'conflicting': 1, 'unknown: no billing class stated': 6, 'comparable': 2, 'not found': 2}

**Decision** (edit in place):
- [ ] The alias means this service: yes / no / needs a qualifier (which?)
- [ ] Hospitals represent it as: facility line / professional line / both / varies
- [ ] Lines that should NOT count as this service (modifiers, revenue codes, bundles):
- [ ] Reviewer, date:

## 'screening mammogram' → Mammography, screening, bilateral (CPT 77067)
Aliases: screening mammogram, annual mammogram. Qualifiers: none. Notes: none

**Texas Childrens Hospital** — file dated 2026-03-05, `https://www.texaschildrens.org/sites/tc/files/uploads/documents/741100555_texas-childrens-…`  
verdict: *not found*

**Baylor St Lukes Medical Center** — file dated 2026-02-28, `https://www.commonspirit.org/content/dam/commonspiritorg/en/bslmc/soho/finance/price-trans…`  
verdict: *unknown: no billing class stated* — the file does not say whether this is a facility or professional charge; 1 other line for this code (modifiers, revenue centers or payer-only rates)

| description as written | codes | context | cash | gross | min–max | ref |
|---|---|---|---|---|---|---|
| HC MAMMO SCRN BIL & CAD | CPT 77067 + RC 0403 | inpatient | $297.50 | $850.00 | $382.50–$850.00 | item 9581/charge 1 |
| HC MAMMO SCRN BIL & CAD | CPT 77067 + RC 0403 | outpatient | $297.50 | $850.00 | $119.36–$850.00 | item 9582/charge 1 |

**Houston Methodist Hospital** — file dated 2026-04-01, `https://www.houstonmethodist.org/-/media/files/patient-resources/74110155_the-methodist-ho…`  
verdict: *comparable* — 1 other line for this code (modifiers, revenue centers or payer-only rates)

| description as written | codes | context | cash | gross | min–max | ref |
|---|---|---|---|---|---|---|
| HC MAMMOGRAM SCREENING INCL CAD BIL | HCPCS 77067 + CDM 40300002, RC 0403 | both, facility | $332.50 | $665.00 | —–— | item 13151/charge 1 |
| Scr mammo bi incl cad | HCPCS 77067 | outpatient, facility | — | — | $82.98–$393.90 | item 15937/charge 1 |

**Harris Health** — file dated 3/24/2026, `https://www.harrishealth.org/SiteCollectionDocuments/financials/charge%20description%20mas…`  
verdict: *unknown: no billing class stated* — the file does not say whether this is a facility or professional charge

| description as written | codes | context | cash | gross | min–max | ref |
|---|---|---|---|---|---|---|
| SCREENING MAMMOGRAPHY BILATERAL INCL CAD WHEN PEFORMED | CPT 77067 + CDM 32803890, RC 403 | both | $82.30 | $174.00 | $43.85–$199.38 | row 32991 |

**Houston Methodist The Woodlands Hospital** — file dated 2026-04-01, `https://www.houstonmethodist.org/-/media/files/patient-resources/760545192_houston-methodi…`  
verdict: *comparable* — 1 other line for this code (modifiers, revenue centers or payer-only rates)

| description as written | codes | context | cash | gross | min–max | ref |
|---|---|---|---|---|---|---|
| HC MAMMOGRAM SCREENING INCL CAD BIL | HCPCS 77067 + CDM 40300002, RC 0403 | both, facility | $715.50 | $1,431.00 | —–— | item 13155/charge 1 |
| Scr mammo bi incl cad | HCPCS 77067 | outpatient, facility | — | — | $82.98–$393.90 | item 16068/charge 1 |

**CHI St Lukes Lakeside Hospital** — file dated 2026-02-28, `https://www.commonspirit.org/content/dam/commonspiritorg/en/stluh/soho/finance/price-trans…`  
verdict: *unknown: no billing class stated* — the file does not say whether this is a facility or professional charge; 1 other line for this code (modifiers, revenue centers or payer-only rates)

| description as written | codes | context | cash | gross | min–max | ref |
|---|---|---|---|---|---|---|
| HC MAMMO SCRN BIL & CAD | CPT 77067 + RC 0403 | inpatient | $297.50 | $850.00 | $374.00–$850.00 | item 9623/charge 1 |
| HC MAMMO SCRN BIL & CAD | CPT 77067 + RC 0403 | outpatient | $297.50 | $850.00 | $140.25–$850.00 | item 9624/charge 1 |

**St Luke's The Woodlands Hospital** — file dated 2026-02-28, `https://www.commonspirit.org/content/dam/commonspiritorg/en/stluh/soho/finance/price-trans…`  
verdict: *unknown: no billing class stated* — the file does not say whether this is a facility or professional charge; 1 other line for this code (modifiers, revenue centers or payer-only rates)

| description as written | codes | context | cash | gross | min–max | ref |
|---|---|---|---|---|---|---|
| HC MAMMO SCRN BIL & CAD | CPT 77067 + RC 0403 | inpatient | $297.50 | $850.00 | $365.50–$850.00 | item 9623/charge 1 |
| HC MAMMO SCRN BIL & CAD | CPT 77067 + RC 0403 | outpatient | $297.50 | $850.00 | $140.25–$850.00 | item 9624/charge 1 |

**Woodland Springs** — file dated 7/31/2026, `https://www.woodlandspringshealth.com/docs/bhwoodlandspringslibraries/3q26/352565165_woodl…`  
verdict: *not found*

**Elite Hospital Kingwood** — file dated 6/1/2026, `https://elitekingwood.com/823349983_Elite-Hospital-Kingwood_Standard-Charges.csv…`  
verdict: *unknown: no billing class stated* — the file does not say whether this is a facility or professional charge

| description as written | codes | context | cash | gross | min–max | ref |
|---|---|---|---|---|---|---|
| Screening mammography bilateral (2-view study of each breast) includin | CPT 77067 | both | $449.04 | $898.08 | $267.80–$357.06 | row 2080 |

**Kingwood Pines Hospital** — file dated 2026-08-31, `https://uhsfilecdn.eskycity.net/bh/731726290_kingwood-pines_standardcharges.csv…`  
verdict: *not found*

**HCA Houston Healthcare Kingwood** — file dated 2026-05-14, `https://stctrprodsnsvc00455826e6.blob.core.windows.net/pt-final-posting-files/62-1619857_H…`  
verdict: *conflicting* — 4 unmodified lines disagree (cash [Decimal('818.95'), Decimal('912.90')])

| description as written | codes | context | cash | gross | min–max | ref |
|---|---|---|---|---|---|---|
| Screening mammography, bilateral (2-view study of each breast), includ | CPT 77067 | outpatient | — | — | $88.86–$363.07 | item 129983/charge 1 |
| Screening mammography, bilateral (2-view study of each breast), includ | CPT 77067 + RC 324 | outpatient | — | — | $1,751.13–$1,751.13 | item 174767/charge 1 |
| Screening mammography, bilateral (2-view study of each breast), includ | CPT 77067 + RC 320 | outpatient | — | — | $1,751.13–$1,751.13 | item 210539/charge 1 |
| Screening mammography, bilateral (2-view study of each breast), includ | CPT 77067 + RC 323 | outpatient | — | — | $1,751.13–$1,751.13 | item 224486/charge 1 |
| Screening mammography, bilateral (2-view study of each breast), includ | CPT 77067 + RC 403 | outpatient | — | — | $183.64–$665.00 | item 226749/charge 1 |
| Screening mammography, bilateral (2-view study of each breast), includ | CPT 77067 + RC 321 | outpatient | — | — | $1,751.13–$1,751.13 | item 279972/charge 1 |
| Screening mammography, bilateral (2-view study of each breast), includ | CPT 77067 + RC 322 | outpatient | — | — | $1,751.13–$1,751.13 | item 295928/charge 1 |
| MAMMO SCR CAD BI | CPT 77067 + CDM 425035 | outpatient | $912.90 | $912.90 | $54.77–$821.61 | item 314944/charge 1 |
| MAMMO SCR CAD BI | CPT 77067 + CDM 425036 | outpatient | $818.95 | $818.95 | $286.63–$286.63 | item 321320/charge 1 |
| MAMMO SCR CAD BI | CPT 77067 + CDM 425035 | outpatient | $912.90 | $912.90 | $319.51–$319.51 | item 321847/charge 1 |
| MAMMO SCR CAD BI | CPT 77067 + CDM 425036 | outpatient | $818.95 | $818.95 | $49.14–$737.05 | item 335436/charge 1 |
| Screening mammography, bilateral (2-view study of each breast), includ | CPT 77067 + RC 329 | outpatient | — | — | $1,751.13–$1,751.13 | item 75645/charge 1 |

*… 2 more lines; `hpa prices "screening mammogram" --ccn 450775 --all`*

Verdicts across hospitals: {'not found': 3, 'unknown: no billing class stated': 5, 'comparable': 2, 'conflicting': 1}

**Decision** (edit in place):
- [ ] The alias means this service: yes / no / needs a qualifier (which?)
- [ ] Hospitals represent it as: facility line / professional line / both / varies
- [ ] Lines that should NOT count as this service (modifiers, revenue codes, bundles):
- [ ] Reviewer, date:
