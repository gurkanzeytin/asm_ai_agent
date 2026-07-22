"""Deterministic observation wordings — Türkçe.

Nötr, kanıt temelli ifadeler. Asla operasyonel öneri içermez: "dikkat çekebilir"
/ "not edilmelidir" tarzı dil kullanılır, asla "zorunlu" / "gerekli" değil. Bu
şablonlar gerçeklerin tek kaynağıdır; LLM yalnızca yeniden ifade edebilir.
"""

# Rule-based wordings keyed by insight rule name. {placeholders} are filled
# from analytics metrics.
RULE_WORDINGS: dict[str, str] = {
    "DOMINANT_CATEGORY": (
        "Bir kategori belirgin biçimde öne çıkıyor: '{top_category}' en büyük payı oluşturuyor."
    ),
    "BALANCED_DISTRIBUTION": "Kategoriler arasında belirgin bir dengesizlik tespit edilmedi.",
    "OUTLIER_DETECTED": (
        "'{top_category}' bu sonuçtaki diğer kategorilerden belirgin biçimde yüksek, "
        "bu kontrol için kullanılan baskınlık eşiğinin üzerinde."
    ),
    "SINGLE_METRIC": "Sonuç, {total} değerine sahip tek bir metrik.",
    "INSUFFICIENT_EVIDENCE": "Sonuç kümesi, yorum üretmek için yeterli veri içermiyor.",
    "CONSISTENT_UPWARD_TREND": (
        "Dönem genelinde ve uç dönemler arasında tutarlı bir yükseliş görülmektedir."
    ),
    "CONSISTENT_DOWNWARD_TREND": (
        "Dönem genelinde ve uç dönemler arasında tutarlı bir düşüş görülmektedir."
    ),
    # AI-INTELLIGENCE-018 (item 7/8): non-monotonic ("mixed_or_fluctuating")
    # never gets "consistent"/continuous-growth language — states the
    # dalgalanma explicitly and the overall endpoint direction plainly.
    "MIXED_TREND_SIGNAL": (
        "Dalgalanmalara rağmen dönem başından dönem sonuna genel yön "
        "{endpoint_direction_adjective_tr}dır."
    ),
    "FLAT_TREND": "Değerler dönem boyunca büyük ölçüde yatay seyretmiştir.",
    "INSUFFICIENT_COMPLETE_PERIODS": (
        "Eğilim hesaplamak için yeterli sayıda tamamlanmış dönem bulunmuyor."
    ),
    "PARTIAL_PERIOD_EXCLUDED": (
        "Son dönem henüz tamamlanmadığı için eğilim hesabında tam dönemlerle "
        "birlikte değerlendirilmemiştir."
    ),
    "SINGLE_CATEGORY_COMPARISON": (
        "Seçilen kapsamda yalnızca bir kategori bulunduğu için kategoriler arası "
        "karşılaştırma yapılamadı; mevcut kategori özetlenmiştir."
    ),
}

# Metric-derived wordings (fire independently of rules when evidence exists).
TOP_CATEGORY_WORDING = "'{top_category}' bu sonuçtaki en yüksek hacme sahip."
LARGEST_CHANGE_WORDING = "En büyük değişim {largest_change} döneminde gerçekleşti."
SIGNIFICANT_SPREAD_WORDING = (
    "En yüksek ({highest_value}) ve en düşük ({lowest_value}) değerler arasındaki "
    "fark, bu sonucun ölçeğine göre büyük ve dikkat çekebilir."
)

# Modal/imperative words that must never appear in observation wording. Also
# guards against the optional LLM reword step (OBSERVATION_LLM_WORDING)
# injecting a "önemli ölçüde"/"anomali" claim that no deterministic threshold
# backs — only the templates above may use such wording, and only when a rule
# explicitly required a threshold to fire.
FORBIDDEN_WORDING_PATTERNS = (
    "zorunlu",
    "gerekli",
    "gerekiyor",
    "yapmalı",
    "yapılmalı",
    "önermek",
    "öneririz",
    "tavsiye ederiz",
    "önemli ölçüde",
    "anomali",
    "anormallik",
    "kesinlikle",
    "kesin nedeni",
    "kanıtlanmıştır",
    "şüphesiz",
)
