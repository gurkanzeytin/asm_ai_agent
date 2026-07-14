"""Domain ontology for semantic understanding (REASONING-001).

Static, deterministic knowledge about the hospital domain: which entity
types exist, how they relate semantically (not as SQL joins), and which
wording maps to which user goal. Extend here — never in the engine logic.
"""

from app.semantics.models import SemanticRelationship

# Semantic relationships between entity types. Direction reads naturally:
# subject --predicate--> object.
RELATIONSHIPS: list[SemanticRelationship] = [
    SemanticRelationship(subject="Doctor", predicate="works_in", object="Department"),
    SemanticRelationship(subject="Appointment", predicate="belongs_to", object="Doctor"),
    SemanticRelationship(subject="Patient", predicate="has", object="Appointment"),
    SemanticRelationship(subject="Prescription", predicate="written_by", object="Doctor"),
    SemanticRelationship(subject="Patient", predicate="has", object="Prescription"),
    SemanticRelationship(subject="Diagnosis", predicate="assigned_to", object="Patient"),
    SemanticRelationship(subject="Invoice", predicate="billed_to", object="Patient"),
    SemanticRelationship(subject="LaboratoryTest", predicate="performed_for", object="Patient"),
    SemanticRelationship(subject="Hospitalization", predicate="of", object="Patient"),
    SemanticRelationship(subject="Appointment", predicate="scheduled_in", object="Department"),
]


def relationships_between(subjects: set[str]) -> list[SemanticRelationship]:
    """Returns every known relationship whose both ends are among the subjects."""
    return [
        relation
        for relation in RELATIONSHIPS
        if relation.subject in subjects and relation.object in subjects
    ]


# Goal vocabulary on folded (diacritic-free, lowercase) text. Order matters:
# more specific goals are checked before generic listing verbs.
GOAL_MARKERS: list[tuple[str, tuple[str, ...]]] = [
    ("COMPARE", ("karsilastir", "kiyasla", "farki", "gore dagilim")),
    ("TREND", ("trend", "egilim", "degisim", "aylara gore", "gunlere gore", "zaman icinde")),
    ("ANALYZE", ("analiz", "incele", "degerlendir")),
    ("SUMMARIZE", ("ozet", "ozetle")),
    ("RANK", ("en yogun", "en cok", "en fazla", "en az", "en yuksek", "en dusuk", "siralamasi", "sirala")),
    ("AGGREGATE", ("toplam", "ortalama")),
    ("COUNT", ("kac", "sayisi", "sayi", "adet")),
    ("FIND", ("bul", "hangi", "kim")),
    ("LIST", ("goster", "listele", "getir", "goruntule", "liste", "cikar", "ver")),
]

# Ambiguous phrases with the reason no deterministic metric exists for them.
AMBIGUOUS_PHRASES: dict[str, str] = {
    "en iyi": "'iyi' has no measurable metric: appointment volume, patient satisfaction, and revenue are all plausible.",
    "en basarili": "'basarili' has no measurable metric in the schema; success is not a stored value.",
    "en kotu": "'kotu' has no measurable metric: could mean fewest appointments, worst satisfaction, or most complaints.",
    "en verimli": "'verimli' has no measurable metric: efficiency is not a stored value.",
    "performans": "'performans' is not a stored metric: appointment count, satisfaction score, and revenue are all plausible readings.",
}

# Existence-question markers ("... var mı?").
EXISTENCE_MARKERS = ("var mi", "var midir", "mevcut mu", "bulunuyor mu")

# Requested-output rendering per primary subject for list-style goals.
SUBJECT_OUTPUT_NAMES: dict[str, str] = {
    "Doctor": "doctor_names",
    "Department": "department_names",
    "Patient": "patient_names",
    "Appointment": "appointment_list",
    "Prescription": "prescription_list",
    "Diagnosis": "diagnosis_list",
    "Invoice": "invoice_list",
    "LaboratoryTest": "laboratory_test_list",
    "Hospitalization": "hospitalization_list",
}
