"""Family/model split for brands with model families (BMW, Mercedes, Audi).

BMW: "5 Series" + complectation "530Li M Sport" -> family="5 Series", model="530Li"
Mercedes: "C-Class" + complectation "C 260 L Sport" -> family="C-Class", model="C260"
Audi (китайская L-нотация): "A6L" + "55 TFSI quattro" -> family="A6L", model="A6L 55 TFSI"
"""

import re

# Серия/семейство выглядит так
FAMILY_RE = re.compile(
    r'^('
    r'\d+\s*Series.*'                         # 5 Series / 5 Series New Energy
    r'|[A-Z]{1,3}[- ]Class.*'                 # C-Class / GLC-Class / V-Class
    r')$', re.IGNORECASE)

# Конкретные модели внутри семейств
BMW_MODEL_RE = re.compile(r'\b(M[2-8]\d{0,2}[A-Za-z]*|[1-8]\d{2}[A-Za-z]*)\b')
MB_MODEL_RE = re.compile(r'\b([A-Z]{1,4})\s?(\d{2,3}[A-Za-z]*)\b')


def split_family_model(brand: str, model: str,
                       complectation: str) -> tuple[str | None, str, str]:
    """If model looks like a family, extract specific submodel from complectation.

    Returns (family, model, complectation).
    `family` is None when model is not a family (X5, Q6, etc).
    """
    if not model or not FAMILY_RE.match(model):
        return None, model, complectation or ""

    family = model
    new_model = model  # fallback
    comp = complectation or ""

    if brand == "BMW":
        m = BMW_MODEL_RE.search(comp)
        if m:
            new_model = m.group(1)
    elif brand == "Mercedes-Benz":
        m = MB_MODEL_RE.search(comp)
        if m:
            new_model = m.group(1) + m.group(2)

    return family, new_model, comp
