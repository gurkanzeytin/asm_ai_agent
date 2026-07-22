"""Merkezî Türkçe sunum katmanı (AI-INTELLIGENCE-011).

Teknik metric ID'leri ve ham sayılar kullanıcıya asla doğrudan gösterilmez.
Tüm Türkçe etiketler ve sayı biçimleri bu modülden gelir: backend rapor
şablonları, result reasoning ve API sunumu tek sözlüğü paylaşır.
"""

from numbers import Number

# Teknik alias -> kullanıcıya görünen Türkçe etiket. Frontend'deki
# locales/tr.ts metrik sözlüğü ile eş tutulmalıdır.
METRIC_LABELS_TR: dict[str, str] = {
    "appointment_count": "Randevu Sayısı",
    "cohort_total_count": "Son Dakika Randevusu",
    "completed_count": "Gerçekleşen Randevu",
    "completed_rate": "Gerçekleşme Oranı",
    "checked_in_count": "Giriş Yapılmış Randevu",
    "checked_in_rate": "Giriş Yapılma Oranı",
    "no_show_count": "Gelmeyen Randevu",
    "no_show_rate": "Gelmeme Oranı",
    "in_progress_count": "İşlemi Süren Randevu",
    "in_progress_rate": "İşlemde Olanların Oranı",
    "waiting_count": "Bekleyen Randevu",
    "waiting_rate": "Bekleme Oranı",
    "current_period_count": "Mevcut Dönem Randevu Sayısı",
    "baseline_period_count": "Önceki Dönem Randevu Sayısı",
    "absolute_change": "Sayısal Değişim",
    "percentage_change": "Yüzdesel Değişim",
    "rate_point_change": "Oran Farkı",
    "unique_patient_count": "Tekil Hasta Sayısı",
    "group_count": "Grup Sayısı",
    "total_appointments": "Toplam Randevu",
    "average_appointments": "Ortalama Randevu",
    "minimum_appointments": "En Düşük Randevu",
    "maximum_appointments": "En Yüksek Randevu",
    "max_to_average_ratio": "En Yüksek / Ortalama Oranı",
    "top_10_percent_share": "İlk %10 Grubun Payı",
    "current_rate": "Mevcut Dönem Oranı",
    "baseline_rate": "Önceki Dönem Oranı",
}

# Doğrulanmış RandevuDurumu değerleri -> okunur Türkçe durum adı.
STATUS_LABELS_TR: dict[str, str] = {
    "completed": "Gerçekleşti",
    "checked_in": "Giriş Yapılmış",
    "no_show": "Gelmedi",
    "in_progress": "İşlem Sürmekte",
    "waiting": "Beklemede",
}


def label_for(metric_id: str) -> str:
    """Metric/alias için Türkçe etiket; bilinmeyen id okunur hale getirilir."""
    if metric_id in METRIC_LABELS_TR:
        return METRIC_LABELS_TR[metric_id]
    return metric_id.replace("_", " ").strip().title()


def format_number(value: Number | None) -> str:
    """Tam sayıları Türkçe binlik ayraçla biçimler: 678866 -> '678.866'."""
    if value is None or isinstance(value, bool) or not isinstance(value, Number):
        return "—"
    number = float(value)
    if number == int(number):
        return f"{int(number):,}".replace(",", ".")
    # Ondalıklı büyük sayı: binlik nokta + ondalık virgül
    whole, frac = f"{number:,.1f}".split(".")
    return whole.replace(",", ".") + "," + frac


def format_percent(value: Number | None, decimals: int = 1) -> str:
    """Yüzdeleri Türkçe biçimler: 73.409332 -> '%73,4'."""
    if value is None or isinstance(value, bool) or not isinstance(value, Number):
        return "—"
    formatted = f"{float(value):.{decimals}f}".replace(".", ",")
    return f"%{formatted}"


def format_value(metric_id: str, value: Number | None) -> str:
    """Alias adına göre doğru Türkçe biçimi seçer (oran mı sayı mı)."""
    lowered = metric_id.lower()
    if (
        lowered.endswith(("_rate", "_percentage", "_share", "_ratio"))
        or lowered in ("percentage_change", "rate_point_change")
        or "oran" in lowered
        or "yuzde" in lowered
    ):
        return format_percent(value)
    return format_number(value)
