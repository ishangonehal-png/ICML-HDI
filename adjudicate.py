"""
Clinical claim adjudicator for lung cancer IO readiness claims.
Rules:
- supported: claim matches bundle data
- partial: claim is directionally right but specifics don't match
- unsupported: claim contradicts bundle or asserts absent data
"""

import csv
import json
import re


def parse_bundle(bundle_str):
    try:
        return json.loads(bundle_str)
    except Exception:
        return {}


def extract_tier_from_claim(claim):
    """Extract asserted io_tier from claim text, avoiding false matches."""
    # Check for negations/hedges about io_tier first
    if re.search(
        r'(no\s+explicit\s+io\s+(immune\s+)?tier|'
        r'io\s+(immune\s+)?tier.*not\s+(explicitly\s+|available|provided|assessable|determinable)|'
        r'not\s+(explicitly\s+|available|provided|assessable)\s+.*io\s+(immune\s+)?tier|'
        r'not\s+assessable\s+from)',
        claim, re.IGNORECASE
    ):
        return 'UNKNOWN_CLAIMED'

    # Positive tier assertions
    # Must have "IO" or "immune tier" context, OR explicit tier label
    has_tier_context = bool(re.search(
        r'(io\s+(immune\s+)?tier|immune\s+tier|readiness\s+tier)',
        claim, re.IGNORECASE
    ))

    # Look for tier designations
    if re.search(r'tier\s*1\b', claim, re.IGNORECASE):
        return 'Hot'
    if re.search(r'tier\s*2\b', claim, re.IGNORECASE):
        return 'Warm'
    if re.search(r'tier\s*3\b', claim, re.IGNORECASE):
        return 'Cold'

    # Hot indicators - require IO context or explicit "Hot" without negation
    hot_pattern = r'\b(immune[- ]?hot|immune\s+inflamed)\b'
    if re.search(hot_pattern, claim, re.IGNORECASE):
        return 'Hot'
    # "Hot" only when clearly asserting tier
    if has_tier_context and re.search(r'\bHot\b', claim):
        return 'Hot'
    # "inflamed" only in positive tier assertion context (not in "no RNA inflamed signal" etc.)
    if has_tier_context and re.search(r'\binflamed\b', claim, re.IGNORECASE):
        # Check it's not negated
        if not re.search(r'(no|not|without|lack|unavailable|cannot|non)[- ]+(inflamed|immune)', claim, re.IGNORECASE):
            return 'Hot'

    # Warm indicators
    if has_tier_context and re.search(r'\bWarm\b', claim):
        return 'Warm'
    if re.search(r'\bimmune[- ]?warm\b', claim, re.IGNORECASE):
        return 'Warm'

    # Cold indicators
    if has_tier_context and re.search(r'\bCold\b', claim):
        return 'Cold'
    if re.search(r'\bimmune[- ]?cold\b', claim, re.IGNORECASE):
        return 'Cold'

    return None


def scores_within_5pct(val1, val2):
    if val2 == 0:
        return val1 == 0
    return abs(val1 - val2) / abs(val2) <= 0.05


def scores_close(val1, val2, tol=0.01):
    return abs(val1 - val2) <= tol


def normalize_stage(s):
    """Normalize stage string to Roman numeral base (I, II, III, IV)."""
    s = s.upper().strip()
    # Remove substage letters (A, B, C) and TNM staging
    s = re.sub(r'^(I{1,3}V?|IV|I|II|III)[ABC]?.*$', r'\1', s)
    return s


def adjudicate(claim, bundle):
    """Returns (label, note) tuple."""
    claim_lower = claim.lower()

    io_tier = bundle.get('io_tier', '')
    io_score = bundle.get('io_score')
    rna_available = bundle.get('rna_available', False)
    fusion = bundle.get('fusion', {})
    fusion_mode = fusion.get('mode_used', '')
    fusion_active = fusion.get('active_score')
    modality = fusion.get('modality_contributions', {})
    path_contrib = modality.get('pathology', {})
    clin_contrib = modality.get('clinical', {})
    tx_contrib = modality.get('transcriptomics', {})
    pathology = bundle.get('pathology', {})
    tissue_fracs = pathology.get('tissue_fractions', {})
    top_tiles = pathology.get('top_tiles', [])
    til_fraction = pathology.get('til_fraction')
    transcriptomics = bundle.get('transcriptomics', {})
    cyt_available = transcriptomics.get('cyt_available', False)
    gep_available = transcriptomics.get('gep_available', False)
    tide_available = transcriptomics.get('tide_available', False)
    cyt_value = transcriptomics.get('cyt_value')
    gep_value = transcriptomics.get('gep_value')
    tide_value = transcriptomics.get('tide_value')

    # Clinical summary parsing
    clin_summary = clin_contrib.get('summary', '')
    clin_stage = re.search(r'stage=([IVX\d]+)', clin_summary)
    clin_stage = clin_stage.group(1) if clin_stage else None
    clin_smoker = re.search(r'smoker=(\w+)', clin_summary)
    clin_smoker = clin_smoker.group(1) if clin_smoker else None
    clin_age = re.search(r'age=(\d+)', clin_summary)
    clin_age = int(clin_age.group(1)) if clin_age else None
    path_summary = path_contrib.get('summary', '')
    path_top_tile_score = None
    if top_tiles:
        path_top_tile_score = top_tiles[0].get('score')

    # =========================================================
    # RULE 1: Claim explicitly about io_tier
    # =========================================================
    claimed_tier = extract_tier_from_claim(claim)
    if claimed_tier == 'UNKNOWN_CLAIMED':
        if io_tier:
            return 'unsupported', f'Claims IO tier not provided/assessable but bundle has io_tier={io_tier}'
        return 'supported', 'Claims IO tier not provided; bundle lacks io_tier'

    if claimed_tier is not None:
        if claimed_tier == io_tier:
            return 'supported', f'Claimed {claimed_tier} matches bundle io_tier={io_tier}'
        else:
            tier_order = {'Cold': 0, 'Warm': 1, 'Hot': 2}
            diff = abs(tier_order.get(claimed_tier, -1) - tier_order.get(io_tier, -1))
            if diff == 1:
                return 'partial', f'Claimed {claimed_tier} vs bundle {io_tier} (adjacent tiers)'
            return 'unsupported', f'Claimed {claimed_tier} contradicts bundle io_tier={io_tier}'

    # =========================================================
    # RULE 2: Transcriptomics unavailability / availability claims
    # =========================================================
    tx_unavail_patterns = [
        r'transcriptomics?\s+(is\s+)?(un)?available',
        r'transcriptomics?\s+unavailable',
        r'transcriptomics?\s+data\s+is\s+(unavailable|missing)',
        r'transcriptomics?\s+is\s+missing',
        r'no\s+transcriptomics?\s+input',
        r'transcriptomics?\s+missing',
        r'rna\s+(evidence|data|input|signatures?|based[- ]immune)\s*(is\s+)?(not\s+)?(available|provided|detected|unavailable)',
        r'no\s+(structured\s+)?rna[- ]based',
        r'rna\s+(evidence|signature)[^\w]*(un)?available|not\s+available',
        r'no\s+rna\s+evidence',
        r'(rna|transcriptomic)\s+(data|input)\s+(is\s+)?not\s+(available|provided|detected)',
        r'no\s+transcriptomic\s+evidence',
        r'transcriptomic.*unavailable',
        r'limiting.*robustness.*fusion\s+score',
        r'fusion\s+is\s+provisional\s+because\s+transcriptomics',
        r'transcriptomics\s+data\s+is\s+unavailable.*limiting',
        r'no\s+transcriptomics?\s+detected',
        r'transcriptomics?\s+not\s+(provided|available|detected)',
    ]
    tx_avail_positive_patterns = [
        r'(cyt|gep|tide)\s*(value|score)?\s*[=:]\s*[\d.]',
        r'(gzmb|prf1|cd3e|cd8a)',
        r'high\s+interferon',
        r'ifn[- ]?(gamma|γ)\s+signaling',
        r'cytolytic\s+(activity|markers)',
        r'immune\s+signature\s+(shows|indicates|is)',
    ]

    is_tx_unavail_claim = any(re.search(p, claim_lower) for p in tx_unavail_patterns)
    is_tx_avail_claim = any(re.search(p, claim_lower) for p in tx_avail_positive_patterns)

    if is_tx_unavail_claim and not is_tx_avail_claim:
        if not rna_available:
            return 'supported', 'Claims transcriptomics unavailable; bundle rna_available=false'
        else:
            return 'unsupported', 'Claims transcriptomics unavailable but rna_available=true'

    # =========================================================
    # RULE 3: Fusion mode claims
    # =========================================================
    is_provisional_claim = bool(re.search(
        r'(fusion\s+(score|mode|is)\s+(is|remains|uses?|because|provisional)|'
        r'fusion\s+is\s+provisional|'
        r'provisional\s+(score|fusion|mode|because)|'
        r'mode_used.*provisional|'
        r'provisional.*because\s+transcriptomics)',
        claim_lower
    ))
    if is_provisional_claim:
        if fusion_mode == 'provisional':
            return 'supported', f'Claims provisional fusion; bundle fusion.mode_used={fusion_mode}'
        elif fusion_mode == 'refined':
            return 'unsupported', f'Claims provisional but bundle fusion.mode_used=refined'

    if re.search(r'refined\s+(score|fusion|mode)', claim_lower):
        if fusion_mode == 'refined':
            return 'supported', f'Claims refined fusion; bundle fusion.mode_used={fusion_mode}'
        elif fusion_mode == 'provisional':
            return 'unsupported', f'Claims refined but bundle fusion.mode_used=provisional'

    # =========================================================
    # RULE 4: CYT/GEP/TIDE null/unavailable claims
    # =========================================================
    if re.search(r'(cyt|gep|tide).*(null|unavailable|not\s+available)', claim_lower) or \
       re.search(r'(null|unavailable|not\s+available).*(cyt|gep|tide)', claim_lower):
        if not cyt_available and not gep_available and not tide_available:
            return 'supported', 'Claims CYT/GEP/TIDE null/unavailable; all false in bundle'
        return 'unsupported', 'Claims CYT/GEP/TIDE unavailable but some available'

    # =========================================================
    # RULE 4b: Claims asserting RNA levels are present/inferred (when rna=false)
    # =========================================================
    if re.search(r'(rna\s+levels\s+for|inferred\s+from\s+rna|while\s+rna\s+levels|mrna\s+for\s+\*?cd|while\s+mrna)', claim_lower):
        if not rna_available:
            return 'unsupported', 'Claims RNA levels/inference but rna_available=false'

    # =========================================================
    # RULE 5: Transcriptomics positive value claims (when no RNA)
    # =========================================================
    if is_tx_avail_claim:
        if not rna_available:
            return 'unsupported', 'Claims transcriptomics data/scores but rna_available=false'
        return 'partial', 'Transcriptomics values claimed; need specific value check'

    # =========================================================
    # RULE 6: Clinical context claims
    # =========================================================
    if re.search(r'clinical\s+(context|contribution)', claim_lower) and clin_summary:
        errors = []
        # Stage check
        stage_claim_m = re.search(r'stage\s+(I{0,3}V?[A-C]?|IV[A-C]?)\b', claim, re.IGNORECASE)
        if stage_claim_m and clin_stage:
            sc_raw = stage_claim_m.group(1).upper()
            sc = normalize_stage(sc_raw)
            cs = normalize_stage(clin_stage)
            if sc != cs:
                errors.append(f'stage claimed={sc_raw} vs bundle={clin_stage}')
        # Smoker check
        smoker_map = {
            'current': [r'current\s+smok', r'active\s+smok'],
            'former': [r'former\s+smok', r'ex[- ]smok'],
            'never': [r'never\s+smok', r'non[- ]smok'],
            'unknown': [r'unknown\s+smok'],
        }
        for sk, pats in smoker_map.items():
            if any(re.search(p, claim_lower) for p in pats):
                if clin_smoker and sk != clin_smoker:
                    errors.append(f'smoker claimed={sk} vs bundle={clin_smoker}')
                break
        # Age check
        age_m = re.search(r'age\s*[=:]?\s*(\d{2})\b', claim_lower)
        if age_m and clin_age:
            ac = int(age_m.group(1))
            if abs(ac - clin_age) > 1:
                errors.append(f'age claimed={ac} vs bundle={clin_age}')
        # Contribution % check
        pct_m = re.search(r'(\d+\.?\d*)\s*%', claim)
        if pct_m and clin_contrib.get('contribution_percent') is not None:
            cp = float(pct_m.group(1))
            if abs(cp - clin_contrib['contribution_percent']) > 5:
                errors.append(f'clin_contrib% claimed={cp} vs bundle={clin_contrib["contribution_percent"]:.1f}')

        if not errors:
            return 'supported', 'Clinical context matches bundle'
        elif len(errors) == 1:
            return 'partial', f'Mostly matches clinical context, but: {errors[0]}'
        else:
            return 'unsupported', f'Clinical context mismatch: {"; ".join(errors)}'

    # =========================================================
    # RULE 7: Stage-specific claims (without "clinical context" prefix)
    # =========================================================
    stage_claim_m = re.search(r'\bstage\s+(I{0,3}V?[A-C]?)\b', claim, re.IGNORECASE)
    if stage_claim_m and clin_stage:
        sc_raw = stage_claim_m.group(1).upper()
        sc = normalize_stage(sc_raw)
        cs = normalize_stage(clin_stage)
        if sc == cs:
            return 'supported', f'Claimed stage {sc_raw} matches bundle stage={clin_stage}'
        else:
            return 'unsupported', f'Claimed stage {sc_raw} (base={sc}) contradicts bundle stage={clin_stage}'

    # =========================================================
    # RULE 8: Pathology contribution % claims
    # =========================================================
    if re.search(r'pathology\s+(contribut|was\s+the\s+largest|came\s+from)', claim_lower) or \
       re.search(r'(largest\s+contribution|main\s+driver).*pathology', claim_lower) or \
       re.search(r'pathology\s+\(.*%', claim_lower):
        pct_m = re.search(r'(\d+\.?\d*)\s*%', claim)
        if pct_m and path_contrib.get('contribution_percent') is not None:
            cp = float(pct_m.group(1))
            bv = path_contrib['contribution_percent']
            if scores_close(cp, bv, tol=1.0):
                return 'supported', f'Pathology contribution {cp}% matches bundle {bv:.1f}%'
            elif abs(cp - bv) < 5:
                return 'partial', f'Pathology contribution {cp}% close to bundle {bv:.1f}%'
            else:
                return 'unsupported', f'Pathology contribution {cp}% vs bundle {bv:.1f}%'
        # No specific % but claims pathology as largest - check
        if path_contrib.get('contribution_percent') and clin_contrib.get('contribution_percent'):
            if path_contrib['contribution_percent'] > clin_contrib['contribution_percent']:
                return 'supported', f'Pathology is indeed largest contributor ({path_contrib["contribution_percent"]:.1f}%)'
            else:
                return 'unsupported', f'Claims pathology largest but clinical is ({clin_contrib["contribution_percent"]:.1f}%)'

    # =========================================================
    # RULE 9: IO score / fusion score numeric claims
    # =========================================================
    claimed_scores = [float(m) for m in re.findall(r'\b(0\.\d{2,4})\b', claim)]
    if claimed_scores and io_score is not None:
        for cs in claimed_scores:
            if scores_close(cs, io_score, tol=0.005):
                return 'supported', f'Claimed score {cs} matches io_score={io_score}'
            if fusion_active is not None and scores_close(cs, fusion_active, tol=0.005):
                return 'supported', f'Claimed score {cs} matches fusion.active_score={fusion_active}'
        for cs in claimed_scores:
            if scores_within_5pct(cs, io_score):
                return 'supported', f'Claimed score {cs} within 5% of io_score={io_score}'

    # =========================================================
    # RULE 10: Tissue fraction / pathology detail claims
    # =========================================================
    # Tumor fraction
    tumor_pct_m = re.search(r'tumor\s*[=(:]?\s*(\d+\.?\d*)\s*%', claim_lower)
    if tumor_pct_m and tissue_fracs.get('tumor') is not None:
        tp = float(tumor_pct_m.group(1)) / 100
        bv = tissue_fracs['tumor']
        if scores_close(tp, bv, tol=0.02):
            return 'supported', f'Tumor fraction {tp:.2f} matches bundle {bv}'
        return 'partial' if scores_within_5pct(tp, bv) else 'unsupported', \
            f'Tumor fraction claimed={tp:.2f} vs bundle={bv}'

    # Stroma fraction
    stroma_pct_m = re.search(r'stroma\s*[=(:]?\s*(\d+\.?\d*)\s*%', claim_lower)
    if stroma_pct_m and tissue_fracs.get('stroma') is not None:
        sp = float(stroma_pct_m.group(1)) / 100
        bv = tissue_fracs['stroma']
        if scores_close(sp, bv, tol=0.02):
            return 'supported', f'Stroma fraction {sp:.2f} matches bundle {bv}'

    # TIL fraction / TIL density
    if re.search(r'\btil\b.*\b(high|dense|elevated|abundant)', claim_lower) or \
       re.search(r'(high|dense)\s+.*(til|tumor.infiltrat)', claim_lower):
        if til_fraction is not None:
            # til_fraction=0.07 is low, not high
            if til_fraction >= 0.15:
                return 'supported', f'Claims high TIL; bundle til_fraction={til_fraction} (high)'
            else:
                return 'unsupported', f'Claims high TIL but bundle til_fraction={til_fraction} (low)'

    # Top tile score claims
    tile_score_m = re.search(r'(?:top\s+tile|tile_183)[^.]*score[^.]*?(0\.\d+)', claim_lower)
    if tile_score_m and path_top_tile_score is not None:
        ttv = float(tile_score_m.group(1))
        if scores_close(ttv, path_top_tile_score, tol=0.01):
            return 'supported', f'Top tile score claimed={ttv} matches bundle={path_top_tile_score}'
    # "tile_183 scored 0.87" or "top tile, tile_183, scored 0.87"
    if re.search(r'tile_?183.*0\.87|0\.87.*tile_?183', claim_lower):
        if path_top_tile_score is not None and scores_close(path_top_tile_score, 0.87, tol=0.01):
            return 'supported', 'Top tile 183 scored 0.87 matches bundle'

    # =========================================================
    # RULE 11: TMB / mutation / gene claims
    # =========================================================
    if re.search(r'\btmb\b', claim_lower) and re.search(r'\b(high|low|intermediate|elevated|mut/mb|mutations/mb)', claim_lower):
        return 'unsupported', 'Claims TMB value/status but TMB not in bundle'

    mutation_patterns = [
        r'\b(EGFR|KRAS|ALK|ROS1|MET|BRAF|RET|NTRK|HER2|STK11|KEAP1|TP53)\b',
        r'\bL858R\b|\bexon\s+19\b|\bT790M\b|\bV600E\b',
        r'(C1|C2|C3|C4|C5|C6)\s+(subtype|immune\s+subtype)',
    ]
    if any(re.search(p, claim) for p in mutation_patterns):
        return 'unsupported', 'Claims specific mutation/gene/molecular subtype not in bundle'

    # Histology
    if re.search(r'(solid|acinar|lepidic|papillary|micropapillary)\s+(and\s+)?(growth\s+pattern|histology)', claim_lower) or \
       re.search(r'histology[:\s]+(solid|acinar|lepidic|papillary)', claim_lower):
        return 'unsupported', 'Claims histology subtype not in bundle'

    # PD-L1 IHC
    if re.search(r'pd[- ]?l1\s*(ihc|expression|tps|cps|%)', claim_lower):
        return 'unsupported', 'Claims PD-L1 IHC/expression data not in bundle'

    # MSI/TMB specific
    if re.search(r'\bmsi[- ]?(h|high|low|stable)\b|\bmicrosatellite', claim_lower):
        return 'unsupported', 'Claims MSI status not in bundle'

    # Neoantigen load
    if re.search(r'neoantigen\s+load', claim_lower):
        return 'unsupported', 'Claims neoantigen load not in bundle'

    # IFN-gamma / interferon signaling
    if re.search(r'(ifn[- ]?(gamma|γ)|interferon[- ]gamma)\s+signal', claim_lower):
        return 'unsupported', 'Claims IFN-gamma signaling data not in bundle'

    # Literature citations (PMID)
    if re.search(r'pmid[:\s]*\d+', claim_lower):
        return 'partial', 'Literature citation - not verifiable from bundle'

    # =========================================================
    # RULE 12: "No PD-L1, TMB, MSI" claims
    # =========================================================
    if re.search(r'no\s+(pd[- ]?l1|tmb|msi)', claim_lower) and \
       re.search(r'(provided|supplied|available|detected)', claim_lower):
        # These fields genuinely aren't in the bundle
        # But if it also says "no immune infiltration" that might be wrong (bundle has pathology)
        if re.search(r'no.*immune\s+infiltration', claim_lower):
            return 'partial', 'Correct that PD-L1/TMB/MSI absent but bundle does have pathology immune data'
        return 'supported', 'Claims PD-L1/TMB/MSI absent; these fields not in bundle'

    # =========================================================
    # RULE 13: Generic hedges / disclaimers / research caveats
    # =========================================================
    hedge_patterns = [
        r'cannot\s+(be\s+)?(reliably\s+)?(inferred|determined|assessed|established)',
        r'unable\s+to\s+(determine|assess|establish)',
        r'(insufficient|inadequate|limited)\s+(data|evidence|information)',
        r'requires?\s+additional\s+(data|testing|information)',
        r'no\s+conclusion.*can\s+be\s+made',
        r'cannot\s+be\s+determined',
        r'not\s+enough\s+(data|evidence|information)',
        r'lacks?\s+the\s+necessary',
    ]
    if any(re.search(p, claim_lower) for p in hedge_patterns):
        return 'partial', 'Generic hedge/uncertainty claim'

    disclaimer_patterns = [
        r'research[- ]only',
        r'not\s+for\s+clinical\s+(use|application)',
        r'should\s+not\s+be\s+used\s+for\s+clinical',
        r'tcga\s+data\s+represents\s+a\s+single\s+time\s+point',
        r'snapshot\s+limitation',
        r'tcga\s+records\s+provide\s+baseline',
        r'treatment[- ]naive\s+primary\s+surgical',
        r'actual\s+clinical\s+response.*not\s+recorded',
        r'does\s+not\s+imply\s+definitive\s+clinical',
        r'prior\s+to\s+clinical\s+application',
        r'retrospective\s+nature',
        r'hla\s+diversity|gut\s+microbiome',
        r'pembrolizumab|nivolumab|docetaxel',
        r'clinical\s+response\s+can\s+be\s+influenced',
        r'moderately\s+favorable\s+for\s+immunotherapy',
        r'early[- ]stage.*predictive\s+value',
    ]
    if any(re.search(p, claim_lower) for p in disclaimer_patterns):
        return 'partial', 'Disclaimer/research caveat - not fully verifiable from bundle'

    # =========================================================
    # RULE 14: "Limited pathology" / generic pathology claims
    # =========================================================
    if re.search(r'(structured\s+)?pathology.*(information\s+is\s+limited|markers\s+provided\s+here)', claim_lower):
        # Bundle has rich pathology data, so this is incorrect
        if pathology:
            return 'unsupported', 'Claims pathology information limited but bundle has pathology data'
        return 'supported', 'Claims pathology absent; bundle indeed lacks pathology'

    # =========================================================
    # RULE 15: "This is a research-only proxy" type claims
    # =========================================================
    if re.search(r'(research[- ]only\s+proxy|not\s+for\s+clinical)', claim_lower):
        return 'partial', 'Research-only disclaimer - partially verifiable'

    # =========================================================
    # RULE 16: "mutations/Mb" TMB claims (even without "tmb" keyword)
    # =========================================================
    if re.search(r'\d+\.?\d*\s*(mut(ations?)?)/mb\b', claim_lower):
        return 'unsupported', 'Claims mutations/Mb (TMB) value not in bundle'

    # =========================================================
    # RULE 17: Multi-fraction pathology summary claims
    # e.g. "Tumor 61%, stroma 24%, necrosis 8%"
    # =========================================================
    multi_frac = re.findall(r'(tumor|stroma|necrosis|lymphocyte)[^\d]*(\d+\.?\d*)\s*%', claim_lower)
    if multi_frac and tissue_fracs:
        errors = []
        for frac_name, frac_val in multi_frac:
            frac_val = float(frac_val) / 100
            key_map = {'tumor': 'tumor', 'stroma': 'stroma', 'necrosis': 'necrosis',
                       'lymphocyte': 'lymphocyte_rich'}
            bundle_key = key_map.get(frac_name)
            if bundle_key and bundle_key in tissue_fracs:
                bv = tissue_fracs[bundle_key]
                if not scores_close(frac_val, bv, tol=0.02):
                    errors.append(f'{frac_name} claimed={frac_val:.2f} vs bundle={bv}')
        if not errors:
            return 'supported', 'Tissue fractions match bundle'
        return 'partial', f'Most fractions match but: {"; ".join(errors)}'

    # =========================================================
    # RULE 18: "No structured pathology details provided here" (when bundle HAS pathology)
    # =========================================================
    if re.search(r'no\s+structured\s+pathology\s+details\s+provided', claim_lower):
        if pathology:
            return 'unsupported', 'Claims no structured pathology but bundle has pathology data'
        return 'supported', 'Claims no pathology; bundle lacks pathology'

    # =========================================================
    # RULE 19: "No documented PD-L1, TIL" - TIL IS in bundle
    # =========================================================
    if re.search(r'no\s+(documented|structured)\s+pd[- ]?l1.*til', claim_lower) or \
       re.search(r'no.*pd[- ]?l1.*til.*pathology', claim_lower):
        if til_fraction is not None:
            return 'partial', 'Correct that PD-L1 absent, but bundle does have TIL/pathology data'
        return 'supported', 'PD-L1 and TIL absent from bundle'

    # =========================================================
    # RULE 20: "Missing key inputs include ... tumor-infiltrating lymphocytes"
    # =========================================================
    if re.search(r'(missing|lacking)\s+(key\s+)?(inputs|data|information).*\btil\b', claim_lower) or \
       re.search(r'tumor[- ]infiltrating\s+lymphocytes.*missing', claim_lower):
        if til_fraction is not None:
            return 'partial', 'Claims TIL missing but bundle has til_fraction'
        return 'supported', 'Claims TIL missing; bundle lacks TIL'

    # =========================================================
    # RULE 21: RNA expression claims when no RNA available
    # =========================================================
    rna_expr_patterns = [
        r'(low|high|elevated|reduced)\s+expression\s+of\s+(cd8|pd[- ]?l1|cd274|ctla4)',
        r'checkpoint\s+expression[:\s]+(high|low|elevated)',
        r'mrna\s+(expression|levels)',
        r'(pd[- ]?l1|cd274|ctla4|pdcd1)\s+mrna',
        r'cd8\+?\s+(t[- ]cell|effector)\s+genes',
        r'pathway\s+activation.*ifn',
        r'ifn[- ]?gamma\s+(dominant|signaling|enrichment)',
        r'antigen\s+processing.*pathway',
        r'mhc\s+class',
    ]
    if any(re.search(p, claim_lower) for p in rna_expr_patterns):
        if not rna_available:
            return 'unsupported', 'Claims RNA expression/pathway data but rna_available=false'
        return 'partial', 'RNA expression claimed; need specific value check'

    # =========================================================
    # RULE 22: "Intermediate/moderately favorable" io tier claim
    # =========================================================
    if re.search(r'(intermediate|moderately\s+favorable|intermediate.*readiness)', claim_lower):
        if re.search(r'(io\s+(immune\s+)?tier|readiness)', claim_lower):
            tier_order = {'Cold': 0, 'Warm': 1, 'Hot': 2}
            # "Intermediate" ≈ Warm
            if io_tier == 'Warm':
                return 'supported', 'Claims intermediate/moderate tier; bundle=Warm'
            return 'partial', f'Claims intermediate tier but bundle={io_tier}'

    # =========================================================
    # RULE 23: "Primarily driven by pathology evidence" - check pathology vs clinical %
    # =========================================================
    if re.search(r'primarily\s+driven\s+by\s+pathology|pathology.*primary\s+driver', claim_lower):
        if path_contrib.get('contribution_percent') and clin_contrib.get('contribution_percent'):
            if path_contrib['contribution_percent'] > clin_contrib['contribution_percent']:
                return 'supported', f'Pathology ({path_contrib["contribution_percent"]:.1f}%) > clinical ({clin_contrib["contribution_percent"]:.1f}%)'
            return 'unsupported', f'Pathology ({path_contrib["contribution_percent"]:.1f}%) not primary over clinical ({clin_contrib["contribution_percent"]:.1f}%)'

    # =========================================================
    # RULE 24: Specific TIL claims with low density
    # =========================================================
    if re.search(r'(dense\s+tumor[- ]infiltrating\s+lymphocyte|til[- ]rich\s+pathology)', claim_lower):
        if til_fraction is not None:
            if til_fraction >= 0.15:
                return 'supported', f'Claims dense TIL; bundle til_fraction={til_fraction}'
            return 'unsupported', f'Claims dense TIL but bundle til_fraction={til_fraction} (low)'

    # =========================================================
    # RULE 25: Generic "may provide benefits" / prediction claims
    # =========================================================
    if re.search(r'(may\s+provide|suggest(s)?\s+that\s+immunotherapy|survival\s+benefit|checkpoint\s+blockade\s+if)', claim_lower):
        return 'partial', 'Subjective prediction/implication claim'

    # =========================================================
    # RULE 26: Treatment-related missing data claims
    # =========================================================
    if re.search(r'no\s+(treatment\s+history|metastatic\s+status|prior\s+immunotherapy)', claim_lower):
        # These fields are not in the bundle → supported
        return 'supported', 'Claims treatment/metastatic/immunotherapy data absent; not in bundle'

    # =========================================================
    # RULE 27: Literature context claims (without PMID - already handled with PMID)
    # =========================================================
    if re.search(r'(literature\s+(context|suggest|review)|in\s+hcc\b|hepatocellular\s+carcinoma|adoptive\s+cell\s+therapy|til[- ]based)', claim_lower):
        return 'partial', 'Literature context claim - not verifiable from bundle'

    # =========================================================
    # RULE 28: "No clinical source/survival fields"
    # =========================================================
    if re.search(r'no\s+(clinical\s+source|survival\s+follow[- ]up)', claim_lower):
        return 'partial', 'Claims clinical source/survival absent - partially verifiable'

    # =========================================================
    # RULE 29: "This case is primarily driven by pathology evidence, with no transcriptomic data"
    # =========================================================
    if re.search(r'primarily\s+driven\s+by\s+pathology.*no\s+transcriptomic', claim_lower):
        if not rna_available and path_contrib.get('contribution_percent', 0) > clin_contrib.get('contribution_percent', 0):
            return 'supported', 'Pathology dominant, transcriptomics absent - both correct'
        return 'partial', 'Mixed correctness for pathology-driven + no transcriptomics claim'

    # =========================================================
    # RULE 30: "Missing key inputs include TIL/immune infiltrates" - bundle has pathology
    # =========================================================
    if re.search(r'(missing|lacking)\s+(key\s+)?(inputs|data|biomarkers).*\b(til|immune\s+infiltrat|tumor\s+immune\s+infiltrat)', claim_lower):
        if pathology:
            return 'partial', 'Claims TIL/immune infiltration missing but bundle has pathology data'
        return 'supported', 'Claims biomarkers missing; bundle lacks them'

    # =========================================================
    # RULE 31: LUAD / Lung Adenocarcinoma diagnosis claim
    # =========================================================
    if re.search(r'lung\s+adenocarcinoma\s+\(luad\)', claim_lower) and \
       re.search(r'(key\s+pathology|diagnosis)[:\s]', claim_lower):
        # This is a diagnosis claim that's correct for TCGA-LUAD
        case_id = bundle.get('case_id', '')
        if 'LUAD' in case_id or 'TCGA' in case_id:
            return 'supported', 'LUAD diagnosis consistent with TCGA-LUAD case'
        return 'partial', 'LUAD diagnosis not explicitly in bundle'

    # =========================================================
    # RULE 32: "Structured pathology evidence is limited to diagnosis of LUAD"
    # =========================================================
    if re.search(r'structured\s+pathology\s+evidence\s+is\s+limited\s+to\s+the\s+diagnosis', claim_lower):
        if pathology and (tissue_fracs or top_tiles):
            return 'unsupported', 'Claims pathology limited to diagnosis but bundle has detailed pathology'
        return 'supported', 'Claims pathology limited; bundle indeed lacks detailed pathology'

    # =========================================================
    # RULE 33: "Lack of transcriptomics" / "not RNA-informed"
    # =========================================================
    if re.search(r'lack\s+of\s+transcriptomics|not\s+rna[- ]informed', claim_lower):
        if not rna_available:
            return 'supported', 'Claims no RNA data; rna_available=false confirmed'
        return 'unsupported', 'Claims no RNA but rna_available=true'

    # =========================================================
    # RULE 34: "Fusion remains provisional with no transcriptomic contribution"
    # =========================================================
    if re.search(r'fusion\s+remains\s+provisional.*no\s+transcriptomic', claim_lower) or \
       re.search(r'no\s+transcriptomic\s+contribution\s+detected', claim_lower):
        if fusion_mode == 'provisional' and not rna_available:
            return 'supported', 'Fusion provisional with no transcriptomic contribution - both correct'
        return 'partial', 'Partially matches fusion mode/transcriptomics'

    # =========================================================
    # RULE 35: "No structured pathology markers of immune responsiveness (PD-L1, TILs)"
    # =========================================================
    if re.search(r'no\s+structured\s+pathology\s+markers', claim_lower):
        if til_fraction is not None or top_tiles:
            return 'partial', 'Correct PD-L1/MSI absent but bundle does have TIL/tile pathology data'
        return 'supported', 'Claims no pathology markers; bundle indeed lacks them'

    # =========================================================
    # RULE 36: "IO readiness is predictive of potential response in recurrence scenario"
    # =========================================================
    if re.search(r'io\s+readiness.*predictive.*recurrence|recurrence\s+scenario', claim_lower):
        return 'partial', 'Interpretive claim about recurrence context - not verifiable from bundle'

    # =========================================================
    # RULE 37: CIBERSORT / cell deconvolution claims
    # =========================================================
    if re.search(r'(cibersort|deconvolution|bulk\s+rna[- ]seq)', claim_lower):
        if not rna_available:
            return 'unsupported', 'Claims CIBERSORT/deconvolution but rna_available=false'
        return 'partial', 'Deconvolution claim; need value check'

    # =========================================================
    # RULE 38: Toxicity/clinical trial data claims
    # =========================================================
    if re.search(r'(grade\s+\d|toxicity|adverse\s+events?|complete\s+response\s+rate)', claim_lower):
        return 'partial', 'Clinical trial/toxicity claim - not verifiable from bundle'

    # =========================================================
    # RULE 39: Spatial heterogeneity / bulk RNA-seq methodology
    # =========================================================
    if re.search(r'spatial\s+(heterogeneity|distribution)|bulk\s+rna[- ]seq\s+(does\s+not|cannot)', claim_lower):
        return 'partial', 'Methodology caveat - not verifiable from bundle'

    # =========================================================
    # RULE 40: "No clinical source/follow-up survival fields available"
    # =========================================================
    if re.search(r'no\s+(direct\s+)?clinical\s+(source|follow[- ]up\s+survival)', claim_lower):
        return 'partial', 'Claims clinical source/survival absent - partially verifiable'

    # =========================================================
    # RULE 41: General "missing data" claims about immune infiltration
    # =========================================================
    if re.search(r'missing\s+(data|information)\s+on.*\b(immune\s+infiltrat|pd[- ]?l1)', claim_lower):
        if pathology:
            return 'partial', 'Claims immune infiltration data missing but bundle has pathology'
        return 'supported', 'Claims immune data missing; bundle lacks it'

    # =========================================================
    # RULE 42: "Missing key inputs include PD-L1, TIL, TMB/MSI"
    # =========================================================
    if re.search(r'missing\s+key\s+(inputs|biomarkers|data)', claim_lower):
        if pathology and til_fraction is not None:
            return 'partial', 'Claims key inputs (TIL) missing but bundle has pathology/TIL data'
        return 'supported', 'Claims key inputs missing; confirmed absent in bundle'

    # =========================================================
    # RULE 43: Generic benefit/implication claims
    # =========================================================
    if re.search(r'(highlight\s+the\s+potential|benefits\s+of\s+immunotherapy|similar\s+patient\s+populations)', claim_lower):
        return 'partial', 'Generic benefit/implication claim not verifiable from bundle'

    # =========================================================
    # FALLBACK
    # =========================================================
    return 'partial', 'Claim type not matched by rules; conservative partial assignment'


def main():
    input_path = '/Users/ishangonehal/Downloads/yc-aixbio-hackathon-main/adjudication_input.csv'
    output_path = '/Users/ishangonehal/Downloads/yc-aixbio-hackathon-main/adjudication_output.csv'

    with open(input_path) as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
        rows = list(reader)

    results = []
    label_counts = {'supported': 0, 'partial': 0, 'unsupported': 0}

    for i, row in enumerate(rows):
        bundle = parse_bundle(row['bundle_excerpt'])
        label, note = adjudicate(row['claim'], bundle)
        row['human_label'] = label
        row['human_notes'] = note
        results.append(row)
        label_counts[label] += 1
        if (i + 1) % 50 == 0:
            print(f'Processed {i+1}/300 rows...')

    with open(output_path, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(results)

    print(f'\nDone! Label distribution:')
    for k, v in label_counts.items():
        print(f'  {k}: {v}')
    print(f'\nOutput written to: {output_path}')

    # Show fallback count
    fallbacks = [r for r in results if 'not matched by rules' in r['human_notes']]
    print(f'Fallback partials: {len(fallbacks)}')


if __name__ == '__main__':
    main()
