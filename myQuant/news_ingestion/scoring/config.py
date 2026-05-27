# ── RelationType weights (v0.22 mapping: spec → actual DB values) ──
RELATION_WEIGHT = {
    "direct_company": 1.00,
    "supply_chain": 0.75,
    "industry": 0.60,
    "macro_policy": 0.60,   # merged from spec "macro"(0.45) + "policy"(0.70) → compromise
    "market_sentiment": 0.40,
    "risk_event": 0.75,      # mapped from spec "regulation"(0.75)
    "unknown": 0.50,         # mapped from spec "other"(0.50)
}
DEFAULT_RELATION_WEIGHT = 0.50

# ── Time horizon weights ──
HORIZON_WEIGHT = {
    "intraday": 0.50,
    "short": 1.00,
    "medium": 0.75,
    "long": 0.45,
}
DEFAULT_HORIZON_WEIGHT = 0.60

# ── Scoring nonlinear params ──
STRENGTH_EXPONENT = 1.2
CONFIDENCE_FLOOR = 0.45
CONFIDENCE_SCALE = 0.55

# ── Ensemble params ──
ENSEMBLE_AGREEMENT_BASE = 0.5
ENSEMBLE_AGREEMENT_WEIGHT = 0.5

# ── Event dedup stopwords ──
EVENT_STOPWORDS = ["公告", "表示", "称", "公司", "相关", "影响", "消息", "新闻"]

# ── Daily aggregation ──
DAILY_TEMPERATURE = 0.8
MIXED_PENALTY_COEFF = 0.3

# ── Direction thresholds ──
POSITIVE_THRESHOLD = 0.25
NEGATIVE_THRESHOLD = -0.25

# ── Version tracking ──
CONFIG_VERSION = "v0.22"
AGGREGATION_VERSION = "v0.22"
RELATION_WEIGHT_VERSION = "v0.22"
HORIZON_WEIGHT_VERSION = "v0.22"
EVENT_DEDUP_VERSION = "v0.22"
CONFIG_MAPPING_NOTES = (
    "relation_type mapping: spec competitor→removed, "
    "macro+policy→macro_policy(0.60 compromise), "
    "regulation→risk_event(0.75), other→unknown(0.50)"
)
