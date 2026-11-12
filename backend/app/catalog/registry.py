"""
Business-category and storefront-template registries.

Both are plain data so new categories/templates are added here (plus a
template file under app/templates/storefront/) without touching the
onboarding flow, API or frontend — the frontend renders whatever
GET /api/qr/meta returns. The AI category prompt is generated from
CATEGORIES too, so a new entry is immediately detectable.
"""
from dataclasses import asdict, dataclass, field


@dataclass(frozen=True)
class BusinessCategory:
    key: str
    label: str
    description: str
    icon: str                    # emoji used in cards / placeholders
    item_noun: str               # "dish", "product", "vehicle" ...
    catalogue_noun: str          # "Menu", "Catalogue", "Collection" ...
    templates: tuple[str, ...]   # recommended template keys, best first
    placeholder: str             # placeholder art key (app/templates/storefront/placeholders)
    ai_hints: str                # cues for the category classifier
    supports_diet_labels: bool = False
    supports_split_bill: bool = False   # food businesses: customers can split the bill on WhatsApp
    supports_delivery_links: bool = False  # food businesses: Zomato / Swiggy order links


CATEGORIES: tuple[BusinessCategory, ...] = (
    BusinessCategory(
        key="restaurant", label="Restaurant, café & bakery",
        description="Restaurants, cafés, bakeries, sweet shops, cloud kitchens and food outlets.",
        icon="🍽️", item_noun="dish", catalogue_noun="Menu",
        templates=("menu-classic", "cafe-cards", "retail-grid"), placeholder="food",
        ai_hints="food or drink items, dishes, menu sections like starters/mains/beverages, veg/non-veg marks",
        supports_diet_labels=True, supports_split_bill=True, supports_delivery_links=True,
    ),
    BusinessCategory(
        key="wedding", label="Wedding collection & jewellery",
        description="Bridal wear, wedding collections, sherwanis, jewellery and accessories.",
        icon="💍", item_noun="piece", catalogue_noun="Collection",
        templates=("boutique-elegant", "retail-grid"), placeholder="jewellery",
        ai_hints="bridal lehengas, sarees, sherwanis, jewellery sets, gold/silver, wedding collection",
    ),
    BusinessCategory(
        key="automobile", label="Automobile & vehicle services",
        description="Showrooms, used cars and bikes, accessories, spare parts and vehicle servicing.",
        icon="🚗", item_noun="vehicle", catalogue_noun="Catalogue",
        templates=("auto-showroom", "retail-grid"), placeholder="vehicle",
        ai_hints="cars, bikes, scooters, spare parts, tyres, accessories, service packages, mileage/engine specs",
    ),
    BusinessCategory(
        key="retail", label="Retail & general store",
        description="General merchandise, gift shops, stationery, hardware and variety stores.",
        icon="🛍️", item_noun="product", catalogue_noun="Catalogue",
        templates=("retail-grid", "boutique-elegant"), placeholder="product",
        ai_hints="assorted general merchandise, household items, gifts, stationery, hardware",
    ),
    BusinessCategory(
        key="grocery", label="Grocery & supermarket",
        description="Kirana stores, supermarkets, fruits and vegetables, dairy and staples.",
        icon="🛒", item_noun="product", catalogue_noun="Price list",
        templates=("retail-grid", "menu-classic"), placeholder="grocery",
        ai_hints="staples, rice, dal, oil, packaged foods, fruits, vegetables, per-kg / per-litre prices",
    ),
    BusinessCategory(
        key="fashion", label="Fashion, clothing & footwear",
        description="Apparel, ethnic wear, footwear, bags and fashion accessories.",
        icon="👗", item_noun="product", catalogue_noun="Collection",
        templates=("boutique-elegant", "retail-grid"), placeholder="fashion",
        ai_hints="shirts, kurtas, dresses, jeans, shoes, sizes S/M/L, fabrics",
    ),
    BusinessCategory(
        key="electronics", label="Electronics & home appliances",
        description="Mobiles, laptops, TVs, appliances, repairs and accessories.",
        icon="📱", item_noun="product", catalogue_noun="Catalogue",
        templates=("auto-showroom", "retail-grid"), placeholder="electronics",
        ai_hints="phones, laptops, TVs, refrigerators, washing machines, model numbers, warranty",
    ),
    BusinessCategory(
        key="beauty", label="Beauty, cosmetics & personal care",
        description="Salons, spas, cosmetics and personal-care products and services.",
        icon="💄", item_noun="service", catalogue_noun="Menu",
        templates=("boutique-elegant", "cafe-cards", "retail-grid"), placeholder="beauty",
        ai_hints="haircut, facial, makeup, skincare products, salon or spa service menu",
    ),
    BusinessCategory(
        key="other", label="Other business or service",
        description="Any other retail or service business.",
        icon="🏪", item_noun="item", catalogue_noun="Catalogue",
        templates=("retail-grid", "menu-classic", "boutique-elegant", "cafe-cards", "auto-showroom"),
        placeholder="product",
        ai_hints="anything that does not clearly fit the other categories",
    ),
)


@dataclass(frozen=True)
class StoreTemplate:
    key: str
    name: str
    description: str
    file: str                      # Jinja template under app/templates/storefront/
    best_for: tuple[str, ...]      # category keys
    defaults: dict = field(default_factory=dict)  # default branding for this template
    highlights: tuple[str, ...] = ()


TEMPLATES: tuple[StoreTemplate, ...] = (
    StoreTemplate(
        key="menu-classic", name="Menu Classic",
        description="A printed-menu feel: sticky section tabs, tidy rows with prices on the right and veg/non-veg marks.",
        file="menu_classic.html.j2", best_for=("restaurant", "grocery"),
        defaults={"primary": "#b4441b", "secondary": "#f2b84b", "background": "#fffaf3", "text": "#2b1d14", "font": "Lora"},
        highlights=("Sticky category tabs", "Veg / non-veg indicators", "Compact price rows"),
    ),
    StoreTemplate(
        key="cafe-cards", name="Café Cards",
        description="Photo-first rounded cards in a two-column grid, ideal for cafés, bakeries and salons.",
        file="cafe_cards.html.j2", best_for=("restaurant", "beauty"),
        defaults={"primary": "#7a4b35", "secondary": "#e9c9a8", "background": "#fbf6f1", "text": "#2e221b", "font": "Nunito"},
        highlights=("Large food photography", "Popular picks first", "Soft, friendly styling"),
    ),
    StoreTemplate(
        key="boutique-elegant", name="Boutique Elegant",
        description="Refined serif typography and tall image cards for bridal, fashion and jewellery collections.",
        file="boutique_elegant.html.j2", best_for=("wedding", "fashion", "beauty"),
        defaults={"primary": "#7b1e3a", "secondary": "#c9a14a", "background": "#fdf9f4", "text": "#2a1a1f", "font": "Playfair Display"},
        highlights=("Collection headers", "Tall portrait product cards", "Gold accent details"),
    ),
    StoreTemplate(
        key="auto-showroom", name="Auto Showroom",
        description="Bold, wide cards with spec chips and a prominent contact strip for vehicles and electronics.",
        file="auto_showroom.html.j2", best_for=("automobile", "electronics"),
        defaults={"primary": "#d62828", "secondary": "#1d3557", "background": "#f4f5f7", "text": "#111827", "font": "Montserrat"},
        highlights=("Wide landscape cards", "Spec / option chips", "Call + WhatsApp contact strip"),
    ),
    StoreTemplate(
        key="retail-grid", name="Retail Grid",
        description="A flexible product grid with search and category filter chips — works for any shop.",
        file="retail_grid.html.j2", best_for=("retail", "grocery", "fashion", "electronics", "other"),
        defaults={"primary": "#1f6feb", "secondary": "#10b981", "background": "#f8fafc", "text": "#0f172a", "font": "Inter"},
        highlights=("Search + filter chips", "Dense product grid", "Cart-first enquiries"),
    ),
)

# Controlled font set: name -> Google Fonts family spec + CSS fallback stack.
FONTS: dict[str, tuple[str, str]] = {
    "Inter": ("Inter:wght@400;600;700", "'Inter', system-ui, sans-serif"),
    "Poppins": ("Poppins:wght@400;600;700", "'Poppins', system-ui, sans-serif"),
    "Montserrat": ("Montserrat:wght@400;600;700", "'Montserrat', system-ui, sans-serif"),
    "Nunito": ("Nunito:wght@400;600;700", "'Nunito', system-ui, sans-serif"),
    "Lora": ("Lora:wght@400;600;700", "'Lora', Georgia, serif"),
    "Playfair Display": ("Playfair+Display:wght@400;600;700", "'Playfair Display', Georgia, serif"),
    "Merriweather": ("Merriweather:wght@400;700", "'Merriweather', Georgia, serif"),
}

ITEM_LABELS: dict[str, str] = {
    "veg": "Veg", "non_veg": "Non-veg", "egg": "Contains egg", "vegan": "Vegan", "jain": "Jain",
    "spicy": "Spicy", "gluten_free": "Gluten-free", "bestseller": "Bestseller", "new": "New",
}

CATEGORY_BY_KEY = {c.key: c for c in CATEGORIES}
TEMPLATE_BY_KEY = {t.key: t for t in TEMPLATES}


def get_category(key: str | None) -> BusinessCategory:
    return CATEGORY_BY_KEY.get(key or "", CATEGORY_BY_KEY["other"])


def templates_for(category_key: str | None) -> list[StoreTemplate]:
    """All templates, the category's recommended ones first (in its order)."""
    recommended = get_category(category_key).templates
    ordered = [TEMPLATE_BY_KEY[k] for k in recommended if k in TEMPLATE_BY_KEY]
    return ordered + [t for t in TEMPLATES if t.key not in recommended]


def meta_payload() -> dict:
    return {
        "categories": [asdict(c) for c in CATEGORIES],
        "templates": [{k: v for k, v in asdict(t).items() if k != "file"} for t in TEMPLATES],
        "fonts": list(FONTS.keys()),
        "item_labels": ITEM_LABELS,
    }
