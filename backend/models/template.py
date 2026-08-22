from backend.extensions import db

class Template(db.Model):
    """
    Static catalogue of available resume templates.
    """
    __tablename__ = "templates"

    id          = db.Column(db.Integer, primary_key=True)
    slug        = db.Column(db.String(50), unique=True, nullable=False)  # "template1"
    name        = db.Column(db.String(80), nullable=False)               # "Executive"
    tag         = db.Column(db.String(50))                               # "Professional"
    preview_img = db.Column(db.String(120))                              # "templateA.webp"
    is_active   = db.Column(db.Boolean, default=True)
    sort_order  = db.Column(db.Integer, default=0)

    def to_dict(self) -> dict:
        return {
            "id":          self.id,
            "slug":        self.slug,
            "name":        self.name,
            "tag":         self.tag,
            "preview_img": self.preview_img,
        }

    def __repr__(self):
        return f"<Template slug={self.slug!r}>"


TEMPLATE_SEED = [
    {"slug": "template1", "name": "Executive",    "tag": "Professional", "preview_img": "templateA.webp", "sort_order": 1},
    {"slug": "template2", "name": "Modern",       "tag": "Trendy",       "preview_img": "templateB.webp", "sort_order": 2},
    {"slug": "template3", "name": "Creative",     "tag": "Expressive",   "preview_img": "templateC.webp", "sort_order": 3},
    {"slug": "template4", "name": "Minimalist",   "tag": "Clean",        "preview_img": "templateD.webp", "sort_order": 4},
    {"slug": "template5", "name": "Academic",     "tag": "Scholarly",    "preview_img": "templateE.webp", "sort_order": 5},
    {"slug": "template6", "name": "Professional", "tag": "Robust",       "preview_img": "templateF.webp", "sort_order": 6},
    {"slug": "template7", "name": "Classic",      "tag": "Elegant",      "preview_img": "templateG.webp", "sort_order": 7},
    {"slug": "template8", "name": "Compact",      "tag": "Sleek",        "preview_img": "templateH.webp", "sort_order": 8},
]


def seed_templates():
    """Insert template rows if they don't already exist."""
    for tdata in TEMPLATE_SEED:
        exists = Template.query.filter_by(slug=tdata["slug"]).first()
        if not exists:
            db.session.add(Template(**tdata))
    db.session.commit()
